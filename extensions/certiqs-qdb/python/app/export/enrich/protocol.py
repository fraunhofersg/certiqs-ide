"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/enrich/protocol.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

§6 Protocol template merge — protocol = merge(familyTemplate[name], systemOverrides).
The template supplies encoding / bit_mapping / basis_selection / coincidence /
packet-type defaults; overrides pin whatever the specific system deviates on
(e.g. bit_mapping derived from the actual detector annotations, coincidence window).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.export.ir import DetectorMeta, ProtocolBlock


@dataclass
class FamilyTemplate:
    encoding: str | None
    bit_mapping: dict[str, int]
    basis_selection: str
    coincidence: dict[str, object]
    packet_types: list[str]


_FAMILY_TEMPLATES: dict[str, FamilyTemplate] = {
    "BBM92": FamilyTemplate(
        encoding="polarization",
        bit_mapping={"H": 0, "V": 1, "D": 0, "A": 1},
        basis_selection="passive",
        coincidence={"window_ps": 1000, "multi_click_policy": "discard", "require_one_click_per_side": True},
        packet_types=["basis_announce", "coincidence_report", "ec_metadata", "pa_metadata"],
    ),
}


@dataclass
class ProtocolOverrides:
    coincidence: dict[str, object] | None = None
    extra: dict[str, object] | None = None


def merge_protocol(
    name: str,
    family: str,
    encoding: str | None,
    detectors: list[DetectorMeta],
    overrides: ProtocolOverrides | None = None,
) -> ProtocolBlock:
    """Merge the protocol-family template with system-specific overrides."""
    overrides = overrides or ProtocolOverrides()
    template = _FAMILY_TEMPLATES.get(name, _FAMILY_TEMPLATES["BBM92"])

    # Derive bit_mapping from the actual detector annotations where available; this
    # is the cross-cutting invariant validated in §8 against each detector's `bit`.
    derived: dict[str, int] = {}
    for d in detectors:
        if d.state and isinstance(d.bit, int):
            derived[d.state] = d.bit
    bit_mapping = derived if derived else template.bit_mapping

    return ProtocolBlock(
        name=name,
        family=family,
        encoding=encoding if encoding is not None else template.encoding,
        bit_mapping=bit_mapping,
        basis_selection=template.basis_selection,
        coincidence={**template.coincidence, **(overrides.coincidence or {})},
        packet_types=template.packet_types,
        overrides=overrides.extra or {},
    )
