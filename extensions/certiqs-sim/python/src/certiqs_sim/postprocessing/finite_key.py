"""Finite-key secure-length analysis.

Computes the extractable secret-key length from a reconciled block of finite size,
accounting for the reconciliation leakage and the composable security parameters
(``epsilon_correct`` / ``epsilon_secret``) declared in ``01_protocol.yaml``.

The bound used is the standard finite-key expression (cf. Tomamichel et al. 2012;
Lim et al. 2014) specialised to an entanglement-based protocol with a symmetric
channel:

    ℓ = ⌊ n·(1 − h(e_ph)) − leak_EC − log2(2/ε_cor) − 2·log2(1/ε_PA) ⌋

where ``n`` is the number of key-generation bits, ``e_ph`` the phase-error upper
bound (from the publicly-sampled QBER + a finite-size fluctuation term), ``leak_EC``
the measured error-correction leakage, and ``ε_PA = ε_secret``.  In the asymptotic
limit with ``leak_EC → n·h(q)`` this reduces to the familiar ``n·(1 − 2h(q))``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _h2(x: float) -> float:
    from certiqs_sim.core.keyrate import binary_entropy2

    return binary_entropy2(x)


@dataclass
class FiniteKeyResult:
    n_bits: int
    phase_error_bound: float
    leak_ec_bits: float
    secure_key_bits: int
    secret_fraction: float
    epsilon_correct: float
    epsilon_secret: float


def finite_key_length(
    n_bits: int,
    qber_upper_bound: float,
    leak_ec_bits: float,
    epsilon_correct: float = 1e-12,
    epsilon_secret: float = 1e-12,
) -> FiniteKeyResult:
    """Return the finite-key secure length for a reconciled block."""
    n = max(0, int(n_bits))
    if n == 0:
        return FiniteKeyResult(
            0, qber_upper_bound, leak_ec_bits, 0, 0.0, epsilon_correct, epsilon_secret
        )

    e_ph = min(max(qber_upper_bound, 0.0), 0.5)
    eps_cor = min(max(epsilon_correct, 1e-300), 1.0)
    eps_pa = min(max(epsilon_secret, 1e-300), 1.0)

    correctness_penalty = math.log2(2.0 / eps_cor)
    secrecy_penalty = 2.0 * math.log2(1.0 / eps_pa)

    ell = n * (1.0 - _h2(e_ph)) - leak_ec_bits - correctness_penalty - secrecy_penalty
    secure = max(0, math.floor(ell))
    return FiniteKeyResult(
        n_bits=n,
        phase_error_bound=e_ph,
        leak_ec_bits=leak_ec_bits,
        secure_key_bits=secure,
        secret_fraction=secure / n if n else 0.0,
        epsilon_correct=eps_cor,
        epsilon_secret=eps_pa,
    )


__all__ = ["FiniteKeyResult", "finite_key_length"]
