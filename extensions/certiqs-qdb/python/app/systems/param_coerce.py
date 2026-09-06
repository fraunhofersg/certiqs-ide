"""Port of the parameter-value coercion logic inlined identically in both
../../../src/app/api/qsecdb/systems/route.ts (POST) and
.../systems/[id]/route.ts (PATCH) — kept in sync line-by-line, extracted
once here since the two call sites are byte-identical in the TS source.

For spec fields (component_type + key matches parameter_specs.py), stamps the
canonical unit and coerces into the typed column dictated by the spec. For
free-form keys, keeps the original auto-detect behavior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.components.parameter_specs import get_field_def


@dataclass
class CoercedParam:
    value_text: str | None
    value_num: float | None
    value_bool: bool | None
    unit: str | None
    param_group: str


def _js_number(raw: str) -> float:
    """Mirrors JS `Number(str)` for realistic component-parameter value strings
    (plain decimal / scientific notation) — doesn't replicate JS's hex/octal/
    binary literal parsing (e.g. "0x1A"), which no real parameter value uses."""
    try:
        return float(raw.strip())
    except ValueError:
        return math.nan


def resolve_param_group(param_group_input: str | None) -> str:
    """The `param_group` value `coerce_parameter` will actually store.

    Callers that batch parameters into a single `INSERT ... ON CONFLICT` must
    de-dupe on THIS value, since it's half of the conflict target
    `(module_component_id, state, param_group, key)`. Note the null check is
    NOT a falsy check: an explicit empty-string group stays `""` and is a
    distinct row from `"parameters"`. De-duping with `or "parameters"` instead
    collapses the two and silently drops one of the rows.
    """
    return param_group_input if param_group_input is not None else "parameters"


def coerce_parameter(
    raw_value: str | None,
    unit_input: str | None,
    param_group_input: str | None,
    component_type_name: str | None,
    key: str,
) -> CoercedParam:
    raw = raw_value if raw_value is not None else ""
    field_def = get_field_def(component_type_name, key)

    value_num: float | None = None
    value_bool: bool | None = None
    value_text: str | None = None

    if field_def is not None and field_def.type == "number":
        n = _js_number(raw)
        value_num = n if raw != "" and not math.isnan(n) else None
    elif field_def is not None and field_def.type == "boolean":
        value_bool = True if raw == "true" else (False if raw == "false" else None)
    elif field_def is not None:
        value_text = raw if raw != "" else None
    else:
        n = _js_number(raw)
        num = n if raw != "" and not math.isnan(n) else None
        bool_ = True if raw == "true" else (False if raw == "false" else None)
        value_num = num
        value_bool = bool_
        value_text = raw if (num is None and bool_ is None) else None

    unit = field_def.unit if (field_def is not None and field_def.unit is not None) else (unit_input or None)
    param_group = resolve_param_group(param_group_input)

    return CoercedParam(value_text=value_text, value_num=value_num, value_bool=value_bool, unit=unit, param_group=param_group)
