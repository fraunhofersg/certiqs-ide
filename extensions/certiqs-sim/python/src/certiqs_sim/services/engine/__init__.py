"""certiqs-engine: the NetSquid quantum-channel twin data-plane service.

One engine process = one NetSquid twin (the engine is non-reentrant).  The service
runs a continuous :class:`TwinWorker`, publishes per-window datapoints and raw
sifted blocks to the event bus, and exposes health/metrics plus a small control
surface.  Scale-out = more engine pods behind the bus.
"""

from __future__ import annotations

from certiqs_sim.services.engine.app import create_app

__all__ = ["create_app"]
