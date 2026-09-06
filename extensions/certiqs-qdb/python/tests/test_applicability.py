from app.qkd.applicability import (
    Condition,
    DetectorRow,
    ScopeRow,
    SystemFeatures,
    VulnRecord,
    derive_detector_types,
    describe_condition,
    evaluate_applicability,
    evaluate_condition,
    normalize_component_terms,
    row_matches,
    scope_matches,
)


def make_features(**overrides: object) -> SystemFeatures:
    base = dict(
        protocol_ids=[1],
        protocol_family_ids=[10],
        protocol_names=["BB84"],
        module_type_ids=[1, 2],
        component_type_ids=[1, 7],
        component_placements=[
            {"module_type_id": 1, "component_type_id": 1},
            {"module_type_id": 2, "component_type_id": 7},
        ],
        encoding_ids=[1],
        architecture=None,
    )
    base.update(overrides)
    return SystemFeatures(**base)


# ── camelCase JSON wire format ────────────────────────────────────────────────


def test_system_features_round_trips_camelcase_json():
    features = make_features(basis_choice="passive")
    dumped = features.model_dump(by_alias=True)
    assert dumped["protocolIds"] == [1]
    assert dumped["basisChoice"] == "passive"
    assert "protocol_ids" not in dumped

    restored = SystemFeatures.model_validate(dumped)
    assert restored.protocol_ids == [1]
    assert restored.basis_choice == "passive"


# ── row_matches / scope_matches ───────────────────────────────────────────────


def test_scope_matches_system_wide_when_no_rows():
    features = make_features()
    result = scope_matches(features, [])
    assert result.matched is True
    assert result.components == ["system-wide"]
    assert result.is_cross_family is False


def test_scope_matches_labels_an_unrestricted_row_system_wide():
    # A vulnerability like "Hardware-software Trojans" owns a real scope row whose
    # module/component columns are both NULL. It must still render the "system-wide"
    # chip rather than an empty matched-components list.
    features = make_features()
    result = scope_matches(features, [ScopeRow(encoding_id=1)])
    assert result.matched is True
    assert result.components == ["system-wide"]


def test_row_matches_wildcards_null_dimensions():
    features = make_features()
    row = ScopeRow(protocol_family_id=None, protocol_id=None, module_type_id=None, component_type_id=None)
    assert row_matches(features, row) is True


def test_row_matches_encoding_mismatch_fails():
    features = make_features(encoding_ids=[1])
    row = ScopeRow(encoding_id=2)
    assert row_matches(features, row) is False


def test_row_matches_accepts_either_encoding_of_a_dual_encoding_system():
    # A system carrying both a DV and a CV protocol must match scope rows on BOTH
    # encodings — collapsing to a single encoding dropped half the catalogue.
    features = make_features(encoding_ids=[1, 2])
    assert row_matches(features, ScopeRow(encoding_id=1)) is True
    assert row_matches(features, ScopeRow(encoding_id=2)) is True
    assert row_matches(features, ScopeRow(encoding_id=3)) is False


def test_row_matches_encoding_row_never_matches_a_system_with_no_encoding():
    features = make_features(encoding_ids=[])
    assert row_matches(features, ScopeRow(encoding_id=1)) is False
    # ... but an encoding-wildcard row still does.
    assert row_matches(features, ScopeRow()) is True


def test_row_matches_requires_component_installed_in_specific_module():
    # module_type_id=2 (RX) has component_type_id=1 required, but component 1 is
    # actually placed in module 1 (TX) per make_features() —
    # docs/COMPONENT_MODULE_PLACEMENT.md, Rule 3.
    features = make_features()
    row = ScopeRow(module_type_id=2, component_type_id=1)
    assert row_matches(features, row) is False

    row_correct = ScopeRow(module_type_id=1, component_type_id=1)
    assert row_matches(features, row_correct) is True


