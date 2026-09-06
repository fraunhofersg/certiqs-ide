"""Adapter: hierarchical topology → flat subsystem documents + UI simulation graph."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from certiqs_sim.core.topology.models import ResolvedTopology
from certiqs_sim.core.topology.virtual_model import (
    VirtualNode,
    VirtualTopologyModel,
    build_virtual_topology,
    enrich_hierarchy_node_group,
)

# Hierarchical component_id → flat subsystem component key
_FLAT_COMPONENT_IDS: dict[str, str] = {
    "spdc_crystal": "spdc_entangled_pair_source",
    "alice_basis_bs": "alice_basis_splitter",
    "alice_pbs_z": "alice_z_analyzer",
    "alice_pbs_x": "alice_x_analyzer",
    "alice_hwp_x": "alice_x_hwp",
    "bob_basis_bs": "bob_basis_splitter",
    "bob_pbs_z": "bob_z_analyzer",
    "bob_pbs_x": "bob_x_analyzer",
    "bob_hwp_x": "bob_x_hwp",
    "alice_coincidence_matcher": "coincidence_matcher",
    "alice_clock_synchronizer": "clock_synchronizer",
    "alice_sifting_processor": "sifting",
    "alice_parameter_estimator": "qber_estimation",
}

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

# component_type (hierarchical) → component_class (flat/registry)
_COMPONENT_CLASS: dict[str, str] = {
    "pulsed_laser": "pulsed_laser",
    "spdc_entangled_pair_source": "entangled_pair_source_spdc",
    "polarization_controller": "polarization_controller",
    "beam_splitter": "nonpolarizing_beamsplitter",
    "nonpolarizing_beamsplitter": "nonpolarizing_beamsplitter",
    "half_wave_plate": "half_wave_plate",
    "polarizing_beam_splitter": "polarizing_beamsplitter",
    "polarizing_beamsplitter": "polarizing_beamsplitter",
    "single_photon_detector": "single_photon_detector",
    "time_to_digital_converter": "time_to_digital_converter",
    "time_sync_unit": "time_sync_unit",
    "coincidence_matcher": "coincidence_matcher",
    "basis_sifting": "basis_sifting",
    "qber_estimator": "qber_estimator",
}

_STATION_SIDES = {
    "node_alice": ("alice_station", "alice", "03_alice_station.yaml"),
    "node_bob": ("bob_station", "bob", "04_bob_station.yaml"),
}

_CHANNEL_TO_FLAT = {
    "qch_source_alice": "quantum_to_alice",
    "qch_source_bob": "quantum_to_bob",
    "cch_alice_bob": "authenticated_classical_link",
    "sync_source_alice": "time_sync_link",
    "sync_source_bob": "time_sync_link",
}

_FLAT_TO_CHANNEL = {v: k for k, v in _CHANNEL_TO_FLAT.items() if k != "sync_source_bob"}


def _supplemental_doc(resolved: ResolvedTopology, *candidates: str) -> dict[str, Any]:
    for key in candidates:
        doc = resolved.supplemental.get(key)
        if doc:
            return doc
    return {}


def _timing_doc(resolved: ResolvedTopology) -> dict[str, Any]:
    net_control = _supplemental_doc(resolved, "network/control.yaml")
    if net_control.get("timing"):
        return dict(net_control["timing"])
    return _supplemental_doc(resolved, "10_timing_and_digital.yaml")


def _post_processing_for_side(resolved: ResolvedTopology, side: str) -> dict[str, Any]:
    pkg_key = f"post_processing_pkg_{side}.yaml"
    doc = _supplemental_doc(resolved, pkg_key)
    if doc.get("post_processing"):
        return dict(doc["post_processing"])
    legacy = _supplemental_doc(resolved, "11_post_processing.yaml")
    full = dict(legacy.get("post_processing") or {})
    if side == "alice":
        return {k: full[k] for k in ("sifting", "qber_estimation") if k in full}
    return {
        k: full[k]
        for k in ("reconciliation", "privacy_amplification", "finite_key_engine")
        if k in full
    }


def _kms_for_node(resolved: ResolvedTopology, node_id: str) -> dict[str, Any] | None:
    for kms in resolved.kms.values():
        if kms.get("parent_node_id") == node_id:
            return kms
    return None


def _aggregate_channels_and_bindings(
    resolved: ResolvedTopology,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge network-level (cross-node) links with per-node intra-node links.

    Intra-node channel physics + wiring are authored self-contained in each
    ``node.yaml`` (``channels`` / ``connections``). Cross-node links stay in the
    network channel file. This aggregation is config-driven: it reads whatever
    the config declares and never assumes specific node/channel identities.
    """
    channels_doc = _supplemental_doc(resolved, "network/channels.yaml", "09_channels.yaml")
    channels: dict[str, Any] = dict(channels_doc.get("channels") or {})
    bindings: list[dict[str, Any]] = [
        dict(b) for b in (channels_doc.get("bindings") or []) if isinstance(b, dict)
    ]
    explicit_connections: list[dict[str, Any]] = [
        dict(c) for c in (channels_doc.get("connections") or []) if isinstance(c, dict)
    ]

    for package in resolved.packages.values():
        for channel_id, spec in (package.intra_channels or {}).items():
            channels.setdefault(str(channel_id), deepcopy(spec))
        for conn in package.intra_connections or []:
            binding = dict(conn)
            binding.setdefault("from_package", package.package_id)
            binding.setdefault("to_package", package.package_id)
            bindings.append(binding)

    return channels, bindings, explicit_connections


def _frame_link_edge_kind(channel: dict[str, Any]) -> str:
    """Classify a channel into a UI edge kind (quantum / digital / link)."""
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


