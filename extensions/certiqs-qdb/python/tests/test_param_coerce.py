from app.systems.param_coerce import coerce_parameter
from app.systems.pivot import pivot


def test_pivot_produces_parallel_arrays():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    result = pivot(rows, "a", "b")
    assert result == {"a": [1, 2], "b": ["x", "y"]}


def test_spec_field_number_type_coerces_and_stamps_unit():
    result = coerce_parameter("0.8", None, None, "Laser Source", "mean_photon_number")
    assert result.value_num == 0.8
    assert result.value_bool is None
    assert result.value_text is None
    assert result.unit == "photons/pulse"  # canonical unit stamped even though caller passed none
    assert result.param_group == "parameters"


def test_spec_field_boolean_type():
    result = coerce_parameter("true", None, None, "Coherent Detector", "detection_scheme")
    # detection_scheme is actually type "select" in the real spec, so this exercises
    # the "spec exists but not number/boolean" -> value_text branch instead.
    assert result.value_text == "true"


def test_spec_field_text_type_empty_string_becomes_none():
    result = coerce_parameter("", None, None, "Laser Source", "source_emission_temporal_profile")
    assert result.value_text is None


def test_unknown_key_falls_back_to_auto_detect_number():
    result = coerce_parameter("3.14", None, None, "Laser Source", "not_a_real_key")
    assert result.value_num == 3.14
    assert result.value_bool is None
    assert result.value_text is None


def test_unknown_key_falls_back_to_auto_detect_boolean():
    result = coerce_parameter("false", None, None, "Laser Source", "not_a_real_key")
    assert result.value_bool is False
    assert result.value_num is None
    assert result.value_text is None


def test_unknown_key_falls_back_to_auto_detect_text():
    result = coerce_parameter("some free text", None, None, "Laser Source", "not_a_real_key")
    assert result.value_text == "some free text"
    assert result.value_num is None
    assert result.value_bool is None


def test_unknown_component_type_uses_caller_supplied_unit():
    result = coerce_parameter("5", "custom-unit", None, "Nonexistent Component", "some_key")
    assert result.unit == "custom-unit"


def test_param_group_defaults_to_parameters_when_none():
    result = coerce_parameter("5", None, None, "Laser Source", "mean_photon_number")
    assert result.param_group == "parameters"


def test_param_group_empty_string_is_preserved_not_defaulted():
    # Mirrors JS `??` (null/undefined-check only) — an empty string is a present
    # value, not a missing one, so it must NOT fall back to "parameters".
    result = coerce_parameter("5", None, "", "Laser Source", "mean_photon_number")
    assert result.param_group == ""


def test_none_raw_value_treated_as_empty_string():
    result = coerce_parameter(None, None, None, "Laser Source", "mean_photon_number")
    assert result.value_num is None