def test_scope_matches_falls_back_to_cross_family_only_when_no_primary_matches():
    features = make_features(protocol_family_ids=[99])
    primary = ScopeRow(protocol_family_id=10)  # won't match
    cross = ScopeRow(protocol_family_id=99, cross_family_uncertain=True)
    result = scope_matches(features, [primary, cross])
    assert result.matched is True
    assert result.is_cross_family is True


# ── describe_condition / JS-parity string formatting ─────────────────────────


def test_describe_condition_flag_equals_bool_true():
    cond = Condition(cond_type="flagEquals", path="basis_choice", value_bool=True)
    assert describe_condition(cond) == "basis_choice = true"


def test_describe_condition_flag_equals_bool_false_not_skipped():
    # Regression guard: must use "first non-None", not Python truthiness (`or`
    # would incorrectly skip False and fall through to value_text/value_num).
    cond = Condition(cond_type="flagEquals", path="detector_accepts_clicks_outside_gate", value_bool=False)
    assert describe_condition(cond) == "detector_accepts_clicks_outside_gate = false"


def test_describe_condition_all_values_none_renders_js_null():
    cond = Condition(cond_type="flagEquals", path="basis_choice")
    assert describe_condition(cond) == "basis_choice = null"


def test_describe_condition_integral_float_drops_trailing_zero():
    cond = Condition(cond_type="numericGte", path="mean_photon_number", value_num=3.0)
    assert describe_condition(cond) == "mean_photon_number ≥ 3"


def test_describe_condition_non_integral_float_preserved():
    cond = Condition(cond_type="numericLte", path="mean_photon_number", value_num=0.5)
    assert describe_condition(cond) == "mean_photon_number ≤ 0.5"


def test_describe_condition_set_intersects_empty_list():
    cond = Condition(cond_type="setIntersects", path="detector_types", values_text=[])
    assert describe_condition(cond) == "detector_types ∋ {}"


def test_describe_condition_set_intersects_joins_values():
    cond = Condition(cond_type="setIntersects", path="detector_types", values_text=["gated-APD", "SNSPD"])
    assert describe_condition(cond) == "detector_types ∋ {gated-APD, SNSPD}"


# ── evaluate_condition ────────────────────────────────────────────────────────


def test_evaluate_condition_flag_equals_string():
    features = make_features(basis_choice="passive")
    cond = Condition(cond_type="flagEquals", path="basis_choice", value_text="passive")
    assert evaluate_condition(features, cond) is True


def test_evaluate_condition_bool_vs_int_not_conflated():
    # Python's `1 == True` is True, but JS `1 === true` is false — evaluate_condition
    # must use strict-eq semantics, not Python's default bool/int equality.
    features = make_features(detector_accepts_clicks_outside_gate=True)
    cond = Condition(cond_type="flagEquals", path="detector_accepts_clicks_outside_gate", value_num=1)
    assert evaluate_condition(features, cond) is False


def test_evaluate_condition_flag_not_equals():
    features = make_features(basis_choice="passive")
    cond = Condition(cond_type="flagNotEquals", path="basis_choice", value_text="active")
    assert evaluate_condition(features, cond) is True


def test_evaluate_condition_set_intersects_true_when_overlap():
    features = make_features(detector_types=["gated-APD", "SNSPD"])
    cond = Condition(cond_type="setIntersects", path="detector_types", values_text=["SNSPD"])
    assert evaluate_condition(features, cond) is True


def test_evaluate_condition_set_intersects_false_when_not_a_list():
    features = make_features(basis_choice="passive")
    cond = Condition(cond_type="setIntersects", path="basis_choice", values_text=["passive"])
    assert evaluate_condition(features, cond) is False


# ── derive_detector_types ─────────────────────────────────────────────────────


def test_derive_detector_types_known_variant():
    rows = [DetectorRow(variant_value="Gated APD", component_type="Single-Photon Detector")]
    assert derive_detector_types(rows) == ["gated-APD"]


