"""Guards the faithfulness fix in export/routes.py: the prepare endpoint
serializes with exclude_none=True so absent optional ParamSpec fields
(unit/hardMin/hardMax/softMin/softMax) come out ABSENT, not null — because
the TS prompt modal makes `!== undefined` bound checks that a present-but-null
value would wrongly satisfy. See the comment in get_export_prepare.
"""

from app.export.orchestrator import MissingParamDTO, PrepareResult


def _dto(**overrides) -> MissingParamDTO:
    base = dict(
        location="instance:x.efficiency", label="x · efficiency", field="efficiency",
        type="number", typical=0.8, required=True, description="d", source="s",
    )
    base.update(overrides)
    return MissingParamDTO(**base)


def test_absent_optional_fields_are_omitted_not_null():
    # A spec with no unit/bounds (e.g. detection_efficiency has type but no unit).
    dumped = _dto().model_dump(by_alias=True, exclude_none=True)
    for absent in ("unit", "hardMin", "hardMax", "softMin", "softMax"):
        assert absent not in dumped, f"{absent} should be omitted when None, not present-as-null"


def test_present_optional_fields_are_kept_with_camel_alias():
    dumped = _dto(unit="Hz", hard_min=0.0, hard_max=1.0).model_dump(by_alias=True, exclude_none=True)
    assert dumped["unit"] == "Hz"
    assert dumped["hardMin"] == 0.0
    assert dumped["hardMax"] == 1.0
    assert "softMin" not in dumped  # still omitted


def test_required_and_typical_always_present():
    dumped = _dto().model_dump(by_alias=True, exclude_none=True)
    assert dumped["required"] is True
    assert dumped["typical"] == 0.8


def test_prepare_result_success_shape_is_camelcase():
    result = PrepareResult(found=True, system_name="Sys", manifest_name="sys_system", missing=[_dto()])
    dumped = result.model_dump(by_alias=True, exclude_none=True)
    assert dumped["found"] is True
    assert dumped["systemName"] == "Sys"
    assert dumped["manifestName"] == "sys_system"
    assert isinstance(dumped["missing"], list) and len(dumped["missing"]) == 1
    # nested DTO also excludes None
    assert "unit" not in dumped["missing"][0]