def _port_owner_frame(
    resolved: ResolvedTopology,
    package_id: str,
    port_id: str,
    node_by_package: dict[str, str],
) -> str | None:
    """Resolve a binding endpoint (package + boundary port) to its owning frame.

    A boundary port owned by a component/module hosted in a device renders on the
    device frame; otherwise (node-level owner such as the KMS) it renders on the
    node frame. Purely config-driven via interface ``owner_id`` + hierarchy.
    """
    package = resolved.packages.get(package_id)
    if not package:
        return None
    iface = package.interfaces.get(port_id)
    if not iface:
        return None
    device_id = resolved.owner_device_id(iface.get("owner_id"))
    if device_id:
        return device_id
    return node_by_package.get(package_id)


def build_frame_boundary_links(resolved: ResolvedTopology) -> list[dict[str, Any]]:
    """Authoritative frame-to-frame boundary links for the UI.

    Every declared channel binding whose two endpoints live on different frames
    (device↔device, device↔node, node↔node — intra- or cross-node) becomes one
    link. This is the single source of truth for connections drawn between
    hierarchy frames, replacing the frontend's port-matching heuristics. It is
    fully config-driven: endpoints are resolved from the actual bindings and
    interface ownership, never from node/port identity guesses.
    """
    channels, bindings, _ = _aggregate_channels_and_bindings(resolved)
    node_by_package = {
        pkg: node_id
        for node_id, pkg in resolved.entity_package.items()
        if node_id in resolved.nodes
    }

    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for binding in bindings:
        from_port = str(binding.get("from_port") or "")
        to_port = str(binding.get("to_port") or "")
        if not from_port or not to_port:
            continue
        source_frame = _port_owner_frame(
            resolved, str(binding.get("from_package") or ""), from_port, node_by_package
        )
        target_frame = _port_owner_frame(
            resolved, str(binding.get("to_package") or ""), to_port, node_by_package
        )
        if not source_frame or not target_frame or source_frame == target_frame:
            continue
        key = (source_frame, from_port, target_frame, to_port)
        if key in seen:
            continue
        seen.add(key)
        channel_id = str(binding.get("channel_id") or "")
        edge_kind = _frame_link_edge_kind(channels.get(channel_id) or {})
        links.append(
            {
                "id": f"frame_link|{source_frame}~{target_frame}~{channel_id or from_port}",
                "source_frame": source_frame,
                "target_frame": target_frame,
                "source_port": from_port,
                "target_port": to_port,
                "edge_kind": edge_kind,
                "channel_id": channel_id or None,
                "via": channel_id or None,
                "source_file": binding.get("source_file"),
            }
        )
    return links


def _flat_channels_doc(resolved: ResolvedTopology) -> dict[str, Any]:
    channels, bindings, explicit_connections = _aggregate_channels_and_bindings(resolved)

    flat_channels: dict[str, Any] = {}
    for channel_id, spec in channels.items():
        flat_id = _CHANNEL_TO_FLAT.get(channel_id, channel_id)
        if flat_id in flat_channels and flat_id == "time_sync_link":
            continue
        flat_channels[flat_id] = deepcopy(spec)

    flat_connections: list[dict[str, Any]] = []
    for conn in explicit_connections:
        via = str(conn.get("via", ""))
        flat_conn = dict(conn)
        flat_conn["via"] = _CHANNEL_TO_FLAT.get(via, via)
        flat_connections.append(flat_conn)

    if not flat_connections and bindings:
        for binding in bindings:
            channel_id = str(binding.get("channel_id", ""))
            flat_connections.append(
                {
                    "from": f"central_entanglement_source.{binding.get('from_port', 'out')}",
                    "via": _CHANNEL_TO_FLAT.get(channel_id, channel_id),
                    "to": f"{binding.get('to_package', '').replace('pkg_', '')}_station.quantum_in",
                }
            )

    return {
        "schema_version": "2.0",
        "channels": flat_channels,
        "connections": flat_connections,
    }


def _flat_id(component_id: str) -> str:
    return _FLAT_COMPONENT_IDS.get(component_id, component_id)


_PAM_CHANNEL_FLAT: dict[str, tuple[str, str]] = {
    "h": ("z_analyzer", "port_0"),
    "v": ("z_analyzer", "port_1"),
    "d": ("x_analyzer", "port_0"),
    "a": ("x_analyzer", "port_1"),
}


def _package_hier_connections(resolved: ResolvedTopology, package_id: str) -> list[dict[str, Any]]:
    pkg = resolved.packages.get(package_id)
    if not pkg:
        return []
    iface_ids = set(pkg.interfaces)
    return [
        c
        for c in resolved.connections
        if c.get("from_interface_id") in iface_ids and c.get("to_interface_id") in iface_ids
    ]


def _channel_letter_from_iface(iface_id: str) -> str | None:
    for ch in ("h", "v", "d", "a"):
        if f"_{ch}_" in iface_id or iface_id.endswith(f"_{ch}"):
            return ch
    return None


def _default_pam_to_detector_connections(prefix: str) -> list[dict[str, Any]]:
    return [
        {"from": f"{prefix}_z_analyzer.port_0", "to": f"{prefix}_detectors.{prefix}_detector_h.in"},
        {"from": f"{prefix}_z_analyzer.port_1", "to": f"{prefix}_detectors.{prefix}_detector_v.in"},
        {"from": f"{prefix}_x_analyzer.port_0", "to": f"{prefix}_detectors.{prefix}_detector_d.in"},
        {"from": f"{prefix}_x_analyzer.port_1", "to": f"{prefix}_detectors.{prefix}_detector_a.in"},
    ]


def _default_detector_to_tdc_connections(prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "from": f"{prefix}_detectors.{prefix}_detector_{letter}.out",
            "to": f"{prefix}_tdc.clicks_in",
        }
        for letter in ("h", "v", "d", "a")
    ]


