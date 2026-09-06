"""QKD protocol plugins.

The twin engine is protocol-agnostic; a :class:`Protocol` plugin supplies the
protocol-specific rules — sifting, coincidence handling, and the asymptotic
secret-key fraction.  ``bbm92`` is the first plugin; BB84 / E91 can be added by
registering another :class:`Protocol` without touching the engine.
"""

from __future__ import annotations

from certiqs_sim.core.protocols.base import (
    Protocol,
    get_protocol,
    list_protocols,
    register_protocol,
)
from certiqs_sim.core.protocols.bbm92 import BBM92Protocol

__all__ = [
    "BBM92Protocol",
    "Protocol",
    "get_protocol",
    "list_protocols",
    "register_protocol",
]
