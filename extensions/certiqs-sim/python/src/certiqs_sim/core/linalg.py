"""Density-matrix linear-algebra utilities.

Framework-free helpers extracted from the original monolithic physics module.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

import numpy as np

C_M_PER_S = 299_792_458.0
FIBER_GROUP_INDEX = 1.468
DEFAULT_COHERENCE_TIME_PS = 50.0

I2 = np.eye(2, dtype=complex)
I4 = np.eye(4, dtype=complex)

H = np.array([[1.0], [0.0]], dtype=complex)
V = np.array([[0.0], [1.0]], dtype=complex)
D = (H + V) / np.sqrt(2.0)
A = (H - V) / np.sqrt(2.0)

PH = H @ H.conj().T
PV = V @ V.conj().T
PD = D @ D.conj().T
PA = A @ A.conj().T

X = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=complex)
Y = np.array([[0.0, -1j], [1j, 0.0]], dtype=complex)
Z = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=complex)

phi_plus = np.array([[1.0], [0.0], [0.0], [1.0]], dtype=complex) / np.sqrt(2.0)
rho_phi_plus = phi_plus @ phi_plus.conj().T

OUTCOME_TO_BASIS_BIT: dict[str, tuple[str, int]] = {
    "H": ("Z", 0),
    "V": ("Z", 1),
    "D": ("X", 0),
    "A": ("X", 1),
}


def kron(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.kron(a, b)


def ry(theta: float) -> np.ndarray:
    c = np.cos(theta / 2.0)
    s = np.sin(theta / 2.0)
    return np.array([[c, -s], [s, c]], dtype=complex)


def rz(theta: float) -> np.ndarray:
    return np.array(
        [[np.exp(-1j * theta / 2.0), 0.0], [0.0, np.exp(1j * theta / 2.0)]],
        dtype=complex,
    )


def random_su2(sigma_rad: float) -> np.ndarray:
    theta = random.gauss(0.0, sigma_rad)
    phi = random.gauss(0.0, sigma_rad)
    psi = random.gauss(0.0, sigma_rad)
    return rz(phi) @ ry(theta) @ rz(psi)


def apply_local_unitary(rho_ab: np.ndarray, U: np.ndarray, side: str) -> np.ndarray:
    op = kron(U, I2) if side == "alice" else kron(I2, U)
    return op @ rho_ab @ op.conj().T


def apply_local_pauli_channel(rho_ab: np.ndarray, probs: dict[str, float], side: str) -> np.ndarray:
    ops = {"I": I2, "X": X, "Y": Y, "Z": Z}
    out = np.zeros_like(rho_ab, dtype=complex)
    for label, p in probs.items():
        if p <= 0.0:
            continue
        P = ops[label]
        op = kron(P, I2) if side == "alice" else kron(I2, P)
        out += float(p) * (op @ rho_ab @ op.conj().T)
    return out


def normalize_probabilities(prob_dict: Mapping[Any, float]) -> dict[Any, float]:
    cleaned = {k: max(0.0, float(v)) for k, v in prob_dict.items()}
    total = sum(cleaned.values())
    if total <= 0.0:
        first_key = next(iter(cleaned), None)
        return {first_key: 1.0} if first_key is not None else {}
    return {k: v / total for k, v in cleaned.items()}


def sample_from_probs(prob_dict: Mapping[Any, float]) -> Any:
    normalized = normalize_probabilities(prob_dict)
    labels = list(normalized.keys())
    probs = np.array([normalized[k] for k in labels], dtype=float)
    idx = np.random.choice(len(labels), p=probs)
    return labels[idx]


def hermitian_psd_clip(mat: np.ndarray) -> np.ndarray:
    hmat = 0.5 * (mat + mat.conj().T)
    eigvals, eigvecs = np.linalg.eigh(hmat)
    eigvals = np.clip(eigvals, 0.0, None)
    return eigvecs @ np.diag(eigvals) @ eigvecs.conj().T


def db_to_efficiency(loss_db: float) -> float:
    return 10 ** (-max(0.0, float(loss_db)) / 10.0)


__all__ = [
    "C_M_PER_S",
    "DEFAULT_COHERENCE_TIME_PS",
    "FIBER_GROUP_INDEX",
    "I2",
    "I4",
    "OUTCOME_TO_BASIS_BIT",
    "PA",
    "PD",
    "PH",
    "PV",
    "A",
    "D",
    "H",
    "V",
    "X",
    "Y",
    "Z",
    "apply_local_pauli_channel",
    "apply_local_unitary",
    "db_to_efficiency",
    "hermitian_psd_clip",
    "kron",
    "normalize_probabilities",
    "phi_plus",
    "random_su2",
    "rho_phi_plus",
    "ry",
    "rz",
    "sample_from_probs",
]
