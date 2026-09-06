"""In-memory event bus for single-process dev and tests.

Bridges synchronous publishers (the engine worker thread) to async subscribers via
``loop.call_soon_threadsafe``.  Subjects match NATS-style: ``*`` matches one token
and ``>`` matches the remainder.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from certiqs_sim.bus.base import EventBus, Subscription


def subject_matches(pattern: str, subject: str) -> bool:
    p_tokens = pattern.split(".")
    s_tokens = subject.split(".")
    for i, pt in enumerate(p_tokens):
        if pt == ">":
            return True
        if i >= len(s_tokens):
            return False
        if pt == "*":
            continue
        if pt != s_tokens[i]:
            return False
    return len(p_tokens) == len(s_tokens)


class InMemoryBus(EventBus):
    def __init__(self, *, queue_maxsize: int = 0) -> None:
        self._subscriptions: list[Subscription] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue_maxsize = max(0, int(queue_maxsize))

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()

    def _enqueue(self, sub: Subscription, message: dict[str, Any]) -> None:
        queue = sub.queue
        if self._queue_maxsize <= 0:
            queue.put_nowait(message)
            return
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Live dashboards only need the freshest metrics when the client lags.
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    def publish_sync(self, subject: str, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        for sub in list(self._subscriptions):
            if subject_matches(sub.subject, subject):
                loop.call_soon_threadsafe(self._enqueue, sub, message)

    async def publish(self, subject: str, message: dict[str, Any]) -> None:
        for sub in list(self._subscriptions):
            if subject_matches(sub.subject, subject):
                self._enqueue(sub, message)

    async def subscribe(self, subject: str) -> Subscription:
        maxsize = self._queue_maxsize if self._queue_maxsize > 0 else 0
        sub = Subscription(subject=subject, queue=asyncio.Queue(maxsize=maxsize))
        self._subscriptions.append(sub)
        return sub

    async def unsubscribe(self, subscription: Subscription) -> None:
        with contextlib.suppress(ValueError):
            self._subscriptions.remove(subscription)


__all__ = ["InMemoryBus", "subject_matches"]
