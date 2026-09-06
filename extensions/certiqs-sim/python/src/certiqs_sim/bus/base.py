"""Event-bus interface + subject constants.

The bus carries JSON-serialisable messages on named *subjects*.  Publishers are
synchronous (the engine worker thread publishes); subscribers are async
(FastAPI/asyncio consumers).  Backends implement both surfaces.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── subject naming ─────────────────────────────────────────────────────────────
def datapoint_subject(prefix: str, run_id: str) -> str:
    return f"{prefix}.runs.{run_id}.datapoint"


def sifted_subject(prefix: str, run_id: str) -> str:
    return f"{prefix}.runs.{run_id}.sifted"


def status_subject(prefix: str, run_id: str) -> str:
    return f"{prefix}.runs.{run_id}.status"


def postproc_subject(prefix: str, run_id: str) -> str:
    return f"{prefix}.runs.{run_id}.postproc"


@dataclass
class Subscription:
    """An async subscription yielding messages via an :class:`asyncio.Queue`."""

    subject: str
    queue: asyncio.Queue[dict[str, Any]]
    #: backend-specific handles (NATS subscription, redis pubsub, reader task, …)
    backend_data: dict[str, Any] = field(default_factory=dict)


class EventBus(ABC):
    @abstractmethod
    def publish_sync(self, subject: str, message: dict[str, Any]) -> None:
        """Publish from synchronous code (e.g. the engine worker thread)."""

    @abstractmethod
    async def publish(self, subject: str, message: dict[str, Any]) -> None:
        """Publish from async code."""

    @abstractmethod
    async def subscribe(self, subject: str) -> Subscription:
        """Subscribe to a subject (supports a trailing ``*`` / ``>`` wildcard)."""

    @abstractmethod
    async def unsubscribe(self, subscription: Subscription) -> None: ...

    async def start(self) -> None:  # noqa: B027 — optional hook, not abstract
        """Optional backend connection setup."""

    async def close(self) -> None:  # noqa: B027 — optional hook, not abstract
        """Optional backend teardown."""


__all__ = [
    "EventBus",
    "Subscription",
    "datapoint_subject",
    "postproc_subject",
    "sifted_subject",
    "status_subject",
]