def _build_station_connections(
    resolved: ResolvedTopology,
    *,
    side: str,
    subsystem_id: str,
    prefix: str,
    has_detectors: bool,
) -> list[dict[str, Any]]:
    """Map hierarchical package connections to flat station wiring when present."""
    connections: list[dict[str, Any]] = [
        {"from": f"{subsystem_id}.quantum_in", "to": f"{prefix}_polarization_controller.in"},
        {"from": f"{prefix}_polarization_controller.out", "to": f"{prefix}_basis_splitter.in"},
        {"from": f"{prefix}_basis_splitter.transmitted", "to": f"{prefix}_z_analyzer.in"},
        {"from": f"{prefix}_basis_splitter.reflected", "to": f"{prefix}_x_hwp.in"},
        {"from": f"{prefix}_x_hwp.out", "to": f"{prefix}_x_analyzer.in"},
    ]
    if not has_detectors:
        return connections

    hier = _package_hier_connections(resolved, f"pkg_{side}")
    pam_to_det = [
        c
        for c in hier
        if "pam" in str(c.get("from_interface_id", ""))
        and "det" in str(c.get("to_interface_id", ""))
    ]
    det_to_tdc = [
        c
        for c in hier
        if "detector" in str(c.get("from_interface_id", ""))
        and "tdc" in str(c.get("to_interface_id", ""))
    ]

    if pam_to_det:
        for conn in pam_to_det:
            ch = _channel_letter_from_iface(str(conn.get("from_interface_id", "")))
            if not ch:
                continue
            flat_dev, flat_port = _PAM_CHANNEL_FLAT[ch]
            connections.append(
                {
                    "from": f"{prefix}_{flat_dev}.{flat_port}",
                    "to": f"{prefix}_detectors.{prefix}_detector_{ch}.in",
                }
            )
    else:
        connections.extend(_default_pam_to_detector_connections(prefix))

    if det_to_tdc:
        seen: set[str] = set()
        for conn in det_to_tdc:
            ch = _channel_letter_from_iface(str(conn.get("from_interface_id", "")))
            if not ch or ch in seen:
                continue
            seen.add(ch)
            connections.append(
                {
                    "from": f"{prefix}_detectors.{prefix}_detector_{ch}.out",
                    "to": f"{prefix}_tdc.clicks_in",
                }
            )
    else:
        connections.extend(_default_detector_to_tdc_connections(prefix))

    connections.append(
        {"from": f"{prefix}_tdc.timestamps_out", "to": f"{subsystem_id}.timestamps_out"}
    )
    return connections


def collect_graph_component_ids(flat_docs: dict[str, dict[str, Any]]) -> set[str]:
    """Component / channel / post-processing ids present in the flat simulation graph."""
    ids: set[str] = set()
    for doc in flat_docs.values():
        for comp_id, comp in (doc.get("components") or {}).items():
            ids.add(str(comp_id))
            if isinstance(comp, dict) and comp.get("component_class") == "detector_array":
                for ch_id in (comp.get("channels") or {}):
                    ids.add(str(ch_id))
        for pp_id in (doc.get("post_processing") or {}):
            ids.add(str(pp_id))
    return ids


def _is_peer_stub(comp: dict[str, Any]) -> bool:
    return str((comp.get("execution_binding") or {}).get("role", "")) == "peer_stub"


def _authoritative_component(
    resolved: ResolvedTopology,
    *,
    component_class: str,
) -> tuple[str | None, dict[str, Any] | None]:
    for comp_id, comp in resolved.components.items():
        if _is_peer_stub(comp):
            continue
        ctype = str(comp.get("component_type", ""))
        cclass = str(comp.get("component_class", ""))
        if component_class not in (ctype, cclass):
            continue
        return comp_id, comp
    return None, None


def _hierarchy_member_ids(
    resolved: ResolvedTopology,
    comp_ids: list[str],
    graph_ids: set[str],
) -> list[str]:
    """Hierarchy members: flat graph ids where mapped, else declared component ids."""
    members: list[str] = []
    for comp_id in comp_ids:
        comp = resolved.components.get(comp_id, {})
        if _is_peer_stub(comp):
            if comp_id not in members:
                members.append(comp_id)
            continue
        for candidate in (_flat_id(comp_id), comp_id):
            if candidate in graph_ids and candidate not in members:
                members.append(candidate)
                break
        else:
            if comp_id not in members:
                members.append(comp_id)
    return members


def _graph_member_ids(comp_ids: list[str], graph_ids: set[str]) -> list[str]:
    """Map hierarchical component ids to ids used in ``build_topology`` nodes/edges."""
    members: list[str] = []
    for comp_id in comp_ids:
        for candidate in (_flat_id(comp_id), comp_id):
            if candidate in graph_ids and candidate not in members:
                members.append(candidate)
                break
    return members


