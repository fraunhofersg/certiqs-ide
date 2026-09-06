"""Flatten colocated ports/connections from node, module, and component YAML."""

from __future__ import annotations

from typing import Any

_PORT_KEYS = frozenset(
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
    }
)


def _default_interface_id(owner_id: str, port_name: str) -> str:
    safe_port = port_name.replace(".", "_")
    if owner_id.startswith("module_"):
        # module_alice_pam + quantum_in -> alice_pam_quantum_in; callers should set interface_id
        suffix = owner_id.removeprefix("module_")
        return f"{suffix}_{safe_port}"
    return f"{owner_id}_{safe_port}"


def _port_entry(
    owner_id: str,
    port_name: str,
    spec: dict[str, Any] | str | None,
) -> dict[str, Any]:
    if isinstance(spec, str):
        spec = {"signal_type": spec}
    if not isinstance(spec, dict):
        spec = {}
    iface_id = str(spec.get("interface_id") or _default_interface_id(owner_id, port_name))
    entry: dict[str, Any] = {
        "interface_id": iface_id,
        "owner_id": owner_id,
        "interface_type": spec.get("interface_type", "signal"),
        "direction": spec.get("direction", "inout"),
        "signal_type": spec.get("signal_type", port_name),
    }
    for key in _PORT_KEYS:
        if key in spec and key != "interface_id":
            entry[key] = spec[key]
    if spec.get("boundary"):
        entry["boundary"] = True
        entry["interface_type"] = spec.get("interface_type", "boundary")
    return entry


def _resolve_port_ref(
    ref: str,
    port_map: dict[str, str],
) -> str | None:
    """Resolve `component.port` or bare interface_id to global interface_id."""
    ref = str(ref).strip()
    if not ref:
        return None
    if ref in port_map:
        return port_map[ref]
    if "." in ref:
        owner, port = ref.split(".", 1)
        key = f"{owner}.{port}"
        if key in port_map:
            return port_map[key]
        return _default_interface_id(owner, port)
    return ref


