"""Pluggable event backbone.

The in-process ``Hub`` of the original monolith is replaced by an :class:`EventBus`
abstraction with three backends: an in-memory bus (dev / single process), NATS,
and Redis Streams.  Engine pods publish datapoints/sifted blocks; the API gateway,
post-processing and security-eval services subscribe.
"""

from __future__ import annotations

from certiqs_sim.bus.base import EventBus, Subscription
from certiqs_sim.bus.factory import build_bus
from certiqs_sim.bus.memory import InMemoryBus

__all__ = ["EventBus", "InMemoryBus", "Subscription", "build_bus"]