def _hier_to_flat_settings(comp: dict[str, Any]) -> dict[str, Any]:
    """Convert hierarchical component record to flat inline component dict."""
    params = dict(comp.get("parameters") or {})
    component_type = str(comp.get("component_type", ""))
    component_class = _COMPONENT_CLASS.get(component_type, component_type)
    flat: dict[str, Any] = {"component_class": component_class}
    if comp.get("model_binding_id"):
        flat["model_binding_id"] = comp["model_binding_id"]

    # SPDC source
    if component_class == "entangled_pair_source_spdc":
        flat["pair_statistics"] = {
            "model": params.get("pair_statistics", "multimode_thermal"),
            "mean_pairs_per_pulse": params.get("mean_pairs_per_pulse", 0.015),
            "effective_schmidt_modes": params.get("schmidt_modes", 20),
        }
        flat["quantum_state"] = {
            "target_state": params.get("target_bell_state", "phi_plus"),
            "model": "werner_state",
            "fidelity": params.get("state_fidelity", 0.985),
        }
        flat["spectrum"] = {
            "signal_center_nm": params.get("output_wavelength_nm", 1550.0),
            "idler_center_nm": params.get("output_wavelength_nm", 1550.0),
        }
        return flat

    if component_class == "pulsed_laser":
        flat["repetition_rate_hz"] = params.get("repetition_rate_hz", 100e6)
        flat["center_wavelength_nm"] = params.get("wavelength_nm", 775.0)
        flat["pulse_width_ps_fwhm"] = params.get("pulse_width_ps", 3.0)
        flat["timing_jitter_ps_rms"] = params.get("timing_jitter_ps_rms", 1.5)
        return flat

    if component_class == "polarization_controller":
        flat["insertion_loss_db"] = params.get("insertion_loss_db", 0.25)
        return flat

    if component_class == "nonpolarizing_beamsplitter":
        ratio = params.get("split_ratio", params.get("splitting_ratio", 0.5))
        if isinstance(ratio, dict):
            flat["splitting_ratio"] = ratio
        else:
            flat["splitting_ratio"] = {"transmission": ratio, "reflection": 1.0 - float(ratio)}
        flat["insertion_loss_db"] = params.get("insertion_loss_db", 0.15)
        return flat

    if component_class == "half_wave_plate":
        flat["angle_deg"] = params.get("fast_axis_deg", params.get("angle_deg", 22.5))
        flat["insertion_loss_db"] = params.get("insertion_loss_db", 0.05)
        return flat

    if component_class == "polarizing_beamsplitter":
        basis = params.get("basis")
        if basis:
            flat["basis"] = basis
        flat["extinction_ratio_db"] = params.get("extinction_ratio_db", 28)
        flat["insertion_loss_db"] = params.get("insertion_loss_db", 0.20)
        if flat.get("model_binding_id", "").startswith("models."):
            flat["model_binding_id"] = "optics.pbs.v1"
        return flat

    if component_class == "single_photon_detector":
        flat["efficiency"] = params.get("efficiency", 0.8)
        flat["dark_count_hz"] = params.get("dark_count_hz", 250)
        flat["dead_time_ns"] = params.get("dead_time_ns", 20)
        jitter = params.get("jitter_ps_rms", params.get("timing_response", {}).get("sigma_ps", 55))
        flat["timing_response"] = {"model": "gaussian", "sigma_ps": jitter}
        ap = params.get("afterpulse_probability", 0.006)
        flat["afterpulsing"] = {
            "model": "single_exponential",
            "probability": ap,
            "decay_ns": params.get("decay_ns", 500),
        }
        flat["saturation_count_rate_hz"] = params.get("saturation_count_rate_hz", 15_000_000)
        return flat

    if component_class == "time_to_digital_converter":
        flat["clock_domain"] = params.get("clock_domain", "alice_tdc_clk")
        flat["channels"] = params.get("channel_count", params.get("channels", 4))
        flat["resolution_ps"] = params.get("resolution_ps", 10)
        flat["channel_skew_ps"] = params.get("channel_skew_ps", [0, 12, -8, 5])
        flat["dnl_lsb_rms"] = params.get("dnl_lsb_rms", 0.15)
        flat["inl_lsb_peak"] = params.get("inl_lsb_peak", 0.8)
        flat["input_dead_time_ns"] = params.get("input_dead_time_ns", 2)
        flat["fifo_depth"] = params.get("fifo_depth", 4096)
        return flat

    if component_class in {"time_sync_unit", "coincidence_matcher"}:
        flat.update(params)
        return flat

    flat.update(params)
    return flat


def _pam_basis_annotations(module: dict[str, Any]) -> dict[str, str]:
    """Map flat analyzer keys to Z/X basis from PAM module metadata."""
    mapping: dict[str, str] = {}
    states = module.get("states_by_basis") or {}
    for basis, letters in states.items():
        for letter in letters:
            mapping[str(letter).upper()] = str(basis)
    return mapping


def _build_source_doc(resolved: ResolvedTopology) -> dict[str, Any]:
    components: dict[str, Any] = {}
    for comp_id in ("pump_laser", "spdc_crystal"):
        comp = resolved.components.get(comp_id)
        if comp:
            components[_flat_id(comp_id)] = _hier_to_flat_settings(comp)

    return {
        "schema_version": "2.0",
        "subsystem": {
            "id": "central_entanglement_source",
            "deployment_role": "quantum_source",
            "endpoint_side": "source",
            "topology_scope": "point_to_point",
            "component_class": "entangled_pair_source_subsystem",
            "ports": {
                "optical_outputs": {
                    "alice_out": {"signal_type": "quantum_optical_stream", "wavelength_nm": 1550.0},
                    "bob_out": {"signal_type": "quantum_optical_stream", "wavelength_nm": 1550.0},
                }
            },
        },
        "components": components,
        "connections": [
            {"from": "pump_laser.out", "to": "spdc_entangled_pair_source.pump_in"},
            {"from": "spdc_entangled_pair_source.signal_out", "to": "central_entanglement_source.alice_out"},
            {"from": "spdc_entangled_pair_source.idler_out", "to": "central_entanglement_source.bob_out"},
        ],
    }


