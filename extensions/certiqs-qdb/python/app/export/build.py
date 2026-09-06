"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/build.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

IR builder — assembles the hydrated aggregate into a fully-resolved ExportModel
by running the enrich stage (routing · connection classify · annotation parse ·
protocol merge). After this returns, the IR is the only contract emitters read.

Departs from the TS source in one way, behavior-preserving: TS stashes the
resolved connections on the model via a non-enumerable property
(`(model as any).__connections = connections`) because changing buildModel's
return shape would ripple through every caller. Python has no equivalent
"hidden but attached" affordance worth reaching for — and no callers to keep
stable yet — so build_model() just returns both values directly via
BuiltModel.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.export.assemble import SystemAggregate
from app.export.enrich.annotations import parse_detector_meta, split_params
from app.export.enrich.connections import InstanceLoc, classify_connections
from app.export.enrich.protocol import ProtocolOverrides, merge_protocol
from app.export.enrich.routing import file_for_instance, subsystem_for_module
from app.export.ir import (
    CosimBlock,
    DetectorMeta,
    ExportModel,
    Instance,
    MANIFEST_SCHEMA_VERSION,
    PostProcessingStage,
    ResolvedConnection,
    SubsystemNode,
)


def _slugify(s: str) -> str:
    return re.sub(r"^_+|_+$", "", re.sub(r"[^\w]+", "_", s.lower(), flags=re.ASCII), flags=re.ASCII)


@dataclass
class BuiltModel:
    model: ExportModel
    connections: list[ResolvedConnection]


def build_model(agg: SystemAggregate) -> BuiltModel:
    primary = next((p for p in agg.protocols if p.is_primary), agg.protocols[0] if agg.protocols else None)
    proto_name = primary.name if primary else "QKD"
    family = primary.family if primary else ""
    encoding = primary.encoding if primary else None

    # ── Instances + subsystem nodes ────────────────────────────────────────────
    instances: list[Instance] = []
    loc_by_instance: dict[str, InstanceLoc] = {}
    nodes_by_key: dict[str, SubsystemNode] = {}
    detectors: list[DetectorMeta] = []

    for mod in agg.modules:
        if mod.module_type == "POST_PROCESSING":
            continue  # handled via system_pp
        sub = subsystem_for_module(mod)
        if sub.key not in nodes_by_key:
            nodes_by_key[sub.key] = SubsystemNode(key=sub.key, name=sub.name, role=sub.role)
        for c in mod.components:
            instance_name = (c.instance_name or "").strip()
            if not instance_name:
                continue  # an instance with no name cannot be referenced
            domain = "digital" if c.domain == "digital" else "optical"
            split = split_params(c.parameters)
            detector = parse_detector_meta(split.annotations)
            if detector:
                detectors.append(detector)
            instances.append(Instance(
                name=instance_name,
                subsystem=sub.key,
                domain=domain,
                component=_slugify(c.component_type),
                role=c.role,
                branch_side=c.branch_side,
                settings=split.settings,
                ports={},
                annotations=split.annotations,
                detector=detector,
                file=file_for_instance(sub.key, domain, c.role),
            ))
            loc_by_instance[instance_name] = InstanceLoc(subsystem=sub.key, domain=domain)

    # ── Ports: net-names live on the connection endpoints (from_port/to_port). ──
    inst_by_name = {i.name: i for i in instances}
    for cn in agg.connections:
        if cn.from_instance and cn.from_port:
            inst = inst_by_name.get(cn.from_instance)
            if inst:
                inst.ports[cn.from_port] = cn.from_port
        if cn.to_instance and cn.to_port:
            inst = inst_by_name.get(cn.to_instance)
            if inst:
                inst.ports[cn.to_port] = cn.to_port

    # ── Connection classification (channels + bindings + resolved edges) ────────
    classified = classify_connections(agg.connections, loc_by_instance)

    # ── Coincidence window override from the coincidence-matcher instance ───────
    matcher = next((i for i in instances if "coincidence" in i.component), None)
    coincidence = None
    if matcher is not None:
        window_sec = matcher.settings.get("coincidence_window")
        try:
            window_sec = float(window_sec)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            window_sec = math.nan
        if not math.isnan(window_sec) and window_sec > 0:
            coincidence = {"window_ps": round(window_sec * 1e12)}

    protocol = merge_protocol(proto_name, family, encoding, detectors, ProtocolOverrides(coincidence=coincidence))

    # ── Post-processing stages ─────────────────────────────────────────────────
    post_processing = [
        PostProcessingStage(name=pp.pp_type_name, config=pp.annotation, params={})
        for pp in agg.system_pp
    ]

    # ── Cosim block ────────────────────────────────────────────────────────────
    digital_instances = [i for i in instances if i.domain == "digital"]
    cosim = CosimBlock(
        mode="event_driven",
        reset="sync_reset_active_high",
        verilog_sources=list(dict.fromkeys(f"{i.name}.v" for i in digital_instances)),
        bindings=classified.bindings,
    )

    nodes = list(nodes_by_key.values())

    system_name = agg.system.get("name")
    model = ExportModel(
        schema_version=MANIFEST_SCHEMA_VERSION,
        manifest_name=f"{_slugify(proto_name)}_system",
        system_name=_slugify(system_name if system_name is not None else proto_name),
        system_id=agg.system["id"],
        protocol=protocol,
        nodes=nodes,
        instances=instances,
        channels=classified.channels,
        post_processing=post_processing,
        cosim=cosim,
        validation_flags={
            "require_unique_instance_names": True,
            "require_declared_ports": True,
            "require_declared_clock_domains": False,
            "require_declared_packet_types": True,
            "require_bit_mapping_consistency": True,
        },
    )

    return BuiltModel(model=model, connections=classified.connections)
