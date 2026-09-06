"""Load schema-3.0/3.1/4.0 hierarchical topology from a config directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from certiqs_sim.core.topology.colocated_io import collect_package_io
from certiqs_sim.core.topology.models import BoundaryContract, NodePackage, ResolvedTopology

_HIERARCHY_FILES = {
    "system": "01_system_topology.yaml",
    "nodes": "02_nodes.yaml",
    "boxes": "03_qkd_boxes.yaml",
    "domains": "04_domains.yaml",
    "modules": "05_modules.yaml",
    "components": "06_components.yaml",
    "interfaces": "07_interfaces_and_connections.yaml",
}

_NODE_PACKAGE_FILES_31 = {
    "node": "node.yaml",
    "box": "box.yaml",
    "domains": "domains.yaml",
    "modules": "modules.yaml",
    "components": "components.yaml",
    "interfaces": "interfaces.yaml",
    "control": "control.yaml",
    "environment": "environment.yaml",
}

_NODE_PACKAGE_FILES_40 = {
    "node": "node.yaml",
    "environment": "environment.yaml",
    "physical_protection": "physical_protection.yaml",
    "trusted_node_security": "trusted_node_security.yaml",
    "orchestration": "orchestration.yaml",
    "monitoring": "monitoring.yaml",
    "control": "control.yaml",
    "interfaces": "interfaces.yaml",
}

_DEVICE_FILES = {
    "device": "device.yaml",
    "domains": "domains.yaml",
    "modules": "modules.yaml",
    "components": "components.yaml",
}

_KMS_FILES = {
    "kms": "kms.yaml",
    "post_processing": "post_processing.yaml",
}

_NETWORK_FILES = {
    "topology": "topology.yaml",
    "channels": "channels.yaml",
    "control": "control.yaml",
    "management": "management.yaml",
}

_SHARED_FILES = {
    "protocol": "protocol.yaml",
    "taxonomy": "taxonomy.yaml",
    "catalog": "catalog.yaml",
    "qkd_software_domain": "qkd_software_domain.yaml",
}

_EXPERIMENT_FILES = {
    "experiments": "experiments.yaml",
    "attacks": "attacks.yaml",
    "validation": "validation.yaml",
    "agent_workflow": "agent_workflow.yaml",
}

_SUPPLEMENTAL_PREFIXES = (
    "08_protocol",
    "09_channels",
    "10_timing",
    "11_post_processing",
    "12_control",
    "13_environment",
    "14_attacks",
    "15_experiments",
    "16_metrics",
    "17_validation",
    "18_component_catalog",
    "19_component_taxonomy",
    "20_agent_workflow",
)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _index_by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(item[key]): item for item in items if isinstance(item, dict) and item.get(key)}


def _configuration_hash(docs: dict[str, Any]) -> str:
    payload = json.dumps(docs, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _schema_version(manifest_doc: dict[str, Any]) -> str:
    return str(manifest_doc.get("schema_version", manifest_doc.get("manifest", {}).get("schema_version", "")))


def _is_schema_40(version: str) -> bool:
    return version.startswith("4")


def _normalize_device_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize schema 3.1 box record to 4.0 device terminology."""
    out = dict(record)
    if "box_id" in out and "device_id" not in out:
        out["device_id"] = out.pop("box_id")
    if "box_type" in out and "device_type" not in out:
        out["device_type"] = out.pop("box_type")
    return out


