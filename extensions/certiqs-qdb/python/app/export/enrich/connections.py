"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/enrich/connections.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

§5 Connection classification.

Resolve both endpoints to "<instance>.<netName>" and classify each connection
by its `medium` (the reliable DB signal) + endpoint subsystems:
  optical + same subsystem      -> optical_intra  (subsystem file)
  optical + crosses subsystems  -> optical_channel (channel in 05, legs in receiver file)
  classical/sync link           -> channel in 05
  electrical / digital control  -> binding in 08_cosim (event_bridge | control_bridge)
Emitters only FILTER by category + owning file; they never re-derive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.export.enrich.routing import file_for_instance
from app.export.ir import Channel, CosimBinding, ExportFile, ResolvedConnection, SubsystemKey

if TYPE_CHECKING:
    from app.export.assemble import RawConnection


@dataclass
class InstanceLoc:
    subsystem: SubsystemKey
    domain: Literal["optical", "digital"]


MediumClass = Literal["optical", "link_classical", "link_sync", "binding"]

_SYNC_RE = re.compile(r"sync")
_CLASSICAL_RE = re.compile(r"ethernet|serial")
_OPTICAL_RE = re.compile(r"free-space|fibre|fiber|optic")
_LINK_LABEL_RE = re.compile(r"([a-z_]+link)", re.IGNORECASE)
_CLICK_EVENT_RE = re.compile(r"click|event", re.IGNORECASE)


def _classify_medium(medium: str) -> MediumClass:
    m = medium.lower()
    # Order matters: a "sync" / "ethernet" link must win before the optical test,
    # since a medium like "electrical_or_optical_sync" contains the substring "optic".
    if _SYNC_RE.search(m):
        return "link_sync"
    if _CLASSICAL_RE.search(m):
        return "link_classical"
    if _OPTICAL_RE.search(m):
        return "optical"
    return "binding"  # coaxial / electrical / digital bus / digital control (trigger)


def _endpoint(instance: str | None, port: str | None, fallback: str) -> str:
    return f"{instance if instance is not None else '?'}.{port if port is not None else fallback}"


@dataclass
class ClassifyResult:
    connections: list[ResolvedConnection]  # optical_intra + optical_channel legs
    channels: list[Channel]
    bindings: list[CosimBinding]


def classify_connections(
    raw_conns: list[RawConnection],
    loc_by_instance: dict[str, InstanceLoc],
) -> ClassifyResult:
    connections: list[ResolvedConnection] = []
    channels: list[Channel] = []
    bindings: list[CosimBinding] = []

    for cn in raw_conns:
        from_ = _endpoint(cn.from_instance, cn.from_port, "out")
        to = _endpoint(cn.to_instance, cn.to_port, "in")
        from_loc = loc_by_instance.get(cn.from_instance) if cn.from_instance else None
        to_loc = loc_by_instance.get(cn.to_instance) if cn.to_instance else None
        cls = _classify_medium(cn.medium)

        if cls == "optical":
            same_subsystem = bool(from_loc and to_loc and from_loc.subsystem == to_loc.subsystem)
            if same_subsystem:
                connections.append(ResolvedConnection(
                    domain="optical", from_=from_, to=to, category="optical_intra",
                    medium=cn.medium, label=cn.label,
                    file=file_for_instance(from_loc.subsystem, "optical", None),
                ))
            else:
                # Cross-subsystem optical -> a quantum channel + two legs in the receiver file.
                receiver_file: ExportFile = (
                    file_for_instance(to_loc.subsystem, "optical", None) if to_loc else "05_channels.yaml"
                )
                label_slug = re.sub(r"\W+", "_", cn.label, flags=re.ASCII).lower() if cn.label else None
                name = cn.from_port or label_slug or "quantum_channel"
                channels.append(Channel(name=name, type="quantum", medium=cn.medium, from_=from_, to=to, params={}))
                connections.append(ResolvedConnection(
                    domain="optical", from_=from_, to=f"{name}.in", category="optical_channel",
                    medium=cn.medium, label=cn.label, file=receiver_file,
                ))
                connections.append(ResolvedConnection(
                    domain="optical", from_=f"{name}.out", to=to, category="optical_channel",
                    medium=cn.medium, label=cn.label, file=receiver_file,
                ))
            continue

        if cls in ("link_classical", "link_sync"):
            match = _LINK_LABEL_RE.search(cn.label) if cn.label else None
            name = (
                match.group(1) if match
                else ("time_sync_link" if cls == "link_sync" else "qkd_classical_link")
            )
            channels.append(Channel(
                name=name, type=("sync" if cls == "link_sync" else "classical"),
                medium=cn.medium, from_=from_, to=to, params={},
            ))
            continue

        # binding -> cosim
        if from_loc and from_loc.domain == "optical" and to_loc and to_loc.domain == "digital":
            binding_type = "event_bridge"
        elif from_loc and from_loc.domain == "digital" and to_loc and to_loc.domain == "optical":
            binding_type = "control_bridge"
        # JS template-literal semantics: `${null}` stringifies to "null", not Python
        # f-string's "None" — doesn't change this particular regex's outcome (neither
        # string contains "click"/"event"), but kept exact rather than relying on that.
        elif _CLICK_EVENT_RE.search(
            f"{cn.from_port if cn.from_port is not None else 'null'} "
            f"{cn.to_port if cn.to_port is not None else 'null'}"
        ):
            binding_type = "event_bridge"
        else:
            binding_type = "control_bridge"
        bindings.append(CosimBinding(from_=from_, to=to, type=binding_type, medium=cn.medium, label=cn.label))

    return ClassifyResult(connections=connections, channels=channels, bindings=bindings)
