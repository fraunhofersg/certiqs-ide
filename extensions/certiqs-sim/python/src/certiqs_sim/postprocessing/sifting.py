"""Sifting audit for a sifted key block.

The twin already performs coincidence + same-basis sifting.  This module audits a
delivered sifted block: it checks Alice/Bob lengths agree and reports the raw
mismatch count, which downstream QBER estimation and error correction consume.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class SiftingAudit:
    sifted_length: int
    mismatches: int
    raw_qber: float


def audit_sifted_block(alice_bits: Sequence[int], bob_bits: Sequence[int]) -> SiftingAudit:
    if len(alice_bits) != len(bob_bits):
        raise ValueError(
            f"Sifted block length mismatch: alice={len(alice_bits)} bob={len(bob_bits)}"
        )
    n = len(alice_bits)
    mismatches = sum(1 for a, b in zip(alice_bits, bob_bits, strict=True) if a != b)
    raw_qber = mismatches / n if n else 0.0
    return SiftingAudit(sifted_length=n, mismatches=mismatches, raw_qber=raw_qber)


def as_bit_list(bits: Sequence[int]) -> list[int]:
    return [int(b) & 1 for b in bits]


__all__ = ["SiftingAudit", "as_bit_list", "audit_sifted_block"]
