"""Cascade information-reconciliation (error correction).

A faithful implementation of the Cascade protocol (Brassard & Salvail, 1993):
Bob's sifted string is reconciled to Alice's reference string over multiple passes
with permuted blocks; a parity mismatch triggers a binary-search correction, and
each correction *cascades* back to previously-processed blocks that now contain an
odd number of errors.  The actual number of parity bits disclosed is tracked as
the reconciliation *leakage*, which the privacy-amplification / finite-key step
subtracts from the extractable key length.

``01_protocol.yaml`` reveals only basis (not bit values); the disclosed parities
here are the classical-channel information an eavesdropper also learns, so
accounting for them is exactly the ``leakage_accounting`` the manifest requests.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class _Block:
    indices: list[int]
    odd: bool = False


@dataclass
class CascadeResult:
    corrected_bits: list[int]
    leakage_bits: int
    remaining_errors: int
    passes: int
    frame_errors: int = 0
    block_sizes: list[int] = field(default_factory=list)


def _shannon_leakage(n: int, qber: float) -> float:
    from certiqs_sim.core.keyrate import binary_entropy2

    return n * binary_entropy2(qber)


def ec_leakage_bits(n: int, qber: float, efficiency: float = 1.1) -> float:
    """Shannon-limit reconciliation leakage f_EC · n · h(QBER).

    Used as a fallback / comparison when actual Cascade leakage is not measured.
    """
    return efficiency * _shannon_leakage(n, qber)


def cascade_correct(
    alice_bits: Sequence[int],
    bob_bits: Sequence[int],
    qber_estimate: float,
    passes: int = 4,
    seed: int = 0,
) -> CascadeResult:
    """Reconcile ``bob_bits`` to ``alice_bits`` with Cascade; return corrected bits
    and the measured leakage."""
    n = len(bob_bits)
    if n != len(alice_bits):
        raise ValueError("Alice/Bob blocks differ in length")
    if n == 0:
        return CascadeResult([], 0, 0, passes, 0, [])

    alice = [int(b) & 1 for b in alice_bits]
    bob = [int(b) & 1 for b in bob_bits]
    rng = random.Random(seed)

    leakage = 0
    blocks: list[_Block] = []
    index_to_blocks: dict[int, list[int]] = {i: [] for i in range(n)}
    block_sizes: list[int] = []

    q = min(max(qber_estimate, 1e-3), 0.5)
    base_k = max(1, round(0.73 / q))

    def parity(indices: list[int], bits: list[int]) -> int:
        s = 0
        for i in indices:
            s ^= bits[i]
        return s

    def binary_search_correct(indices: list[int]) -> int:
        nonlocal leakage
        sub = list(indices)
        while len(sub) > 1:
            mid = len(sub) // 2
            half = sub[:mid]
            leakage += 1  # Alice discloses the parity of this sub-block
            sub = half if parity(half, alice) != parity(half, bob) else sub[mid:]
        return sub[0]

    def correct_block(block_id: int) -> None:
        idx = binary_search_correct(blocks[block_id].indices)
        bob[idx] ^= 1
        queue: list[int] = []
        for bid in index_to_blocks[idx]:
            blocks[bid].odd = not blocks[bid].odd
            if blocks[bid].odd:
                queue.append(bid)
        # Cascade: process every block that now has an odd error count.
        while queue:
            bid = queue.pop()
            if not blocks[bid].odd:
                continue
            inner_idx = binary_search_correct(blocks[bid].indices)
            bob[inner_idx] ^= 1
            for other in index_to_blocks[inner_idx]:
                blocks[other].odd = not blocks[other].odd
                if blocks[other].odd:
                    queue.append(other)

    for p in range(max(1, passes)):
        k = min(n, base_k * (2**p))
        block_sizes.append(k)
        order = list(range(n))
        if p > 0:
            rng.shuffle(order)
        for start in range(0, n, k):
            indices = order[start : start + k]
            block = _Block(indices=indices)
            block_id = len(blocks)
            blocks.append(block)
            for i in indices:
                index_to_blocks[i].append(block_id)
            leakage += 1  # Alice discloses this block's parity
            block.odd = parity(indices, alice) != parity(indices, bob)
            if block.odd:
                correct_block(block_id)

    remaining_errors = sum(1 for a, b in zip(alice, bob, strict=True) if a != b)
    frame_errors = 1 if remaining_errors else 0
    return CascadeResult(
        corrected_bits=bob,
        leakage_bits=leakage,
        remaining_errors=remaining_errors,
        passes=max(1, passes),
        frame_errors=frame_errors,
        block_sizes=block_sizes,
    )


__all__ = ["CascadeResult", "cascade_correct", "ec_leakage_bits"]
