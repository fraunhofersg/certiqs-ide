from app.qkd.applicability import SystemFeatures, VulnRecord
from app.qkd.get_system_features import SystemFeaturesResult, SystemSummary
from app.qkd.routes import build_applicability_response


def make_loaded(features_kwargs: dict | None = None, **vuln_kwargs: object) -> SystemFeaturesResult:
    feature_fields = {
        "protocol_ids": [], "protocol_family_ids": [], "protocol_names": [],
        "module_type_ids": [], "component_type_ids": [], "component_placements": [],
    }
    feature_fields.update(features_kwargs or {})
    features = SystemFeatures(**feature_fields)
    vuln_fields = {"vulnerability_id": 1, "name": "V1", "module": "Receiver", "scope": [], "conditions": []}
    vuln_fields.update(vuln_kwargs)
    vuln = VulnRecord(**vuln_fields)
    return SystemFeaturesResult(
        system=SystemSummary(id=1, name="Test System", manufacturer="Acme"),
        features=features,
        vulns=[vuln],
        comp_type_rows=[{"component_type_id": 7, "component_type_name": "Single-Photon Detector", "module_type_id": 2}],
        system_cm_rows=[{
            "countermeasure_id": 100, "module_id": 5, "module_type_id": 2, "module_type_name": "RX",
            "name": "Optical Isolator", "description": "desc", "countermeasure_type": "Hardware",
            "cm_modules": ["Receiver"], "component_type_ids": [10],
        }],
    )


def test_applicable_entry_gets_covering_countermeasure():
    loaded = make_loaded()
    vuln_cm_rows = [{
        "vulnerability_id": 1, "countermeasure_id": 100, "name": "Optical Isolator",
        "description": "desc", "defense_effectiveness": ["Full"],
    }]
    response = build_applicability_response(1, loaded, vuln_cm_rows)

    assert response["systemId"] == 1
    entry = response["applicable"][0]
    assert entry["countermeasures"][0]["countermeasureId"] == 100
    assert entry["countermeasures"][0]["defenseEffectiveness"] == ["Full"]
    # module_type_name "RX" -> display "Receiver", matching the vuln's module="Receiver"
    assert len(entry["implementedCountermeasures"]) == 1


def test_countermeasure_installed_in_non_matching_module_not_implemented():
    loaded = make_loaded()
    # Countermeasure is installed at RX ("Receiver"), but this vuln targets Transmitter.
    loaded.vulns[0].module = "Transmitter"
    vuln_cm_rows = [{
        "vulnerability_id": 1, "countermeasure_id": 100, "name": "Optical Isolator",
        "description": "desc", "defense_effectiveness": ["Full"],
    }]
    response = build_applicability_response(1, loaded, vuln_cm_rows)
    entry = response["applicable"][0]
    assert entry["countermeasures"]  # still listed as a possible countermeasure...
    assert entry["implementedCountermeasures"] == []  # ...but not implemented for this module


def test_countermeasure_covering_both_modules_always_implemented():
    loaded = make_loaded()
    loaded.vulns[0].module = "Transmitter"
    vuln_cm_rows = [{
        "vulnerability_id": 1, "countermeasure_id": 100, "name": "Optical Isolator",
        "description": "desc", "defense_effectiveness": None,
    }]
    # Attack module is "Both" -> should count as implemented regardless of installed module.
    loaded.vulns[0].module = "Both"
    response = build_applicability_response(1, loaded, vuln_cm_rows)
    entry = response["applicable"][0]
    assert len(entry["implementedCountermeasures"]) == 1
    assert entry["implementedCountermeasures"][0]["defenseEffectiveness"] is None


def test_countermeasure_implemented_for_any_targeted_module_in_multi_module_attack():
    loaded = make_loaded()
    # Countermeasure is installed only at RX ("Receiver"), and the attack targets
    # two modules jointly ("Transmitter, Receiver") — installed in either one
    # should count as implemented, not just an exact string match on the whole
    # comma-joined value.
    loaded.vulns[0].module = "Transmitter, Receiver"
    vuln_cm_rows = [{
        "vulnerability_id": 1, "countermeasure_id": 100, "name": "Optical Isolator",
        "description": "desc", "defense_effectiveness": ["Full"],
    }]
    response = build_applicability_response(1, loaded, vuln_cm_rows)
    entry = response["applicable"][0]
    assert len(entry["implementedCountermeasures"]) == 1


def test_countermeasure_not_implemented_when_none_of_multi_module_attack_matches():
    loaded = make_loaded()
    # Countermeasure is installed only at RX ("Receiver"); attack targets two
    # other modules jointly, neither of which is Receiver.
    loaded.vulns[0].module = "Transmitter, Post-processing"
    vuln_cm_rows = [{
        "vulnerability_id": 1, "countermeasure_id": 100, "name": "Optical Isolator",
        "description": "desc", "defense_effectiveness": ["Full"],
    }]
    response = build_applicability_response(1, loaded, vuln_cm_rows)
    entry = response["applicable"][0]
    assert entry["implementedCountermeasures"] == []


def test_system_countermeasures_passthrough_stays_snake_case():
    loaded = make_loaded()
    response = build_applicability_response(1, loaded, [])
    row = response["systemCountermeasures"][0]
    assert row == {
        "countermeasure_id": 100, "module_id": 5, "module_type_id": 2, "module_type_name": "RX",
        "name": "Optical Isolator", "description": "desc", "countermeasure_type": "Hardware",
        "cm_modules": ["Receiver"], "component_type_ids": [10],
    }
    # And the rest of the response is camelCase, confirming the mixed-convention split is deliberate.
    assert "systemComponentTypeNames" in response
    assert "system_component_type_names" not in response


def test_cross_family_unknown_entry_lists_countermeasures_without_implemented_field():
    loaded = make_loaded(
        features_kwargs={"protocol_family_ids": [10]},
        scope=[{"protocol_family_id": 10, "cross_family_uncertain": True}],
    )
    vuln_cm_rows = [{
        "vulnerability_id": 1, "countermeasure_id": 100, "name": "Optical Isolator",
        "description": "desc", "defense_effectiveness": ["Partial"],
    }]
    response = build_applicability_response(1, loaded, vuln_cm_rows)
    assert response["applicable"] == []
    entry = response["crossFamilyUnknown"][0]
    assert entry["countermeasures"][0]["countermeasureId"] == 100
    assert "implementedCountermeasures" not in entry
