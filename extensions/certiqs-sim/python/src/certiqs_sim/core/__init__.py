"""Framework-free domain layer: the NetSquid quantum-channel twin and its physics.

Nothing in ``core`` imports FastAPI, a database, a message bus, or any service
concern.  It is the validated scientific kernel the rest of the platform wraps.
"""

from __future__ import annotations

from certiqs_sim.core.config_models import (
    DetectorSpec,
    FiberConfig,
    LinkBudgetConfig,
    ReceiverConfig,
    SourceConfig,
    TimingConfig,
)
from certiqs_sim.core.keyrate import (
    asymptotic_bbm92_key_rate_per_pulse,
    asymptotic_bbm92_secret_key_fraction,
    binary_entropy2,
)
from certiqs_sim.core.manifest import (
    YAMLManifest,
    build_fiber_config,
    build_source_config,
    build_timing_config,
)

# Twin / NetSquid stay lazy so the control plane can import this package
# without the optional engine extra.

__all__ = [
    "BBM92DigitalTwin",
    "DetectorSpec",
    "FiberConfig",
    "LinkBudgetConfig",
    "QuantumChannelTwin",
    "ReceiverConfig",
    "SourceConfig",
    "TimingConfig",
    "YAMLManifest",
    "asymptotic_bbm92_key_rate_per_pulse",
    "asymptotic_bbm92_secret_key_fraction",
    "binary_entropy2",
    "build_fiber_config",
    "build_source_config",
    "build_timing_config",
    "build_twin_from_yaml_directory",
]


def __getattr__(name: str):
    if name in {"QuantumChannelTwin", "build_twin_from_yaml_directory", "BBM92DigitalTwin"}:
        from certiqs_sim.core.twin import QuantumChannelTwin, build_twin_from_yaml_directory
        exported = {
            "QuantumChannelTwin": QuantumChannelTwin,
            "build_twin_from_yaml_directory": build_twin_from_yaml_directory,
            "BBM92DigitalTwin": QuantumChannelTwin,
        }
        return exported[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