def _normalize_domain_record(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    if "parent_box_id" in out and "parent_device_id" not in out:
        out["parent_device_id"] = out.pop("parent_box_id")
    return out


def _normalize_node_record(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    if "box_ids" in out and "device_ids" not in out:
        out["device_ids"] = out.pop("box_ids")
    return out


def is_package_config(config_dir: Path) -> bool:
    """True when manifest declares schema 3.1+ or 4.0+ with packages."""
    config_dir = Path(config_dir)
    for candidate in sorted(config_dir.glob("00_*.y*ml")):
        doc = _read_yaml(candidate)
        version = _schema_version(doc)
        if (version.startswith("3.1") or version.startswith("4")) and doc.get("packages"):
            return True
    return False


def is_hierarchical_config(config_dir: Path) -> bool:
    """True when manifest declares schema 3.x or 4.x."""
    config_dir = Path(config_dir)
    for candidate in sorted(config_dir.glob("00_*.y*ml")):
        doc = _read_yaml(candidate)
        version = _schema_version(doc)
        if version.startswith("3") or version.startswith("4"):
            return True
    return False


def _load_package_docs(package_dir: Path, file_map: dict[str, str]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for name, filename in file_map.items():
        path = package_dir / filename
        if path.is_file():
            docs[name] = _read_yaml(path)
    return docs


def _parse_devices_from_doc(devices_doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Parse qkd_device(s) or legacy qkd_box(es) from a device/box YAML doc."""
    entries = devices_doc.get("qkd_devices")
    if not entries:
        entries = devices_doc.get("qkd_boxes")
    if not entries:
        single = devices_doc.get("qkd_device") or devices_doc.get("qkd_box")
        entries = [single] if single else []
    devices = _index_by_id(
        [_normalize_device_record(b) for b in entries if b],
        "device_id",
    )
    return devices


def _load_device_subfolder(device_dir: Path) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load one device subfolder under devices/."""
    docs = _load_package_docs(device_dir, _DEVICE_FILES)
    devices_doc = docs.get("device") or {}
    devices = _parse_devices_from_doc(devices_doc)
    device = next(iter(devices.values()), None)

    domains_doc = docs.get("domains") or {}
    domains = {
        did: _normalize_domain_record(d)
        for did, d in _index_by_id(domains_doc.get("domains") or [], "domain_id").items()
    }
    subdomains = _index_by_id(domains_doc.get("subdomains") or [], "subdomain_id")
    modules = _index_by_id((docs.get("modules") or {}).get("modules") or [], "module_id")
    components = _index_by_id((docs.get("components") or {}).get("components") or [], "component_id")
    return device, devices, domains, subdomains, modules, components


def _load_kms(package_dir: Path) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, dict[str, Any]]]:
    kms_doc: dict[str, Any] | None = None
    post_processing: dict[str, Any] = {}
    kms_components: dict[str, dict[str, Any]] = {}
    kms_dir = package_dir / "kms"
    if kms_dir.is_dir():
        kms_docs = _load_package_docs(kms_dir, _KMS_FILES)
        kms_file = kms_docs.get("kms") or {}
        kms_meta = kms_file.get("kms") if isinstance(kms_file.get("kms"), dict) else kms_file
        kms_doc = kms_meta if kms_meta else None
        post_doc = kms_docs.get("post_processing") or {}
        post_processing = dict(post_doc.get("post_processing") or {})
        kms_components = _index_by_id(kms_file.get("components") or [], "component_id")
    return kms_doc, post_processing, kms_components


def load_node_package(package_dir: Path, *, schema_version: str = "") -> NodePackage:
    """Load a self-contained node package directory (schema 3.1 or 4.0)."""
    package_dir = Path(package_dir)
    version = schema_version or _schema_version(_read_yaml(package_dir / "node.yaml"))
    if _is_schema_40(version) and (package_dir / "devices").is_dir():
        return _load_node_package_v40(package_dir)
    return _load_node_package_v31(package_dir)


def _intra_node_links(node_doc: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Extract self-contained intra-node channel physics + wiring from node.yaml.

    Both endpoints of an intra-node connection live inside the same node, so the
    wiring is authored here (not in the network channel file). Generic: whatever
    the config declares under ``channels`` / ``connections`` is used verbatim.
    """
    channels = node_doc.get("channels")
    channels = dict(channels) if isinstance(channels, dict) else {}
    raw_connections = node_doc.get("connections")
    connections: list[dict[str, Any]] = []
    if isinstance(raw_connections, list):
        connections = [dict(c) for c in raw_connections if isinstance(c, dict)]
    return channels, connections


def _load_node_package_v40(package_dir: Path) -> NodePackage:
    """Load schema 4.0 node package with per-device subfolders."""
    docs = _load_package_docs(package_dir, _NODE_PACKAGE_FILES_40)
    node_doc = docs.get("node") or {}
    package_id = str(node_doc.get("package_id") or package_dir.name)
    node_id = str(node_doc.get("node_id") or "")
    node_role = str(node_doc.get("node_role") or "")
    boundary = BoundaryContract(
        provides=[str(p) for p in node_doc.get("provides") or []],
        requires=[str(r) for r in node_doc.get("requires") or []],
    )

    nodes = _index_by_id([node_doc.get("node") or node_doc], "node_id") if node_id else {}
    node = nodes.get(node_id) or node_doc.get("node") or node_doc
    if isinstance(node, dict):
        node = _normalize_node_record(node)
        if node_doc.get("boundary_ports"):
            node = {**node, "boundary_ports": node_doc["boundary_ports"]}
        if node_doc.get("layout"):
            node = {**node, "layout": node_doc["layout"]}

    devices: dict[str, dict[str, Any]] = {}
    device_paths: dict[str, str] = {}
    domains: dict[str, dict[str, Any]] = {}
    subdomains: dict[str, dict[str, Any]] = {}
    modules: dict[str, dict[str, Any]] = {}
    components: dict[str, dict[str, Any]] = {}

    devices_dir = package_dir / "devices"
    device_dirs = sorted(d for d in devices_dir.iterdir() if d.is_dir()) if devices_dir.is_dir() else []
    for device_dir in device_dirs:
        device, dev_map, dev_domains, dev_subdomains, dev_modules, dev_components = _load_device_subfolder(
            device_dir
        )
        if device:
            devices.update(dev_map)
            device_paths[str(device.get("device_id", device_dir.name))] = str(
                device_dir.relative_to(package_dir)
            )
        domains.update(dev_domains)
        subdomains.update(dev_subdomains)
        modules.update(dev_modules)
        components.update(dev_components)

    device = next(iter(devices.values()), None)

    io_doc = docs.get("interfaces") or {}
    interfaces, connections = collect_package_io(
        node_doc=node_doc,
        modules=modules,
        components=components,
        legacy_io_doc=io_doc if io_doc else None,
    )

    kms_doc, post_processing, kms_components = _load_kms(package_dir)
    components.update(kms_components)

    supplemental: dict[str, dict[str, Any]] = {}
    for key in (
        "control",
        "environment",
        "physical_protection",
        "trusted_node_security",
        "orchestration",
        "monitoring",
    ):
        if key in docs:
            supplemental[f"{key}.yaml"] = docs[key]

    intra_channels, intra_connections = _intra_node_links(node_doc)

    return NodePackage(
        package_id=package_id,
        package_dir=str(package_dir),
        node_id=node_id,
        node_role=node_role,
        boundary=boundary,
        node=node,
        device=device,
        devices=devices,
        kms=kms_doc,
        domains=domains,
        subdomains=subdomains,
        modules=modules,
        components=components,
        interfaces=interfaces,
        connections=connections,
        supplemental=supplemental,
        post_processing=post_processing,
        device_paths=device_paths,
        intra_channels=intra_channels,
        intra_connections=intra_connections,
    )


def _load_node_package_v31(package_dir: Path) -> NodePackage:
    """Load schema 3.1 node package (read-only fallback; flat box layout)."""
    package_dir = Path(package_dir)
    docs = _load_package_docs(package_dir, _NODE_PACKAGE_FILES_31)
    node_doc = docs.get("node") or {}
    package_id = str(node_doc.get("package_id") or package_dir.name)
    node_id = str(node_doc.get("node_id") or "")
    node_role = str(node_doc.get("node_role") or "")
    boundary = BoundaryContract(
        provides=[str(p) for p in node_doc.get("provides") or []],
        requires=[str(r) for r in node_doc.get("requires") or []],
    )

    nodes = _index_by_id([node_doc.get("node") or node_doc], "node_id") if node_id else {}
    node = nodes.get(node_id) or node_doc.get("node") or node_doc
    if isinstance(node, dict):
        node = _normalize_node_record(node)
        if node_doc.get("boundary_ports"):
            node = {**node, "boundary_ports": node_doc["boundary_ports"]}
        if node_doc.get("layout"):
            node = {**node, "layout": node_doc["layout"]}

    devices = _parse_devices_from_doc(docs.get("box") or {})
    device = next(iter(devices.values()), None)

    domains_doc = docs.get("domains") or {}
    domains = {
        did: _normalize_domain_record(d)
        for did, d in _index_by_id(domains_doc.get("domains") or [], "domain_id").items()
    }
    subdomains = _index_by_id(domains_doc.get("subdomains") or [], "subdomain_id")
    modules = _index_by_id((docs.get("modules") or {}).get("modules") or [], "module_id")
    components = _index_by_id((docs.get("components") or {}).get("components") or [], "component_id")
    io_doc = docs.get("interfaces") or {}
    interfaces, connections = collect_package_io(
        node_doc=node_doc,
        modules=modules,
        components=components,
        legacy_io_doc=io_doc if io_doc else None,
    )

    kms_doc, post_processing, kms_components = _load_kms(package_dir)
    components.update(kms_components)

    supplemental: dict[str, dict[str, Any]] = {}
    for key in ("control", "environment"):
        if key in docs:
            supplemental[f"{key}.yaml"] = docs[key]

    intra_channels, intra_connections = _intra_node_links(node_doc)

    return NodePackage(
        package_id=package_id,
        package_dir=str(package_dir),
        node_id=node_id,
        node_role=node_role,
        boundary=boundary,
        node=node,
        device=device,
        devices=devices,
        kms=kms_doc,
        domains=domains,
        subdomains=subdomains,
        modules=modules,
        components=components,
        interfaces=interfaces,
        connections=connections,
        supplemental=supplemental,
        post_processing=post_processing,
        intra_channels=intra_channels,
        intra_connections=intra_connections,
    )


def _merge_package_into(
    resolved_parts: dict[str, Any],
    package: NodePackage,
) -> None:
    """Merge one NodePackage into aggregate topology dicts."""
    resolved_parts["packages"][package.package_id] = package
    if package.node_id:
        resolved_parts["nodes"][package.node_id] = package.node
        resolved_parts["entity_package"][package.node_id] = package.package_id
    for device in package.all_devices():
        device_id = str(device.get("device_id", ""))
        if not device_id:
            continue
        resolved_parts["devices"][device_id] = device
        resolved_parts["entity_package"][device_id] = package.package_id
    if package.kms:
        kms_id = str(package.kms.get("kms_id", f"{package.package_id}_kms"))
        resolved_parts["kms"][kms_id] = package.kms
        resolved_parts["entity_package"][kms_id] = package.package_id
        for key in ("kma_id", "ksa_id", "key_store_id"):
            val = package.kms.get(key)
            if val:
                resolved_parts["entity_package"][str(val)] = package.package_id
    for entity_map, entities in (
        ("domains", package.domains),
        ("subdomains", package.subdomains),
        ("modules", package.modules),
        ("components", package.components),
        ("interfaces", package.interfaces),
    ):
        bucket = resolved_parts[entity_map]
        for eid, entity in entities.items():
            bucket[eid] = entity
            resolved_parts["entity_package"][eid] = package.package_id
    resolved_parts["connections"].extend(package.connections)
    resolved_parts["supplemental"].update(package.supplemental)
    if package.post_processing:
        resolved_parts["supplemental"][f"post_processing_{package.package_id}.yaml"] = {
            "post_processing": package.post_processing,
            "node_id": package.node_id,
        }


def _load_package_topology(config_dir: Path, manifest_doc: dict[str, Any]) -> ResolvedTopology:
    config_dir = Path(config_dir)
    schema_version = _schema_version(manifest_doc)
    hash_input: dict[str, Any] = {"manifest": manifest_doc}

    resolved_parts: dict[str, Any] = {
        "nodes": {},
        "devices": {},
        "domains": {},
        "subdomains": {},
        "modules": {},
        "components": {},
        "interfaces": {},
        "connections": [],
        "supplemental": {},
        "packages": {},
        "kms": {},
        "entity_package": {},
        "system": {},
    }

    network_dir = config_dir / "network"
    if network_dir.is_dir():
        net_docs = _load_package_docs(network_dir, _NETWORK_FILES)
        hash_input["network"] = net_docs
        resolved_parts["system"] = net_docs.get("topology") or {}
        for name, doc in net_docs.items():
            resolved_parts["supplemental"][f"network/{name}.yaml"] = doc

    shared_dir = config_dir / "shared"
    if shared_dir.is_dir():
        shared_docs = _load_package_docs(shared_dir, _SHARED_FILES)
        hash_input["shared"] = shared_docs
        for name, doc in shared_docs.items():
            resolved_parts["supplemental"][f"shared/{name}.yaml"] = doc

    experiments_dir = config_dir / "experiments"
    if experiments_dir.is_dir():
        exp_docs = _load_package_docs(experiments_dir, _EXPERIMENT_FILES)
        hash_input["experiments"] = exp_docs
        for name, doc in exp_docs.items():
            resolved_parts["supplemental"][f"experiments/{name}.yaml"] = doc

    packages_spec = manifest_doc.get("packages") or []
    for spec in packages_spec:
        if not isinstance(spec, dict):
            continue
        if spec.get("kind") != "node":
            continue
        rel_path = str(spec.get("path", ""))
        package_dir = config_dir / rel_path
        if not package_dir.is_dir():
            continue
        package = load_node_package(package_dir, schema_version=schema_version)
        hash_input.setdefault("packages", {})[package.package_id] = {
            "node_id": package.node_id,
            "path": rel_path,
        }
        _merge_package_into(resolved_parts, package)

    return ResolvedTopology(
        config_dir=str(config_dir),
        schema_version=schema_version,
        manifest=manifest_doc,
        system=resolved_parts["system"],
        nodes=resolved_parts["nodes"],
        devices=resolved_parts["devices"],
        domains=resolved_parts["domains"],
        subdomains=resolved_parts["subdomains"],
        modules=resolved_parts["modules"],
        components=resolved_parts["components"],
        interfaces=resolved_parts["interfaces"],
        connections=resolved_parts["connections"],
        supplemental=resolved_parts["supplemental"],
        configuration_hash=_configuration_hash(hash_input),
        packages=resolved_parts["packages"],
        kms=resolved_parts["kms"],
        entity_package=resolved_parts["entity_package"],
    )


def _load_topology_v30(config_dir: Path, manifest_doc: dict[str, Any]) -> ResolvedTopology:
    config_dir = Path(config_dir)
    schema_version = _schema_version(manifest_doc) or "3.0.0"
    docs: dict[str, Any] = {"manifest": manifest_doc}

    for name, filename in _HIERARCHY_FILES.items():
        path = config_dir / filename
        if path.is_file():
            docs[name] = _read_yaml(path)

    supplemental: dict[str, dict[str, Any]] = {}
    for path in sorted(config_dir.glob("*.y*ml")):
        if path.name.startswith("00_"):
            continue
        if any(path.name.startswith(prefix) for prefix in _SUPPLEMENTAL_PREFIXES):
            supplemental[path.name] = _read_yaml(path)

    nodes_doc = docs.get("nodes") or {}
    boxes_doc = docs.get("boxes") or {}
    domains_doc = docs.get("domains") or {}
    modules_doc = docs.get("modules") or {}
    components_doc = docs.get("components") or {}
    io_doc = docs.get("interfaces") or {}

    nodes = {
        nid: _normalize_node_record(n)
        for nid, n in _index_by_id(nodes_doc.get("nodes") or [], "node_id").items()
    }
    devices = _parse_devices_from_doc({"qkd_boxes": boxes_doc.get("qkd_boxes") or []})
    domains = {
        did: _normalize_domain_record(d)
        for did, d in _index_by_id(domains_doc.get("domains") or [], "domain_id").items()
    }
    subdomains = _index_by_id(domains_doc.get("subdomains") or [], "subdomain_id")
    modules = _index_by_id(modules_doc.get("modules") or [], "module_id")
    components = _index_by_id(components_doc.get("components") or [], "component_id")
    interfaces = _index_by_id(io_doc.get("interfaces") or [], "interface_id")
    connections = [c for c in (io_doc.get("connections") or []) if isinstance(c, dict)]

    hash_input = {**docs, "supplemental": supplemental}
    return ResolvedTopology(
        config_dir=str(config_dir),
        schema_version=schema_version,
        manifest=manifest_doc,
        system=docs.get("system") or {},
        nodes=nodes,
        devices=devices,
        domains=domains,
        subdomains=subdomains,
        modules=modules,
        components=components,
        interfaces=interfaces,
        connections=connections,
        supplemental=supplemental,
        configuration_hash=_configuration_hash(hash_input),
    )


def load_topology(config_dir: Path) -> ResolvedTopology:
    """Parse hierarchical YAML documents into a resolved topology bundle."""
    config_dir = Path(config_dir)
    manifest_doc: dict[str, Any] = {}
    for candidate in sorted(config_dir.glob("00_*.y*ml")):
        manifest_doc = _read_yaml(candidate)
        break

    if is_package_config(config_dir):
        return _load_package_topology(config_dir, manifest_doc)
    return _load_topology_v30(config_dir, manifest_doc)


__all__ = [
    "is_hierarchical_config",
    "is_package_config",
    "load_node_package",
    "load_topology",
]
