"""NATS-backed event bus.

Recommended production backend: lightweight and Kubernetes-native.  Requires the
``nats-py`` package (install the ``bus`` extra).  Synchronous publishes from the
engine worker thread are marshalled onto the service event loop.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from certiqs_sim.bus.base import EventBus, Subscription


class NatsBus(EventBus):
    def __init__(self, url: str = "nats://127.0.0.1:4222") -> None:
        self.url = url
        self._nc: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: list[Any] = []

    async def start(self) -> None:
        import nats  # imported lazily so the package imports without nats-py

        self._loop = asyncio.get_running_loop()
        self._nc = await nats.connect(self.url)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None

    @staticmethod
    def _to_nats_subject(subject: str) -> str:
        # NATS uses the same '.'-delimited tokens with '*' and '>' wildcards.
        return subject

    def publish_sync(self, subject: str, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or self._nc is None:
            return
        asyncio.run_coroutine_threadsafe(self.publish(subject, message), loop)

    async def publish(self, subject: str, message: dict[str, Any]) -> None:
        if self._nc is None:
            return
        await self._nc.publish(self._to_nats_subject(subject), json.dumps(message).encode())

    async def subscribe(self, subject: str) -> Subscription:
        if self._nc is None:
            raise RuntimeError("NatsBus.start() must be awaited before subscribing")
        sub_obj = Subscription(subject=subject, queue=asyncio.Queue())

        async def _handler(msg: Any) -> None:
            try:
                payload = json.loads(msg.data.decode())
            except (ValueError, UnicodeDecodeError):
                return
            await sub_obj.queue.put(payload)

        nats_sub = await self._nc.subscribe(self._to_nats_subject(subject), cb=_handler)
        self._subs.append(nats_sub)
        sub_obj.backend_data["nats_sub"] = nats_sub
        return sub_obj

    async def unsubscribe(self, subscription: Subscription) -> None:
        nats_sub = subscription.backend_data.get("nats_sub")
        if nats_sub is not None:
            await nats_sub.unsubscribe()


__all__ = ["NatsBus"]
