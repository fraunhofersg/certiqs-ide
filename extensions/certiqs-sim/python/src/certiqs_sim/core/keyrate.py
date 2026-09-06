"""Asymptotic BBM92 key-rate helpers.

These give the *asymptotic* secret-key fraction used by the live twin for a quick
estimate.  The finite-key, error-correction-aware key length is computed by the
post-processing layer (``certiqs_sim.postprocessing.finite_key``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np


def binary_entropy2(q: float | None) -> float:
    if q is None:
        return float("nan")
    q = min(max(float(q), 0.0), 1.0)
    if q <= 0.0 or q >= 1.0:
        return 0.0
    return -(q * math.log2(q) + (1.0 - q) * math.log2(1.0 - q))


def asymptotic_bbm92_secret_key_fraction(qber: float | None) -> float:
    if qber is None:
        return 0.0
    if not np.isfinite(float(qber)):
        return 0.0
    return max(0.0, 1.0 - 2.0 * binary_entropy2(float(qber)))


def asymptotic_bbm92_key_rate_per_pulse(results: Mapping[str, Any], shots: int) -> float:
    if shots <= 0:
        return 0.0
    qber = results.get("qber")
    sifted_fraction = float(results.get("sifted_key_bits", 0)) / float(shots)
    return sifted_fraction * asymptotic_bbm92_secret_key_fraction(qber)


__all__ = [
    "asymptotic_bbm92_key_rate_per_pulse",
    "asymptotic_bbm92_secret_key_fraction",
    "binary_entropy2",
]
