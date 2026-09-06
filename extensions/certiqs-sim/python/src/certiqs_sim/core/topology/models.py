"""Typed models for hierarchical CA-QKD topology (schema 3.0 / 3.1 / 4.0)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StructuralPath:
    system_id: str
    node_id: str | None = None
    device_id: str | None = None
    domain_id: str | None = None
    subdomain_id: str | None = None
    module_id: str | None = None
    component_id: str | None = None
    package_id: str | None = None
    kms_id: str | None = None

    def as_list(self) -> list[str]:
        parts: list[str] = [self.system_id]
        for value in (
            self.package_id,
            self.node_id,
            self.kms_id,
            self.device_id,
            self.domain_id,
            self.subdomain_id,
            self.module_id,
            self.component_id,
        ):
            if value:
                parts.append(value)
        return parts

    def as_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"system_id": self.system_id}
        if self.package_id:
            out["package_id"] = self.package_id
        if self.node_id:
            out["node_id"] = self.node_id
        if self.kms_id:
            out["kms_id"] = self.kms_id
        if self.device_id:
            out["device_id"] = self.device_id
        if self.domain_id:
            out["domain_id"] = self.domain_id
        if self.subdomain_id:
            out["subdomain_id"] = self.subdomain_id
        if self.module_id:
            out["module_id"] = self.module_id
        if self.component_id:
            out["component_id"] = self.component_id
        return out


@dataclass
class BoundaryContract:
    """Declared external boundary for a self-contained package."""

    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)


@dataclass
class NodePackage:
    """Self-contained QKD node package (schema 3.1 / 4.0)."""

    package_id: str
    package_dir: str
    node_id: str
    node_role: str
    boundary: BoundaryContract
    node: dict[str, Any]
    device: dict[str, Any] | None = None
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    kms: dict[str, Any] | None = None
    domains: dict[str, dict[str, Any]] = field(default_factory=dict)
    subdomains: dict[str, dict[str, Any]] = field(default_factory=dict)
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    interfaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    connections: list[dict[str, Any]] = field(default_factory=list)
    supplemental: dict[str, dict[str, Any]] = field(default_factory=dict)
    post_processing: dict[str, Any] = field(default_factory=dict)
    device_paths: dict[str, str] = field(default_factory=dict)
    #: Intra-node channel physics declared in ``node.yaml`` (self-contained).
    intra_channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Intra-node port wiring declared in ``node.yaml`` (both endpoints local).
    intra_connections: list[dict[str, Any]] = field(default_factory=list)

    def all_devices(self) -> list[dict[str, Any]]:
        """All devices owned by this package (supports multi-device nodes)."""
        if self.devices:
            return list(self.devices.values())
        return [self.device] if self.device else []

    def local_ids(self) -> set[str]:
        ids: set[str] = {self.node_id, self.package_id}
        for device in self.all_devices():
            ids.add(str(device.get("device_id", "")))
        if self.kms:
            ids.add(str(self.kms.get("kms_id", "")))
            for key in ("kma_id", "ksa_id", "key_store_id"):
                val = self.kms.get(key)
                if val:
                    ids.add(str(val))
        ids.update(self.domains)
        ids.update(self.subdomains)
        ids.update(self.modules)
        ids.update(self.components)
        ids.update(self.interfaces)
        ids.update(self.post_processing)
        return {i for i in ids if i}


@dataclass
class ResolvedTopology:
    """Immutable resolved bundle loaded from a schema-3.x/4.x config directory."""

    config_dir: str
    schema_version: str
    manifest: dict[str, Any]
    system: dict[str, Any]
    nodes: dict[str, dict[str, Any]]
    devices: dict[str, dict[str, Any]]
    domains: dict[str, dict[str, Any]]
    subdomains: dict[str, dict[str, Any]]
    modules: dict[str, dict[str, Any]]
    components: dict[str, dict[str, Any]]
    interfaces: dict[str, dict[str, Any]]
    connections: list[dict[str, Any]]
    supplemental: dict[str, dict[str, Any]] = field(default_factory=dict)
    configuration_hash: str = ""
    packages: dict[str, NodePackage] = field(default_factory=dict)
    kms: dict[str, dict[str, Any]] = field(default_factory=dict)
    entity_package: dict[str, str] = field(default_factory=dict)

    def package_for_entity(self, entity_id: str) -> str | None:
        return self.entity_package.get(entity_id)

    def owner_device_id(self, owner_id: str | None) -> str | None:
        """Resolve a port owner (component or module id) to its hosting device.

        Owners that resolve to node-level entities (e.g. a KMS key-management
        agent, or the node itself) return ``None``.
        """
        if not owner_id:
            return None
        if owner_id in self.components:
            path = self.structural_path_for_component(owner_id)
            return path.device_id if path else None
        module = self.modules.get(owner_id)
        if module:
            subdomain = self.subdomains.get(str(module.get("parent_subdomain_id") or ""))
            domain = (
                self.domains.get(str(subdomain.get("parent_domain_id") or ""))
                if subdomain
                else None
            )
            if domain:
                device_id = domain.get("parent_device_id") or domain.get("parent_box_id")
                return str(device_id) if device_id else None
        return None

    def structural_path_for_component(self, component_id: str) -> StructuralPath | None:
        comp = self.components.get(component_id)
        if not comp:
            return None
        module_id = comp.get("parent_module_id")
        module = self.modules.get(str(module_id)) if module_id else None
        subdomain_id = (
            module.get("parent_subdomain_id") if module else comp.get("parent_subdomain_id")
        )
        subdomain = self.subdomains.get(str(subdomain_id)) if subdomain_id else None
        domain_id = subdomain.get("parent_domain_id") if subdomain else None
        domain = self.domains.get(str(domain_id)) if domain_id else None
        device_id = domain.get("parent_device_id") if domain else None
        device = self.devices.get(str(device_id)) if device_id else None
        node_id = device.get("parent_node_id") if device else None
        if not node_id and comp.get("parent_kms_id"):
            kms = self.kms.get(str(comp["parent_kms_id"]))
            node_id = kms.get("parent_node_id") if kms else None
        system_id = str((self.system.get("qkd_system") or {}).get("system_id", "qkd_system"))
        package_id = self.entity_package.get(component_id)
        kms_id = str(comp.get("parent_kms_id")) if comp.get("parent_kms_id") else None
        return StructuralPath(
            system_id=system_id,
            package_id=package_id,
            node_id=str(node_id) if node_id else None,
            kms_id=kms_id,
            device_id=str(device_id) if device_id else None,
            domain_id=str(domain_id) if domain_id else None,
            subdomain_id=str(subdomain_id) if subdomain_id else None,
            module_id=str(module_id) if module_id else None,
            component_id=component_id,
        )


__all__ = ["BoundaryContract", "NodePackage", "ResolvedTopology", "StructuralPath"]
