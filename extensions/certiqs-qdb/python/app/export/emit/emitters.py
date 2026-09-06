"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/emit/emitters.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

The 9 file emitters. Each reads the resolved IR and returns file text; they
only FILTER the IR by file/category and never re-derive routing or endpoints.
emit_top_level runs LAST and consumes the *filenames the others produced*, so
the `imports:` list and `composition.nodes` are correct by construction
(design-doc §8 — the hand-authored sample drifted on exactly these two).

Careful line-by-line note: only fields the TS source explicitly writes as
`x ?? undefined` (role, branch_side, connection/binding label) are omitted
when null — everything else (encoding, channel params, etc.) is passed
through prune_empty unchanged and an explicit null stays in the output.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.export.emit.yaml_ import UNSET, prune_empty, to_yaml
from app.export.ir import ExportFile, ExportModel, Instance, ResolvedConnection, SubsystemKey


@dataclass
class EmittedFile:
    filename: ExportFile
    content: str


def _instance_obj(i: Instance) -> dict:
    obj: dict = {
        "name": i.name,
        "component": i.component,
        "domain": i.domain,
        "role": i.role if i.role is not None else UNSET,
        "branch_side": i.branch_side if i.branch_side is not None else UNSET,
    }
    if i.domain == "digital":
        obj["implementation"] = "verilog"
        obj["module"] = i.name
    obj["settings"] = i.settings
    obj["ports"] = i.ports
    obj["annotations"] = i.annotations
    return prune_empty(obj)


def _node_name(m: ExportModel, key: SubsystemKey) -> str:
    node = next((n for n in m.nodes if n.key == key), None)
    return node.name if node is not None else key


def _node_role(m: ExportModel, key: SubsystemKey) -> str:
    node = next((n for n in m.nodes if n.key == key), None)
    return node.role if node is not None else key


def _subsystem_file(
    m: ExportModel, conns: list[ResolvedConnection], file: ExportFile, key: SubsystemKey
) -> EmittedFile:
    instances = [_instance_obj(i) for i in m.instances if i.file == file]
    optical = [
        prune_empty({"from": c.from_, "to": c.to, "label": c.label if c.label is not None else UNSET})
        for c in conns if c.file == file
    ]
    body = prune_empty({
        "subsystem": _node_name(m, key),
        "role": _node_role(m, key),
        "instances": instances,
        "connections": {"optical": optical} if optical else {},
    })
    return EmittedFile(filename=file, content=to_yaml(body))


# 01
def emit_protocol(m: ExportModel, _c: list[ResolvedConnection] | None = None) -> EmittedFile:
    return EmittedFile(filename="01_protocol.yaml", content=to_yaml({
        "protocol": prune_empty({
            "name": m.protocol.name,
            "family": m.protocol.family,
            "encoding": m.protocol.encoding,
            "bit_mapping": m.protocol.bit_mapping,
            "basis_selection": m.protocol.basis_selection,
            "coincidence": m.protocol.coincidence,
            "packet_types": m.protocol.packet_types,
            "overrides": m.protocol.overrides,
        }),
    }))


# 02 / 03 / 04
def emit_source(m: ExportModel, c: list[ResolvedConnection]) -> EmittedFile:
    return _subsystem_file(m, c, "02_source_central.yaml", "source")


def emit_alice(m: ExportModel, c: list[ResolvedConnection]) -> EmittedFile:
    return _subsystem_file(m, c, "03_alice_node.yaml", "alice")


def emit_bob(m: ExportModel, c: list[ResolvedConnection]) -> EmittedFile:
    return _subsystem_file(m, c, "04_bob_node.yaml", "bob")


# 05
def emit_channels(m: ExportModel, _c: list[ResolvedConnection] | None = None) -> EmittedFile:
    return EmittedFile(filename="05_channels.yaml", content=to_yaml({
        "channels": [
            prune_empty({
                "name": ch.name, "type": ch.type, "medium": ch.medium,
                "from": ch.from_, "to": ch.to, "params": ch.params,
            })
            for ch in m.channels
        ],
    }))


# 06 — digital control instances (non post-processing)
def emit_digital(m: ExportModel, _c: list[ResolvedConnection] | None = None) -> EmittedFile:
    return EmittedFile(filename="06_digital.yaml", content=to_yaml({
        "subsystem": "digital",
        "instances": [_instance_obj(i) for i in m.instances if i.file == "06_digital.yaml"],
    }))


# 07 — post-processing config + any postproc/crypto digital instances
def emit_post_processing(m: ExportModel, _c: list[ResolvedConnection] | None = None) -> EmittedFile:
    instances = [_instance_obj(i) for i in m.instances if i.file == "07_post_processing.yaml"]
    return EmittedFile(filename="07_post_processing.yaml", content=to_yaml(prune_empty({
        "post_processing": [
            prune_empty({"stage": s.name, "config": s.config, "params": s.params})
            for s in m.post_processing
        ],
        "instances": instances if instances else UNSET,
    })))


# 08 — cosim bindings + reset + verilog sources
def emit_cosim(m: ExportModel, _c: list[ResolvedConnection] | None = None) -> EmittedFile:
    return EmittedFile(filename="08_cosim.yaml", content=to_yaml({
        "co_simulation": {
            "mode": m.cosim.mode,
            "reset": m.cosim.reset,
            "verilog_sources": m.cosim.verilog_sources,
            "bindings": [
                prune_empty({
                    "from": b.from_, "to": b.to, "type": b.type, "medium": b.medium,
                    "label": b.label if b.label is not None else UNSET,
                })
                for b in m.cosim.bindings
            ],
        },
    }))


# 00 — orchestrator; consumes the emitted filenames so imports can't drift
def emit_top_level(m: ExportModel, emitted_filenames: list[ExportFile]) -> EmittedFile:
    return EmittedFile(filename="00_toplevel.yaml", content=to_yaml({
        "manifest": m.manifest_name,
        "system": m.system_name,
        "schema_version": m.schema_version,
        "imports": sorted(emitted_filenames),
        "composition": {"nodes": [n.name for n in m.nodes]},
        "validation": m.validation_flags,
    }))
