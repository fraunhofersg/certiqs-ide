"""Map legacy flat-adapter filenames to config-package-relative YAML paths.

Hierarchical configs (``config/bbm92-generic``) are adapted to schema-2.0 flat
documents for the simulation graph. Those synthetic keys (e.g.
``06_network_coordination.yaml``) must not surface in API/UI — callers receive
paths relative to the active configuration set root instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from certiqs_sim.core.topology.models import ResolvedTopology

# Legacy flat adapter document → canonical path inside the config set.
FLAT_DOC_PATHS: dict[str, str] = {
    "00_manifest.yaml": "00_manifest.yaml",
    "01_protocol.yaml": "shared/protocol.yaml",
    "02_source.yaml": "nodes/source/components.yaml",
    "03_alice_station.yaml": "nodes/alice/components.yaml",
    "04_bob_station.yaml": "nodes/bob/components.yaml",
    "05_channels.yaml": "network/channels.yaml",
    "06_network_coordination.yaml": "network/control.yaml",
    "06_timing_and_digital.yaml": "network/control.yaml",
    "07_alice_qkd_node.yaml": "nodes/alice/kms/post_processing.yaml",
    "07_post_processing.yaml": "nodes/alice/kms/post_processing.yaml",
    "08_bob_qkd_node.yaml": "nodes/bob/kms/post_processing.yaml",
}

# Subsystem / synthetic frame ids → primary declaration files.
GROUP_SOURCE_PATHS: dict[str, list[str]] = {
    "central_entanglement_source": [
        "nodes/source/components.yaml",
        "nodes/source/node.yaml",
    ],
    "alice_station": [
        "nodes/alice/components.yaml",
        "nodes/alice/modules.yaml",
        "nodes/alice/node.yaml",
    ],
    "bob_station": [
        "nodes/bob/components.yaml",
        "nodes/bob/modules.yaml",
        "nodes/bob/node.yaml",
    ],
    "network_coordination": ["network/control.yaml"],
    "alice_qkd_node": ["nodes/alice/kms/post_processing.yaml"],
    "bob_qkd_node": ["nodes/bob/kms/post_processing.yaml"],
}


def is_legacy_flat_name(path: str) -> bool:
    name = Path(path).name
    return name in FLAT_DOC_PATHS and name != FLAT_DOC_PATHS[name]


def remap_flat_source_file(flat_name: str) -> str:
    if not flat_name:
        return flat_name
    name = Path(flat_name).name
    if name in FLAT_DOC_PATHS:
        return FLAT_DOC_PATHS[name]
    if "/" in flat_name:
        return flat_name
    return flat_name


def _side_from_id(*ids: str) -> str | None:
    joined = " ".join(ids).lower()
    if "bob" in joined and "alice" not in joined:
        return "bob"
    if "alice" in joined:
        return "alice"
    if "source" in joined or "central" in joined or "entanglement" in joined:
        return "source"
    return None


def resolve_edge_source_file(edge: dict[str, Any]) -> str:
    """Pick the config YAML that declares a graph edge."""
    flat = str(edge.get("source_file") or "")
    src = str(edge.get("source") or "")
    tgt = str(edge.get("target") or "")
    src_port = str(edge.get("source_port") or "")
    tgt_port = str(edge.get("target_port") or "")
    via = str(edge.get("via") or "")
    kind = str(edge.get("edge_kind") or "")
    endpoints = (src, tgt, src_port, tgt_port, via)

    if via or kind == "quantum":
        return "network/channels.yaml"
    if kind == "classical" or "kx1" in src_port or "kx1" in tgt_port:
        return "network/channels.yaml"
    if any("quantum_to" in part for part in endpoints):
        return "network/channels.yaml"
    if "central_entanglement_source" in (src, tgt) and (
        "alice_station" in (src, tgt) or "bob_station" in (src, tgt)
    ):
        return "network/channels.yaml"
    if src_port == "quantum_in" or tgt_port == "quantum_in":
        return "network/channels.yaml"

    if "sifting" in (src, tgt) and "coincidence_matcher" in (src, tgt):
        return "nodes/alice/kms/post_processing.yaml"
    if any(
        token in (src, tgt)
        for token in ("coincidence_matcher", "network_coordination", "clock_synchronizer")
    ):
        return "network/control.yaml"
    if "timestamps" in src_port or "timestamps" in tgt_port:
        return "network/control.yaml"
    if src_port.endswith("_events") or tgt_port.endswith("_events"):
        return "network/control.yaml"

    if any(
        token in (src, tgt)
        for token in (
            "sifting",
            "reconciliation",
            "privacy_amplification",
            "finite_key_engine",
            "qber_estimation",
            "key_manager",
        )
    ):
        side = _side_from_id(src, tgt)
        if side == "bob":
            return "nodes/bob/kms/post_processing.yaml"
        return "nodes/alice/kms/post_processing.yaml"
    if "qkd_node" in src or "qkd_node" in tgt:
        side = _side_from_id(src, tgt)
        if side == "bob":
            return "nodes/bob/kms/post_processing.yaml"
        return "nodes/alice/kms/post_processing.yaml"

    side = _side_from_id(src, tgt, flat)
    if side == "source":
        return "nodes/source/components.yaml"
    if side == "alice":
        if "alice_station" in (src, tgt) and "coincidence" in (src, tgt):
            return "network/control.yaml"
        return "nodes/alice/components.yaml"
    if side == "bob":
        if "bob_station" in (src, tgt) and "coincidence" in (src, tgt):
            return "network/control.yaml"
        return "nodes/bob/components.yaml"

    return remap_flat_source_file(flat)


def resolve_node_source_file(node: dict[str, Any], *, resolved: ResolvedTopology | None) -> str:
    node_id = str(node.get("id") or "")
    if node_id in GROUP_SOURCE_PATHS:
        return GROUP_SOURCE_PATHS[node_id][0]

    if resolved is not None:
        pkg_id = resolved.entity_package.get(node_id)
        if pkg_id:
            pkg = resolved.packages.get(pkg_id)
            if pkg:
                rel = Path(pkg.package_dir).name
                if node_id in pkg.components:
                    return f"nodes/{rel}/components.yaml"
                if node_id in pkg.interfaces:
                    owner = (pkg.interfaces.get(node_id) or {}).get("owner_id", "")
                    if owner in pkg.components:
                        return f"nodes/{rel}/components.yaml"
                    if owner in pkg.modules:
                        return f"nodes/{rel}/modules.yaml"
                    return f"nodes/{rel}/node.yaml"
                if node_id == pkg.node_id:
                    return f"nodes/{rel}/node.yaml"
                for device in pkg.all_devices():
                    device_id = str(device.get("device_id", ""))
                    if node_id == device_id:
                        rel_path = pkg.device_paths.get(device_id)
                        if rel_path:
                            return f"nodes/{rel}/{rel_path}/device.yaml"
                        return f"nodes/{rel}/devices/{device_id}/device.yaml"
                if node_id in pkg.domains:
                    for device_id, rel_path in pkg.device_paths.items():
                        if node_id in (pkg.devices.get(device_id) or {}).get("domain_ids", []):
                            return f"nodes/{rel}/{rel_path}/domains.yaml"
                    return f"nodes/{rel}/devices/*/domains.yaml"
                if node_id in pkg.components:
                    for device_id, rel_path in pkg.device_paths.items():
                        if node_id in pkg.components:
                            return f"nodes/{rel}/{rel_path}/components.yaml"
                    return f"nodes/{rel}/components.yaml"

    if node.get("node_type") == "channel":
        return "network/channels.yaml"
    if node_id.startswith("alice_"):
        return "nodes/alice/components.yaml"
    if node_id.startswith("bob_"):
        return "nodes/bob/components.yaml"
    if node_id.startswith("central_") or node_id in {"pump_laser", "spdc_entangled_pair_source"}:
        return "nodes/source/components.yaml"

    return remap_flat_source_file(str(node.get("source_file") or ""))


def apply_config_source_paths(
    topology: dict[str, Any],
    resolved: ResolvedTopology | None = None,
) -> None:
    """Rewrite legacy adapter filenames on nodes, edges, and group boundaries."""
    for edge in topology.get("edges") or []:
        if edge.get("source_file"):
            edge["source_file"] = resolve_edge_source_file(edge)

    for node in topology.get("nodes") or []:
        node["source_file"] = resolve_node_source_file(node, resolved=resolved)

    for group in topology.get("groups") or []:
        gid = str(group.get("id", ""))
        if gid in GROUP_SOURCE_PATHS:
            group["source_files"] = list(GROUP_SOURCE_PATHS[gid])
        elif group.get("source_files"):
            group["source_files"] = [
                remap_flat_source_file(str(path)) for path in group["source_files"]
            ]
        for boundary in group.get("boundary_edges") or []:
            if boundary.get("source_file"):
                boundary["source_file"] = resolve_edge_source_file(
                    {
                        "source_file": boundary["source_file"],
                        "source": boundary.get("external_node", ""),
                        "target": boundary.get("internal_node", ""),
                        "source_port": boundary.get("source_port"),
                        "target_port": boundary.get("target_port"),
                        "edge_kind": boundary.get("edge_kind"),
                    }
                )


__all__ = [
    "FLAT_DOC_PATHS",
    "apply_config_source_paths",
    "is_legacy_flat_name",
    "remap_flat_source_file",
    "resolve_edge_source_file",
    "resolve_node_source_file",
]
