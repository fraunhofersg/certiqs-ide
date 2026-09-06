"""Component-model registry: declarative component classes -> versioned models.

Every ``component_class`` appearing in the YAML configuration maps to a
versioned model spec.  Executable specs carry a factory that builds the runtime
object; parametric specs are consumed by an assembly factory (e.g. the passive
optics folded into a receiver POVM); digital specs are RTL/firmware/software
stubs that the Python engine represents but does not simulate directly.

Model ids follow the ``model_binding_id`` values declared in the active
configuration set (``config/bbm92-generic``), so the YAML bindings and the
registry agree by construction.

The registry is the stable contract between the declarative configuration and
the Python implementation: swapping a model means registering a new version,
not rewriting the simulator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: factory(instance_id, settings, context) -> runtime object
ComponentFactory = Callable[[str, dict[str, Any], dict[str, Any]], Any]

KIND_EXECUTABLE = "executable"  # standalone runtime object (source, channel, receiver)
KIND_PARAMETRIC = "parametric"  # parameters folded into an assembly model
KIND_DIGITAL = "digital"  # RTL/firmware/software stub, represented but not simulated


@dataclass(frozen=True)
class ComponentModelSpec:
    model_id: str  # e.g. "quantum.spdc_entangled_source.v2"
    component_class: str  # e.g. "entangled_pair_source_spdc"
    version: str
    kind: str
    category_id: str  # taxonomy category (16_component_taxonomy.yaml)
    subcategory_id: str  # taxonomy subcategory
    description: str
    factory: ComponentFactory | None = field(default=None, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "component_class": self.component_class,
            "version": self.version,
            "kind": self.kind,
            "category_id": self.category_id,
            "subcategory_id": self.subcategory_id,
            "description": self.description,
        }


_REGISTRY: dict[str, ComponentModelSpec] = {}


def register_component_model(spec: ComponentModelSpec) -> ComponentModelSpec:
    _REGISTRY[spec.component_class] = spec
    return spec


def get_model_for_class(component_class: str) -> ComponentModelSpec | None:
    return _REGISTRY.get(str(component_class))


def list_component_models() -> list[ComponentModelSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: s.model_id)


# ── executable factories ──────────────────────────────────────────────────────
def _build_entangled_source(
    instance_id: str, settings: dict[str, Any], context: dict[str, Any]
) -> Any:
    from certiqs_sim.core.channel import EntangledSource
    from certiqs_sim.core.config_models import SourceConfig
    from certiqs_sim.core.manifest import werner_visibility_from_fidelity

    pair_stats = settings.get("pair_statistics", {}) or {}
    qstate = settings.get("quantum_state", {}) or {}
    spectrum = settings.get("spectrum", {}) or {}
    stats_model = str(pair_stats.get("model", "poisson")).lower()

    config = SourceConfig(
        bell_state=str(qstate.get("target_state", "phi_plus")),
        pair_generation_probability_per_pulse=float(
            pair_stats.get("mean_pairs_per_pulse", 0.01)
        ),
        intrinsic_visibility=werner_visibility_from_fidelity(float(qstate.get("fidelity", 1.0))),
        repetition_rate_hz=float(settings.get("repetition_rate_hz", 100e6)),
        generated_wavelength_nm=float(spectrum.get("signal_center_nm", 1550.0)),
        multi_pair_model=(
            "poisson" if stats_model in ("poisson", "multimode_thermal") else stats_model
        ),
    )
    return EntangledSource(instance_id, config)


def _build_fiber_channel(
    instance_id: str, settings: dict[str, Any], context: dict[str, Any]
) -> Any:
    from certiqs_sim.core.channel import FiberChannel
    from certiqs_sim.core.config_models import FiberConfig
    from certiqs_sim.core.manifest import _fiber_fields_from_channel

    length_km = float(settings.get("length_km", 0.0))
    fields = _fiber_fields_from_channel(settings, length_km)
    fields["coupling_efficiency"] = float(context.get("coupling_efficiency", 1.0))
    config = FiberConfig(**fields)
    return FiberChannel(instance_id, config, side=str(context.get("side", "")))


def _build_receiver_station(
    instance_id: str, settings: dict[str, Any], context: dict[str, Any]
) -> Any:
    from certiqs_sim.core.detectors import OpticalReceiver
    from certiqs_sim.core.manifest import receiver_config_from_node

    node_doc = context["node_doc"]
    return OpticalReceiver(receiver_config_from_node(node_doc, instance_id))


# ── registrations ─────────────────────────────────────────────────────────────
register_component_model(
    ComponentModelSpec(
        model_id="quantum.spdc_entangled_source.v2",
        component_class="entangled_pair_source_spdc",
        version="2",
        kind=KIND_EXECUTABLE,
        category_id="quantum_sources",
        subcategory_id="entangled_pair_sources",
        description="SPDC entangled photon-pair source (Werner-state fidelity model).",
        factory=_build_entangled_source,
    )
)
register_component_model(
    ComponentModelSpec(
        model_id="channels.fiber.dynamic_jones.v2",
        component_class="single_mode_fiber_channel",
        version="2",
        kind=KIND_EXECUTABLE,
        category_id="quantum_channels",
        subcategory_id="fiber_channels",
        description=(
            "NetSquid single-mode fibre channel: loss, PMD, polarization drift, "
            "background counts, delay."
        ),
        factory=_build_fiber_channel,
    )
)
register_component_model(
    ComponentModelSpec(
        model_id="stations.bbm92_receiver.v2",
        component_class="bbm92_receiver_station",
        version="2",
        kind=KIND_EXECUTABLE,
        category_id="photon_detection",
        subcategory_id="single_photon_detectors",
        description="Passive-basis BBM92 polarization analysis station (optics + detector array).",
        factory=_build_receiver_station,
    )
)

_PARAMETRIC: list[tuple[str, str, str, str, str]] = [
    # (model_id, component_class, category, subcategory, description)
    (
        "assemblies.entangled_pair_source_subsystem.v1",
        "entangled_pair_source_subsystem",
        "quantum_sources",
        "entangled_pair_sources",
        "Central entanglement source subsystem wrapper (pump + SPDC assembly).",
    ),
    (
        "optics.pulsed_laser.v1",
        "pulsed_laser",
        "quantum_sources",
        "pump_lasers",
        "Pulsed pump laser: repetition rate drives the twin's pulse clock.",
    ),
    (
        "optics.polarization_controller.v1",
        "polarization_controller",
        "optical_components",
        "polarization_control",
        "Programmable polarization controller (drift compensation; loss folded into POVM).",
    ),
    (
        "optics.npbs.v1",
        "nonpolarizing_beamsplitter",
        "optical_components",
        "beam_splitters",
        "Non-polarizing 50:50 basis-choice beam splitter.",
    ),
    (
        "optics.pbs.v1",
        "polarizing_beamsplitter",
        "optical_components",
        "beam_splitters",
        "Polarizing beam splitter; extinction ratio maps to leakage probability.",
    ),
    (
        "optics.half_wave_plate.v1",
        "half_wave_plate",
        "optical_components",
        "polarization_control",
        "Half-wave plate (X-basis rotation / compensation).",
    ),
    (
        "detectors.array.v1",
        "detector_array",
        "photon_detection",
        "single_photon_detectors",
        "Detector-array wrapper grouping a station's single-photon detector channels.",
    ),
    (
        "detectors.spad.free_running.v2",
        "single_photon_detector",
        "photon_detection",
        "single_photon_detectors",
        "Free-running SPAD: efficiency, dark counts, timing response, dead time, afterpulsing.",
    ),
    (
        "monitors.optical_power.v1",
        "optical_power_monitor",
        "photon_detection",
        "monitoring_detectors",
        "Receiver input optical-power watchdog (blinding countermeasure).",
    ),
    (
        "comms.classical_network_link.v1",
        "classical_network_link",
        "classical_communications",
        "network_interfaces",
        "Authenticated classical channel for sifting and post-processing traffic.",
    ),
    (
        "nodes.network_coordination.v1",
        "network_coordination_subsystem",
        "timing_and_synchronization",
        "clock_sync",
        "Bilateral classical/timing coordination between QKD boxes and nodes.",
    ),
    (
        "nodes.qkd_key_routing.v1",
        "qkd_key_routing_node",
        "post_processing",
        "reconciliation",
        "Per-side QKD node wrapping key routing and post-processing stages.",
    ),
    (
        "timing.time_sync_channel.v1",
        "time_sync_channel",
        "timing_and_synchronization",
        "clock_sync",
        "Time-synchronization channel; latency jitter enters the coincidence model.",
    ),
]
for model_id, cls, cat, sub, desc in _PARAMETRIC:
    register_component_model(
        ComponentModelSpec(
            model_id=model_id,
            component_class=cls,
            version=model_id.rsplit(".v", 1)[-1],
            kind=KIND_PARAMETRIC,
            category_id=cat,
            subcategory_id=sub,
            description=desc,
        )
    )

_DIGITAL: list[tuple[str, str, str, str, str]] = [
    (
        "timing.tdc.multichannel.v2",
        "time_to_digital_converter",
        "timing_and_synchronization",
        "time_tagging",
        "Multichannel time-to-digital converter (resolution, skew, DNL/INL, FIFO).",
    ),
    (
        "timing.two_way_sync.v1",
        "time_sync_unit",
        "timing_and_synchronization",
        "clock_sync",
        "Two-way time-transfer synchronizer (residual offset model).",
    ),
    (
        "digital.coincidence.fpga_reference.v1",
        "coincidence_matcher",
        "digital_processing",
        "coincidence_processing",
        "FPGA coincidence matcher; Python model is the golden reference.",
    ),
    (
        "digital.coincidence_matcher.rtl.v1",
        "fpga_coincidence_matcher",
        "digital_processing",
        "coincidence_processing",
        "RTL coincidence-matcher build (hardware identity binding).",
    ),
    (
        "postprocessing.sifting.v1",
        "basis_sifting",
        "post_processing",
        "reconciliation",
        "Basis sifting: key basis vs parameter-estimation basis separation.",
    ),
    (
        "postprocessing.qber_estimator.v1",
        "qber_estimator",
        "post_processing",
        "reconciliation",
        "QBER estimation with statistical (Serfling) confidence bounds.",
    ),
    (
        "postprocessing.ldpc.rate_adaptive.v2",
        "ldpc_reconciliation",
        "post_processing",
        "reconciliation",
        "Rate-adaptive LDPC information reconciliation with leakage accounting.",
    ),
    (
        "postprocessing.two_universal_hashing.v1",
        "two_universal_hashing",
        "post_processing",
        "privacy_amplification",
        "Two-universal (Toeplitz) hashing privacy amplification.",
    ),
    (
        "security.finite_key_bbm92.v1",
        "finite_key_engine",
        "post_processing",
        "privacy_amplification",
        "Composable finite-key secret-length engine (entropic uncertainty, BBM92).",
    ),
    (
        "comms.wegman_carter_auth.v1",
        "classical_authentication",
        "classical_communications",
        "authentication_modules",
        "Wegman-Carter authentication with key-consumption accounting.",
    ),
    (
        "postprocessing.key_store.v1",
        "key_store_interface",
        "classical_communications",
        "authentication_modules",
        "Key store / delivery interface (net secret key only).",
    ),
]
for model_id, cls, cat, sub, desc in _DIGITAL:
    register_component_model(
        ComponentModelSpec(
            model_id=model_id,
            component_class=cls,
            version=model_id.rsplit(".v", 1)[-1],
            kind=KIND_DIGITAL,
            category_id=cat,
            subcategory_id=sub,
            description=desc,
        )
    )


__all__ = [
    "KIND_DIGITAL",
    "KIND_EXECUTABLE",
    "KIND_PARAMETRIC",
    "ComponentFactory",
    "ComponentModelSpec",
    "get_model_for_class",
    "list_component_models",
    "register_component_model",
]
