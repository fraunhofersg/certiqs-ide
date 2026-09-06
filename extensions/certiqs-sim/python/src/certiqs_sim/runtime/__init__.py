"""Live-runtime layer: tunable-parameter surface, metric registry, twin worker."""

from __future__ import annotations

from certiqs_sim.runtime.metrics_registry import (
    DEFAULT_METRICS,
    MetricRegistry,
    MetricSpec,
)
from certiqs_sim.runtime.params import (
    ATTACK_PARAM_META,
    BASE_PARAM_META,
    SELFTEST_MODES,
    SELFTEST_PARAM_META,
    apply_attack,
    apply_overrides,
    apply_selftest,
    default_params_for_config,
    read_attack_params,
    read_current_params,
    read_selftest_params,
)

__all__ = [
    "ATTACK_PARAM_META",
    "BASE_PARAM_META",
    "DEFAULT_METRICS",
    "SELFTEST_MODES",
    "SELFTEST_PARAM_META",
    "MetricRegistry",
    "MetricSpec",
    "TwinWorker",
    "apply_attack",
    "apply_overrides",
    "apply_selftest",
    "default_params_for_config",
    "read_attack_params",
    "read_current_params",
    "read_selftest_params",
]


def __getattr__(name: str):
    if name == "TwinWorker":
        from certiqs_sim.runtime.worker import TwinWorker
        return TwinWorker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
