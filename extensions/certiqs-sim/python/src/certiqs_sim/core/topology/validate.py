"""Semantic validation for hierarchical CA-QKD topology (schema 3.0 / 3.1)."""

from __future__ import annotations

from certiqs_sim.core.topology.models import NodePackage, ResolvedTopology

_CORE_DOMAIN_TYPES = frozenset({"quantum_optics", "electronics", "software"})
_KMS_REQUIRED_KEYS = ("kma_id", "ksa_id", "key_store_id")


def _validate_core_topology(resolved: ResolvedTopology) -> list[str]:
    errors: list[str] = []

    if not resolved.system.get("qkd_system"):
        errors.append("Missing qkd_system in system topology")

    for device in resolved.devices.values():
        parent = device.get("parent_node_id")
        device_id = device.get("device_id")
        if parent not in resolved.nodes:
            errors.append(f"Missing parent node '{parent}' for device '{device_id}'")
        domain_ids = device.get("domain_ids") or []
        types = {
            resolved.domains[d]["domain_type"]
            for d in domain_ids
            if d in resolved.domains
        }
        if types != _CORE_DOMAIN_TYPES:
            errors.append(
                f"Device '{device_id}' must have quantum_optics, electronics, "
                f"software domains; got {sorted(types)}"
            )

    for domain in resolved.domains.values():
        parent_device = domain.get("parent_device_id")
        if parent_device not in resolved.devices:
            errors.append(f"Missing parent device for domain '{domain.get('domain_id')}'")

    for subdomain in resolved.subdomains.values():
        if subdomain.get("parent_domain_id") not in resolved.domains:
            errors.append(f"Missing parent domain for subdomain '{subdomain.get('subdomain_id')}'")

    for module in resolved.modules.values():
        if module.get("parent_subdomain_id") not in resolved.subdomains:
            errors.append(f"Missing parent subdomain for module '{module.get('module_id')}'")
        if module.get("module_type") == "polarization_analyzer_module":
            states = module.get("states_by_basis") or {}
            for basis, letters in states.items():
                if not letters or len(letters) < 2:
                    errors.append(
                        f"PAM '{module.get('module_id')}' basis '{basis}' needs >=2 output states"
                    )

    for component in resolved.components.values():
        parent = component.get("parent_module_id")
        parent_sub = component.get("parent_subdomain_id")
        parent_kms = component.get("parent_kms_id")
        if parent and parent not in resolved.modules:
            if not (parent_kms and parent_kms in resolved.kms):
                errors.append(f"Missing parent module for component '{component.get('component_id')}'")
        if parent_sub and parent_sub not in resolved.subdomains:
            errors.append(
                f"Missing parent subdomain for component '{component.get('component_id')}'"
            )
        if not parent and not parent_sub and not parent_kms:
            errors.append(
                f"Component '{component.get('component_id')}' has no parent module, subdomain, or KMS"
            )

    iface_ids = set(resolved.interfaces)
    for conn in resolved.connections:
        for key in ("from_interface_id", "to_interface_id"):
            iface = conn.get(key)
            if iface and iface not in iface_ids:
                errors.append(
                    f"Connection '{conn.get('connection_id')}' references unknown interface '{iface}'"
                )

    for side in ("alice", "bob"):
        pam_id = f"module_{side}_pam"
        if pam_id not in resolved.modules:
            errors.append(f"Missing PAM module '{pam_id}'")
            continue
        det_mod = f"module_{side}_detection"
        if det_mod not in resolved.modules:
            errors.append(f"Missing detection module '{det_mod}'")

    return errors