def test_derive_detector_types_unknown_variant_falls_back_to_spd():
    rows = [DetectorRow(variant_value="Some New Detector Model", component_type="Single-Photon Detector")]
    assert derive_detector_types(rows) == ["SPD"]


def test_derive_detector_types_component_type_fallback():
    rows = [DetectorRow(variant_value=None, component_type="Coherent Detector")]
    # Bare coherent detector pins no detection scheme, so both schemes are emitted.
    assert derive_detector_types(rows) == ["coherent", "homodyne", "heterodyne"]


def test_derive_detector_types_empty_returns_none():
    assert derive_detector_types([]) is None


# Quenching axis: "free-running" states gating but not quenching, so both quenching
# tags are emitted and both BSI 4.12 / 4.14 detector-control attacks surface.


def test_derive_detector_types_free_running_emits_both_quenching_tags():
    rows = [DetectorRow(variant_value="APD (free-running)", component_type="Single-Photon Detector")]
    assert derive_detector_types(rows) == [
        "free-running-APD",
        "actively-quenched-APD",
        "passively-quenched-APD",
    ]


def test_derive_detector_types_gated_does_not_expand_quenching():
    rows = [DetectorRow(variant_value="APD (gated)", component_type="Single-Photon Detector")]
    assert derive_detector_types(rows) == ["gated-APD"]


def test_derive_detector_types_explicit_quenching_pins_one_tag():
    passive = [DetectorRow(variant_value="APD (free-running, passively quenched)", component_type="Single-Photon Detector")]
    assert derive_detector_types(passive) == ["free-running-APD", "passively-quenched-APD"]

    active = [DetectorRow(variant_value="APD (free-running, actively quenched)", component_type="Single-Photon Detector")]
    assert derive_detector_types(active) == ["free-running-APD", "actively-quenched-APD"]


def test_derive_detector_types_negative_feedback_is_passively_quenched():
    # BSI Table 4.12's subcomponent is "Passively-quenched or negative-feedback APD".
    rows = [DetectorRow(variant_value="Negative feedback APD", component_type="Single-Photon Detector")]
    assert derive_detector_types(rows) == ["free-running-APD", "passively-quenched-APD"]


def test_derive_detector_types_bare_apd_component_resolves_to_nothing():
    # The legacy bare "Avalanche Photon Detector" type pins neither axis, and its
    # four candidate tags are mutually exclusive — emitting them all made BSI 4.12,
    # 4.13, 4.14 and 4.17 all report applicable on one physical detector. No tag
    # means the detector-gated vulnerabilities land in `unevaluated` instead.
    rows = [DetectorRow(variant_value=None, component_type="Avalanche Photon Detector")]
    assert derive_detector_types(rows) is None


def test_derive_detector_types_variant_wins_over_component_type():
    # A detector_variant stored on a legacy APD / Coherent Detector row is the most
    # specific fact available and must not be discarded in favour of the bare
    # component-type mapping.
    apd = [DetectorRow(variant_value="APD (gated)", component_type="Avalanche Photon Detector")]
    assert derive_detector_types(apd) == ["gated-APD"]

    coherent = [DetectorRow(variant_value="Homodyne detector", component_type="Coherent Detector")]
    assert derive_detector_types(coherent) == ["homodyne"]


def test_derive_detector_types_dedupes_across_detector_rows():
    rows = [
        DetectorRow(variant_value="APD (free-running)", component_type="Single-Photon Detector"),
        DetectorRow(variant_value="APD (free-running)", component_type="Single-Photon Detector"),
        DetectorRow(variant_value="SNSPD", component_type="Single-Photon Detector"),
    ]
    assert derive_detector_types(rows) == [
        "free-running-APD",
        "actively-quenched-APD",
        "passively-quenched-APD",
        "SNSPD",
    ]


# ── normalize_component_terms ─────────────────────────────────────────────────


def test_normalize_component_terms_expands_generic_detector():
    assert normalize_component_terms("detector") == ["Single-Photon Detector", "Avalanche Photon Detector"]


