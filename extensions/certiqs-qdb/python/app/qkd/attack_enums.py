"""Port of ../../../src/lib/qkd/attackEnums.ts's validation helpers — keep in
sync line-by-line. The enum value tuples themselves already live in
app/search/enums.py (ported for the field registry) and are reused here
rather than duplicated.
"""

from __future__ import annotations

from app.search.enums import (
    ATTACK_RATINGS,
    ATTACK_TYPES,
    EQUIPMENT_OPTIONS,
    EXPERTISE_OPTIONS,
    FEASIBILITY_OPTIONS,
    MODULES,
    OPPORTUNITY_OPTIONS,
)


def parse_module_field(value: object) -> tuple[list[str] | None, str | None]:
    """`attacks.module` is a plain text column: a single canonical value, or several
    joined with ", " (e.g. "Transmitter, Receiver"). Splits and validates each token."""
    if value is None or value == "":
        return None, None
    if not isinstance(value, str):
        return None, "module must be a string"
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    invalid = [t for t in tokens if t not in MODULES]
    if invalid:
        return None, f"Invalid module value(s): {', '.join(invalid)}. Must be one of: {', '.join(MODULES)}"
    return tokens, None


def _validate_enum(value: object, allowed: tuple[str, ...], field_name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in allowed:
        return f"Invalid {field_name} value: {value}. Must be one of: {', '.join(allowed)}"
    return None


def validate_attack_fields(attack: dict) -> str | None:
    """Validates the fixed-enum attack fields; returns the first error message found, or None."""
    _tokens, module_error = parse_module_field(attack.get("module"))
    return (
        module_error
        or _validate_enum(attack.get("attack_type"), ATTACK_TYPES, "attack_type")
        or _validate_enum(attack.get("feasibility"), FEASIBILITY_OPTIONS, "feasibility")
        or _validate_enum(attack.get("expertise"), EXPERTISE_OPTIONS, "expertise")
        or _validate_enum(attack.get("opportunity"), OPPORTUNITY_OPTIONS, "opportunity")
        or _validate_enum(attack.get("equipment"), EQUIPMENT_OPTIONS, "equipment")
        or _validate_enum(attack.get("attack_rating"), ATTACK_RATINGS, "attack_rating")
        or None
    )
