"""Virtual Topology Model (VTM) — config-driven graph built from ResolvedTopology.

No network-specific ID literals; all roles, sides, lanes, ports, edges, and
authority relations are derived from declared configuration fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from certiqs_sim.core.topology.models import ResolvedTopology

_PORT_META_KEYS = frozenset(
    {
        "direction",
        "signal_type",
        "interface_type",
        "boundary",
        "connector",
        "comment",
        "packet_type",
        "interface_id",
        "edge_kind",
        "medium",
        "owner_id",
    }
)

_EDGE_KIND_BY_SIGNAL = {
    "quantum_optical_stream": "quantum",
    "timestamp_event_stream": "digital",
    "kx1_key_relay": "digital",
    "secret_key": "digital",
}


def _medium_for_port(port: dict[str, Any]) -> str | None:
    medium = port.get("medium")
    if medium:
        return str(medium)
    edge_kind = port.get("edge_kind")
    if edge_kind:
        return str(edge_kind)
    signal = str(port.get("signal_type") or "")
    return _EDGE_KIND_BY_SIGNAL.get(signal)


def _normalize_direction(direction: str | None) -> str:
    raw = str(direction or "").lower()
    if raw in ("inout", "bidirectional", "bidir"):
        return "inout"
    if raw in ("in", "out"):
        return raw
    return raw or "in"


def _port_entry(port_id: str, spec: dict[str, Any], *, source_file: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": str(port_id)}
    for key in _PORT_META_KEYS:
        if key in spec and spec[key] is not None:
            entry[key] = spec[key]
    medium = _medium_for_port(spec)
    if medium:
        entry["medium"] = medium
    if source_file:
        entry["source_file"] = source_file
    direction = _normalize_direction(spec.get("direction"))
    if direction:
        entry["direction"] = direction
    return entry


def _bucket_ports(ports: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    bidirectional: list[dict[str, Any]] = []
    for port in ports:
        direction = _normalize_direction(port.get("direction"))
        if direction == "inout":
            bidirectional.append(port)
        elif direction == "in":
            inputs.append(port)
        elif direction == "out":
            outputs.append(port)
    return {"inputs": inputs, "outputs": outputs, "bidirectional": bidirectional}


@dataclass
class VirtualPort:
    id: str
    owner_id: str | None = None
    direction: str = "in"
    edge_kind: str | None = None
    medium: str | None = None
    signal_type: str | None = None
    connector: dict[str, Any] | None = None
    boundary: bool = False
    source_file: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "direction": self.direction,
            "boundary": self.boundary,
        }
        if self.owner_id:
            out["owner_id"] = self.owner_id
        if self.edge_kind:
            out["edge_kind"] = self.edge_kind
        if self.medium:
            out["medium"] = self.medium
        if self.signal_type:
            out["signal_type"] = self.signal_type
        if self.connector:
            out["connector"] = self.connector
        if self.source_file:
            out["source_file"] = self.source_file
        return out


@dataclass
class VirtualNode:
    node_id: str
    package_id: str
    name: str
    node_role: str
    endpoint_side: str | None = None
    lane: str | None = None
    order: int = 0
    authoritative_host: bool = False
    layout: dict[str, Any] = field(default_factory=dict)
    boundary_ports: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    subsystem_id: str | None = None
    qkd_node_id: str | None = None

    @property
    def station_subsystem_id(self) -> str:
        if self.subsystem_id:
            return self.subsystem_id
        side = self.endpoint_side or self.node_id.removeprefix("node_")
        return f"{side}_station"


@dataclass
class VirtualEdge:
    source_id: str
    target_id: str
    source_port: str | None = None
    target_port: str | None = None
    edge_kind: str = "link"
    medium: str | None = None
    via: str | None = None
    channel_id: str | None = None
    source_file: str | None = None
    bidirectional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "source_port": self.source_port,
            "target_port": self.target_port,
            "edge_kind": self.edge_kind,
            "medium": self.medium or self.edge_kind,
            "via": self.via,
            "channel_id": self.channel_id,
            "source_file": self.source_file,
            "bidirectional": self.bidirectional,
        }


@dataclass
class VirtualChannel:
    channel_id: str
    component_class: str
    edge_kind: str | None = None
    bidirectional: bool = False
    bindings: list[dict[str, Any]] = field(default_factory=list)
    source_file: str = "network/channels.yaml"


@dataclass
class AuthorityRelation:
    host_endpoint_side: str
    peer_endpoint_sides: list[str] = field(default_factory=list)
    component_id: str | None = None
    source_file: str = "network/control.yaml"


@dataclass
class VirtualTopologyModel:
    system_id: str
    system_name: str
    node_order: list[str]
    nodes: dict[str, VirtualNode]
    edges: list[VirtualEdge]
    channels: dict[str, VirtualChannel]
    authority: list[AuthorityRelation]
    coordination_endpoint_side: str | None = None

    def node_by_endpoint_side(self, side: str) -> VirtualNode | None:
        for node in self.nodes.values():
            if node.endpoint_side == side:
                return node
        return None

    def authoritative_host_node(self) -> VirtualNode | None:
        for node in self.nodes.values():
            if node.authoritative_host:
                return node
        return None


def _package_node_doc(resolved: ResolvedTopology, package_id: str) -> dict[str, Any]:
    package = resolved.packages.get(package_id)
    if not package:
        return {}
    node_doc_path = f"nodes/{package.package_dir.split('/')[-1]}/node.yaml"
    # Top-level fields live on the package loader's node merge; recover from package.node
    merged = dict(package.node)
    # layout may only exist on the raw node.yaml root — check supplemental isn't needed
    return merged


def _node_layout(resolved: ResolvedTopology, node_id: str, package: Any) -> dict[str, Any]:
    layout = package.node.get("layout") if package else None
    if not layout:
        node = resolved.nodes.get(node_id) or {}
        layout = node.get("layout")
    return dict(layout) if isinstance(layout, dict) else {}


def _authority_from_control(resolved: ResolvedTopology) -> tuple[list[AuthorityRelation], str | None]:
    control = resolved.supplemental.get("network/control.yaml") or {}
    timing = control.get("timing") or control
    proc = timing.get("coincidence_processor") or {}
    host = proc.get("authoritative_host")
    peers = [str(p) for p in (proc.get("peer_nodes") or []) if p]
    relations: list[AuthorityRelation] = []
    coord_side: str | None = str(host) if host else None
    if host:
        relations.append(
            AuthorityRelation(
                host_endpoint_side=str(host),
                peer_endpoint_sides=peers,
                component_id=str(proc.get("execution_location") or "") or None,
                source_file="network/control.yaml",
            )
        )
    return relations, coord_side


def _channel_edge_kind(channel: dict[str, Any]) -> str:
    edge_kind = channel.get("edge_kind")
    if edge_kind:
        return str(edge_kind)
    component_class = str(channel.get("component_class") or "")
    if component_class == "classical_network_link":
        return "digital"
    if component_class == "time_sync_channel":
        return "digital"
    if "fiber" in component_class or "quantum" in component_class:
        return "quantum"
    return "link"


def _collect_boundary_ports(
    resolved: ResolvedTopology,
    node_id: str,
    *,
    source_file: str,
) -> dict[str, list[dict[str, Any]]]:
    package_id = resolved.entity_package.get(node_id)
    if not package_id:
        return {"inputs": [], "outputs": [], "bidirectional": []}
    package = resolved.packages.get(package_id)
    if not package:
        return {"inputs": [], "outputs": [], "bidirectional": []}

    ports: list[dict[str, Any]] = []
    for iface_id, iface in package.interfaces.items():
        if not iface.get("boundary"):
            continue
        # Ports hosted by a device (box) render on that device frame, not the node.
        if resolved.owner_device_id(iface.get("owner_id")) is not None:
            continue
        ports.append(_port_entry(str(iface_id), iface, source_file=source_file))
    return _bucket_ports(ports)


def _binding_edges(
    resolved: ResolvedTopology,
    channels_doc: dict[str, Any],
) -> list[VirtualEdge]:
    channels = channels_doc.get("channels") or {}
    bindings = channels_doc.get("bindings") or []
    edges: list[VirtualEdge] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        channel_id = str(binding.get("channel_id", ""))
        channel = channels.get(channel_id) or {}
        edge_kind = _channel_edge_kind(channel)
        from_pkg = str(binding.get("from_package", ""))
        to_pkg = str(binding.get("to_package", ""))
        from_port = binding.get("from_port")
        to_port = binding.get("to_port")
        source_node = _package_to_node_id(resolved, from_pkg) or from_pkg
        target_node = _package_to_node_id(resolved, to_pkg) or to_pkg
        edges.append(
            VirtualEdge(
                source_id=source_node,
                target_id=target_node,
                source_port=str(from_port) if from_port else None,
                target_port=str(to_port) if to_port else None,
                edge_kind=edge_kind,
                medium=edge_kind,
                via=channel_id,
                channel_id=channel_id,
                source_file="network/channels.yaml",
                bidirectional=bool(channel.get("bidirectional")),
            )
        )
    return edges


def _package_to_node_id(resolved: ResolvedTopology, package_ref: str) -> str | None:
    if not package_ref or package_ref == "network":
        return None
    for pkg_id, package in resolved.packages.items():
        if pkg_id == package_ref:
            return package.node_id
    return None


def build_virtual_topology(resolved: ResolvedTopology) -> VirtualTopologyModel:
    """Build a config-driven virtual model with no hardcoded network IDs."""
    system = resolved.system.get("qkd_system") or {}
    system_id = str(system.get("system_id", "qkd_system"))
    system_name = str(system.get("name", "QKD System"))
    node_order = [str(n) for n in (system.get("node_ids") or [])]

    authority, coord_side = _authority_from_control(resolved)
    auth_hosts = {rel.host_endpoint_side for rel in authority}

    nodes: dict[str, VirtualNode] = {}
    for node_id in node_order:
        node = resolved.nodes.get(node_id) or {}
        package_id = str(resolved.entity_package.get(node_id, ""))
        package = resolved.packages.get(package_id)
        layout = _node_layout(resolved, node_id, package)
        endpoint_side = layout.get("endpoint_side")
        if endpoint_side is not None:
            endpoint_side = str(endpoint_side)
        node_role = str(node.get("node_role") or (package.node_role if package else ""))
        lane = str(layout.get("lane")) if layout.get("lane") else None
        order = int(layout.get("order", 0) or 0)
        pkg_dir_name = ""
        if package:
            pkg_dir_name = package.package_dir.rstrip("/").split("/")[-1]
        source_file = f"nodes/{pkg_dir_name}/node.yaml" if pkg_dir_name else None
        boundary = _collect_boundary_ports(
            resolved,
            node_id,
            source_file=source_file or "nodes/node.yaml",
        )
        vnode = VirtualNode(
            node_id=node_id,
            package_id=package_id,
            name=str(node.get("name", node_id)),
            node_role=node_role,
            endpoint_side=endpoint_side,
            lane=lane,
            order=order,
            authoritative_host=bool(endpoint_side and endpoint_side in auth_hosts),
            layout=layout,
            boundary_ports=boundary,
            subsystem_id=str(layout.get("subsystem_id") or "") or None,
            qkd_node_id=str(layout.get("qkd_node_id") or "") or None,
        )
        if not vnode.qkd_node_id and endpoint_side:
            vnode.qkd_node_id = f"{endpoint_side}_qkd_node"
        nodes[node_id] = vnode

    channels_doc = resolved.supplemental.get("network/channels.yaml") or {}
    channel_specs: dict[str, VirtualChannel] = {}
    for channel_id, spec in (channels_doc.get("channels") or {}).items():
        if not isinstance(spec, dict):
            continue
        channel_specs[str(channel_id)] = VirtualChannel(
            channel_id=str(channel_id),
            component_class=str(spec.get("component_class", "")),
            edge_kind=_channel_edge_kind(spec),
            bidirectional=bool(spec.get("bidirectional")),
            bindings=[],
        )
    for binding in channels_doc.get("bindings") or []:
        if not isinstance(binding, dict):
            continue
        cid = str(binding.get("channel_id", ""))
        if cid in channel_specs:
            channel_specs[cid].bindings.append(binding)

    edges = _binding_edges(resolved, channels_doc)

    return VirtualTopologyModel(
        system_id=system_id,
        system_name=system_name,
        node_order=node_order,
        nodes=nodes,
        edges=edges,
        channels=channel_specs,
        authority=authority,
        coordination_endpoint_side=coord_side,
    )


def enrich_hierarchy_node_group(
    group: dict[str, Any],
    vtm: VirtualTopologyModel,
) -> dict[str, Any]:
    """Attach VTM metadata to a qkd_node hierarchy group."""
    node_id = str(group.get("id", ""))
    vnode = vtm.nodes.get(node_id)
    if not vnode:
        return group
    enriched = dict(group)
    if vnode.endpoint_side:
        enriched["endpoint_side"] = vnode.endpoint_side
    if vnode.lane:
        enriched["lane"] = vnode.lane
    enriched["order"] = vnode.order
    if vnode.authoritative_host:
        enriched["authoritative_host"] = True
    if vnode.boundary_ports:
        enriched["ports"] = vnode.boundary_ports
    return enriched


__all__ = [
    "AuthorityRelation",
    "VirtualChannel",
    "VirtualEdge",
    "VirtualNode",
    "VirtualPort",
    "VirtualTopologyModel",
    "build_virtual_topology",
    "enrich_hierarchy_node_group",
]
