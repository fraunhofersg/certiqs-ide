"""QBER estimation by public sampling.

Implements the ``qber_estimation.sample_fraction`` step from ``01_protocol.yaml``:
a random fraction of the sifted bits is publicly revealed to estimate the error
rate.  Those sample bits are then *discarded* from the key (they were disclosed),
leaving the remaining bits for error correction and privacy amplification.  A
one-sided Clopper–Pearson-style upper bound on the true QBER is returned for the
finite-key analysis.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class QberEstimate:
    sampled: int
    sample_errors: int
    qber_estimate: float
    qber_upper_bound: float
    remaining_length: int


def _hoeffding_upper_bound(qber: float, n: int, epsilon: float) -> float:
    """One-sided Hoeffding upper confidence bound on the sampled error rate."""
    if n <= 0:
        return 1.0
    slack = math.sqrt(math.log(1.0 / max(epsilon, 1e-300)) / (2.0 * n))
    return min(1.0, qber + slack)


def estimate_qber(
    alice_bits: Sequence[int],
    bob_bits: Sequence[int],
    sample_fraction: float = 0.1,
    epsilon: float = 1e-10,
    rng: random.Random | None = None,
) -> tuple[QberEstimate, list[int], list[int]]:
    """Publicly sample ``sample_fraction`` of the sifted bits to estimate QBER.

    Returns the estimate plus the *remaining* (unrevealed) Alice/Bob bits that go
    on to error correction.
    """
    if len(alice_bits) != len(bob_bits):
        raise ValueError("Alice/Bob sifted blocks differ in length")
    rng = rng or random.Random()
    n = len(alice_bits)
    if n == 0:
        return QberEstimate(0, 0, 0.0, 1.0, 0), [], []

    sample_size = min(n, max(0, round(sample_fraction * n)))
    sample_idx = set(rng.sample(range(n), sample_size)) if sample_size else set()

    sample_errors = 0
    remaining_a: list[int] = []
    remaining_b: list[int] = []
    for i in range(n):
        a, b = int(alice_bits[i]) & 1, int(bob_bits[i]) & 1
        if i in sample_idx:
            sample_errors += int(a != b)
        else:
            remaining_a.append(a)
            remaining_b.append(b)

    qber_est = sample_errors / sample_size if sample_size else 0.0
    qber_ub = _hoeffding_upper_bound(qber_est, sample_size, epsilon)
    return (
        QberEstimate(
            sampled=sample_size,
            sample_errors=sample_errors,
            qber_estimate=qber_est,
            qber_upper_bound=qber_ub,
            remaining_length=len(remaining_a),
        ),
        remaining_a,
        remaining_b,
    )


__all__ = ["QberEstimate", "estimate_qber"]
