"""Design-graph topology extracted from schema-2.0 YAML connection declarations.

Walks every document in a config directory, registers logical nodes (subsystems,
components, channels, post-processing stages) and expands declared ``connections:``
into directed edges.  Endpoint references like ``detectors.alice_detector_h.in`` are
resolved against the node registry; ``via`` channel hops become two edges.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from certiqs_sim.core.components.catalog import manifest_sha256
from certiqs_sim.core.components.registry import get_model_for_class

_DEPLOYMENT_ROLE_LABELS: dict[str, str] = {
    "qkd_device": "QKD device",
    "qkd_node": "QKD node",
    "network_coordination": "Coordination",
    "quantum_source": "Quantum source",
}

_KNOWN_PORTS = frozenset(
    {
        "in",
        "out",
        "pump_in",
        "signal_out",
        "idler_out",
        "clicks_in",
        "clicks_out",
        "timestamps_out",
        "alice_events",
        "bob_events",
        "clock_offset",
        "coincidences_out",
        "quantum_in",
        "alice_out",
        "bob_out",
        "transmitted",
        "reflected",
        "port_0",
        "port_1",
        "clicks",
        "test_bits",
        "raw_key_bits",
        "corrected_bits",
        "result",
        "leakage",
        "parameter_estimation",
        "reconciliation_leakage",
        "output_length",
        "secret_key",
        "offset_estimate",
    }
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _parse_endpoint(ref: str) -> tuple[str, str | None]:
    """Split ``node_id.port``; supports nested detector channel names."""
    if "." not in ref:
        return ref, None
    parts = ref.split(".")
    # detectors.alice_detector_h.in -> channel node alice_detector_h
    if len(parts) >= 3 and parts[0] == "detectors" and parts[-1] in _KNOWN_PORTS:
        return parts[1], parts[-1]
    if parts[-1] in _KNOWN_PORTS:
        return ".".join(parts[:-1]), parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1]
    return ref, None


class _NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}

    def add(self, node: dict[str, Any]) -> None:
        node_id = str(node["id"])
        if node_id not in self._nodes:
            self._nodes[node_id] = node

    def resolve(self, ref: str) -> str | None:
        node_id, _ = _parse_endpoint(ref)
        if node_id in self._nodes:
            return node_id
        # Longest-prefix match for compound references.
        parts = ref.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in self._nodes:
                return candidate
        return None

    def values(self) -> list[dict[str, Any]]:
        return list(self._nodes.values())


def _flatten_declared_ports(ports: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    """Normalize subsystem ``ports:`` blocks into inputs/outputs lists."""
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    if not isinstance(ports, dict):
        return {"inputs": inputs, "outputs": outputs}
    for group_name, group_ports in ports.items():
        if not isinstance(group_ports, dict):
            continue
        group = str(group_name)
        side = "inputs" if group.endswith("_inputs") or group.endswith("_input") else "outputs"
        if side == "outputs" and not (group.endswith("_outputs") or group.endswith("_output")):
            if "input" in group:
                side = "inputs"
            elif "output" not in group:
                continue
        bucket = inputs if side == "inputs" else outputs
        for port_id, meta in group_ports.items():
            entry: dict[str, Any] = {"id": str(port_id), "group": group}
            if isinstance(meta, dict):
                entry.update(meta)
            bucket.append(entry)
    return {"inputs": inputs, "outputs": outputs}


def _merge_ports(
    declared: dict[str, list[dict[str, Any]]],
    inferred: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Declared YAML ports take precedence; inferred edge ports fill gaps."""
    out: dict[str, list[dict[str, Any]]] = {"inputs": [], "outputs": []}
    for side in ("inputs", "outputs"):
        seen: set[str] = set()
        for port in declared.get(side, []):
            pid = str(port.get("id", ""))
            if pid and pid not in seen:
                seen.add(pid)
                out[side].append(port)
        for port in inferred.get(side, []):
            pid = str(port.get("id", ""))
            if pid and pid not in seen:
                seen.add(pid)
                out[side].append(port)
    return out


