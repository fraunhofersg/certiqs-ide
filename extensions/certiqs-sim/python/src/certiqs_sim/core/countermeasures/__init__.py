"""Countermeasure library + registry.

``detector_selftest`` is the first countermeasure (Shen & Kurtsiefer 2025).
Others can be added by registering another factory.
"""

from __future__ import annotations

from certiqs_sim.core.countermeasures.base import (
    COUNTERMEASURE_REGISTRY,
    get_countermeasure_factory,
    list_countermeasures,
    register_countermeasure,
)
from certiqs_sim.core.countermeasures.detector_selftest import (
    DetectorSelfTest,
    SelfTestConfig,
)

__all__ = [
    "COUNTERMEASURE_REGISTRY",
    "DetectorSelfTest",
    "SelfTestConfig",
    "get_countermeasure_factory",
    "list_countermeasures",
    "register_countermeasure",
]
