"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/enrich/annotations.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Parse the DB's param bags into IR-shaped settings / annotations, and pull the
structured detector metadata (basis/state/bit/channel_id) that the BBM92 seed
smuggles into a `detector_role` annotation string. See design-doc §3, §6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.export.ir import DetectorMeta

if TYPE_CHECKING:
    from app.export.assemble import RawParam

_INT_RE = re.compile(r"^-?\d+$", re.ASCII)
_FLOAT_RE = re.compile(r"^-?\d*\.?\d+(e-?\d+)?$", re.ASCII | re.IGNORECASE)


def coerce_value(raw: str | None) -> object:
    """Coerce a stored string value to a YAML scalar (number / bool / None / string)."""
    if raw is None or raw == "":
        return None
    t = raw.strip()
    if t == "true":
        return True
    if t == "false":
        return False
    # Integers stay integers; floats/scientific stay numbers; everything else is text.
    if _INT_RE.match(t):
        return int(t)
    if _FLOAT_RE.match(t):
        return float(t)
    return raw


@dataclass
class SplitParams:
    settings: dict[str, object] = field(default_factory=dict)
    annotations: dict[str, object] = field(default_factory=dict)


def split_params(params: list[RawParam]) -> SplitParams:
    """Split a component's params into `settings` (physical/config params, coerced to
    scalars) and `annotations` (free-form traceability notes, kept verbatim as text).
    Groups "parameters" and "settings" -> settings; group "annotations" -> annotations.
    """
    settings: dict[str, object] = {}
    annotations: dict[str, object] = {}
    for p in params:
        if p.param_group == "annotations":
            annotations[p.key] = p.value  # keep verbatim — annotations are documentation
        else:
            settings[p.key] = coerce_value(p.value)
    return SplitParams(settings=settings, annotations=annotations)


def parse_detector_meta(annotations: dict[str, object]) -> DetectorMeta | None:
    """Parse "basis=Z, state=H, bit=0, channel_id=0" (the seed's `detector_role`
    annotation) into structured fields. Returns None when absent.
    """
    raw = annotations.get("detector_role")
    if not isinstance(raw, str):
        return None
    meta = DetectorMeta()
    found = False
    for part in raw.split(","):
        # Mirrors JS `const [k, v] = part.split("=").map(trim)`: array destructuring
        # takes only the first two pieces (extra "="s are silently ignored, not an
        # error) and a missing piece becomes undefined rather than raising.
        kv = part.split("=")
        k = kv[0].strip() if len(kv) > 0 else None
        v = kv[1].strip() if len(kv) > 1 else None
        if not k or v is None:
            continue
        if k == "basis":
            meta.basis = v
            found = True
        elif k == "state":
            meta.state = v
            found = True
        elif k == "bit":
            meta.bit = int(v)
            found = True
        elif k == "channel_id":
            meta.channel_id = int(v)
            found = True
    return meta if found else None