def validate_node_package(package: NodePackage) -> list[str]:
    """Validate a standalone node package (internal refs + boundary contract)."""
    errors: list[str] = []
    local_ids = package.local_ids()

    if not package.node_id:
        errors.append(f"Package '{package.package_id}' missing node_id")

    for device in package.all_devices():
        domain_ids = device.get("domain_ids") or []
        types = {package.domains[d]["domain_type"] for d in domain_ids if d in package.domains}
        if types != _CORE_DOMAIN_TYPES:
            errors.append(
                f"Package '{package.package_id}' device '{device.get('device_id')}' must have "
                f"three core domains; got {sorted(types)}"
            )

    for domain in package.domains.values():
        parent_device = domain.get("parent_device_id")
        if parent_device not in local_ids:
            errors.append(
                f"Package '{package.package_id}' domain '{domain.get('domain_id')}' "
                f"references external device '{parent_device}'"
            )

    for subdomain in package.subdomains.values():
        parent = subdomain.get("parent_domain_id")
        if parent not in local_ids and parent not in package.boundary.requires:
            errors.append(
                f"Package '{package.package_id}' subdomain '{subdomain.get('subdomain_id')}' "
                f"references undeclared external '{parent}'"
            )

    for module in package.modules.values():
        parent = module.get("parent_subdomain_id")
        if parent not in local_ids and parent not in package.boundary.requires:
            errors.append(
                f"Package '{package.package_id}' module '{module.get('module_id')}' "
                f"references undeclared external '{parent}'"
            )

    for component in package.components.values():
        parent = component.get("parent_module_id")
        parent_sub = component.get("parent_subdomain_id")
        parent_kms = component.get("parent_kms_id")
        if parent and parent not in local_ids:
            errors.append(
                f"Package '{package.package_id}' component '{component.get('component_id')}' "
                f"references undeclared external module '{parent}'"
            )
        if parent_sub and parent_sub not in local_ids:
            errors.append(
                f"Package '{package.package_id}' component '{component.get('component_id')}' "
                f"references undeclared external subdomain '{parent_sub}'"
            )
        if parent_kms and parent_kms not in local_ids:
            errors.append(
                f"Package '{package.package_id}' component '{component.get('component_id')}' "
                f"references undeclared external kms '{parent_kms}'"
            )

    iface_ids = set(package.interfaces)
    for port in package.boundary.provides:
        if port not in iface_ids:
            errors.append(
                f"Package '{package.package_id}' provides undeclared boundary port '{port}'"
            )

    for conn in package.connections:
        for key in ("from_interface_id", "to_interface_id"):
            iface = conn.get(key)
            if iface and iface not in iface_ids:
                if iface not in package.boundary.requires:
                    errors.append(
                        f"Package '{package.package_id}' connection references "
                        f"undeclared external interface '{iface}'"
                    )

    # Module external_connections target modules must exist in package
    for module_id, module in package.modules.items():
        module_ports = module.get("ports") or {}
        for conn in module.get("external_connections") or []:
            if not isinstance(conn, dict):
                continue
            to_module = str(conn.get("to_module", ""))
            if to_module and to_module not in package.modules:
                errors.append(
                    f"Module '{module_id}' external connection targets unknown module '{to_module}'"
                )
            to_port = str(conn.get("to_port", ""))
            if to_module and to_port:
                target_ports = (package.modules.get(to_module) or {}).get("ports") or {}
                if to_port not in target_ports:
                    errors.append(
                        f"Module '{module_id}' external connection references unknown "
                        f"port '{to_port}' on module '{to_module}'"
                    )
            from_port = str(conn.get("from_port", ""))
            if from_port and isinstance(module_ports, dict) and from_port not in module_ports:
                errors.append(
                    f"Module '{module_id}' external connection references unknown from_port '{from_port}'"
                )

    # boundary_ports keys must align with provides / requires contract
    node_doc = package.node or {}
    boundary_ports = node_doc.get("boundary_ports") or {}
    if isinstance(boundary_ports, dict):
        for port_id in boundary_ports:
            if port_id not in package.boundary.provides and port_id not in package.boundary.requires:
                errors.append(
                    f"Package '{package.package_id}' boundary_ports entry '{port_id}' "
                    f"not listed in provides or requires"
                )
        for port in package.boundary.provides:
            if port not in boundary_ports and port not in iface_ids:
                pass  # may be declared via legacy flat interface only during migration

    # Component-scoped connections must stay within the same parent module
    iface_owner = {
        str(iface.get("interface_id", iid)): str(iface.get("owner_id", ""))
        for iid, iface in package.interfaces.items()
    }
    comp_module = {
        str(cid): str(comp.get("parent_module_id") or "")
        for cid, comp in package.components.items()
    }
    for conn in package.connections:
        if conn.get("_scope") != "component":
            continue
        from_owner = iface_owner.get(str(conn.get("from_interface_id", "")), "")
        to_owner = iface_owner.get(str(conn.get("to_interface_id", "")), "")
        if from_owner in comp_module and to_owner in comp_module:
            from_mod = comp_module[from_owner]
            to_mod = comp_module[to_owner]
            if from_mod and to_mod and from_mod != to_mod:
                errors.append(
                    f"Component connection '{conn.get('connection_id')}' crosses modules "
                    f"('{comp_module[from_owner]}' → '{comp_module[to_owner]}'); "
                    f"use module external_connections instead"
                )

    return errors


