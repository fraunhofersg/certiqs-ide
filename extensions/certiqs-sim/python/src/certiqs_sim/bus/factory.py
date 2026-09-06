"""Event-bus factory: pick a backend from settings."""

from __future__ import annotations

from certiqs_sim.bus.base import EventBus
from certiqs_sim.bus.memory import InMemoryBus


def build_bus(
    backend: str,
    *,
    nats_url: str = "nats://127.0.0.1:4222",
    redis_url: str = "redis://127.0.0.1:6379/0",
    ws_queue_max: int = 0,
) -> EventBus:
    backend = (backend or "memory").lower()
    if backend == "memory":
        return InMemoryBus(queue_maxsize=ws_queue_max)
    if backend == "nats":
        from certiqs_sim.bus.nats_bus import NatsBus

        return NatsBus(nats_url)
    if backend == "redis":
        from certiqs_sim.bus.redis_bus import RedisBus

        return RedisBus(redis_url)
    raise ValueError(f"Unknown bus backend {backend!r} (expected memory|nats|redis)")


__all__ = ["build_bus"]
