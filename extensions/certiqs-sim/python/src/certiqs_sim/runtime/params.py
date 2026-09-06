"""Tunable-parameter metadata + apply/read helpers.

Single source of truth for the parameters the web UI exposes.  ``apply_overrides``
mutates the live twin's config dataclasses between simulation windows, so changes
take effect from the next epoch.  Attack / countermeasure application delegates to
the ``core.attacks`` / ``core.countermeasures`` registries so there is exactly one
wiring path shared by the live runtime and the security-evaluation service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import math
import numpy as np

from certiqs_sim.core.attacks import AttackConfig, get_attack_factory
from certiqs_sim.core.countermeasures import SelfTestConfig, get_countermeasure_factory
from certiqs_sim.core.countermeasures.detector_selftest import SELFTEST_MODES
from certiqs_sim.core.manifest import (
    YAMLManifest,
    build_fiber_config,
    build_source_config,
    build_timing_config,
    receiver_config_from_node,
)

DETECTOR_LABELS = ("H", "V", "D", "A")
#: The two measurement stations.  Each carries its own H/V/D/A detector set, so
#: the link has eight physically independent detectors in total.
STATIONS = ("alice", "bob")


BASE_PARAM_META: list[dict[str, Any]] = [
    {
        "key": "pair_prob",
        "label": "Pair generation probability",
        "min": 0.0,
        "max": 0.20,
        "step": 0.001,
    },
    {
        "key": "visibility",
        "label": "Intrinsic visibility (source fidelity)",
        "min": 0.0,
        "max": 1.0,
        "step": 0.001,
    },
    {
        "key": "alice_length",
        "label": "Alice fibre length (km)",
        "min": 0.0,
        "max": 100.0,
        "step": 0.1,
    },
    {"key": "bob_length", "label": "Bob fibre length (km)", "min": 0.0, "max": 100.0, "step": 0.1},
    {
        "key": "attenuation",
        "label": "Fibre attenuation (dB/km)",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "key": "wavelength",
        "label": "Fibre wavelength (nm)",
        "min": 1260.0,
        "max": 1675.0,
        "step": 1.0,
    },
    {
        "key": "alice_splices",
        "label": "Alice fibre splices",
        "min": 0.0,
        "max": 50.0,
        "step": 1.0,
    },
    {
        "key": "bob_splices",
        "label": "Bob fibre splices",
        "min": 0.0,
        "max": 50.0,
        "step": 1.0,
    },
    {
        "key": "splice_loss",
        "label": "Splice loss (dB each)",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "key": "alice_connectors",
        "label": "Alice fibre connectors",
        "min": 0.0,
        "max": 20.0,
        "step": 1.0,
    },
    {
        "key": "bob_connectors",
        "label": "Bob fibre connectors",
        "min": 0.0,
        "max": 20.0,
        "step": 1.0,
    },
    {
        "key": "connector_loss",
        "label": "Connector loss (dB each)",
        "min": 0.0,
        "max": 2.0,
        "step": 0.01,
    },
    {
        "key": "depolarization",
        "label": "Depolarization probability",
        "min": 0.0,
        "max": 0.20,
        "step": 0.001,
    },
    {"key": "pmd", "label": "PMD (ps)", "min": 0.0, "max": 200.0, "step": 1.0},
    {"key": "coupling", "label": "Coupling efficiency", "min": 0.0, "max": 1.0, "step": 0.01},
    {"key": "det_eff", "label": "Detector efficiency (all)", "min": 0.0, "max": 1.0, "step": 0.01},
    {"key": "dark", "label": "Dark count rate (all, Hz)", "min": 0.0, "max": 10000.0, "step": 10.0},
    # Per-detector overrides — all eight physical detectors (4 outcomes x 2
    # stations) are addressed independently.  Applied after the "all detectors"
    # keys above, so a request carrying both wins on the specific detector.
    *[
        {
            "key": f"det_eff_{station}_{label}",
            "label": f"{station.capitalize()} detector {label} efficiency",
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
        }
        for station in STATIONS
        for label in DETECTOR_LABELS
    ],
    *[
        {
            "key": f"dark_{station}_{label}",
            "label": f"{station.capitalize()} detector {label} dark count rate (Hz)",
            "min": 0.0,
            "max": 10000.0,
            "step": 10.0,
        }
        for station in STATIONS
        for label in DETECTOR_LABELS
    ],
    {
        "key": "bs_bias",
        "label": "Basis beamsplitter bias (Z fraction)",
        "min": 0.0,
        "max": 1.0,
        "step": 0.01,
    },
    {
        "key": "led_mean_photon",
        "label": "LED salt: mean photon number",
        "min": 0.0,
        "max": 100.0,
        "step": 0.1,
    },
    {
        "key": "led_on_prob",
        "label": "LED salt: on-probability per round",
        "min": 0.0,
        "max": 1.0,
        "step": 0.001,
    },
    {"key": "jitter", "label": "Detector jitter (ps RMS)", "min": 0.0, "max": 1000.0, "step": 1.0},
    {"key": "dead_time", "label": "Dead time (ns)", "min": 0.0, "max": 1000.0, "step": 1.0},
    {
        "key": "afterpulse",
        "label": "Afterpulse probability",
        "min": 0.0,
        "max": 0.20,
        "step": 0.001,
    },
    {
        "key": "window",
        "label": "Coincidence window (ps)",
        "min": 10.0,
        "max": 10000.0,
        "step": 10.0,
    },
    {
        "key": "sync_jitter",
        "label": "Time-sync jitter (ps RMS)",
        "min": 0.0,
        "max": 1000.0,
        "step": 1.0,
    },
]

ATTACK_PARAM_META: list[dict[str, Any]] = [
    {"key": "eve_eff", "label": "Eve detector efficiency", "min": 0.0, "max": 1.0, "step": 0.01},
    {"key": "extra_loss", "label": "Extra Eve loss (dB)", "min": 0.0, "max": 10.0, "step": 0.1},
    {"key": "trigger_prob", "label": "Trigger success prob", "min": 0.0, "max": 1.0, "step": 0.01},
    {"key": "suppression", "label": "Basis suppression prob", "min": 0.0, "max": 1.0, "step": 0.01},
    {"key": "induced_error", "label": "Induced error prob", "min": 0.0, "max": 0.10, "step": 0.001},
]

SELFTEST_PARAM_META: list[dict[str, Any]] = [
    {"key": "n_test_pulses", "label": "Flag: test pulses n", "min": 1.0, "max": 50.0, "step": 1.0},
    {
        "key": "n_threshold",
        "label": "Flag: pass threshold n_th",
        "min": 1.0,
        "max": 50.0,
        "step": 1.0,
    },
    {
        "key": "p_response_unblinded",
        "label": "Flag: p_s (normal)",
        "min": 0.0,
        "max": 1.0,
        "step": 0.001,
    },
    {
        "key": "p_response_blinded",
        "label": "Flag: p_f (blinded)",
        "min": 0.0,
        "max": 0.10,
        "step": 0.001,
    },
    {
        "key": "salt_mean_unblinded",
        "label": "Salt: mean normal",
        "min": 1.0,
        "max": 500.0,
        "step": 1.0,
    },
    {
        "key": "salt_mean_blinded",
        "label": "Salt: mean blinded",
        "min": 0.0,
        "max": 200.0,
        "step": 1.0,
    },
    {"key": "salt_threshold", "label": "Salt: threshold", "min": 1.0, "max": 500.0, "step": 1.0},
    {
        "key": "selfblind_runs",
        "label": "Self-blind: test runs",
        "min": 1.0,
        "max": 50.0,
        "step": 1.0,
    },
    {
        "key": "test_rate_hz",
        "label": "Test pulse rate r_t (Hz)",
        "min": 0.0,
        "max": 20000.0,
        "step": 100.0,
    },
    {
        "key": "detector_dead_time_ns",
        "label": "Detector dead time τ_D (ns)",
        "min": 0.0,
        "max": 5000.0,
        "step": 50.0,
    },
]


def _mean_detector(receiver: Any, attr: str) -> float:
    return float(np.mean([getattr(receiver.config.detectors[la], attr) for la in DETECTOR_LABELS]))


def _set_all_detectors(twin: Any, attr: str, value: float) -> None:
    for receiver in (twin.alice, twin.bob):
        for label in DETECTOR_LABELS:
            setattr(receiver.config.detectors[label], attr, value)


def _set_station_detector(
    twin: Any, station: str, label: str, attr: str, value: float
) -> None:
    """Set one attribute on a single physical detector (one station, one outcome)."""
    receiver = getattr(twin, station)
    setattr(receiver.config.detectors[label], attr, value)


def _per_detector_params(receiver_configs: dict[str, Any]) -> dict[str, float]:
    """Efficiency + dark rate for all eight detectors, keyed ``<attr>_<station>_<label>``."""
    out: dict[str, float] = {}
    for station, cfg in receiver_configs.items():
        for label in DETECTOR_LABELS:
            det = cfg.detectors[label]
            out[f"det_eff_{station}_{label}"] = float(det.efficiency)
            out[f"dark_{station}_{label}"] = float(det.dark_count_hz)
    return out


def read_current_params(twin: Any) -> dict[str, float]:
    s = twin.source.config
    a = twin.chan_to_alice.config
    b = twin.chan_to_bob.config
    t = twin.timing
    return {
        "pair_prob": s.pair_generation_probability_per_pulse,
        "visibility": s.intrinsic_visibility,
        "alice_length": a.length_km,
        "bob_length": b.length_km,
        "attenuation": a.attenuation_db_per_km,
        "wavelength": a.wavelength_nm,
        "alice_splices": float(a.num_splices),
        "bob_splices": float(b.num_splices),
        "splice_loss": a.splice_loss_db,
        "alice_connectors": float(a.num_connectors),
        "bob_connectors": float(b.num_connectors),
        "connector_loss": a.connector_loss_db,
        "depolarization": a.depolarization_prob,
        "pmd": a.pmd_ps,
        "coupling": a.coupling_efficiency,
        "det_eff": _mean_detector(twin.alice, "efficiency"),
        "dark": _mean_detector(twin.alice, "dark_count_hz"),
        "jitter": _mean_detector(twin.alice, "jitter_ps_rms"),
        "dead_time": _mean_detector(twin.alice, "dead_time_ns"),
        "afterpulse": _mean_detector(twin.alice, "afterpulse_prob"),
        "window": t.coincidence_window_ps,
        "sync_jitter": t.time_sync_jitter_ps_rms,
        "bs_bias": twin.alice.config.basis_bs_bias,
        "led_mean_photon": float(twin.alice.config.led.mean_photon_number),
        "led_on_prob": float(twin.alice.config.led.on_probability),
        **_per_detector_params(
            {station: getattr(twin, station).config for station in STATIONS}
        ),
    }


def default_params_for_config(yaml_dir: Any) -> dict[str, float]:
    """Read default base parameters straight from a YAML directory WITHOUT
    building a NetSquid twin (which would reset the global engine)."""
    man = YAMLManifest.from_directory(Path(yaml_dir))
    s = build_source_config(man)
    a = build_fiber_config(man, "quantum_to_alice", "alice")
    b = build_fiber_config(man, "quantum_to_bob", "bob")
    alice = receiver_config_from_node(man.alice, "alice")
    bob = receiver_config_from_node(man.bob, "bob")
    t = build_timing_config(man)

    def mean_det(attr: str) -> float:
        """Mean across all eight detectors (both stations)."""
        return float(
            np.mean(
                [
                    getattr(cfg.detectors[la], attr)
                    for cfg in (alice, bob)
                    for la in DETECTOR_LABELS
                ]
            )
        )

    return {
        "pair_prob": s.pair_generation_probability_per_pulse,
        "visibility": s.intrinsic_visibility,
        "alice_length": a.length_km,
        "bob_length": b.length_km,
        "attenuation": a.attenuation_db_per_km,
        "wavelength": a.wavelength_nm,
        "alice_splices": float(a.num_splices),
        "bob_splices": float(b.num_splices),
        "splice_loss": a.splice_loss_db,
        "alice_connectors": float(a.num_connectors),
        "bob_connectors": float(b.num_connectors),
        "connector_loss": a.connector_loss_db,
        "depolarization": a.depolarization_prob,
        "pmd": a.pmd_ps,
        "coupling": a.coupling_efficiency,
        "det_eff": mean_det("efficiency"),
        "dark": mean_det("dark_count_hz"),
        "jitter": mean_det("jitter_ps_rms"),
        "dead_time": mean_det("dead_time_ns"),
        "afterpulse": mean_det("afterpulse_prob"),
        "window": t.coincidence_window_ps,
        "sync_jitter": t.time_sync_jitter_ps_rms,
        "bs_bias": alice.basis_bs_bias,
        "led_mean_photon": float(alice.led.mean_photon_number),
        "led_on_prob": float(alice.led.on_probability),
        **_per_detector_params({"alice": alice, "bob": bob}),
    }


def _set_fiber_length(channel: Any, length_km: float) -> None:
    """Update fibre length on the live config and NetSquid channel.

    Also rescale ``pmd_ps`` with √L (same convention as channel build) so noise
    tracks link length when the YAML coefficient was baked in at construction.
    """
    cfg = channel.config
    old = max(float(cfg.length_km), 0.0)
    new = max(float(length_km), 0.0)
    if old > 1e-12 and float(cfg.pmd_ps) > 0.0:
        cfg.pmd_ps = float(cfg.pmd_ps) * math.sqrt(new / old)
    elif old <= 1e-12 and new > 0.0:
        # Near-zero stub fibre: keep existing absolute PMD (usually 0).
        pass
    cfg.length_km = new
    channel.sync_netsquid()


def apply_overrides(twin: Any, overrides: dict[str, float]) -> None:
    """Mutate the twin's config dataclasses in place; partial updates supported."""
    if not overrides:
        return
    o = overrides

    if "pair_prob" in o:
        twin.source.config.pair_generation_probability_per_pulse = float(o["pair_prob"])
    if "visibility" in o:
        twin.source.config.intrinsic_visibility = float(o["visibility"])

    if "alice_length" in o:
        _set_fiber_length(twin.chan_to_alice, float(o["alice_length"]))
    if "bob_length" in o:
        _set_fiber_length(twin.chan_to_bob, float(o["bob_length"]))

    if "alice_splices" in o:
        twin.chan_to_alice.config.num_splices = max(int(round(float(o["alice_splices"]))), 0)
    if "bob_splices" in o:
        twin.chan_to_bob.config.num_splices = max(int(round(float(o["bob_splices"]))), 0)
    if "alice_connectors" in o:
        twin.chan_to_alice.config.num_connectors = max(
            int(round(float(o["alice_connectors"]))), 0
        )
    if "bob_connectors" in o:
        twin.chan_to_bob.config.num_connectors = max(int(round(float(o["bob_connectors"]))), 0)

    for ch in (twin.chan_to_alice.config, twin.chan_to_bob.config):
        if "attenuation" in o:
            ch.attenuation_db_per_km = float(o["attenuation"])
        if "wavelength" in o:
            ch.wavelength_nm = float(o["wavelength"])
        if "splice_loss" in o:
            ch.splice_loss_db = max(float(o["splice_loss"]), 0.0)
        if "connector_loss" in o:
            ch.connector_loss_db = max(float(o["connector_loss"]), 0.0)
        if "depolarization" in o:
            ch.depolarization_prob = float(o["depolarization"])
        if "pmd" in o:
            ch.pmd_ps = float(o["pmd"])
        if "coupling" in o:
            ch.coupling_efficiency = float(o["coupling"])

    if "det_eff" in o:
        _set_all_detectors(twin, "efficiency", min(max(float(o["det_eff"]), 0.0), 1.0))
    if "dark" in o:
        _set_all_detectors(twin, "dark_count_hz", float(o["dark"]))
    if "jitter" in o:
        _set_all_detectors(twin, "jitter_ps_rms", float(o["jitter"]))
    if "dead_time" in o:
        _set_all_detectors(twin, "dead_time_ns", float(o["dead_time"]))
    if "afterpulse" in o:
        _set_all_detectors(twin, "afterpulse_prob", float(o["afterpulse"]))

    # Per-detector overrides run after the "all detectors" keys so that a payload
    # carrying both (e.g. det_eff plus det_eff_alice_H) leaves the specific
    # detector's value winning.
    for station in STATIONS:
        for label in DETECTOR_LABELS:
            eff_key = f"det_eff_{station}_{label}"
            if eff_key in o:
                _set_station_detector(
                    twin, station, label, "efficiency", min(max(float(o[eff_key]), 0.0), 1.0)
                )
            dark_key = f"dark_{station}_{label}"
            if dark_key in o:
                _set_station_detector(
                    twin, station, label, "dark_count_hz", max(float(o[dark_key]), 0.0)
                )

    if "bs_bias" in o:
        for receiver in (twin.alice, twin.bob):
            receiver.config.set_basis_bs_bias(float(o["bs_bias"]))

    if "led_mean_photon" in o or "led_on_prob" in o:
        for receiver in (twin.alice, twin.bob):
            led = receiver.config.led
            if "led_mean_photon" in o:
                led.mean_photon_number = max(float(o["led_mean_photon"]), 0.0)
            if "led_on_prob" in o:
                led.on_probability = min(max(float(o["led_on_prob"]), 0.0), 1.0)
            # Salt mode is active exactly when the emitter can actually fire.
            led.enabled = led.mean_photon_number > 0.0 and led.on_probability > 0.0

    if "window" in o:
        twin.timing.coincidence_window_ps = float(o["window"])
    if "sync_jitter" in o:
        twin.timing.time_sync_jitter_ps_rms = float(o["sync_jitter"])