def _build_station_doc(
    resolved: ResolvedTopology,
    *,
    node_id: str,
    subsystem_id: str,
    vnode: VirtualNode,
) -> dict[str, Any]:
    side = str(vnode.endpoint_side or "")
    prefix = side
    pam = resolved.modules.get(f"module_{side}_pam") or {}
    pam_basis = _pam_basis_annotations(pam)

    components: dict[str, Any] = {}
    optical_ids = [
        f"{prefix}_polarization_controller",
        f"{prefix}_basis_bs",
        f"{prefix}_pbs_z",
        f"{prefix}_hwp_x",
        f"{prefix}_pbs_x",
    ]
    # Also accept flat-style ids in hierarchical yaml
    alt_map = {
        f"{prefix}_basis_bs": f"{prefix}_basis_splitter",
        f"{prefix}_pbs_z": f"{prefix}_z_analyzer",
        f"{prefix}_pbs_x": f"{prefix}_x_analyzer",
        f"{prefix}_hwp_x": f"{prefix}_x_hwp",
    }

    for hier_id in optical_ids:
        comp = resolved.components.get(hier_id)
        if not comp:
            # try without remap
            flat_key = alt_map.get(hier_id, _flat_id(hier_id))
            comp = resolved.components.get(flat_key.replace("_splitter", "_bs").replace("_analyzer", "_pbs_z"))
        if comp:
            flat_key = alt_map.get(hier_id, _flat_id(hier_id))
            settings = _hier_to_flat_settings(comp)
            if "pbs_z" in hier_id or flat_key.endswith("_z_analyzer"):
                settings.setdefault("basis", "Z")
            if "pbs_x" in hier_id or flat_key.endswith("_x_analyzer"):
                settings.setdefault("basis", "X")
            components[flat_key] = settings

    # Polarization controller — synthesize if absent from hierarchical components
    pol_key = f"{prefix}_polarization_controller"
    if pol_key not in components:
        components[pol_key] = {
            "component_class": "polarization_controller",
            "model_binding_id": "optics.polarization_controller.v1",
            "insertion_loss_db": 0.25,
            "pdl_db": 0.03,
            "control_range_deg": 360,
        }

    # Detectors → detector_array
    detector_channels: dict[str, Any] = {}
    for letter in ("h", "v", "d", "a"):
        det_id = f"{prefix}_detector_{letter}"
        comp = resolved.components.get(det_id)
        if comp:
            detector_channels[det_id] = _hier_to_flat_settings(comp)

    if detector_channels:
        components[f"{prefix}_detectors"] = {
            "component_class": "detector_array",
            "channels": detector_channels,
        }

    clock_key = f"{prefix}_tdc_clk"
    clock_domains = {
        clock_key: {
            "nominal_frequency_hz": 250_000_000,
            "frequency_offset_ppm": 0.10 if side == "alice" else -0.12,
            "phase_noise_ps_rms": 8 if side == "alice" else 9,
        }
    }

    tdc = resolved.components.get(f"{prefix}_tdc")
    if tdc:
        tdc_settings = _hier_to_flat_settings(tdc)
        tdc_settings["clock_domain"] = clock_key
        tdc_settings.setdefault("model_binding_id", "timing.tdc.multichannel.v2")
        components[f"{prefix}_tdc"] = tdc_settings

    connections = _build_station_connections(
        resolved,
        side=side,
        subsystem_id=subsystem_id,
        prefix=prefix,
        has_detectors=bool(detector_channels),
    )

    return {
        "schema_version": "2.0",
        "subsystem": {
            "id": subsystem_id,
            "deployment_role": "qkd_device",
            "endpoint_side": side,
            "topology_scope": "point_to_point",
            "component_class": "bbm92_receiver_station",
            "ports": {
                "optical_inputs": {
                    "quantum_in": {"signal_type": "quantum_optical_stream", "wavelength_nm": 1550.0}
                },
                "digital_outputs": {
                    "timestamps_out": {"packet_type": "timestamp_event"}
                },
            },
        },
        "clock_domains": clock_domains,
        "components": components,
        "connections": connections,
        "_pam_basis": pam_basis,
    }


def _build_network_coordination_doc(
    resolved: ResolvedTopology,
    vtm: VirtualTopologyModel,
) -> dict[str, Any]:
    components: dict[str, Any] = {}
    for flat_key, component_class in (
        ("clock_synchronizer", "time_sync_unit"),
        ("coincidence_matcher", "coincidence_matcher"),
    ):
        comp_id, comp = _authoritative_component(resolved, component_class=component_class)
        if comp:
            components[flat_key] = _hier_to_flat_settings(comp)

    timing_doc = _timing_doc(resolved)
    raw_clocks = timing_doc.get("clock_domains") or []
    if isinstance(raw_clocks, list):
        clock_domains = {
            str(c.get("clock_domain_id", "processing_clk")): {
                "nominal_frequency_hz": c.get("frequency_hz", 200_000_000),
                "frequency_offset_ppm": c.get("offset_ppm", 0.02),
            }
            for c in raw_clocks
            if isinstance(c, dict)
        }
    else:
        clock_domains = raw_clocks or {
            "processing_clk": {"nominal_frequency_hz": 200_000_000, "frequency_offset_ppm": 0.02}
        }

    if "clock_synchronizer" not in components:
        sync = timing_doc.get("synchronization") or {}
        components["clock_synchronizer"] = {
            "component_class": "time_sync_unit",
            "model_binding_id": "timing.two_way_sync.v1",
            "update_period_ms": sync.get("update_period_ms", 10),
            "residual_offset_ps_rms": sync.get("residual_offset_ps_rms", 45),
            "holdover_timeout_s": 5,
        }
    if "coincidence_matcher" not in components:
        proc = timing_doc.get("coincidence_processor") or {}
        components["coincidence_matcher"] = {
            "component_class": "coincidence_matcher",
            "model_binding_id": "digital.coincidence.fpga_reference.v1",
            "clock_domain": "processing_clk",
            "window_ps": proc.get("window_ps", 800),
            "matching_policy": "nearest_unique",
            "queue_depth_events": proc.get("queue_depth", 16384),
            "out_of_order_tolerance_ps": 5000,
            "overflow_policy": proc.get("overflow_policy", "drop_and_count"),
        }

    endpoint_side = vtm.coordination_endpoint_side or "alice"
    return {
        "schema_version": "2.0",
        "subsystem": {
            "id": "network_coordination",
            "deployment_role": "network_coordination",
            "endpoint_side": endpoint_side,
            "topology_scope": "network",
            "component_class": "network_coordination_subsystem",
            "ports": {
                "digital_inputs": {
                    "alice_timestamps_in": {"packet_type": "timestamp_event"},
                    "bob_timestamps_in": {"packet_type": "timestamp_event"},
                },
            },
        },
        "time_model": timing_doc.get("time_model") or {
            "base_unit": "ps",
            "simulation_resolution_ps": 1,
            "timestamp_bits": 64,
        },
        "clock_domains": clock_domains,
        "components": components,
        "connections": [
            {"from": "alice_station.timestamps_out", "to": "coincidence_matcher.alice_events"},
            {"from": "bob_station.timestamps_out", "to": "coincidence_matcher.bob_events"},
            {"from": "clock_synchronizer.offset_estimate", "to": "coincidence_matcher.clock_offset"},
        ],
    }