def test_normalize_component_terms_unknown_term_falls_back_to_original():
    assert normalize_component_terms("Some Novel Widget") == ["Some Novel Widget"]


def test_normalize_component_terms_none_returns_empty():
    assert normalize_component_terms(None) == []


def test_normalize_component_terms_maps_the_bsi_4_54_and_4_55_subcomponents():
    # Both strings are seeded verbatim by seed-attack-references.ts. An unmapped term
    # falls through as a raw chip that no component filter can ever group under.
    assert normalize_component_terms("Modulation system") == ["Phase Modulator", "Intensity Modulator"]
    assert normalize_component_terms("Balanced homodyne detector, beamsplitter") == [
        "Coherent Detector",
        "Beam Splitter",
    ]


# ── evaluate_applicability — all six classification branches ─────────────────


def test_no_scope_match_when_no_row_matches():
    features = make_features(protocol_family_ids=[999])
    vuln = VulnRecord(
        vulnerability_id=1, name="V1",
        scope=[ScopeRow(protocol_family_id=10)],
        conditions=[],
    )
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.no_scope_match] == [1]


def test_mdi_excludes_receiver_attack_without_override():
    features = make_features(architecture="MDI")
    vuln = VulnRecord(vulnerability_id=2, name="V2", module="Receiver", scope=[], conditions=[])
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.excluded] == [2]
    assert "MDI" in result.excluded[0].reason


def test_mdi_override_bypasses_receiver_exclusion():
    features = make_features(architecture="MDI")
    vuln = VulnRecord(
        vulnerability_id=3, name="V3", module="Receiver",
        scope=[ScopeRow(architecture_exclusion_override=True)],
        conditions=[],
    )
    result = evaluate_applicability(features, [vuln])
    assert result.excluded == []
    assert [v.vulnerability_id for v in result.applicable] == [3]


def test_eb_excludes_transmitter_attack_without_override():
    features = make_features(architecture="EB")
    vuln = VulnRecord(vulnerability_id=4, name="V4", module="Transmitter", scope=[], conditions=[])
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.excluded] == [4]
    assert "EB" in result.excluded[0].reason


def test_eb_excludes_transmitter_attack_regardless_of_matched_components():
    """EB is source-device-independent: a transmitter attack is excluded even when the
    scope row that matched names a component the TX module genuinely has."""
    features = make_features(architecture="EB")
    vuln = VulnRecord(
        vulnerability_id=41, name="Injection-locking", module="Transmitter",
        scope=[ScopeRow(module_type_id=1, component_type_id=1)],  # TX + Laser, which the system has
        conditions=[],
    )
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.excluded] == [41]


# ── multi-module attacks.module ("Transmitter, Receiver") ─────────────────────


def test_eb_does_not_exclude_attack_targeting_more_than_the_transmitter():
    features = make_features(architecture="EB")
    vuln = VulnRecord(
        vulnerability_id=42, name="Laser damage on detectors",
        module="Transmitter, Receiver", scope=[], conditions=[],
    )
    result = evaluate_applicability(features, [vuln])
    assert result.excluded == []
    assert [v.vulnerability_id for v in result.applicable] == [42]


def test_mdi_does_not_exclude_attack_targeting_more_than_the_receiver():
    features = make_features(architecture="MDI")
    vuln = VulnRecord(
        vulnerability_id=43, name="EM radiation",
        module="Transmitter, Receiver", scope=[], conditions=[],
    )
    result = evaluate_applicability(features, [vuln])
    assert result.excluded == []
    assert [v.vulnerability_id for v in result.applicable] == [43]


def test_exclusion_tolerates_whitespace_in_module_token_list():
    features = make_features(architecture="EB")
    vuln = VulnRecord(vulnerability_id=44, name="V44", module="  Transmitter  ", scope=[], conditions=[])
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.excluded] == [44]


