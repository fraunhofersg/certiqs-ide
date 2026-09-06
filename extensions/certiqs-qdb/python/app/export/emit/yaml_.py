"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/emit/yaml.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Shared YAML formatter. The meaning-preserving rules (design-doc §9) are the
non-negotiable ones and are implemented even in this minimal formatter:
  - explicit `null` (never omit a null field)
  - integers stay integers (repetition_rate_hz: 100000000, not 1e8)
  - scientific notation preserved for tiny epsilons, normalised so the mantissa
    always carries a decimal point (1e-12 is emitted as 1.0e-12) — see
    _represent_float for why the bare form is not safe
  - deterministic key order (insertion order) so re-exports diff cleanly
Downstream ingestion is semantic (a YAML parser), so flow-style/folded-scalar
polish is intentionally deferred — this pass is correctness, not cosmetics.

Named yaml_.py, not yaml.py, so it doesn't shadow the PyYAML package it wraps.
"""

from __future__ import annotations

import math
import re
from typing import Any

import yaml

# Sentinel for "omit this key from output", distinct from an explicit YAML
# null. TS leans on `undefined` vs `null` for exactly this distinction (see
# instanceObj in emitters.ts: `role: i.role ?? undefined` turns a null role
# into an omitted key, while other fields pass a null straight through to be
# emitted as `field: null`) — Python's None has to do both jobs unless we
# give "omit" its own marker.
UNSET = object()


class _Dumper(yaml.SafeDumper):
    pass


def _represent_none(dumper: yaml.Dumper, _data: None) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


def _represent_float(dumper: yaml.Dumper, data: float) -> yaml.Node:
    if math.isnan(data):
        return dumper.represent_scalar("tag:yaml.org,2002:float", ".nan")
    if math.isinf(data):
        return dumper.represent_scalar("tag:yaml.org,2002:float", ".inf" if data > 0 else "-.inf")
    if data == int(data) and abs(data) < 1e16:
        # JS has one numeric type: Number("5.0") stringifies as "5", not "5.0".
        # Tagged as int (not float): PyYAML's *default* int resolver already
        # matches bare digit text, so no explicit "!!int"/"!!float" disambiguation
        # tag gets forced into the output — it just prints "5", plain.
        return dumper.represent_scalar("tag:yaml.org,2002:int", repr(int(data)))
    # Python's repr(float) uses the same "shortest round-trip decimal" family of
    # algorithm as JS's Number.prototype.toString() — 0.2 -> "0.2" — and keeps
    # scientific notation for tiny epsilons. It is NOT byte-identical to JS: Python
    # zero-pads the exponent to two digits (5e-08) where JS wrote 5e-8. Harmless.
    #
    # What is NOT harmless is emitting a bare mantissa. YAML 1.1's core schema
    # resolves a plain scalar as a float only when it has BOTH a "." in the mantissa
    # AND a signed exponent — "5e-08" and "1.0e20" both load back as STRINGS, while
    # "5.0e-08" loads as a float. Since downstream ingestion is semantic (a YAML
    # parser), emitting the bare form silently turned every tiny epsilon into a
    # string for consumers. So normalise the mantissa to carry a decimal point.
    # Python always signs the exponent already, but don't rely on it.
    #
    # Only the lowercase "e" form can occur: repr(float) never emits an uppercase
    # exponent, so there is no "E" branch to handle.
    text = repr(data)
    if "e" in text:
        mantissa, _, exponent = text.partition("e")
        if "." not in mantissa:
            mantissa += ".0"
        if exponent and exponent[0] not in "+-":
            exponent = "+" + exponent
        text = f"{mantissa}e{exponent}"
    return dumper.represent_scalar("tag:yaml.org,2002:float", text)


_Dumper.add_representer(type(None), _represent_none)
_Dumper.add_representer(float, _represent_float)

# Broader than PyYAML's default float resolver (which requires a decimal point).
# _represent_float no longer emits the bare form, so this is no longer needed to
# keep FLOAT output untagged — the default resolver already matches "5.0e-08".
# It is kept because it still does useful work in the other direction: a STRING
# whose text looks like bare scientific notation ("5e-08") now collides with a
# float resolver, so PyYAML quotes it instead of emitting an ambiguous plain
# scalar. Removing this would not corrupt anything today, but it would make that
# distinction depend on YAML 1.1 minutiae rather than on an explicit rule.
_Dumper.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^-?\d+(\.\d+)?[eE][-+]?\d+$"),
    list("-0123456789"),
)


def to_yaml(obj: Any) -> str:
    return yaml.dump(
        obj,
        Dumper=_Dumper,
        default_flow_style=False,
        sort_keys=False,  # keep insertion order so output is deterministic + diffable
        width=1_000_000,  # never fold long lines (avoids surprise wrapping of descriptions)
        allow_unicode=True,
    )


def prune_empty(obj: dict[str, Any]) -> dict[str, Any]:
    """Drop UNSET/empty-dict values so instances stay terse, but keep explicit-null
    scalars and empty lists (mirrors pruneEmpty's undefined/empty-object-only check —
    it does NOT touch arrays or null)."""
    out: dict[str, Any] = {}
    for k, v in obj.items():
        if v is UNSET:
            continue
        if v is not None and isinstance(v, dict) and len(v) == 0:
            continue
        out[k] = v
    return out
