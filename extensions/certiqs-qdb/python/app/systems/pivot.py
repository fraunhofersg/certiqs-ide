"""Port of ../../../src/lib/db/pivot.ts — keep in sync line-by-line.

Derives the parallel arrays a batched `INSERT ... FROM unnest(...)` needs, by
field name off a single list of row dicts — so every column list is
guaranteed to be the same length and the same order as its siblings.
Prevents the failure mode where one column is built via its own independent
comprehension over a differently-filtered or differently-ordered source and
silently desyncs from the others.
"""

from __future__ import annotations


def pivot(rows: list[dict], *keys: str) -> dict[str, list]:
    return {k: [r[k] for r in rows] for k in keys}