def _build_qkd_node_doc(
    resolved: ResolvedTopology,
    *,
    vnode: VirtualNode,
) -> dict[str, Any]:
    side = str(vnode.endpoint_side or "")
    post = _post_processing_for_side(resolved, side)
    node_id = vnode.node_id
    kms = _kms_for_node(resolved, node_id)
    subsystem_id = vnode.qkd_node_id or f"{side}_qkd_node"
    authoritative = vnode.authoritative_host
    auth_qkd_id = None
    if not authoritative:
        vtm = build_virtual_topology(resolved)
        host = vtm.authoritative_host_node()
        if host:
            auth_qkd_id = host.qkd_node_id or f"{host.endpoint_side}_qkd_node"
    if authoritative:
        connections = [
            {"from": "coincidence_matcher.coincidences_out", "to": "sifting.in"},
            {"from": "sifting.test_bits", "to": "qber_estimation.in"},
            {"from": "sifting.raw_key_bits", "to": f"{subsystem_id}.sifted_key_out"},
            {"from": "qber_estimation.result", "to": f"{subsystem_id}.qber_result_out"},
        ]
    else:
        key_store_id = str((kms or {}).get("key_store_id", f"{side}_key_store"))
        store = resolved.components.get(key_store_id) or {}
        post["key_manager"] = {
            "component_class": store.get("component_class", "key_store_interface"),
            "export_policy": store.get("export_policy", "net_secret_key_only"),
        }
        connections = [
            {"from": f"{auth_qkd_id or 'alice_qkd_node'}.sifted_key_out", "to": "reconciliation.in"},
            {"from": f"{auth_qkd_id or 'alice_qkd_node'}.qber_result_out", "to": "finite_key_engine.parameter_estimation"},
            {"from": "reconciliation.corrected_bits", "to": "privacy_amplification.in"},
            {"from": "reconciliation.leakage", "to": "finite_key_engine.reconciliation_leakage"},
            {"from": "finite_key_engine.secret_length", "to": "privacy_amplification.output_length"},
            {"from": "privacy_amplification.secret_key", "to": "key_manager.in"},
            {"from": "key_manager.out", "to": f"{subsystem_id}.secret_key_out"},
        ]
    return {
        "schema_version": "2.0",
        "subsystem": {
            "id": subsystem_id,
            "deployment_role": "qkd_node",
            "endpoint_side": side,
            "topology_scope": "network",
            "component_class": "qkd_key_routing_node",
            "ports": {
                "digital_inputs": {
                    "coincidences_in": {"packet_type": "coincidence_event"},
                }
                if authoritative
                else {
                    "sifted_key_in": {"packet_type": "sifted_key_bits"},
                    "qber_result_in": {"packet_type": "qber_estimate"},
                },
                "digital_outputs": {
                    "sifted_key_out": {"packet_type": "sifted_key_bits"},
                    "qber_result_out": {"packet_type": "qber_estimate"},
                }
                if authoritative
                else {
                    "secret_key_out": {"packet_type": "secret_key"},
                },
            },
        },
        "post_processing": post,
        "connections": connections,
    }


_STATION_DOC_FILENAMES: dict[str, str] = {
    "alice": "03_alice_station.yaml",
    "bob": "04_bob_station.yaml",
}
_QKD_DOC_FILENAMES: dict[str, str] = {
    "alice": "07_alice_qkd_node.yaml",
    "bob": "08_bob_qkd_node.yaml",
}


def topology_to_flat_documents(resolved: ResolvedTopology) -> dict[str, dict[str, Any]]:
    """Produce flat schema-2.0 documents keyed by synthetic filename for YAMLManifest."""
    vtm = build_virtual_topology(resolved)
    docs: dict[str, dict[str, Any]] = {
        "02_source.yaml": _build_source_doc(resolved),
    }

    for node_id in vtm.node_order:
        vnode = vtm.nodes.get(node_id)
        if not vnode or vnode.node_role != "measurement_node":
            continue
        side = str(vnode.endpoint_side or "")
        if not side:
            continue
        station_key = _STATION_DOC_FILENAMES.get(side)
        if station_key:
            docs[station_key] = _build_station_doc(
                resolved,
                node_id=vnode.node_id,
                subsystem_id=vnode.station_subsystem_id,
                vnode=vnode,
            )
        qkd_key = _QKD_DOC_FILENAMES.get(side)
        if qkd_key:
            docs[qkd_key] = _build_qkd_node_doc(resolved, vnode=vnode)

    docs["06_network_coordination.yaml"] = _build_network_coordination_doc(resolved, vtm)

    # Pass through supplemental docs used by manifest builders
    protocol_doc = _supplemental_doc(resolved, "shared/protocol.yaml", "08_protocol.yaml")
    if protocol_doc:
        docs["01_protocol.yaml"] = deepcopy(protocol_doc)

    docs["05_channels.yaml"] = _flat_channels_doc(resolved)

    timing_doc = _timing_doc(resolved)
    if timing_doc:
        docs["06_timing_and_digital.yaml"] = deepcopy(timing_doc)

    for name, content in resolved.supplemental.items():
        if name == "11_post_processing.yaml" and "alice" in str(content):
            docs["07_post_processing.yaml"] = deepcopy(content)

    measurement_vnodes = [
        vtm.nodes[nid]
        for nid in vtm.node_order
        if (vtm.nodes.get(nid) and vtm.nodes[nid].node_role == "measurement_node")
    ]
    station_ids = [v.station_subsystem_id for v in measurement_vnodes]
    qkd_ids = [v.qkd_node_id or f"{v.endpoint_side}_qkd_node" for v in measurement_vnodes if v.qkd_node_id or v.endpoint_side]
    docs["00_manifest.yaml"] = {
        "schema_version": "2.0",
        "manifest": resolved.manifest.get("manifest") or {},
        "system": {
            "name": (resolved.system.get("qkd_system") or {}).get("name"),
            "protocol": "BBM92",
            "topology": "central_source_dual_fiber",
        },
        "composition": {
            "subsystems": [
                "central_entanglement_source",
                *station_ids,
                "network_coordination",
                *qkd_ids,
            ],
            "channels": (resolved.system.get("qkd_system") or {}).get("channel_ids", []),
            "groups": {
                "network_coordination": {
                    "deployment_role": "network_coordination",
                    "label": "Network coordination",
                },
            },
        },
    }
    return docs




