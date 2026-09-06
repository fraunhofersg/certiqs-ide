"""Optical receiver model with YAML-driven detector imperfections.

Behaviour-preserving port of the reference ``OpticalReceiver``: efficiency-folded
POVMs (basis BS routing, PBS leakage, HWP misalignment, per-detector efficiency)
plus dark counts, dead time, afterpulses, jitter and no-click / multi-click
handling.  NetSquid has no comparable single-photon-detector model, so this stage
runs in NumPy on the joint reduced density matrix NetSquid hands back.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any

import numpy as np

from certiqs_sim.core.config_models import ReceiverConfig
from certiqs_sim.core.linalg import (
    I2,
    OUTCOME_TO_BASIS_BIT,
    PH,
    PV,
    db_to_efficiency,
    hermitian_psd_clip,
)


class OpticalReceiver:
    CLICK_LABELS: tuple[str, ...] = ("H", "V", "D", "A")

    def __init__(self, config: ReceiverConfig):
        self.config = config
        # Optional delegation of the optical POVM to the rx-povm microservice.
        # When unset the local analytic model below is used unchanged.
        self.povm_provider: Any = None
        self.povm_strict: bool = False
        #: Needed to express detector dark-count *rates* as per-gate probabilities
        #: in the receiver model sent to the service.
        self.coincidence_window_ps: float = 0.0
        #: Whether the self-test LED fired on the most recent shot.
        self.last_led_fired: bool = False
        self.last_click_time_ps: dict[str, float] = dict.fromkeys(self.config.detectors, -1e30)
        # Time-correlated afterpulsing: when a detector registers a click it may
        # *arm* a single afterpulse that fires at the first live gate after dead
        # time.  ``inf`` means no afterpulse is pending for that detector.
        self.afterpulse_fire_time_ps: dict[str, float] = dict.fromkeys(
            self.config.detectors, math.inf
        )
        self.stats: Counter = Counter()

    @staticmethod
    def _db_to_efficiency(loss_db: float) -> float:
        return db_to_efficiency(loss_db)

    def povm_elements(self, transmission_eta: float) -> dict[str, np.ndarray]:
        """Efficiency-folded measurement POVM for this receiver.

        Delegates to the rx-povm microservice when a provider is attached, which
        also samples whether the self-test LED fires on this shot (an LED-on round
        is evaluated against a thermal input state instead of vacuum).  Dark
        counts, dead time and afterpulsing remain the responsibility of
        :meth:`realize_event` in both paths, so they are never double-counted.
        """
        if self.povm_provider is not None:
            elements = self._service_povm_elements(transmission_eta)
            if elements is not None:
                return elements
        return self._local_povm_elements(transmission_eta)

    def _service_povm_elements(self, transmission_eta: float) -> dict[str, np.ndarray] | None:
        led_firing = self.config.led.fires_this_round(random)
        self.last_led_fired = led_firing
        if led_firing:
            self.stats["led_salt_fired"] += 1
        try:
            povm = self.povm_provider.povm_elements(
                self.config,
                transmission_eta,
                coincidence_window_ps=self.coincidence_window_ps,
                led_firing=led_firing,
                include_dark_counts=False,
            )
        except Exception:
            self.stats["povm_service_errors"] += 1
            if self.povm_strict:
                raise
            return None
        self.stats["povm_service_elements"] += 1
        return povm.as_measurement_povm()

    def _local_povm_elements(self, transmission_eta: float) -> dict[str, np.ndarray]:
        c = self.config
        path_eta_in = self._db_to_efficiency(c.input_coupler_loss_db)
        path_eta_bs = self._db_to_efficiency(c.basis_bs_insertion_loss_db)
        path_eta_z = self._db_to_efficiency(c.z_pbs_loss_db)
        path_eta_x = self._db_to_efficiency(c.x_pbs_loss_db)

        norm = max(c.basis_bs_ratio_z + c.basis_bs_ratio_x, 1e-12)
        rz_arm = c.basis_bs_ratio_z / norm
        rx_arm = c.basis_bs_ratio_x / norm

        hwp_angle_rad = math.radians(c.angle_deg_x_hwp + random.gauss(0.0, c.angle_error_deg_sigma))
        theta = 2.0 * hwp_angle_rad
        d_eff = np.array([[math.cos(theta)], [math.sin(theta)]], dtype=complex)
        a_eff = np.array([[-math.sin(theta)], [math.cos(theta)]], dtype=complex)
        PDeff = d_eff @ d_eff.conj().T
        PAeff = a_eff @ a_eff.conj().T

        path_common = min(max(transmission_eta * path_eta_in * path_eta_bs, 0.0), 1.0)

        eta_H = path_common * path_eta_z * c.detectors["H"].efficiency
        eta_V = path_common * path_eta_z * c.detectors["V"].efficiency
        eta_D = path_common * path_eta_x * c.detectors["D"].efficiency
        eta_A = path_common * path_eta_x * c.detectors["A"].efficiency

        E_H = rz_arm * eta_H * ((1.0 - c.eps_z) * PH + c.eps_z * PV)
        E_V = rz_arm * eta_V * (c.eps_z * PH + (1.0 - c.eps_z) * PV)
        E_D = rx_arm * eta_D * ((1.0 - c.eps_x) * PDeff + c.eps_x * PAeff)
        E_A = rx_arm * eta_A * (c.eps_x * PDeff + (1.0 - c.eps_x) * PAeff)

        E_sum = E_H + E_V + E_D + E_A
        E_no = hermitian_psd_clip(I2 - E_sum)

        return {
            "H": hermitian_psd_clip(E_H),
            "V": hermitian_psd_clip(E_V),
            "D": hermitian_psd_clip(E_D),
            "A": hermitian_psd_clip(E_A),
            "no_click": E_no,
        }

    def _detector_live(self, label: str, event_time_ps: float) -> bool:
        det = self.config.detectors[label]
        dead_time_ps = det.dead_time_ns * 1e3
        return (event_time_ps - self.last_click_time_ps[label]) >= dead_time_ps

    def _dark_probability(self, label: str, window_s: float) -> float:
        det = self.config.detectors[label]
        p_dark = 1.0 - math.exp(-max(0.0, det.dark_count_hz) * max(0.0, window_s))
        return min(max(p_dark, 0.0), 1.0)

    def _arm_afterpulse(self, label: str, click_time_ps: float) -> None:
        det = self.config.detectors[label]
        p = min(max(det.afterpulse_prob, 0.0), 1.0)
        if p > 0.0 and random.random() < p:
            self.afterpulse_fire_time_ps[label] = click_time_ps + det.dead_time_ns * 1e3

    def _sample_false_clicks(
        self, event_time_ps: float, window_s: float
    ) -> tuple[set[str], dict[str, str]]:
        false_clicks: set[str] = set()
        causes: dict[str, str] = {}

        for label in self.CLICK_LABELS:
            if not self._detector_live(label, event_time_ps):
                self.stats[f"{label}:dead_time_suppressed_false_gate"] += 1
                continue

            afterpulsed = event_time_ps >= self.afterpulse_fire_time_ps[label]
            if afterpulsed:
                self.afterpulse_fire_time_ps[label] = math.inf

            darked = random.random() < self._dark_probability(label, window_s)

            if afterpulsed or darked:
                false_clicks.add(label)
                if afterpulsed:
                    causes[label] = "afterpulse"
                    self.stats[f"{label}:afterpulse_click"] += 1
                else:
                    causes[label] = "dark"
                    self.stats[f"{label}:dark_click"] += 1

        return false_clicks, causes

    def realize_event(
        self,
        signal_label: str,
        base_time_ps: float,
        window_ps: float,
        sync_jitter_ps_rms: float,
    ) -> tuple[str, dict[str, Any] | None]:
        window_s = max(0.0, window_ps) * 1e-12
        event_time_ps = base_time_ps

        candidate_causes: dict[str, str] = {}

        if signal_label in self.CLICK_LABELS:
            if self._detector_live(signal_label, event_time_ps):
                candidate_causes[signal_label] = "signal"
                self.stats[f"{signal_label}:signal_click_candidate"] += 1
            else:
                self.stats[f"{signal_label}:dead_time_suppressed_signal"] += 1

        false_clicks, false_causes = self._sample_false_clicks(event_time_ps, window_s)
        for label in false_clicks:
            if label in candidate_causes:
                candidate_causes[label] = candidate_causes[label] + "+" + false_causes[label]
            else:
                candidate_causes[label] = false_causes[label]

        if not candidate_causes:
            self.stats["no_click"] += 1
            return "no_click", None

        if len(candidate_causes) > 1:
            self.stats["multi_click_discarded"] += 1
            return "multi_click", None

        label, cause = next(iter(candidate_causes.items()))
        det = self.config.detectors[label]
        measured_time_ps = (
            event_time_ps
            + random.gauss(0.0, det.jitter_ps_rms)
            + random.gauss(0.0, sync_jitter_ps_rms)
        )
        self.last_click_time_ps[label] = measured_time_ps
        self._arm_afterpulse(label, measured_time_ps)
        self.stats[f"{label}:registered_{cause}"] += 1
        self.stats["registered_clicks"] += 1

        basis, bit = OUTCOME_TO_BASIS_BIT[label]
        event = {
            "timestamp_ps": round(measured_time_ps),
            "ideal_arrival_time_ps": round(event_time_ps),
            "channel_id": det.channel_id,
            "basis": basis,
            "bit": bit,
            "state": label,
            "cause": cause,
            "detector_efficiency": det.efficiency,
            "dark_count_hz": det.dark_count_hz,
            "jitter_ps_rms": det.jitter_ps_rms,
            "dead_time_ns": det.dead_time_ns,
            "afterpulse_prob": det.afterpulse_prob,
            "valid": 1,
        }
        return label, event


__all__ = ["OpticalReceiver"]
