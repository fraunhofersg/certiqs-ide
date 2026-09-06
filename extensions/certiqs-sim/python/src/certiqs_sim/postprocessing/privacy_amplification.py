"""Privacy amplification by Toeplitz hashing.

A Toeplitz matrix built from an authenticated random seed maps the ``n``-bit
reconciled string to an ``m``-bit final key (m = extractable secure length from
the finite-key analysis).  Toeplitz hashing is a well-known universal-2 family,
so it is a valid strong extractor for privacy amplification.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

import numpy as np


def generate_toeplitz(n_rows: int, n_cols: int, seed: int) -> np.ndarray:
    """Build an ``n_rows × n_cols`` binary Toeplitz matrix from ``seed``.

    A Toeplitz matrix is fully determined by its first column and first row, i.e.
    ``n_rows + n_cols - 1`` random bits — the seed material shared over the
    authenticated classical channel.
    """
    rng = np.random.default_rng(seed)
    if n_rows <= 0 or n_cols <= 0:
        return np.zeros((max(0, n_rows), max(0, n_cols)), dtype=np.uint8)
    first_col = rng.integers(0, 2, size=n_rows, dtype=np.uint8)
    first_row = rng.integers(0, 2, size=n_cols, dtype=np.uint8)
    diag = np.concatenate([first_col[::-1], first_row[1:]])
    # Toeplitz: T[i, j] = diag[(n_rows - 1) - i + j]
    idx = (n_rows - 1) - np.arange(n_rows)[:, None] + np.arange(n_cols)[None, :]
    return diag[idx].astype(np.uint8)


def toeplitz_hash(
    bits: Sequence[int],
    output_length: int,
    seed: int | None = None,
) -> list[int]:
    """Extract ``output_length`` secure bits from ``bits`` via Toeplitz hashing."""
    n = len(bits)
    m = max(0, int(output_length))
    if m == 0 or n == 0:
        return []
    if seed is None:
        seed = random.getrandbits(63)
    matrix = generate_toeplitz(m, n, seed)
    vec = np.asarray([int(b) & 1 for b in bits], dtype=np.uint8)
    out = (matrix @ vec) & 1
    return [int(x) for x in out.tolist()]


__all__ = ["generate_toeplitz", "toeplitz_hash"]