def _boundary_port_entry(iface_id: str, iface: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a UI port entry for a boundary interface; returns (direction, entry)."""
    direction = str(iface.get("direction") or "").lower()
    entry: dict[str, Any] = {
        "id": str(iface_id),
        "group": "boundary",
        "direction": direction or None,
        "signal_type": iface.get("signal_type"),
        "packet_type": iface.get("packet_type"),
    }
    edge_kind = iface.get("edge_kind")
    if edge_kind:
        entry["edge_kind"] = str(edge_kind)
    medium = iface.get("medium") or (
        "digital" if str(edge_kind) in ("digital", "classical") else None
    )
    if medium:
        entry["medium"] = medium
    connector = iface.get("connector")
    if isinstance(connector, dict):
        entry["connector"] = connector
    return direction, entry


def _boundary_ports_where(
    resolved: ResolvedTopology,
    package_id: str | None,
    predicate: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Collect boundary interfaces of a package matching ``predicate(owner_id)``."""
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    bidirectional: list[dict[str, Any]] = []
    package = resolved.packages.get(package_id or "")
    if not package:
        return {"inputs": inputs, "outputs": outputs, "bidirectional": bidirectional}
    for iface_id, iface in package.interfaces.items():
        if not iface.get("boundary"):
            continue
        if not predicate(iface.get("owner_id")):
            continue
        direction, entry = _boundary_port_entry(str(iface_id), iface)
        if direction in ("inout", "bidirectional", "bidir"):
            bidirectional.append(entry)
        elif direction == "in":
            inputs.append(entry)
        elif direction == "out":
            outputs.append(entry)
    return {"inputs": inputs, "outputs": outputs, "bidirectional": bidirectional}


def _node_boundary_ports(resolved: ResolvedTopology, node_id: str) -> dict[str, list[dict[str, Any]]]:
    """Node-level boundary ports: those whose owner is *not* hosted by a device.

    Device-hosted boundary ports (owned by a component/module inside a box) are
    rendered on the device frame instead — see :func:`_device_boundary_ports`.
    """
    package_id = resolved.entity_package.get(node_id)
    return _boundary_ports_where(
        resolved,
        package_id,
        lambda owner_id: resolved.owner_device_id(owner_id) is None,
    )


def _device_boundary_ports(
    resolved: ResolvedTopology, device_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Boundary ports hosted by a specific device (box) → topology port lists."""
    package_id = resolved.entity_package.get(device_id)
    return _boundary_ports_where(
        resolved,
        package_id,
        lambda owner_id: resolved.owner_device_id(owner_id) == device_id,
    )


def _node_ops_metadata(resolved: ResolvedTopology, node_id: str) -> dict[str, Any]:
    """Attach node-level operational metadata from package supplemental docs."""
    package_id = resolved.entity_package.get(node_id)
    if not package_id:
        return {}
    package = resolved.packages.get(package_id)
    if not package:
        return {}
    ops: dict[str, Any] = {}
    key_map = {
        "environment.yaml": "environment",
        "physical_protection.yaml": "physical_protection",
        "trusted_node_security.yaml": "trusted_node_security",
        "orchestration.yaml": "orchestration",
        "monitoring.yaml": "monitoring",
    }
    for filename, field in key_map.items():
        doc = package.supplemental.get(filename)
        if doc:
            ops[field] = doc
    return ops


def build_hierarchy_groups(
    resolved: ResolvedTopology,
    *,
    graph_component_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Multi-level group frames for UI drill-down."""
    vtm = build_virtual_topology(resolved)
    if graph_component_ids is None:
        graph_component_ids = collect_graph_component_ids(topology_to_flat_documents(resolved))

    groups: list[dict[str, Any]] = []
    system = resolved.system.get("qkd_system") or {}
    system_id = str(system.get("system_id", "qkd_system"))

    groups.append(
        {
            "id": system_id,
            "label": system.get("name", "QKD System"),
            "group_kind": "qkd_system",
            "parent_id": None,
            "children": list(system.get("node_ids") or []),
            "member_ids": [],
        }
    )

    for node_id, node in resolved.nodes.items():
        kms_id = next(
            (kid for kid, kms in resolved.kms.items() if kms.get("parent_node_id") == node_id),
            None,
        )
        children = list(node.get("device_ids") or node.get("box_ids") or [])
        if kms_id:
            children.append(kms_id)
        node_group: dict[str, Any] = {
            "id": node_id,
            "label": node.get("name", node_id),
            "group_kind": "qkd_node",
            "parent_id": system_id,
            "children": children,
            "node_role": node.get("node_role"),
            "package_id": resolved.entity_package.get(node_id),
            "member_ids": [],
            "ports": _node_boundary_ports(resolved, node_id),
        }
        node_group.update(_node_ops_metadata(resolved, node_id))
        groups.append(
            enrich_hierarchy_node_group(
                node_group,
                vtm,
            )
        )

    for kms_id, kms in resolved.kms.items():
        kma_id = str(kms.get("kma_id", ""))
        ksa_id = str(kms.get("ksa_id", ""))
        store_id = str(kms.get("key_store_id", ""))
        kms_children = [kma_id, ksa_id, store_id]
        node_id = str(kms.get("parent_node_id", ""))

        groups.append(
            {
                "id": kms_id,
                "label": f"KMS ({kms_id})",
                "group_kind": "kms",
                "parent_id": node_id,
                "children": kms_children,
                "package_id": resolved.entity_package.get(kms_id),
                "member_ids": kms_children,
            }
        )

        for comp_id in (kma_id, ksa_id, store_id):
            if not comp_id:
                continue
            comp = resolved.components.get(comp_id, {})
            groups.append(
                {
                    "id": comp_id,
                    "label": str(comp.get("description") or comp_id),
                    "group_kind": "kms_component",
                    "parent_id": kms_id,
                    "children": [],
                    "component_type": comp.get("component_type"),
                    "component_class": comp.get("component_class"),
                    "package_id": resolved.entity_package.get(comp_id),
                    "member_ids": [],
                }
            )

    for device_id, device in resolved.devices.items():
        groups.append(
            {
                "id": device_id,
                "label": device.get("name", device_id),
                "group_kind": "qkd_device",
                "parent_id": device.get("parent_node_id"),
                "children": list(device.get("domain_ids") or []),
                "device_type": device.get("device_type") or device.get("box_type"),
                "package_id": resolved.entity_package.get(device_id),
                "member_ids": [],
                "ports": _device_boundary_ports(resolved, device_id),
            }
        )

    software_frames: list[dict[str, Any]] = []
    software_component_groups: list[dict[str, Any]] = []
    for domain_id, domain in resolved.domains.items():
        subdomain_ids = list(domain.get("subdomain_ids") or [])
        module_children = [
            m["module_id"]
            for m in resolved.modules.values()
            if m.get("parent_subdomain_id") in subdomain_ids
        ]
        # QKD classical-processing software has no module layer: each software
        # component is parented directly to its functional-group subdomain and is
        # rendered as a component card under a single "Key Distillation" frame one
        # level below the (generic) software domain.
        is_qkd_software = domain.get("domain_type") == "software" and bool(
            domain.get("ontology_ref")
        )
        if is_qkd_software:
            group_id = f"{domain_id}_key_distillation"
            child_ids: list[str] = []
            for sid in subdomain_ids:
                for comp in resolved.components.values():
                    if comp.get("parent_subdomain_id") != sid:
                        continue
                    comp_id = str(comp["component_id"])
                    software_component_groups.append(
                        {
                            "id": comp_id,
                            "label": comp.get("name", comp_id),
                            "group_kind": "component",
                            "parent_id": group_id,
                            "component_type": comp.get("component_type"),
                            "component_class": comp.get("component_class"),
                            "package_id": resolved.entity_package.get(comp_id),
                            "children": [],
                            "member_ids": _hierarchy_member_ids(
                                resolved, [comp_id], graph_component_ids
                            ),
                        }
                    )
                    child_ids.append(comp_id)
            if child_ids:
                software_frames.append(
                    {
                        "id": group_id,
                        "label": "QKD Classical Processing and Key Distillation Group",
                        "group_kind": "software_group",
                        "parent_id": domain_id,
                        "children": child_ids,
                        "member_ids": [],
                    }
                )
            domain_children: list[str] = [group_id] if child_ids else []
            domain_label = "Software Domain"
        else:
            domain_children = module_children
            domain_label = domain.get("name", domain_id)
        groups.append(
            {
                "id": domain_id,
                "label": domain_label,
                "group_kind": "domain",
                "parent_id": domain.get("parent_device_id") or domain.get("parent_box_id"),
                "domain_type": domain.get("domain_type"),
                "children": domain_children,
                "member_ids": [],
            }
        )
    groups.extend(software_frames)
    groups.extend(software_component_groups)

    for module_id, module in resolved.modules.items():
        comp_children = [
            c["component_id"]
            for c in resolved.components.values()
            if c.get("parent_module_id") == module_id
        ]
        graph_members = _hierarchy_member_ids(resolved, comp_children, graph_component_ids)
        groups.append(
            {
                "id": module_id,
                "label": module.get("name", module_id),
                "group_kind": "module",
                "parent_id": module.get("parent_subdomain_id"),
                "module_type": module.get("module_type"),
                "children": [],
                "member_ids": graph_members,
                "pam": module if module.get("module_type") == "polarization_analyzer_module" else None,
            }
        )

    return groups


def topology_to_simulation_graph(resolved: ResolvedTopology) -> dict[str, Any]:
    """Lightweight graph for inventory / structural_path (components + hierarchy)."""
    flat = topology_to_flat_documents(resolved)
    components: dict[str, Any] = {}
    for doc in flat.values():
        for comp_id, comp in (doc.get("components") or {}).items():
            if isinstance(comp, dict) and comp.get("component_class") == "detector_array":
                for ch_id, ch in (comp.get("channels") or {}).items():
                    components[str(ch_id)] = ch
            else:
                components[str(comp_id)] = comp

    return {
        "components": components,
        "hierarchy": build_hierarchy_groups(resolved),
        "configuration_hash": resolved.configuration_hash,
        "metadata": {"adapter_version": "1.0.0", "fidelity_mode": "aggregate"},
    }


__all__ = [
    "build_frame_boundary_links",
    "build_hierarchy_groups",
    "collect_graph_component_ids",
    "topology_to_flat_documents",
    "topology_to_simulation_graph",
]
