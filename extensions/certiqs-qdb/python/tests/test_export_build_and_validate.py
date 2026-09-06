from app.export.assemble import RawComponent, RawConnection, RawModule, RawParam, RawProtocol, SystemAggregate
from app.export.build import build_model
from app.export.validate import has_errors, validate_model


def _param(group: str, key: str, value: str, unit: str | None = None) -> RawParam:
    return RawParam(param_group=group, key=key, value=value, unit=unit)


def make_minimal_aggregate() -> SystemAggregate:
    """A tiny BBM92-ish system: one source module, one alice detector, one bob
    detector, an intra-subsystem-free cross link, and one classical sync link."""
    source_component = RawComponent(
        mc_id=1, module_id=1, instance_name="central_spdc_source", domain="optical",
        branch_side=None, role=None, component_type="Entangled Photon Source",
        vendor=None, model=None, parameters=[],
    )
    alice_detector = RawComponent(
        mc_id=2, module_id=2, instance_name="alice_apd_h", domain="optical",
        branch_side=None, role=None, component_type="Single-Photon Detector",
        vendor=None, model=None,
        parameters=[
            _param("settings", "detection_efficiency", "0.8"),
            _param("annotations", "detector_role", "basis=Z, state=H, bit=0, channel_id=0"),
        ],
    )
    bob_detector = RawComponent(
        mc_id=3, module_id=3, instance_name="bob_apd_h", domain="optical",
        branch_side=None, role=None, component_type="Single-Photon Detector",
        vendor=None, model=None,
        parameters=[
            _param("settings", "detection_efficiency", "0.75"),
            _param("annotations", "detector_role", "basis=Z, state=H, bit=0, channel_id=0"),
        ],
    )
    modules = [
        RawModule(id=1, name="Source", firmware_revision="central_source", module_type="TX", components=[source_component]),
        RawModule(id=2, name="Alice", firmware_revision="alice_node", module_type="TX", components=[alice_detector]),
        RawModule(id=3, name="Bob", firmware_revision="bob_node", module_type="RX", components=[bob_detector]),
    ]
    connections = [
        RawConnection(
            medium="fibre", label="quantum link to alice", from_port="signal_out", to_port="in",
            from_instance="central_spdc_source", from_module_slug="central_source", from_domain="optical",
            to_instance="alice_apd_h", to_module_slug="alice_node", to_domain="optical",
        ),
        RawConnection(
            medium="ethernet_sync_link", label=None, from_port=None, to_port=None,
            from_instance="alice_apd_h", from_module_slug="alice_node", from_domain="optical",
            to_instance="bob_apd_h", to_module_slug="bob_node", to_domain="optical",
        ),
    ]
    return SystemAggregate(
        system={"id": 42, "name": "Test BBM92 System"},
        protocols=[RawProtocol(id=1, name="BBM92", family="EB-QKD", encoding=None, is_primary=True)],
        modules=modules,
        connections=connections,
        system_pp=[],
    )


def test_build_model_produces_instances_for_every_component():
    built = build_model(make_minimal_aggregate())
    names = {i.name for i in built.model.instances}
    assert names == {"central_spdc_source", "alice_apd_h", "bob_apd_h"}


def test_build_model_derives_bit_mapping_from_detector_annotations():
    built = build_model(make_minimal_aggregate())
    assert built.model.protocol.bit_mapping == {"H": 0}


def test_build_model_manifest_and_system_names_are_slugified():
    built = build_model(make_minimal_aggregate())
    assert built.model.manifest_name == "bbm92_system"
    assert built.model.system_name == "test_bbm92_system"


def test_build_model_classifies_cross_subsystem_channel():
    built = build_model(make_minimal_aggregate())
    assert len(built.model.channels) == 2  # quantum (source->alice) + sync (alice->bob)
    quantum = next(c for c in built.model.channels if c.type == "quantum")
    assert quantum.from_ == "central_spdc_source.signal_out"


def test_build_model_validates_clean_with_no_errors():
    built = build_model(make_minimal_aggregate())
    issues = validate_model(built.model, built.connections)
    assert not has_errors(issues), [i.message for i in issues if i.level == "error"]


def test_validate_model_flags_duplicate_instance_names():
    built = build_model(make_minimal_aggregate())
    built.model.instances.append(built.model.instances[0])  # duplicate "central_spdc_source"
    issues = validate_model(built.model, built.connections)
    assert any(i.code == "unique_instance_names" for i in issues)


def test_validate_model_flags_bit_mapping_disagreement():
    built = build_model(make_minimal_aggregate())
    # Detector says bit=0 for state H, but corrupt the protocol's own bit_mapping.
    built.model.protocol.bit_mapping["H"] = 1
    issues = validate_model(built.model, built.connections)
    assert any(i.code == "bit_mapping" for i in issues)


def test_validate_model_empty_instances_is_an_error():
    built = build_model(make_minimal_aggregate())
    built.model.instances = []
    issues = validate_model(built.model, built.connections)
    assert any(i.code == "empty" for i in issues)
