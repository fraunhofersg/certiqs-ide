"""Detector self-testing countermeasure against detector-manipulation attacks.

Behaviour-preserving port of the scheme of Shen & Kurtsiefer, "Countering
detector manipulation attacks in quantum communication through detector
self-testing," APL Photonics 10, 016106 (2025).

A Light Emitter fired at private, random times reveals a blinded detector: a
manipulated detector ignores the weak test light and responds only to Eve's
bright fake states.  Three modes are modelled per reporting window — ``flag``,
``salt``, and ``self_blinding``.  ``blinded`` is True exactly when the faked-state
attack is active on Bob.  The key result: with the attack on, QBER stays low but
the self-test alarm fires.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb, exp
from typing import Any

import numpy as np

from certiqs_sim.core.countermeasures.base import register_countermeasure

SELFTEST_MODES: list[str] = ["flag", "salt", "self_blinding"]


def binom_tail_ge(n: int, k_th: int, p: float) -> float:
    """P(X >= k_th) for X ~ Binomial(n, p)."""
    n = max(0, int(n))
    k_th = min(max(0, int(k_th)), n)
    p = min(max(float(p), 0.0), 1.0)
    return float(sum(comb(n, k) * p**k * (1.0 - p) ** (n - k) for k in range(k_th, n + 1)))


def poisson_cdf_le(m: int, lam: float) -> float:
    """P(X <= m) for X ~ Poisson(lam)."""
    m = max(0, int(m))
    lam = max(0.0, float(lam))
    total = 0.0
    term = exp(-lam)
    for k in range(0, m + 1):
        total += term
        term *= lam / (k + 1)
    return min(max(total, 0.0), 1.0)


@dataclass
class SelfTestConfig:
    """Tunable parameters for detector self-testing (paper values as defaults)."""

    enabled: bool = False
    mode: str = "flag"
    apply_to_detection: bool = True

    # flag mode (short bright pulses)
    n_test_pulses: int = 10
    n_threshold: int = 4
    p_response_unblinded: float = 0.934
    p_response_blinded: float = 0.003

    # salt mode (low LE power over interval T)
    salt_mean_unblinded: float = 100.0
    salt_mean_blinded: float = 10.0
    salt_threshold: float = 50.0

    # self-blinding mode (local blinding)
    selfblind_runs: int = 10
    selfblind_flag_prob_unblinded: float = 0.976
    selfblind_flag_prob_blinded: float = 0.10
    selfblind_leak_prob_blinded: float = 0.976
    selfblind_leak_prob_normal: float = 0.001
    selfblind_flag_threshold: int = 5

    # timing / duty cost
    test_rate_hz: float = 2000.0
    detector_dead_time_ns: float = 1000.0


class DetectorSelfTest:
    """Runs one self-test evaluation per reporting window and reports whether a
    detector manipulation is detected, plus the statistical power / false-alarm
    rate of the test."""

    def __init__(self, config: SelfTestConfig) -> None:
        self.config = config

    def duty_loss(self) -> float:
        """Fraction of signal-detection opportunities lost to self-testing,
        eta_t = tau_D * r_t (paper); ~0.2% for the defaults."""
        c = self.config
        eta = max(0.0, c.test_rate_hz) * max(0.0, c.detector_dead_time_ns) * 1e-9
        return min(max(eta, 0.0), 0.999)

    def run(self, blinded: bool) -> dict[str, Any]:
        mode = self.config.mode
        if mode == "salt":
            out = self._run_salt(blinded)
        elif mode == "self_blinding":
            out = self._run_self_blinding(blinded)
        else:
            out = self._run_flag(blinded)

        out.update(
            {
                "selftest_enabled": True,
                "selftest_mode": mode,
                "selftest_blinded_truth": bool(blinded),
                "selftest_duty_loss": self.duty_loss(),
            }
        )
        return out

    def _run_flag(self, blinded: bool) -> dict[str, Any]:
        c = self.config
        n, n_th = int(c.n_test_pulses), int(c.n_threshold)
        p_s, p_f = c.p_response_unblinded, c.p_response_blinded

        p_eff = p_f if blinded else p_s
        k = int(np.random.binomial(n, min(max(p_eff, 0.0), 1.0)))
        alarm = k < n_th

        pass_prob_normal = binom_tail_ge(n, n_th, p_s)
        pass_prob_blinded = binom_tail_ge(n, n_th, p_f)
        return {
            "selftest_statistic": float(k),
            "selftest_statistic_max": float(n),
            "selftest_alarm": int(alarm),
            "selftest_false_alarm_prob": float(1.0 - pass_prob_normal),
            "selftest_detection_power": float(1.0 - pass_prob_blinded),
        }

    def _run_salt(self, blinded: bool) -> dict[str, Any]:
        c = self.config
        thr = c.salt_threshold
        mean_eff = c.salt_mean_blinded if blinded else c.salt_mean_unblinded
        count = int(np.random.poisson(max(0.0, mean_eff)))
        alarm = count < thr

        m = int(thr) - 1
        false_alarm = poisson_cdf_le(m, c.salt_mean_unblinded)
        detection_power = poisson_cdf_le(m, c.salt_mean_blinded)
        return {
            "selftest_statistic": float(count),
            "selftest_statistic_max": float(max(c.salt_mean_unblinded * 2.0, thr)),
            "selftest_alarm": int(alarm),
            "selftest_false_alarm_prob": float(false_alarm),
            "selftest_detection_power": float(detection_power),
        }

    def _run_self_blinding(self, blinded: bool) -> dict[str, Any]:
        c = self.config
        runs = int(c.selfblind_runs)

        p_flag = c.selfblind_flag_prob_blinded if blinded else c.selfblind_flag_prob_unblinded
        p_leak = c.selfblind_leak_prob_blinded if blinded else c.selfblind_leak_prob_normal
        flag_count = int(np.random.binomial(runs, min(max(p_flag, 0.0), 1.0)))
        leak_count = int(np.random.binomial(runs, min(max(p_leak, 0.0), 1.0)))

        alarm = (leak_count > 0) or (flag_count < int(c.selfblind_flag_threshold))

        p_no_leak_attacked = (1.0 - c.selfblind_leak_prob_blinded) ** runs
        p_flag_ok_attacked = binom_tail_ge(
            runs, int(c.selfblind_flag_threshold), c.selfblind_flag_prob_blinded
        )
        detection_power = 1.0 - p_no_leak_attacked * p_flag_ok_attacked
        p_leak_normal = 1.0 - (1.0 - c.selfblind_leak_prob_normal) ** runs
        p_flag_low_normal = 1.0 - binom_tail_ge(
            runs, int(c.selfblind_flag_threshold), c.selfblind_flag_prob_unblinded
        )
        false_alarm = 1.0 - (1.0 - p_leak_normal) * (1.0 - p_flag_low_normal)
        return {
            "selftest_statistic": float(leak_count),
            "selftest_statistic_max": float(runs),
            "selftest_flag_count": float(flag_count),
            "selftest_alarm": int(alarm),
            "selftest_false_alarm_prob": float(min(max(false_alarm, 0.0), 1.0)),
            "selftest_detection_power": float(min(max(detection_power, 0.0), 1.0)),
        }


@register_countermeasure("detector_selftest")
def build_detector_selftest(twin: Any, params: dict[str, Any]) -> Any:
    """Install (or clear) the detector self-testing countermeasure on ``twin``."""
    if not bool(params.get("enabled", False)):
        twin.self_test = None
        return None

    defaults = SelfTestConfig()

    def _num(key: str, cast: Any = float) -> Any:
        return cast(params[key]) if params.get(key) is not None else getattr(defaults, key)

    mode = str(params.get("mode", defaults.mode))
    if mode not in SELFTEST_MODES:
        mode = defaults.mode
    cfg = SelfTestConfig(
        enabled=True,
        mode=mode,
        apply_to_detection=bool(params.get("apply_to_detection", True)),
        n_test_pulses=_num("n_test_pulses", int),
        n_threshold=_num("n_threshold", int),
        p_response_unblinded=_num("p_response_unblinded"),
        p_response_blinded=_num("p_response_blinded"),
        salt_mean_unblinded=_num("salt_mean_unblinded"),
        salt_mean_blinded=_num("salt_mean_blinded"),
        salt_threshold=_num("salt_threshold"),
        selfblind_runs=_num("selfblind_runs", int),
        test_rate_hz=_num("test_rate_hz"),
        detector_dead_time_ns=_num("detector_dead_time_ns"),
    )
    st = DetectorSelfTest(cfg)
    twin.self_test = st
    return st


__all__ = [
    "SELFTEST_MODES",
    "DetectorSelfTest",
    "SelfTestConfig",
    "binom_tail_ge",
    "build_detector_selftest",
    "poisson_cdf_le",
]