def _infer_ports_from_edges(
    node_id: str,
    edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    in_seen: set[str] = set()
    out_seen: set[str] = set()
    for edge in edges:
        if edge.get("target") == node_id and edge.get("target_port"):
            pid = str(edge["target_port"])
            if pid not in in_seen:
                in_seen.add(pid)
                inputs.append(
                    {
                        "id": pid,
                        "group": "inferred",
                        "edge_kind": edge.get("edge_kind"),
                    }
                )
        if edge.get("source") == node_id and edge.get("source_port"):
            pid = str(edge["source_port"])
            if pid not in out_seen:
                out_seen.add(pid)
                outputs.append(
                    {
                        "id": pid,
                        "group": "inferred",
                        "edge_kind": edge.get("edge_kind"),
                    }
                )
    return {"inputs": inputs, "outputs": outputs}


def _register_document_nodes(doc: dict[str, Any], source_file: str, registry: _NodeRegistry) -> None:
    subsystem = doc.get("subsystem") or {}
    subsystem_id = subsystem.get("id") or subsystem.get("name")
    if subsystem_id:
        declared_ports = _flatten_declared_ports(subsystem.get("ports"))
        registry.add(
            {
                "id": str(subsystem_id),
                "label": str(subsystem_id).replace("_", " "),
                "node_type": "subsystem",
                "subsystem": None,
                "component_class": subsystem.get("component_class"),
                "deployment_role": subsystem.get("deployment_role"),
                "endpoint_side": subsystem.get("endpoint_side"),
                "topology_scope": subsystem.get("topology_scope"),
                "domain": "subsystem",
                "source_file": source_file,
                "ports": declared_ports,
            }
        )

    components = doc.get("components") or {}
    if isinstance(components, list):
        # Hierarchical schema 3.x lists components; flat adapter docs use mappings.
        return
    for comp_id, comp in components.items():
        if not isinstance(comp, dict) or "component_class" not in comp:
            continue
        if comp.get("component_class") == "detector_array":
            for det_id, det in (comp.get("channels") or {}).items():
                if isinstance(det, dict) and "component_class" in det:
                    registry.add(
                        {
                            "id": str(det_id),
                            "label": str(det_id).replace("_", " "),
                            "node_type": "component",
                            "subsystem": subsystem_id,
                            "component_class": det.get("component_class"),
                            "domain": "optical",
                            "source_file": source_file,
                            "parent_component": str(comp_id),
                        }
                    )
            registry.add(
                {
                    "id": str(comp_id),
                    "label": str(comp_id).replace("_", " "),
                    "node_type": "component",
                    "subsystem": subsystem_id,
                    "component_class": comp.get("component_class"),
                    "domain": "optical",
                    "source_file": source_file,
                }
            )
            continue
        registry.add(
            {
                "id": str(comp_id),
                "label": str(comp_id).replace("_", " "),
                "node_type": "component",
                "subsystem": subsystem_id,
                "component_class": comp.get("component_class"),
                "domain": "optical" if subsystem_id else "digital",
                "source_file": source_file,
                "model_binding_id": comp.get("model_binding_id"),
            }
        )

    for chan_id, chan in (doc.get("channels") or {}).items():
        if not isinstance(chan, dict) or "component_class" not in chan:
            continue
        registry.add(
            {
                "id": str(chan_id),
                "label": str(chan_id).replace("_", " "),
                "node_type": "channel",
                "subsystem": None,
                "component_class": chan.get("component_class"),
                "domain": "channel",
                "source_file": source_file,
                "model_binding_id": chan.get("model_binding_id"),
            }
        )

    for stage_id, stage in (doc.get("post_processing") or {}).items():
        if not isinstance(stage, dict) or "component_class" not in stage:
            continue
        registry.add(
            {
                "id": str(stage_id),
                "label": str(stage_id).replace("_", " "),
                "node_type": "post_processing",
                "subsystem": subsystem_id,
                "component_class": stage.get("component_class"),
                "domain": "software",
                "source_file": source_file,
                "model_binding_id": stage.get("model_binding_id"),
            }
        )


def _parent_for_node(node: dict[str, Any]) -> str | None:
    if node.get("node_type") == "subsystem":
        return None
    if node.get("subsystem"):
        return str(node["subsystem"])
    return None


def _group_member_ids(nodes: list[dict[str, Any]], group_id: str) -> set[str]:
    members = {str(n["id"]) for n in nodes if _parent_for_node(n) == group_id}
    if any(n["id"] == group_id and n.get("node_type") == "subsystem" for n in nodes):
        members.add(group_id)
    return members


def _boundary_edges(
    member_ids: set[str],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    boundary: list[dict[str, Any]] = []
    for edge in edges:
        source_id = str(edge["source"])
        target_id = str(edge["target"])
        source_in = source_id in member_ids
        target_in = target_id in member_ids
        if source_in == target_in:
            continue
        if source_in:
            boundary.append(
                {
                    "direction": "out",
                    "edge_id": edge["id"],
                    "internal_node": source_id,
                    "external_node": target_id,
                    "source_port": edge.get("source_port"),
                    "target_port": edge.get("target_port"),
                    "edge_kind": edge.get("edge_kind"),
                    "source_file": edge.get("source_file"),
                }
            )
        else:
            boundary.append(
                {
                    "direction": "in",
                    "edge_id": edge["id"],
                    "internal_node": target_id,
                    "external_node": source_id,
                    "source_port": edge.get("source_port"),
                    "target_port": edge.get("target_port"),
                    "edge_kind": edge.get("edge_kind"),
                    "source_file": edge.get("source_file"),
                }
            )
    return boundary


def _infer_group_ports(boundary: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    in_seen: set[str] = set()
    out_seen: set[str] = set()
    for hop in boundary:
        if hop["direction"] == "in" and hop.get("target_port"):
            pid = str(hop["target_port"])
            if pid not in in_seen:
                in_seen.add(pid)
                inputs.append(
                    {
                        "id": pid,
                        "group": "inferred_boundary",
                        "edge_kind": hop.get("edge_kind"),
                    }
                )
        if hop["direction"] == "out" and hop.get("source_port"):
            pid = str(hop["source_port"])
            if pid not in out_seen:
                out_seen.add(pid)
                outputs.append(
                    {
                        "id": pid,
                        "group": "inferred_boundary",
                        "edge_kind": hop.get("edge_kind"),
                    }
                )
    return {"inputs": inputs, "outputs": outputs}


def _yaml_hints_for_group(
    group: dict[str, Any],
    *,
    manifest_groups: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    group_id = str(group["id"])
    node = nodes_by_id.get(group_id, {})
    source_file = str(node.get("source_file") or f"{group_id}.yaml")
    deployment_role = group.get("deployment_role") or node.get("deployment_role")

    if node.get("node_type") == "subsystem":
        ports = node.get("ports") or {"inputs": [], "outputs": []}
        if not ports.get("inputs") and not ports.get("outputs"):
            hints.append(
                {
                    "kind": "suggestion",
                    "message": (
                        f"Declare boundary ports on subsystem `{group_id}` so the graph frame "
                        "can show explicit input/output connectors."
                    ),
                    "file": source_file,
                    "snippet": (
                        "subsystem:\n"
                        f"  id: \"{group_id}\"\n"
                        "  ports:\n"
                        "    optical_inputs:\n"
                        "      quantum_in: {signal_type: \"quantum_optical_stream\"}\n"
                        "    digital_outputs:\n"
                        "      timestamps_out: {packet_type: \"timestamp_event\"}"
                    ),
                }
            )
        if not node.get("component_class"):
            hints.append(
                {
                    "kind": "suggestion",
                    "message": f"Add `component_class` to subsystem `{group_id}` for catalog binding.",
                    "file": source_file,
                    "snippet": (
                        "subsystem:\n"
                        f"  id: \"{group_id}\"\n"
                        "  component_class: \"<subsystem_class>\""
                    ),
                }
            )
        if not deployment_role:
            hints.append(
                {
                    "kind": "suggestion",
                    "message": (
                        f"Add `deployment_role`, `endpoint_side`, and `topology_scope` to subsystem "
                        f"`{group_id}` so topology frames distinguish QKD devices from QKD nodes."
                    ),
                    "file": source_file,
                    "snippet": (
                        "subsystem:\n"
                        f"  id: \"{group_id}\"\n"
                        "  deployment_role: qkd_device  # qkd_device | qkd_node | network_coordination | quantum_source\n"
                        "  endpoint_side: alice       # alice | bob | source\n"
                        "  topology_scope: point_to_point  # point_to_point | network"
                    ),
                }
            )
        return hints

    if group_id not in manifest_groups:
        source_files = group.get("source_files") or []
        label = group.get("label") or group_id.replace("_", " ")
        hints.append(
            {
                "kind": "suggestion",
                "message": (
                    f"Document group `{group_id}` under `composition.groups` in the manifest "
                    "so UIs and agents can resolve members and source files."
                ),
                "file": "00_manifest.yaml",
                "snippet": (
                    "composition:\n"
                    "  groups:\n"
                    f"    {group_id}:\n"
                    f"      label: \"{label}\"\n"
                    f"      description: \"{group.get('description') or ''}\"\n"
                    "      source_files:\n"
                    + "".join(f'        - "{path}"\n' for path in source_files)
                ).rstrip(),
            }
        )

    ports = group.get("ports") or {"inputs": [], "outputs": []}
    if not ports.get("inputs") and not ports.get("outputs") and group.get("boundary_edges"):
        hints.append(
            {
                "kind": "info",
                "message": (
                    f"Boundary ports for `{group_id}` are inferred from declared connections. "
                    "Add explicit `composition.groups.<id>.ports` if you want documented frame connectors."
                ),
                "file": "00_manifest.yaml",
                "snippet": (
                    "composition:\n"
                    "  groups:\n"
                    f"    {group_id}:\n"
                    "      ports:\n"
                    "        inputs:\n"
                    "          in: {packet_type: \"<packet_type>\"}\n"
                    "        outputs:\n"
                    "          out: {packet_type: \"<packet_type>\"}"
                ),
            }
        )
    return hints


def _build_groups(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    composition: dict[str, Any],
) -> list[dict[str, Any]]:
    nodes_by_id = {str(n["id"]): n for n in nodes}
    manifest_groups = composition.get("groups") or {}
    if not isinstance(manifest_groups, dict):
        manifest_groups = {}

    manifest_subsystems = composition.get("subsystems") or []
    group_ids: list[str] = []
    seen: set[str] = set()
    if isinstance(manifest_subsystems, list):
        for raw_id in manifest_subsystems:
            gid = str(raw_id)
            if gid not in seen:
                seen.add(gid)
                group_ids.append(gid)
    for node in nodes:
        if node.get("node_type") == "subsystem":
            gid = str(node["id"])
            if gid not in seen:
                seen.add(gid)
                group_ids.append(gid)

    groups: list[dict[str, Any]] = []
    for group_id in group_ids:
        manifest_meta = manifest_groups.get(group_id) if isinstance(manifest_groups, dict) else None
        if not isinstance(manifest_meta, dict):
            manifest_meta = {}

        subsystem_node = nodes_by_id.get(group_id)
        deployment_role = (
            (subsystem_node or {}).get("deployment_role") or manifest_meta.get("deployment_role")
        )
        endpoint_side = (subsystem_node or {}).get("endpoint_side") or manifest_meta.get(
            "endpoint_side"
        )
        topology_scope = (subsystem_node or {}).get("topology_scope") or manifest_meta.get(
            "topology_scope"
        )
        group_kind = str(deployment_role or "subsystem")

        member_ids = sorted(_group_member_ids(nodes, group_id))
        member_set = set(member_ids)
        boundary = _boundary_edges(member_set, edges)

        if subsystem_node and subsystem_node.get("node_type") == "subsystem":
            ports = subsystem_node.get("ports") or {"inputs": [], "outputs": []}
            role_label = _DEPLOYMENT_ROLE_LABELS.get(str(deployment_role or ""))
            label = str(
                manifest_meta.get("label")
                or role_label
                or subsystem_node.get("label")
                or group_id.replace("_", " ")
            )
            description = manifest_meta.get("description")
            component_class = subsystem_node.get("component_class")
            source_files = manifest_meta.get("source_files") or (
                [subsystem_node["source_file"]] if subsystem_node.get("source_file") else []
            )
        else:
            ports = manifest_meta.get("ports")
            if not isinstance(ports, dict):
                ports = _infer_group_ports(boundary)
            else:
                ports = _flatten_declared_ports(ports)
            label = str(manifest_meta.get("label") or group_id.replace("_", " "))
            description = manifest_meta.get("description")
            component_class = manifest_meta.get("component_class")
            source_files = manifest_meta.get("source_files") or []

        group = {
            "id": group_id,
            "label": label,
            "group_kind": group_kind,
            "deployment_role": deployment_role,
            "endpoint_side": endpoint_side,
            "topology_scope": topology_scope,
            "description": description,
            "component_class": component_class,
            "source_files": list(source_files),
            "member_ids": member_ids,
            "member_count": len(member_ids),
            "ports": ports,
            "boundary_edges": boundary,
            "connected": bool(boundary),
        }
        group["yaml_hints"] = _yaml_hints_for_group(
            group,
            manifest_groups=manifest_groups if isinstance(manifest_groups, dict) else {},
            nodes_by_id=nodes_by_id,
        )
        groups.append(group)

    return sorted(groups, key=lambda g: (g.get("group_kind", ""), g["id"]))


def _edge_kind(source_id: str, target_id: str, registry: _NodeRegistry) -> str:
    nodes = {n["id"]: n for n in registry.values()}
    src = nodes.get(source_id, {})
    tgt = nodes.get(target_id, {})
    if src.get("node_type") == "channel" or tgt.get("node_type") == "channel":
        return "quantum" if "quantum" in source_id or "quantum" in target_id else "link"
    if src.get("domain") == "digital" or tgt.get("domain") == "digital":
        return "digital"
    if "classical" in source_id or "classical" in target_id:
        return "classical"
    if src.get("node_type") == "post_processing" or tgt.get("node_type") == "post_processing":
        return "software"
    return "optical"


def build_topology(config_dir: Path) -> dict[str, Any]:
    """Resolved design topology for one config set."""
    config_dir = Path(config_dir)

    try:
        from certiqs_sim.core.topology.loader import is_hierarchical_config, load_topology
        from certiqs_sim.core.topology.adapter import (
            build_frame_boundary_links,
            build_hierarchy_groups,
            collect_graph_component_ids,
            topology_to_flat_documents,
        )
        from certiqs_sim.core.topology.validate import assert_valid

        if is_hierarchical_config(config_dir):
            resolved = load_topology(config_dir)
            assert_valid(resolved)
            flat_docs = topology_to_flat_documents(resolved)
            result = _build_topology_from_docs(flat_docs, config_dir, resolved=resolved)
            from certiqs_sim.core.topology.source_paths import apply_config_source_paths

            apply_config_source_paths(result, resolved)
            result["hierarchy"] = build_hierarchy_groups(
                resolved,
                graph_component_ids=collect_graph_component_ids(flat_docs),
            )
            result["frame_links"] = build_frame_boundary_links(resolved)
            result["schema_version"] = resolved.schema_version
            result["configuration_hash"] = resolved.configuration_hash
            return result
    except ImportError:
        pass

    return _build_topology_from_docs(_load_all_docs(config_dir), config_dir)


def _load_all_docs(config_dir: Path) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for path in sorted(config_dir.glob("*.y*ml")):
        docs[path.name] = _load_yaml(path)
    return docs


def _build_topology_from_docs(
    docs: dict[str, dict[str, Any]],
    config_dir: Path,
    *,
    resolved: Any = None,
) -> dict[str, Any]:
    registry = _NodeRegistry()
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str | None, str | None, str | None]] = set()

    manifest_doc: dict[str, Any] = {}
    for name, doc in docs.items():
        if name.startswith("00_"):
            manifest_doc = doc
        _register_document_nodes(doc, name, registry)

    # Channel connections from channels doc
    channels_doc = docs.get("05_channels.yaml") or docs.get("09_channels.yaml") or {}

    def _add_edge(
        source_ref: str,
        target_ref: str,
        *,
        via: str | None = None,
        source_file: str,
    ) -> None:
        source_id = registry.resolve(source_ref)
        target_id = registry.resolve(target_ref)
        if source_id is None or target_id is None:
            return
        src_node, src_port = _parse_endpoint(source_ref)
        tgt_node, tgt_port = _parse_endpoint(target_ref)
        key = (source_id, target_id, via, src_port, tgt_port)
        if key in edge_keys:
            return
        edge_keys.add(key)
        port_suffix = ""
        if src_port or tgt_port:
            port_suffix = f":{src_port or ''}->{tgt_port or ''}"
        edges.append(
            {
                "id": f"{source_id}->{target_id}{port_suffix}" + (f"@{via}" if via else ""),
                "source": source_id,
                "target": target_id,
                "source_port": src_port,
                "target_port": tgt_port,
                "via": via,
                "edge_kind": _edge_kind(source_id, target_id, registry),
                "source_file": source_file,
            }
        )

    for name, doc in docs.items():
        for conn in doc.get("connections") or []:
            if not isinstance(conn, dict):
                continue
            src = str(conn.get("from", ""))
            tgt = str(conn.get("to", ""))
            via = conn.get("via")
            if not src or not tgt:
                continue
            if via:
                via_id = str(via)
                if via_id not in {n["id"] for n in registry.values()}:
                    registry.add(
                        {
                            "id": via_id,
                            "label": via_id.replace("_", " "),
                            "node_type": "channel",
                            "subsystem": None,
                            "component_class": "channel",
                            "domain": "channel",
                            "source_file": name,
                        }
                    )
                _add_edge(src, via_id, source_file=name)
                _add_edge(via_id, tgt, source_file=name)
            else:
                _add_edge(src, tgt, source_file=name)

    # Detector-array channels declare clicks on the wrapper (`detectors.clicks`).
    # Synthesize channel -> wrapper edges so the graph shows SPAD aggregation.
    for node in registry.values():
        parent_id = node.get("parent_component")
        if not parent_id or node.get("node_type") != "component":
            continue
        parent = registry.resolve(str(parent_id))
        if parent is None:
            continue
        key = (str(node["id"]), parent, None, "clicks", "clicks")
        if key in edge_keys:
            continue
        edge_keys.add(key)
        edges.append(
            {
                "id": f"{node['id']}->{parent}:clicks->clicks",
                "source": str(node["id"]),
                "target": parent,
                "source_port": "clicks",
                "target_port": "clicks",
                "via": None,
                "edge_kind": _edge_kind(str(node["id"]), parent, registry),
                "source_file": str(node.get("source_file") or ""),
                "synthetic": True,
            }
        )

    # Enrich nodes with registry model kind and merged port definitions.
    connected_ids: set[str] = set()
    for edge in edges:
        connected_ids.add(str(edge["source"]))
        connected_ids.add(str(edge["target"]))

    nodes: list[dict[str, Any]] = []
    for node in registry.values():
        spec = get_model_for_class(str(node.get("component_class") or ""))
        enriched = dict(node)
        if spec:
            enriched["model_kind"] = spec.kind
            enriched.setdefault("model_binding_id", spec.model_id)
        for meta_key in ("deployment_role", "endpoint_side", "topology_scope"):
            if node.get(meta_key) is not None:
                enriched[meta_key] = node.get(meta_key)
        declared = enriched.get("ports") or {"inputs": [], "outputs": []}
        inferred = _infer_ports_from_edges(str(node["id"]), edges)
        enriched["ports"] = _merge_ports(declared, inferred)
        if enriched.get("node_type") == "channel" and not enriched["ports"]["inputs"]:
            enriched["ports"]["inputs"] = [{"id": "in", "group": "channel"}]
        if enriched.get("node_type") == "channel" and not enriched["ports"]["outputs"]:
            enriched["ports"]["outputs"] = [{"id": "out", "group": "channel"}]
        enriched["connected"] = str(node["id"]) in connected_ids
        nodes.append(enriched)

    system = manifest_doc.get("system") or {}
    composition = manifest_doc.get("composition") or {}
    sha = resolved.configuration_hash if resolved is not None else manifest_sha256(config_dir)
    return {
        "config_dir": str(config_dir),
        "manifest_sha256": sha,
        "system": {
            "name": system.get("name"),
            "protocol": system.get("protocol"),
            "topology": system.get("topology"),
        },
        "composition": composition,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "connected_node_ids": sorted(connected_ids),
        "groups": _build_groups(nodes, edges, composition=composition),
        "nodes": sorted(nodes, key=lambda n: (n.get("node_type", ""), n["id"])),
        "edges": edges,
    }


__all__ = ["build_topology"]
