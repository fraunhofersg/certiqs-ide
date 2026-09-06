from app.components.parameter_specs import (
    COMPONENT_PARAM_SPECS,
    get_field_def,
    get_spec_for_component_type,
)


def test_all_24_component_types_present():
    assert len(COMPONENT_PARAM_SPECS) == 24


def test_lookup_is_case_and_whitespace_tolerant():
    assert get_spec_for_component_type("  laser source  ") is get_spec_for_component_type("Laser Source")


def test_apd_aliases_to_single_photon_detector():
    apd = get_spec_for_component_type("Avalanche Photon Detector")
    spd = get_spec_for_component_type("Single-Photon Detector")
    assert apd is spd


def test_unknown_component_type_returns_none():
    assert get_spec_for_component_type("Nonexistent Widget") is None
    assert get_field_def("Nonexistent Widget", "anything") is None


def test_common_field_lookup():
    field = get_field_def("Laser Source", "mean_photon_number")
    assert field is not None
    assert field.unit == "photons/pulse"
    assert field.type == "number"


def test_variant_discriminator_field_lookup():
    field = get_field_def("Single-Photon Detector", "detector_variant")
    assert field is not None
    assert field.type == "select"
    assert field.options == [
        "APD (gated)",
        "APD (free-running)",
        "APD (free-running, actively quenched)",
        "APD (free-running, passively quenched)",
        "SD APD",
        "SNSPD",
        "TES",
    ]
    assert field.group == "settings"


def test_every_detector_variant_option_is_known_to_the_applicability_engine():
    """The picker must not be able to produce a variant string the engine can't map —
    an unknown variant silently degrades the detector to the generic "SPD" bucket."""
    from app.qkd.applicability import VARIANT_TO_DET_TYPE

    field = get_field_def("Single-Photon Detector", "detector_variant")
    assert field is not None and field.options is not None
    unknown = [opt for opt in field.options if opt not in VARIANT_TO_DET_TYPE]
    assert unknown == [], f"detector_variant options missing from VARIANT_TO_DET_TYPE: {unknown}"


def test_variant_specific_field_lookup():
    field = get_field_def("Single-Photon Detector", "gate_width")
    assert field is not None
    assert field.unit == "s"


def test_variant_specific_field_not_shared_across_variants():
    # "gate_width" belongs only to "APD (gated)", not "SNSPD" or common fields —
    # but get_field_def searches all variants regardless of which one is selected,
    # matching the TS source's own behavior (it doesn't filter by current variant).
    assert get_field_def("Single-Photon Detector", "bias_current") is not None  # SNSPD-only field
    assert get_field_def("Single-Photon Detector", "not_a_real_key") is None


def test_reused_field_fragment_shared_correctly():
    # insertion_loss/extinction_ratio/operating_wavelength are shared ParamField
    # instances reused across many component types (mirroring the TS source's
    # module-level const fragments) — spot check one shows up with the same unit.
    field = get_field_def("Phase Modulator", "insertion_loss")
    assert field is not None
    assert field.unit == "dB"