def collect_colocated_io(
    *,
    node_doc: dict[str, Any],
    modules: dict[str, dict[str, Any]],
    components: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Build flat interfaces + connections from colocated authoring fields."""
    interfaces: dict[str, dict[str, Any]] = {}
    connections: list[dict[str, Any]] = []
    port_map: dict[str, str] = {}  # scoped ref -> interface_id

    def register(iface: dict[str, Any]) -> str:
        iface_id = str(iface["interface_id"])
        interfaces[iface_id] = iface
        owner = str(iface["owner_id"])
        port_map[iface_id] = iface_id
        port_map[f"{owner}.{iface.get('_port_name', '')}"] = iface_id
        return iface_id

    # Node boundary ports (provides / requires metadata)
    boundary_ports = node_doc.get("boundary_ports") or {}
    if isinstance(boundary_ports, dict):
        for port_name, spec in boundary_ports.items():
            if not isinstance(spec, dict):
                continue
            owner = str(spec.get("owner_id") or node_doc.get("node_id", ""))
            entry = _port_entry(owner, port_name, {**spec, "interface_id": spec.get("interface_id", port_name)})
            entry["_port_name"] = port_name
            if port_name in (node_doc.get("provides") or []):
                entry["boundary"] = True
            register(entry)
            port_map[f"boundary.{port_name}"] = entry["interface_id"]

    # Module ports and module-level connections
    for module_id, module in modules.items():
        ports = module.get("ports") or {}
        if isinstance(ports, dict):
            for port_name, spec in ports.items():
                entry = _port_entry(module_id, port_name, spec)
                entry["_port_name"] = port_name
                iface_id = register(entry)
                port_map[f"{module_id}.{port_name}"] = iface_id

        for idx, conn in enumerate(module.get("internal_connections") or []):
            if not isinstance(conn, dict):
                continue
            from_ref = conn.get("from")
            to_ref = conn.get("to")
            from_port = conn.get("from_port")
            to_port = conn.get("to_port")
            if from_ref and from_port:
                src = _resolve_port_ref(f"{from_ref}.{from_port}", port_map)
            elif from_ref:
                src = _resolve_port_ref(str(from_ref), port_map)
            else:
                src = _resolve_port_ref(str(conn.get("from_interface_id", "")), port_map)
            if to_ref and to_port:
                tgt = _resolve_port_ref(f"{to_ref}.{to_port}", port_map)
            elif to_ref:
                tgt = _resolve_port_ref(str(to_ref), port_map)
            else:
                tgt = _resolve_port_ref(str(conn.get("to_interface_id", "")), port_map)
            if not src or not tgt:
                continue
            connections.append(
                {
                    "connection_id": str(conn.get("connection_id") or f"{module_id}_internal_{idx}"),
                    "from_interface_id": src,
                    "to_interface_id": tgt,
                    "connection_type": conn.get("connection_type", "internal_signal"),
                    "_scope": "module_internal",
                    "_owner_module": module_id,
                }
            )

        for idx, conn in enumerate(module.get("external_connections") or []):
            if not isinstance(conn, dict):
                continue
            from_port = str(conn.get("from_port", ""))
            src = port_map.get(f"{module_id}.{from_port}") or _resolve_port_ref(
                f"{module_id}.{from_port}", port_map
            )
            to_module = str(conn.get("to_module", ""))
            to_port = str(conn.get("to_port", ""))
            tgt_module = modules.get(to_module, {})
            tgt_ports = tgt_module.get("ports") or {}
            tgt_spec = tgt_ports.get(to_port) if isinstance(tgt_ports, dict) else None
            if isinstance(tgt_spec, dict) and tgt_spec.get("interface_id"):
                tgt = str(tgt_spec["interface_id"])
            else:
                tgt = port_map.get(f"{to_module}.{to_port}") or _resolve_port_ref(
                    f"{to_module}.{to_port}", port_map
                )
            if not src or not tgt:
                continue
            connections.append(
                {
                    "connection_id": str(conn.get("connection_id") or f"{module_id}_ext_{idx}"),
                    "from_interface_id": src,
                    "to_interface_id": tgt,
                    "connection_type": conn.get("connection_type", "internal_signal"),
                    "_scope": "module_external",
                    "_owner_module": module_id,
                }
            )

    # Component ports and connections
    for comp_id, comp in components.items():
        ports = comp.get("ports") or {}
        if isinstance(ports, dict):
            for port_name, spec in ports.items():
                entry = _port_entry(comp_id, port_name, spec)
                entry["_port_name"] = port_name
                iface_id = register(entry)
                port_map[f"{comp_id}.{port_name}"] = iface_id

        parent_module = str(comp.get("parent_module_id") or "")
        for idx, conn in enumerate(comp.get("connections") or []):
            if not isinstance(conn, dict):
                continue
            from_port = str(conn.get("from_port", ""))
            src = port_map.get(f"{comp_id}.{from_port}") or _resolve_port_ref(
                f"{comp_id}.{from_port}", port_map
            )
            to_ref = str(conn.get("to", conn.get("to_component", "")))
            to_port = str(conn.get("to_port", ""))
            if to_ref and to_port:
                tgt = _resolve_port_ref(f"{to_ref}.{to_port}", port_map)
            elif to_ref:
                tgt = _resolve_port_ref(to_ref, port_map)
            else:
                tgt = _resolve_port_ref(str(conn.get("to_interface_id", "")), port_map)
            if not src or not tgt:
                continue
            connections.append(
                {
                    "connection_id": str(conn.get("connection_id") or f"{comp_id}_conn_{idx}"),
                    "from_interface_id": src,
                    "to_interface_id": tgt,
                    "connection_type": conn.get("connection_type", "internal_signal"),
                    "_scope": "component",
                    "_owner_component": comp_id,
                    "_owner_module": parent_module,
                }
            )

    # Strip internal _port_name from exported interfaces
    for iface in interfaces.values():
        iface.pop("_port_name", None)

    return interfaces, connections


def collect_package_io(
    *,
    node_doc: dict[str, Any],
    modules: dict[str, dict[str, Any]],
    components: dict[str, dict[str, Any]],
    legacy_io_doc: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Prefer colocated fields; fall back to legacy interfaces.yaml when empty."""
    colocated_ifaces, colocated_conns = collect_colocated_io(
        node_doc=node_doc,
        modules=modules,
        components=components,
    )
    if colocated_ifaces or colocated_conns:
        return colocated_ifaces, colocated_conns

    legacy_io = legacy_io_doc or {}
    interfaces = {
        str(item["interface_id"]): item
        for item in (legacy_io.get("interfaces") or [])
        if isinstance(item, dict) and item.get("interface_id")
    }
    connections = [c for c in (legacy_io.get("connections") or []) if isinstance(c, dict)]
    return interfaces, connections


__all__ = ["collect_colocated_io", "collect_package_io"]
