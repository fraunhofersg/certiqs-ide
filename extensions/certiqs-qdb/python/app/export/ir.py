"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/ir.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Stage 2 — Intermediate Representation (the linchpin).

The IR is the single serialization-agnostic contract every emitter reads. It
carries no DB rows or ids: connection endpoints are already resolved to
"<instance>.<netName>" strings, files are already assigned per instance/
connection by the router, and detector annotations are already parsed into
structured fields. See QSECDB_YAML_EXPORT_DESIGN.md §3.

None of this crosses the JSON wire boundary (the pipeline's output is a
YAML/zip, not JSON), so — unlike Phase 1/2's models — these are plain
mutable dataclasses, not CamelModel: closer to the TS interfaces' own
mutable-object-literal style, and simpler since there's no JSON aliasing to
manage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MANIFEST_SCHEMA_VERSION = "1.1"

# The 9 canonical output files (design-doc §4). Also the routing target ids.
ExportFile = Literal[
    "00_toplevel.yaml",
    "01_protocol.yaml",
    "02_source_central.yaml",
    "03_alice_node.yaml",
    "04_bob_node.yaml",
    "05_channels.yaml",
    "06_digital.yaml",
    "07_post_processing.yaml",
    "08_cosim.yaml",
]

# Logical composition node (source / alice / bob). Drives composition.nodes.
SubsystemKey = Literal["source", "alice", "bob", "post_processing", "unassigned"]

Domain = Literal["optical", "digital"]


@dataclass
class SubsystemNode:
    key: SubsystemKey
    name: str  # canonical manifest node name — sole source of truth for composition.nodes
    role: str


@dataclass
class DetectorMeta:
    basis: str | None = None
    state: str | None = None
    bit: int | None = None
    channel_id: int | None = None


@dataclass
class Instance:
    name: str  # unique instance name (module_components.instance_name)
    subsystem: SubsystemKey
    domain: Domain
    component: str  # component-type slug
    role: str | None
    branch_side: str | None
    settings: dict[str, object]
    ports: dict[str, str] = field(default_factory=dict)  # portRole -> netName (value is the ref target)
    annotations: dict[str, object] = field(default_factory=dict)
    detector: DetectorMeta | None = None
    file: ExportFile | None = None  # assigned by the router (§4)


ConnectionCategory = Literal["optical_intra", "optical_channel", "binding"]
BindingType = Literal["event_bridge", "control_bridge"]


@dataclass
class ResolvedConnection:
    domain: Domain
    from_: str  # "<instance>.<netName>" (netName, NOT port role)
    to: str
    category: ConnectionCategory
    medium: str
    label: str | None
    file: ExportFile
    binding_type: BindingType | None = None


@dataclass
class Channel:
    name: str  # e.g. "quantum_to_alice"
    type: str  # "quantum" | "classical" | "sync"
    medium: str
    from_: str  # "<instance>.<netName>"
    to: str
    params: dict[str, object] = field(default_factory=dict)


@dataclass
class ProtocolBlock:
    name: str  # "BBM92"
    family: str
    encoding: str | None
    bit_mapping: dict[str, int]  # { H:0, V:1, D:0, A:1 }
    basis_selection: str
    coincidence: dict[str, object]
    packet_types: list[str]
    overrides: dict[str, object]


@dataclass
class PostProcessingStage:
    name: str
    config: str | None  # parsed / raw annotation text
    params: dict[str, object] = field(default_factory=dict)  # resolved structured params (e.g. code_rate)


@dataclass
class CosimBinding:
    from_: str
    to: str
    type: BindingType
    medium: str
    label: str | None


@dataclass
class CosimBlock:
    mode: str
    reset: str
    verilog_sources: list[str]
    bindings: list[CosimBinding]


@dataclass
class ExportModel:
    """Full IR consumed by every emitter (design-doc §3)."""

    schema_version: str
    manifest_name: str
    system_name: str
    system_id: int
    protocol: ProtocolBlock
    nodes: list[SubsystemNode]
    instances: list[Instance]
    channels: list[Channel]
    post_processing: list[PostProcessingStage]
    cosim: CosimBlock
    validation_flags: dict[str, bool]


def instances_for_file(m: ExportModel, file: ExportFile) -> list[Instance]:
    return [i for i in m.instances if i.file == file]


def connections_for_file(
    file: ExportFile, conns: list[ResolvedConnection]
) -> list[ResolvedConnection]:
    return [c for c in conns if c.file == file]