def read_attack_params(twin: Any) -> dict[str, Any]:
    atk = twin.attack
    cfg = atk.config if atk is not None else AttackConfig()
    return {
        "enabled": bool(cfg.enabled and atk is not None),
        "eve_eff": cfg.eve_detection_efficiency,
        "extra_loss": cfg.extra_loss_db,
        "trigger_prob": cfg.trigger_success_prob,
        "suppression": cfg.wrong_basis_suppression_prob,
        "induced_error": cfg.induced_error_prob,
        "passive_basis_choice": cfg.passive_basis_choice,
    }


def apply_attack(twin: Any, attack_settings: dict[str, Any]) -> None:
    """Enable/disable/tune the faked-state attack live (delegates to the registry)."""
    get_attack_factory("faked_state")(twin, attack_settings or {})


def read_selftest_params(twin: Any) -> dict[str, Any]:
    st = twin.self_test
    cfg = st.config if st is not None else SelfTestConfig()
    return {
        "enabled": bool(cfg.enabled and st is not None),
        "mode": cfg.mode,
        "apply_to_detection": cfg.apply_to_detection,
        "n_test_pulses": cfg.n_test_pulses,
        "n_threshold": cfg.n_threshold,
        "p_response_unblinded": cfg.p_response_unblinded,
        "p_response_blinded": cfg.p_response_blinded,
        "salt_mean_unblinded": cfg.salt_mean_unblinded,
        "salt_mean_blinded": cfg.salt_mean_blinded,
        "salt_threshold": cfg.salt_threshold,
        "selfblind_runs": cfg.selfblind_runs,
        "test_rate_hz": cfg.test_rate_hz,
        "detector_dead_time_ns": cfg.detector_dead_time_ns,
    }


def apply_selftest(twin: Any, settings: dict[str, Any]) -> None:
    """Enable/disable/tune the detector self-testing countermeasure live."""
    get_countermeasure_factory("detector_selftest")(twin, settings or {})


__all__ = [
    "ATTACK_PARAM_META",
    "BASE_PARAM_META",
    "DETECTOR_LABELS",
    "SELFTEST_MODES",
    "SELFTEST_PARAM_META",
    "apply_attack",
    "apply_overrides",
    "apply_selftest",
    "default_params_for_config",
    "read_attack_params",
    "read_current_params",
    "read_selftest_params",
]
