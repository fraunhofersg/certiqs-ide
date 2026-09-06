from app.export.assemble import RawConnection, RawModule, RawParam
from app.export.enrich.annotations import coerce_value, parse_detector_meta, split_params
from app.export.enrich.connections import InstanceLoc, classify_connections
from app.export.enrich.protocol import ProtocolOverrides, merge_protocol
from app.export.enrich.routing import file_for_instance, subsystem_for_module

# ── annotations.py ────────────────────────────────────────────────────────────


def test_coerce_value_bool():
    assert coerce_value("true") is True
    assert coerce_value("false") is False


def test_coerce_value_integer_stays_int():
    result = coerce_value("100000000")
    assert result == 100_000_000
    assert isinstance(result, int)


def test_coerce_value_float():
    result = coerce_value("0.85")
    assert result == 0.85
    assert isinstance(result, float)


def test_coerce_value_scientific_notation():
    assert coerce_value("1e-12") == 1e-12


def test_coerce_value_empty_and_none_are_none():
    assert coerce_value(None) is None
    assert coerce_value("") is None


def test_coerce_value_non_numeric_stays_text():
    assert coerce_value("APD (gated)") == "APD (gated)"


def test_split_params_groups_by_annotations():
    params = [
        RawParam(param_group="settings", key="efficiency", value="0.8", unit=None),
        RawParam(param_group="annotations", key="detector_role", value="basis=Z, state=H, bit=0", unit=None),
    ]
    result = split_params(params)
    assert result.settings == {"efficiency": 0.8}
    assert result.annotations == {"detector_role": "basis=Z, state=H, bit=0"}


def test_parse_detector_meta_extracts_structured_fields():
    meta = parse_detector_meta({"detector_role": "basis=Z, state=H, bit=0, channel_id=2"})
    assert meta.basis == "Z"
    assert meta.state == "H"
    assert meta.bit == 0
    assert meta.channel_id == 2


def test_parse_detector_meta_absent_returns_none():
    assert parse_detector_meta({}) is None
    assert parse_detector_meta({"detector_role": 123}) is None


def test_parse_detector_meta_ignores_malformed_parts():
    # "novalue" has no "=" at all -> only one piece after split -> skipped
    meta = parse_detector_meta({"detector_role": "basis=Z, novalue, state=H"})
    assert meta.basis == "Z"
    assert meta.state == "H"


# ── routing.py ────────────────────────────────────────────────────────────────


def test_subsystem_for_module_detects_alice():
    mod = RawModule(id=1, name="Alice Station", firmware_revision="alice_node", module_type="TX")
    info = subsystem_for_module(mod)
    assert info.key == "alice"
    assert info.role == "measurement_station"


def test_subsystem_for_module_detects_source():
    mod = RawModule(id=2, name="Central Source", firmware_revision=None, module_type="TX")
    info = subsystem_for_module(mod)
    assert info.key == "source"
    assert info.name == "central_source"  # falls back to slugified mod.name


def test_subsystem_for_module_post_processing():
    mod = RawModule(id=3, name="PP Stage", firmware_revision=None, module_type="POST_PROCESSING")
    info = subsystem_for_module(mod)
    assert info.key == "post_processing"


def test_file_for_instance_digital_postproc_role():
    assert file_for_instance("bob", "digital", "crypto_engine") == "07_post_processing.yaml"


def test_file_for_instance_digital_generic_role():
    assert file_for_instance("bob", "digital", "controller") == "06_digital.yaml"


def test_file_for_instance_optical_by_subsystem():
    assert file_for_instance("alice", "optical", None) == "03_alice_node.yaml"
    assert file_for_instance("bob", "optical", None) == "04_bob_node.yaml"
    assert file_for_instance("source", "optical", None) == "02_source_central.yaml"


# ── protocol.py ───────────────────────────────────────────────────────────────