def _validate_kms_presence(resolved: ResolvedTopology) -> list[str]:
    errors: list[str] = []
    for node_id, node in resolved.nodes.items():
        if node.get("node_role") != "measurement_node":
            continue
        kms_for_node = [
            kms for kms in resolved.kms.values() if kms.get("parent_node_id") == node_id
        ]
        if not kms_for_node:
            errors.append(f"Measurement node '{node_id}' missing KMS package")
            continue
        kms = kms_for_node[0]
        for key in _KMS_REQUIRED_KEYS:
            if not kms.get(key):
                errors.append(f"KMS for node '{node_id}' missing '{key}'")
        for key in _KMS_REQUIRED_KEYS:
            comp_id = kms.get(key)
            if comp_id and comp_id not in resolved.components:
                errors.append(f"KMS component '{comp_id}' for node '{node_id}' not declared")
    return errors


def _validate_network_contracts(resolved: ResolvedTopology) -> list[str]:
    errors: list[str] = []
    if not resolved.packages:
        return errors

    all_provides: set[str] = set()
    all_requires: set[str] = set()
    for package in resolved.packages.values():
        all_provides.update(package.boundary.provides)
        all_requires.update(package.boundary.requires)

    system_channels = set((resolved.system.get("qkd_system") or {}).get("channel_ids") or [])
    channels_doc = resolved.supplemental.get("network/channels.yaml") or resolved.supplemental.get(
        "09_channels.yaml"
    ) or {}
    channel_ids = set((channels_doc.get("channels") or {}).keys())

    for req in all_requires:
        if req in all_provides:
            continue
        if req in system_channels or req in channel_ids:
            continue
        if req.startswith("protocol:") or req.startswith("shared:"):
            continue
        errors.append(f"Unresolved package requirement '{req}'")

    return errors


_MEASUREMENT_SOFTWARE_SUBDOMAINS = frozenset({
    "time_tag_ingestion",
    "timing_alignment",
    "delay_calibration",
    "coincidence_correlation",
    "event_validation",
    "coincidence_monitoring",
    "basis_reconciliation",
    "parameter_estimation",
    "information_reconciliation",
    "key_verification",
    "privacy_amplification",
    "final_key_management",
    "cross_cutting",
})


def _validate_software_domain(resolved: ResolvedTopology) -> list[str]:
    errors: list[str] = []
    if not resolved.packages:
        return errors

    authoritative_matchers = 0
    for comp in resolved.components.values():
        ctype = str(comp.get("component_type", ""))
        cclass = str(comp.get("component_class", ""))
        if "coincidence_matcher" not in (ctype, cclass):
            continue
        subdomain_id = comp.get("parent_subdomain_id")
        if not subdomain_id or subdomain_id not in resolved.subdomains:
            errors.append(
                f"Coordination component '{comp.get('component_id')}' missing software-domain subdomain parent"
            )
            continue
        subdomain = resolved.subdomains.get(str(subdomain_id), {})
        if subdomain.get("subdomain_type") != "coincidence_correlation":
            errors.append(
                f"Coordination component '{comp.get('component_id')}' must live under coincidence_correlation subdomain"
            )
        binding = comp.get("execution_binding") or {}
        if binding.get("role") == "authoritative_matcher":
            authoritative_matchers += 1

    if authoritative_matchers != 1:
        errors.append(
            f"Expected exactly one authoritative coincidence matcher; found {authoritative_matchers}"
        )

    for node_id, node in resolved.nodes.items():
        if node.get("node_role") != "measurement_node":
            continue
        side = "alice" if "alice" in node_id else "bob" if "bob" in node_id else ""
        if not side:
            continue
        software_domain_id = f"domain_{side}_software"
        domain = resolved.domains.get(software_domain_id)
        if not domain:
            errors.append(f"Measurement node '{node_id}' missing software domain")
            continue
        present = {
            resolved.subdomains[sid]["subdomain_type"]
            for sid in (domain.get("subdomain_ids") or [])
            if sid in resolved.subdomains
        }
        missing = _MEASUREMENT_SOFTWARE_SUBDOMAINS - present
        if missing:
            errors.append(
                f"Software domain for '{node_id}' missing subdomains: {sorted(missing)}"
            )

    return errors


def validate_topology(resolved: ResolvedTopology) -> list[str]:
    """Return a list of validation errors (empty when valid)."""
    errors = _validate_core_topology(resolved)
    errors.extend(_validate_kms_presence(resolved))
    errors.extend(_validate_network_contracts(resolved))
    errors.extend(_validate_software_domain(resolved))
    return errors


def assert_valid(resolved: ResolvedTopology) -> None:
    errors = validate_topology(resolved)
    if errors:
        raise ValueError("Topology validation failed:\n" + "\n".join(errors))


__all__ = ["assert_valid", "validate_node_package", "validate_topology"]
