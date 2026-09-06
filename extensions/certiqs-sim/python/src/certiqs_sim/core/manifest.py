"""YAML manifest loading and YAML -> runtime-config builders (schema 2.0).

Parses the hierarchical configuration package layout (``config/bbm92-generic``):
subsystem documents declare ``components:`` keyed by logical id, each carrying a
``component_class`` and inline engineering parameters; channels carry their
parameters directly.  The builders translate those declarative parameters into
the live runtime dataclasses the engine mutates.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from certiqs_sim.core.config_models import (
    DetectorSpec,
    FiberConfig,
    LinkBudgetAgeing,
    LinkBudgetBending,
    LinkBudgetConfig,
    LinkBudgetContamination,
    LinkBudgetMeasurementUncertainty,
    ReceiverConfig,
    SourceConfig,
    TimingConfig,
)
from certiqs_sim.core.linalg import (
    DEFAULT_COHERENCE_TIME_PS,
    FIBER_GROUP_INDEX,
)


def _read_yaml_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML file {path} did not parse to a mapping.")
    return data


class YAMLManifest:
    """Parsed multi-document manifest, indexed by the section each doc represents."""

    def __init__(self, raw_docs: Mapping[str, dict[str, Any]]):
        self.raw_docs = dict(raw_docs)
        self.protocol = self._find_doc("protocol")
        self.source = self._find_doc("subsystem", expected_id={"central_entanglement_source"})
        self.alice = self._find_doc("subsystem", expected_id={"alice_station"})
        self.bob = self._find_doc("subsystem", expected_id={"bob_station"})
        self.channels = self._find_doc("channels")
        self.digital = self._merge_section("clock_domains")
        self.post_processing = self._merge_post_processing()
        self.top = self._find_doc("system")
        # Optional sections of the full CA-QKD package.
        self.control = self._find_doc_optional("control_loops")
        self.environment = self._find_doc_optional("environment")
        self.attacks = self._find_doc_optional("attacks")
        self.experiments = self._find_doc_optional("experiments")
        self.metrics = self._find_doc_optional("metrics")
        self.validation_plan = self._find_doc_optional("validation_plan")

    def _find_doc(
        self, required_key: str, expected_id: set[str] | None = None
    ) -> dict[str, Any]:
        for doc in self.raw_docs.values():
            if required_key not in doc:
                continue
            if expected_id is None:
                return doc
            subsystem = doc.get("subsystem", {}) or {}
            if subsystem.get("id") in expected_id or subsystem.get("name") in expected_id:
                return doc
        raise KeyError(
            f"Could not find YAML section with key {required_key!r} and id {expected_id}."
        )

    def _find_doc_optional(self, required_key: str) -> dict[str, Any] | None:
        try:
            return self._find_doc(required_key)
        except KeyError:
            return None

    def _merge_section(self, section_key: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for doc in self.raw_docs.values():
            section = doc.get(section_key)
            if isinstance(section, dict):
                merged.update(section)
        return {section_key: merged} if merged else {}

    def _merge_post_processing(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for doc in self.raw_docs.values():
            section = doc.get("post_processing")
            if isinstance(section, dict):
                merged.update(section)
        if not merged:
            raise KeyError("Could not find YAML section with key 'post_processing'.")
        return {"post_processing": merged}

    @classmethod
    def from_directory(cls, directory: Path) -> YAMLManifest:
        directory = Path(directory)
        try:
            from certiqs_sim.core.topology.loader import is_hierarchical_config, load_topology
            from certiqs_sim.core.topology.adapter import topology_to_flat_documents
            from certiqs_sim.core.topology.validate import assert_valid

            if is_hierarchical_config(directory):
                resolved = load_topology(directory)
                assert_valid(resolved)
                raw_docs = topology_to_flat_documents(resolved)
                return cls(raw_docs)
        except ImportError:
            pass

        raw_docs: dict[str, dict[str, Any]] = {}
        for path in sorted(directory.glob("*.y*ml")):
            raw_docs[path.name] = _read_yaml_file(path)
        if not raw_docs:
            raise ValueError(f"No YAML documents found in {directory}.")
        return cls(raw_docs)


def find_component_by_class(
    doc: Mapping[str, Any], component_class: str
) -> tuple[str, dict[str, Any]] | None:
    """First ``components:`` entry of the given class -> (logical_id, settings)."""
    for comp_id, comp in (doc.get("components") or {}).items():
        if isinstance(comp, dict) and comp.get("component_class") == component_class:
            return str(comp_id), comp
    return None


def werner_visibility_from_fidelity(fidelity: float) -> float:
    """Werner parameter w for a state of fidelity F: rho = w|Φ+><Φ+| + (1-w)I/4."""
    return min(max((4.0 * float(fidelity) - 1.0) / 3.0, 0.0), 1.0)


def build_source_config(manifest: YAMLManifest) -> SourceConfig:
    spdc_found = find_component_by_class(manifest.source, "entangled_pair_source_spdc")
    spdc = spdc_found[1] if spdc_found else {}
    laser_found = find_component_by_class(manifest.source, "pulsed_laser")
    laser = laser_found[1] if laser_found else {}

    pair_stats = spdc.get("pair_statistics", {}) or {}
    qstate = spdc.get("quantum_state", {}) or {}
    spectrum = spdc.get("spectrum", {}) or {}

    # The engine samples pair counts Poisson-like; the multimode-thermal example
    # (20 Schmidt modes) is Poisson to excellent approximation.
    stats_model = str(pair_stats.get("model", "poisson")).lower()
    multi_pair_model = "poisson" if stats_model in ("poisson", "multimode_thermal") else stats_model

    return SourceConfig(
        bell_state=str(qstate.get("target_state", "phi_plus")),
        pair_generation_probability_per_pulse=float(
            pair_stats.get("mean_pairs_per_pulse", 0.01)
        ),
        intrinsic_visibility=werner_visibility_from_fidelity(float(qstate.get("fidelity", 1.0))),
        repetition_rate_hz=float(laser.get("repetition_rate_hz", 100e6)),
        generated_wavelength_nm=float(spectrum.get("signal_center_nm", 1550.0)),
        multi_pair_model=multi_pair_model,
    )


def source_coupling_efficiency(manifest: YAMLManifest, side: str) -> float:
    spdc_found = find_component_by_class(manifest.source, "entangled_pair_source_spdc")
    spdc = spdc_found[1] if spdc_found else {}
    coupling = spdc.get("coupling_efficiency", {}) or {}
    return float(coupling.get(side, 1.0))


def _link_budget_from_channel(chan: Mapping[str, Any]) -> LinkBudgetConfig:
    """Parse optional ``link_budget`` block for QKD fibre channels.

    Defaults keep ageing / contamination / bending disabled so existing configs
    are numerically unchanged until fields are enabled.
    """
    raw = chan.get("link_budget") or {}
    if not isinstance(raw, Mapping):
        raw = {}

    ageing_raw = raw.get("ageing") or {}
    contam_raw = raw.get("contamination") or {}
    bend_raw = raw.get("bending") or {}
    unc_raw = raw.get("measurement_uncertainty") or {}
    if not isinstance(ageing_raw, Mapping):
        ageing_raw = {}
    if not isinstance(contam_raw, Mapping):
        contam_raw = {}
    if not isinstance(bend_raw, Mapping):
        bend_raw = {}
    if not isinstance(unc_raw, Mapping):
        unc_raw = {}

    return LinkBudgetConfig(
        design_margin_db=float(raw.get("design_margin_db", 0.0)),
        apply_design_margin=bool(raw.get("apply_design_margin", False)),
        ageing=LinkBudgetAgeing(
            enabled=bool(ageing_raw.get("enabled", False)),
            excess_loss_db=float(ageing_raw.get("excess_loss_db", 0.0)),
            rate_db_per_year=float(ageing_raw.get("rate_db_per_year", 0.0)),
            service_life_years=float(ageing_raw.get("service_life_years", 0.0)),
        ),
        contamination=LinkBudgetContamination(
            enabled=bool(contam_raw.get("enabled", False)),
            excess_loss_db=float(contam_raw.get("excess_loss_db", 0.0)),
            connector_contamination_prob=float(
                contam_raw.get("connector_contamination_prob", 0.0)
            ),
        ),
        bending=LinkBudgetBending(
            enabled=bool(bend_raw.get("enabled", False)),
            excess_loss_db=float(bend_raw.get("excess_loss_db", 0.0)),
            min_bend_radius_mm=float(bend_raw.get("min_bend_radius_mm", 30.0)),
            induced_loss_db_per_turn=float(bend_raw.get("induced_loss_db_per_turn", 0.1)),
            num_tight_bends=max(int(bend_raw.get("num_tight_bends", 0)), 0),
        ),
        measurement_uncertainty=LinkBudgetMeasurementUncertainty(
            attenuation_db_per_km_sigma=float(
                unc_raw.get("attenuation_db_per_km_sigma", 0.0)
            ),
            length_km_sigma=float(unc_raw.get("length_km_sigma", 0.0)),
            splice_loss_db_sigma=float(unc_raw.get("splice_loss_db_sigma", 0.0)),
            connector_loss_db_sigma=float(unc_raw.get("connector_loss_db_sigma", 0.0)),
            loss_budget_confidence=float(unc_raw.get("loss_budget_confidence", 0.95)),
        ),
    )


def _fiber_fields_from_channel(chan: Mapping[str, Any], length_km: float) -> dict[str, Any]:
    """Parse fibre physics fields from a channel YAML row.

    Discrete losses support either:
    - modern: ``num_splices`` × ``splice_loss_db`` (per splice) and
      ``num_connectors`` × ``connector_loss_db`` (per connector), or
    - legacy lump: ``splice_loss_db`` / ``connector_loss_db`` totals folded into
      ``insertion_loss_db`` when counts are omitted.

    Omitting count keys entirely keeps discrete loss at zero (legacy YAML with
    only length / attenuation stays numerically unchanged).

    Optional ``link_budget`` captures design margin, ageing, contamination,
    bending, and measurement uncertainty for later life / Monte Carlo models.
    """
    wavelength_nm = float(chan.get("wavelength_nm", 1550.0))

    if "num_splices" in chan:
        num_splices = max(int(chan.get("num_splices", 0)), 0)
        splice_loss_db = float(chan.get("splice_loss_db", 0.05))
        legacy_splice = 0.0
    else:
        num_splices = 0
        splice_loss_db = 0.05  # per-splice default for live overrides
        # Legacy: ``splice_loss_db`` was a lump total when no count was given.
        legacy_splice = float(chan.get("splice_loss_db", 0.0)) if "splice_loss_db" in chan else 0.0

    if "num_connectors" in chan:
        num_connectors = max(int(chan.get("num_connectors", 0)), 0)
        connector_loss_db = float(chan.get("connector_loss_db", 0.25))
        legacy_connector = 0.0
    else:
        num_connectors = 0
        connector_loss_db = 0.25  # per-connector default for live overrides
        legacy_connector = (
            float(chan.get("connector_loss_db", 0.0)) if "connector_loss_db" in chan else 0.0
        )

    insertion_loss_db = (
        float(chan.get("insertion_loss_db", 0.0)) + legacy_splice + legacy_connector
    )
    pmd_ps = float(chan.get("pmd_ps_sqrt_km", 0.0)) * math.sqrt(max(length_km, 0.0))
    drift_sigma_rad = math.radians(float(chan.get("polarization_drift_deg_rms_per_sqrt_s", 0.0)))
    return {
        "length_km": length_km,
        "attenuation_db_per_km": float(chan.get("attenuation_db_per_km", 0.2)),
        "wavelength_nm": wavelength_nm,
        "num_splices": num_splices,
        "splice_loss_db": splice_loss_db,
        "num_connectors": num_connectors,
        "connector_loss_db": connector_loss_db,
        "insertion_loss_db": insertion_loss_db,
        "depolarization_prob": float(chan.get("depolarization_prob", 0.0)),
        "depolarization_per_km": float(chan.get("depolarization_per_km", 0.002)),
        "pmd_ps": pmd_ps,
        "background_photon_rate_hz": float(chan.get("background_count_equivalent_hz", 0.0)),
        "static_rotation_rad": float(chan.get("static_rotation_rad", 0.0)),
        "drift_sigma_rad": drift_sigma_rad,
        "fiber_group_index": float(chan.get("group_index", FIBER_GROUP_INDEX)),
        "coherence_time_ps": float(chan.get("coherence_time_ps", DEFAULT_COHERENCE_TIME_PS)),
        "link_budget": _link_budget_from_channel(chan),
    }


def build_fiber_config(manifest: YAMLManifest, channel_name: str, side: str) -> FiberConfig:
    chan = manifest.channels.get("channels", {}).get(channel_name, {}) or {}
    length_km = float(chan.get("length_km", 0.0))
    fields = _fiber_fields_from_channel(chan, length_km)
    fields["coupling_efficiency"] = source_coupling_efficiency(manifest, side)
    return FiberConfig(**fields)


def _extinction_leakage_prob(settings: Mapping[str, Any]) -> float:
    """Polarization leakage probability from a PBS extinction ratio in dB."""
    er_db = float(settings.get("extinction_ratio_db", 200.0))
    return 10.0 ** (-er_db / 10.0)


#: detector logical-name suffix -> (state, basis, bit)
_DETECTOR_SUFFIX = {
    "h": ("H", "Z", 0),
    "v": ("V", "Z", 1),
    "d": ("D", "X", 0),
    "a": ("A", "X", 1),
}


def receiver_config_from_node(node_doc: Mapping[str, Any], station_name: str) -> ReceiverConfig:
    components = node_doc.get("components", {}) or {}

    def _by_class(component_class: str) -> dict[str, Any]:
        found = find_component_by_class(node_doc, component_class)
        return found[1] if found else {}

    pol_ctrl = _by_class("polarization_controller")
    npbs = _by_class("nonpolarizing_beamsplitter")
    ratio = npbs.get("splitting_ratio", {}) or {}

    # Z and X analyzers are polarizing beam splitters distinguished by `basis`.
    z_pbs: dict[str, Any] = {}
    x_pbs: dict[str, Any] = {}
    hwp: dict[str, Any] = {}
    for comp in components.values():
        if not isinstance(comp, dict):
            continue
        cls = comp.get("component_class")
        if cls == "polarizing_beamsplitter":
            if str(comp.get("basis", "")).upper() == "X":
                x_pbs = comp
            else:
                z_pbs = comp
        elif cls == "half_wave_plate":
            hwp = comp

    detectors: dict[str, DetectorSpec] = {}
    det_array = _by_class("detector_array")
    for channel_id, (det_id, det) in enumerate((det_array.get("channels") or {}).items()):
        if not isinstance(det, dict):
            continue
        suffix = str(det_id).rsplit("_", 1)[-1].lower()
        if suffix not in _DETECTOR_SUFFIX:
            continue
        state, basis, bit = _DETECTOR_SUFFIX[suffix]
        timing = det.get("timing_response", {}) or {}
        afterpulsing = det.get("afterpulsing", {}) or {}
        detectors[state] = DetectorSpec(
            label=state,
            basis=basis,
            bit=bit,
            channel_id=channel_id,
            efficiency=min(max(float(det.get("efficiency", 1.0)), 0.0), 1.0),
            dark_count_hz=float(det.get("dark_count_hz", 0.0)),
            jitter_ps_rms=float(timing.get("sigma_ps", 0.0)),
            dead_time_ns=float(det.get("dead_time_ns", 0.0)),
            afterpulse_prob=float(afterpulsing.get("probability", 0.0)),
        )

    missing = {"H", "V", "D", "A"} - set(detectors)
    if missing:
        raise KeyError(
            f"Station {station_name!r} detector_array does not declare channels for "
            f"outcome(s) {sorted(missing)} (expected *_h/_v/_d/_a channel names)."
        )

    # The retardance error of the HWP is mapped onto an equivalent rotation-angle
    # spread; a small retardance error delta translates to ~delta/2 rotation error.
    retardance_sigma_rad = float(hwp.get("retardance_error_rad_sigma", 0.0))
    angle_error_deg_sigma = math.degrees(retardance_sigma_rad / 2.0)

    return ReceiverConfig(
        name=station_name,
        input_coupler_loss_db=float(pol_ctrl.get("insertion_loss_db", 0.0)),
        basis_bs_ratio_z=float(ratio.get("transmission", 0.5)),
        basis_bs_ratio_x=float(ratio.get("reflection", 0.5)),
        basis_bs_insertion_loss_db=float(npbs.get("insertion_loss_db", 0.0)),
        z_pbs_loss_db=float(z_pbs.get("insertion_loss_db", 0.0)),
        x_pbs_loss_db=float(x_pbs.get("insertion_loss_db", 0.0)),
        eps_z=_extinction_leakage_prob(z_pbs),
        eps_x=_extinction_leakage_prob(x_pbs),
        angle_deg_x_hwp=float(hwp.get("angle_deg", 22.5)),
        angle_error_deg_sigma=angle_error_deg_sigma,
        detectors=detectors,
    )


def build_timing_config(manifest: YAMLManifest) -> TimingConfig:
    coincidence = manifest.protocol.get("protocol", {}).get("coincidence", {}) or {}
    sync = manifest.channels.get("channels", {}).get("time_sync_link", {}) or {}
    return TimingConfig(
        coincidence_window_ps=float(coincidence.get("window_ps", 1000.0)),
        time_sync_jitter_ps_rms=float(sync.get("latency_jitter_ps_rms", 0.0)),
    )


__all__ = [
    "YAMLManifest",
    "build_fiber_config",
    "build_source_config",
    "build_timing_config",
    "find_component_by_class",
    "receiver_config_from_node",
    "source_coupling_efficiency",
    "werner_visibility_from_fidelity",
]
