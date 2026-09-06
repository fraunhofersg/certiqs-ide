"""Redis-backed event bus (pub/sub).

Alternative backend using ``redis.asyncio`` pub/sub.  Requires the ``redis``
package (install the ``bus`` extra).  Subjects are mapped to Redis channels;
NATS-style ``*`` / ``>`` wildcards are translated to Redis glob patterns.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from certiqs_sim.bus.base import EventBus, Subscription


def _to_redis_pattern(subject: str) -> str:
    # NATS '*' (one token) and '>' (rest) -> Redis glob. Redis '*' spans tokens,
    # which is an acceptable superset for our fixed subject shapes.
    return subject.replace(">", "*").replace("*", "*")


class RedisBus(EventBus):
    def __init__(self, url: str = "redis://127.0.0.1:6379/0") -> None:
        self.url = url
        self._redis: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        import redis.asyncio as aioredis  # lazy import

        self._loop = asyncio.get_running_loop()
        self._redis = aioredis.from_url(self.url, decode_responses=True)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def publish_sync(self, subject: str, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or self._redis is None:
            return
        asyncio.run_coroutine_threadsafe(self.publish(subject, message), loop)

    async def publish(self, subject: str, message: dict[str, Any]) -> None:
        if self._redis is None:
            return
        await self._redis.publish(subject, json.dumps(message))

    async def subscribe(self, subject: str) -> Subscription:
        if self._redis is None:
            raise RuntimeError("RedisBus.start() must be awaited before subscribing")
        sub_obj = Subscription(subject=subject, queue=asyncio.Queue())
        pubsub = self._redis.pubsub()
        pattern = _to_redis_pattern(subject)
        await pubsub.psubscribe(pattern)

        async def _reader() -> None:
            async for msg in pubsub.listen():
                if msg.get("type") not in ("pmessage", "message"):
                    continue
                try:
                    payload = json.loads(msg["data"])
                except (ValueError, TypeError):
                    continue
                await sub_obj.queue.put(payload)

        task = asyncio.ensure_future(_reader())
        self._tasks.append(task)
        sub_obj.backend_data["pubsub"] = pubsub
        sub_obj.backend_data["task"] = task
        return sub_obj

    async def unsubscribe(self, subscription: Subscription) -> None:
        task = subscription.backend_data.get("task")
        if task is not None:
            task.cancel()
        pubsub = subscription.backend_data.get("pubsub")
        if pubsub is not None:
            await pubsub.close()


__all__ = ["RedisBus"]