def test_null_module_is_never_excluded_by_architecture():
    features = make_features(architecture="EB")
    vuln = VulnRecord(vulnerability_id=45, name="V45", module=None, scope=[], conditions=[])
    result = evaluate_applicability(features, [vuln])
    assert result.excluded == []
    assert [v.vulnerability_id for v in result.applicable] == [45]


def test_unparseable_module_is_never_excluded_by_architecture():
    features = make_features(architecture="EB")
    vuln = VulnRecord(vulnerability_id=46, name="V46", module="Both", scope=[], conditions=[])
    result = evaluate_applicability(features, [vuln])
    assert result.excluded == []


def test_unevaluated_when_condition_data_missing():
    features = make_features(basis_choice=None)
    vuln = VulnRecord(
        vulnerability_id=5, name="V5", scope=[],
        conditions=[Condition(cond_type="flagEquals", path="basis_choice", value_text="passive")],
    )
    result = evaluate_applicability(features, [vuln])
    assert result.unevaluated[0].vulnerability_id == 5
    assert result.unevaluated[0].missing == ["basis_choice"]


def test_conditions_failed_when_condition_evaluates_false():
    features = make_features(basis_choice="active")
    vuln = VulnRecord(
        vulnerability_id=6, name="V6", scope=[],
        conditions=[Condition(cond_type="flagEquals", path="basis_choice", value_text="passive")],
    )
    result = evaluate_applicability(features, [vuln])
    assert result.conditions_failed[0].vulnerability_id == 6
    assert result.conditions_failed[0].failed_path == "basis_choice"


def test_cross_family_unknown_when_only_cross_family_row_matches():
    features = make_features(protocol_family_ids=[10])
    vuln = VulnRecord(
        vulnerability_id=7, name="V7",
        scope=[ScopeRow(protocol_family_id=10, cross_family_uncertain=True)],
        conditions=[],
    )
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.cross_family_unknown] == [7]


def test_applicable_when_scope_and_conditions_both_satisfied():
    features = make_features(basis_choice="passive")
    vuln = VulnRecord(
        vulnerability_id=8, name="V8", scope=[],
        conditions=[Condition(cond_type="flagEquals", path="basis_choice", value_text="passive")],
    )
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.applicable] == [8]
    assert result.applicable[0].matched_conditions == ["basis_choice = passive"]


def _three_mixed_conditions() -> list[Condition]:
    return [
        Condition(cond_type="flagEquals", path="source_type", value_text="weak-coherent"),
        Condition(cond_type="flagEquals", path="has_decoy_countermeasure", value_bool=False),
        Condition(cond_type="setIntersects", path="detector_types", values_text=["gated-APD", "free-running-APD"]),
    ]


def test_applicable_requires_all_of_several_mixed_condition_types_to_pass():
    features = make_features(
        source_type="weak-coherent",
        has_decoy_countermeasure=False,
        detector_types=["gated-APD"],
    )
    vuln = VulnRecord(vulnerability_id=9, name="V9", scope=[], conditions=_three_mixed_conditions())
    result = evaluate_applicability(features, [vuln])
    assert [v.vulnerability_id for v in result.applicable] == [9]
    assert result.applicable[0].matched_conditions == [
        "source_type = weak-coherent",
        "has_decoy_countermeasure = false",
        "detector_types ∋ {gated-APD, free-running-APD}",
    ]


def test_applicable_fails_if_any_one_of_several_conditions_fails():
    # Same three conditions as above, but has_decoy_countermeasure is True instead
    # of the required False. Guards against a future AND-loop refactor in
    # evaluate_applicability that stops requiring every condition to pass (e.g.
    # short-circuits on the first match instead of the first failure).
    features = make_features(
        source_type="weak-coherent",
        has_decoy_countermeasure=True,
        detector_types=["gated-APD"],
    )
    vuln = VulnRecord(vulnerability_id=9, name="V9", scope=[], conditions=_three_mixed_conditions())
    result = evaluate_applicability(features, [vuln])
    assert result.applicable == []
    assert [v.vulnerability_id for v in result.conditions_failed] == [9]
