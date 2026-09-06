"""Factory-driven twin assembly from a declarative YAML config directory.

Components are *discovered* by their ``component:`` class and built through the
component-model registry — instance names are free-form.  This replaces the
previous hard-coded construction (fixed instance names, direct constructor
calls) with the CA-QKD pattern: YAML declares what the system contains, the
registry supplies the executable model, this builder connects them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from certiqs_sim.core.components.catalog import manifest_sha256
from certiqs_sim.core.components.registry import get_model_for_class
from certiqs_sim.core.manifest import (
    YAMLManifest,
    build_timing_config,
    find_component_by_class,
    source_coupling_efficiency,
)

QUANTUM_CHANNEL_CLASSES = {"single_mode_fiber_channel", "fiber_channel"}


def _require_factory(component_class: str) -> Any:
    spec = get_model_for_class(component_class)
    if spec is None or spec.factory is None:
        raise KeyError(
            f"No executable model registered for component class {component_class!r}"
        )
    return spec.factory


def build_source(manifest: YAMLManifest) -> Any:
    """SPDC source discovered by class; pump laser supplies the pulse clock."""
    found = find_component_by_class(manifest.source, "entangled_pair_source_spdc")
    if found is None:
        raise KeyError("Config declares no 'entangled_pair_source_spdc' component")
    inst_id, settings = found
    settings = dict(settings)

    laser = find_component_by_class(manifest.source, "pulsed_laser")
    if laser is not None:
        settings.setdefault("repetition_rate_hz", laser[1].get("repetition_rate_hz", 100e6))

    return _require_factory("entangled_pair_source_spdc")(inst_id, settings, {})


def build_quantum_channels(manifest: YAMLManifest) -> dict[str, Any]:
    """Quantum channels discovered by class; side inferred from the channel name."""
    channels: dict[str, Any] = {}
    quantum = [
        (name, chan)
        for name, chan in (manifest.channels.get("channels") or {}).items()
        if isinstance(chan, dict) and chan.get("component_class") in QUANTUM_CHANNEL_CLASSES
    ]
    for name, chan in quantum:
        factory = _require_factory(str(chan["component_class"]))
        lowered = name.lower()
        if "alice" in lowered:
            side = "alice"
        elif "bob" in lowered:
            side = "bob"
        else:
            side = "alice" if "alice" not in channels else "bob"
        context = {
            "side": side,
            # Source-arm fibre coupling belongs to the channel's launch efficiency.
            "coupling_efficiency": source_coupling_efficiency(manifest, side),
        }
        channels[side] = factory(name, dict(chan), context)
    missing = {"alice", "bob"} - set(channels)
    if missing:
        raise KeyError(f"Config declares no quantum channel for side(s): {sorted(missing)}")
    return channels


def build_receivers(manifest: YAMLManifest) -> dict[str, Any]:
    factory = _require_factory("bbm92_receiver_station")
    return {
        "alice": factory("alice", {}, {"node_doc": manifest.alice}),
        "bob": factory("bob", {}, {"node_doc": manifest.bob}),
    }


def build_twin_from_config(yaml_dir: Path, protocol_name: str = "bbm92") -> Any:
    """Assemble a :class:`QuantumChannelTwin` entirely through the registry."""
    import netsquid as ns
    from netsquid.qubits.qformalism import QFormalism

    from certiqs_sim.core.protocols.base import get_protocol
    from certiqs_sim.core.twin import QuantumChannelTwin

    ns.sim_reset()
    ns.set_qstate_formalism(QFormalism.DM)

    yaml_dir = Path(yaml_dir)
    manifest = YAMLManifest.from_directory(yaml_dir)

    source = build_source(manifest)
    channels = build_quantum_channels(manifest)
    receivers = build_receivers(manifest)
    timing = build_timing_config(manifest)
    protocol = get_protocol(protocol_name, manifest)

    twin = QuantumChannelTwin(
        source,
        channels["alice"],
        channels["bob"],
        receivers["alice"],
        receivers["bob"],
        timing,
        manifest,
        protocol,
    )
    twin.manifest_sha256 = manifest_sha256(yaml_dir)
    twin.config_dir = str(yaml_dir)
    return twin


__all__ = [
    "build_quantum_channels",
    "build_receivers",
    "build_source",
    "build_twin_from_config",
]