def test_merge_protocol_uses_bbm92_template_defaults():
    protocol = merge_protocol("BBM92", "EB-QKD", None, [])
    assert protocol.encoding == "polarization"
    assert protocol.bit_mapping == {"H": 0, "V": 1, "D": 0, "A": 1}
    assert protocol.basis_selection == "passive"


def test_merge_protocol_derives_bit_mapping_from_detectors():
    from app.export.ir import DetectorMeta

    detectors = [DetectorMeta(state="H", bit=1), DetectorMeta(state="V", bit=0)]
    protocol = merge_protocol("BBM92", "EB-QKD", None, detectors)
    assert protocol.bit_mapping == {"H": 1, "V": 0}


def test_merge_protocol_coincidence_override_merges_not_replaces():
    protocol = merge_protocol("BBM92", "EB-QKD", None, [], ProtocolOverrides(coincidence={"window_ps": 500}))
    assert protocol.coincidence["window_ps"] == 500
    assert protocol.coincidence["multi_click_policy"] == "discard"  # template default retained


def test_merge_protocol_unknown_name_falls_back_to_bbm92_template():
    protocol = merge_protocol("SomeUnknownProtocol", "X", "custom_encoding", [])
    assert protocol.basis_selection == "passive"  # BBM92 template values used
    assert protocol.encoding == "custom_encoding"  # but explicit encoding arg wins


# ── connections.py ────────────────────────────────────────────────────────────


def _conn(**kwargs) -> RawConnection:
    base = dict(
        medium="fibre", label=None, from_port=None, to_port=None,
        from_instance=None, from_module_slug=None, from_domain=None,
        to_instance=None, to_module_slug=None, to_domain=None,
    )
    base.update(kwargs)
    return RawConnection(**base)


def test_classify_optical_same_subsystem_is_intra():
    locs = {"a": InstanceLoc(subsystem="alice", domain="optical"), "b": InstanceLoc(subsystem="alice", domain="optical")}
    result = classify_connections([_conn(medium="fibre", from_instance="a", from_port="out", to_instance="b", to_port="in")], locs)
    assert len(result.connections) == 1
    assert result.connections[0].category == "optical_intra"
    assert not result.channels


def test_classify_optical_cross_subsystem_creates_channel_and_two_legs():
    locs = {"a": InstanceLoc(subsystem="source", domain="optical"), "b": InstanceLoc(subsystem="alice", domain="optical")}
    result = classify_connections([_conn(medium="fibre", from_instance="a", from_port="signal_out", to_instance="b", to_port="in")], locs)
    assert len(result.channels) == 1
    assert result.channels[0].type == "quantum"
    assert len(result.connections) == 2
    assert all(c.category == "optical_channel" for c in result.connections)


def test_classify_sync_link_becomes_channel():
    result = classify_connections([_conn(medium="electrical_sync_link", from_instance="a", to_instance="b")], {})
    assert len(result.channels) == 1
    assert result.channels[0].type == "sync"


def test_classify_medium_order_sync_wins_over_optical_substring():
    # "electrical_or_optical_sync" contains "optic" but must classify as sync, not optical.
    result = classify_connections([_conn(medium="electrical_or_optical_sync", from_instance="a", to_instance="b")], {})
    assert len(result.channels) == 1
    assert result.channels[0].type == "sync"
    assert not result.connections


def test_classify_binding_event_bridge_optical_to_digital():
    locs = {"a": InstanceLoc(subsystem="bob", domain="optical"), "b": InstanceLoc(subsystem="bob", domain="digital")}
    result = classify_connections(
        [_conn(medium="coaxial", from_instance="a", from_port="click", to_instance="b", to_port="click_in[0]")], locs
    )
    assert len(result.bindings) == 1
    assert result.bindings[0].type == "event_bridge"


def test_classify_binding_control_bridge_digital_to_optical():
    locs = {"a": InstanceLoc(subsystem="bob", domain="digital"), "b": InstanceLoc(subsystem="bob", domain="optical")}
    result = classify_connections([_conn(medium="coaxial", from_instance="a", to_instance="b")], locs)
    assert result.bindings[0].type == "control_bridge"
