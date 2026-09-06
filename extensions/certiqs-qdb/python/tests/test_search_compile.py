"""Offline structural tests for app/search/compile.py — no DB connection needed.

SQLAlchemy can render a compiled statement to literal SQL text without ever
opening a connection (`compile(dialect=..., compile_kwargs={"literal_binds": True})`),
which is what lets these tests check the compiler produces syntactically
sound, semantically plausible SQL for every field type/operator/family
combination without live Neon access. This is a structural smoke test, not a
substitute for Phase 2.5's live-DB parity harness (comparing actual returned
row ID sets against the real TS engine) — see fixtures/search_cases.json.
"""

import pytest
from sqlalchemy.dialects import postgresql

from app.search.compile import (
    SearchValidationError,
    _escape_like_pattern,
    compile_node,
    validate_tree,
    wrap_exists,
)
from app.search.field_registry import get_field_def
from app.search.types import Condition, ConditionGroup, ConditionValue


def render(expr) -> str:
    return str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def cond(field: str, operator: str, **value_kwargs) -> Condition:
    return Condition(id="c1", field=field, operator=operator, value=ConditionValue(**value_kwargs))


def group(combinator: str, *children) -> ConditionGroup:
    return ConditionGroup(id="g1", combinator=combinator, children=list(children))


# ── validate_tree ─────────────────────────────────────────────────────────────


def test_validate_tree_rejects_empty():
    with pytest.raises(SearchValidationError):
        validate_tree(group("AND"))


def test_validate_tree_rejects_too_many_conditions():
    tree = group("AND", *[cond("vuln_name", "contains", text="x") for _ in range(26)])
    with pytest.raises(SearchValidationError):
        validate_tree(tree)


def test_validate_tree_rejects_too_deep():
    # MAX_DEPTH=5 is inclusive (depth==5 is valid) — 6 wraps is the first
    # depth that must be rejected.
    tree = cond("vuln_name", "contains", text="x")
    for _ in range(6):
        tree = group("AND", tree)
    with pytest.raises(SearchValidationError):
        validate_tree(tree)


def test_validate_tree_accepts_valid_tree():
    validate_tree(group("AND", cond("vuln_name", "contains", text="x")))


# ── compile_node: structure ───────────────────────────────────────────────────


def test_unknown_field_key_compiles_to_true():
    node = cond("this_field_does_not_exist", "contains", text="x")
    sql = render(compile_node(node, "attacks"))
    assert sql == "true"


def test_empty_group_and_is_true_or_is_false():
    assert render(compile_node(group("AND"), "attacks")) == "true"
    assert render(compile_node(group("OR"), "attacks")) == "false"


def test_and_group_combines_with_and_keyword():
    tree = group("AND", cond("vuln_name", "contains", text="a"), cond("vuln_description", "contains", text="b"))
    sql = render(compile_node(tree, "attacks"))
    assert " AND " in sql
    assert "vulnerabilities.name" in sql
    assert "vulnerabilities.short_description" in sql


def test_or_group_combines_with_or_keyword():
    tree = group("OR", cond("vuln_name", "contains", text="a"), cond("vuln_description", "contains", text="b"))
    sql = render(compile_node(tree, "attacks"))
    assert " OR " in sql


def test_nested_group_composes():
    inner = group("OR", cond("vuln_name", "contains", text="a"), cond("vuln_name", "contains", text="b"))
    outer = group("AND", inner, cond("attack_rating", "is_any_of", values=["High"]))
    sql = render(compile_node(outer, "attacks"))
    assert sql.count("ILIKE") == 2
    assert "attack_rating" in sql or "attacks.attack_rating" in sql


# ── Text leaves ────────────────────────────────────────────────────────────────


def test_text_contains_uses_ilike_wildcards():
    sql = render(compile_node(cond("vuln_name", "contains", text="laser"), "attacks"))
    assert "ILIKE" in sql and "%laser%" in sql


def test_text_starts_with():
    sql = render(compile_node(cond("vuln_name", "starts_with", text="laser"), "attacks"))
    assert "ILIKE" in sql and "laser" in sql


def test_text_not_contains_includes_null_fallback():
    sql = render(compile_node(cond("vuln_description", "not_contains", text="x"), "attacks"))
    assert "IS NULL" in sql
    assert "NOT" in sql


def test_escape_like_pattern_escapes_percent_underscore_backslash():
    # Tested directly (not via rendered SQL) since SQLAlchemy's literal_binds
    # compile mode doubles literal "%" for its own display purposes, which
    # would make a substring assertion on rendered SQL misleading either way.
    assert _escape_like_pattern("100%_free") == r"100\%\_free"
    assert _escape_like_pattern(r"back\slash") == r"back\\slash"


# ── Enum leaves (incl. csv_multi_value) ────────────────────────────────────────


def test_enum_is_any_of_uses_in_clause():
    sql = render(compile_node(cond("attack_rating", "is_any_of", values=["High", "Beyond High"]), "attacks"))
    assert "IN" in sql
    assert "High" in sql and "Beyond High" in sql


def test_enum_is_any_of_empty_values_is_false():
    sql = render(compile_node(cond("attack_rating", "is_any_of", values=[]), "attacks"))
    assert sql == "false"


def test_enum_is_none_of_empty_values_is_true():
    sql = render(compile_node(cond("attack_rating", "is_none_of", values=[]), "attacks"))
    assert sql == "true"


def test_csv_multi_value_field_uses_regex_match_not_in_clause():
    field = get_field_def("attacks", "attack_module")
    assert field.csv_multi_value is True
    sql = render(compile_node(cond("attack_module", "is_any_of", values=["Transmitter"]), "attacks"))
    assert "~*" in sql
    assert "IN (" not in sql


def test_non_csv_enum_field_uses_plain_in_clause():
    field = get_field_def("attacks", "attack_rating")
    assert field.csv_multi_value is False
    sql = render(compile_node(cond("attack_rating", "is_any_of", values=["High"]), "attacks"))
    assert "~*" not in sql


# ── Number leaves ──────────────────────────────────────────────────────────────


def test_number_between():
    sql = render(compile_node(cond("sys_protocol_count", "between", number_range=(0.1, 0.9)), "systems"))
    assert "BETWEEN" in sql
    assert "0.1" in sql and "0.9" in sql


def test_number_gte():
    sql = render(compile_node(cond("sys_protocol_count", "gte", number=0.5), "systems"))
    assert ">=" in sql


def test_number_equals():
    # Previously a gap: "equals" is a valid Operator literal but had no branch
    # in _compile_number_leaf, so it silently compiled to `true()` (matched
    # every row) for any number field. This is the fix, verified on an
    # aggregate number field — the only "number"-typed fields left in the
    # registry route through the same _compile_number_leaf regardless.
    sql = render(compile_node(cond("sys_protocol_count", "equals", number=0.5), "systems"))
    assert "= 0.5" in sql


# ── Date leaves (day-boundary semantics) ───────────────────────────────────────


def test_date_on_casts_both_sides_to_date():
    sql = render(compile_node(cond("sys_created_at", "on", date="2026-01-15"), "systems"))
    assert "DATE" in sql.upper()
    assert "2026-01-15" in sql


def test_date_after_adds_one_day_interval():
    sql = render(compile_node(cond("sys_created_at", "after", date="2026-01-15"), "systems"))
    assert ">=" in sql
    # A one-day interval must appear in some form (SQLAlchemy renders timedelta as INTERVAL).
    assert "1" in sql


def test_date_between_is_half_open_range():
    sql = render(compile_node(cond("sys_created_at", "date_between", date_range=("2026-01-01", "2026-01-31")), "systems"))
    assert ">=" in sql and "<" in sql
    assert "2026-01-01" in sql
    # Exclusive upper bound is the day *after* the end date (half-open range).
    assert "2026-02-01" in sql


# ── Boolean leaves ─────────────────────────────────────────────────────────────


def test_boolean_is_true():
    sql = render(compile_node(cond("sys_is_public", "is_true"), "systems"))
    assert "true" in sql.lower()


# ── Array leaves ───────────────────────────────────────────────────────────────


def test_array_contains_any_uses_overlap_operator():
    sql = render(compile_node(cond("cm_component_types", "array_contains_any", values=["1", "2"]), "countermeasures"))
    assert "&&" in sql
    assert "ARRAY" in sql
    assert "integer" in sql.lower()


def test_array_contains_all_uses_contains_operator():
    sql = render(compile_node(cond("cm_component_types", "array_contains_all", values=["1"]), "countermeasures"))
    assert "@>" in sql


def test_array_contains_none_empty_values_is_true():
    sql = render(compile_node(cond("cm_component_types", "array_contains_none", values=[]), "countermeasures"))
    assert sql == "true"


def test_array_pg_type_defaults_to_text_when_unset():
    field = get_field_def("countermeasures", "cm_covers_defense_effectiveness")
    assert field.pg_array_type is None
    sql = render(compile_node(cond("cm_covers_defense_effectiveness", "array_contains_any", values=["Full"]), "countermeasures"))
    assert "text" in sql.lower()


def test_is_empty_on_array_field_checks_cardinality():
    sql = render(compile_node(cond("cm_component_types", "is_empty"), "countermeasures"))
    assert "cardinality" in sql.lower()


def test_is_empty_on_scalar_field_is_plain_null_check():
    sql = render(compile_node(cond("vuln_description", "is_empty"), "attacks"))
    assert "IS NULL" in sql
    assert "cardinality" not in sql.lower()


# ── wrap_exists: all 6 families ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("domain", "field_key", "expected_tables"),
    [
        ("attacks", "ea_code", ["ea_covers_attack", "evaluation_activities", "ea_parameters"]),
        ("attacks", "cm_coverage_name", ["vulnerability_countermeasures", "countermeasures"]),
        ("systems", "sys_protocol_name", ["system_protocols", "protocols", "protocol_families"]),
        ("evaluation_activities", "ea_param_name", ["ea_parameters"]),
        ("evaluation_activities", "ea_covers_vuln_name", ["ea_covers_attack", "attacks", "vulnerabilities"]),
        ("countermeasures", "cm_covers_vuln_name", ["vulnerability_countermeasures", "vulnerabilities"]),
    ],
)
def test_exists_family_join_chain_references_expected_tables(domain, field_key, expected_tables):
    node = cond(field_key, "contains", text="x")
    sql = render(compile_node(node, domain))
    assert "EXISTS" in sql
    for table in expected_tables:
        assert table in sql, f"expected {table!r} in EXISTS subquery for {field_key}"


def test_exists_conditions_compile_independently_not_shared_joins():
    # Two EXISTS conditions ANDed together must each carry their own full join
    # chain — this is what makes arbitrary nesting composable (see wrap_exists docstring).
    tree = group(
        "AND",
        cond("ea_code", "contains", text="EA-1"),
        cond("cm_coverage_name", "contains", text="Isolator"),
    )
    sql = render(compile_node(tree, "attacks"))
    assert sql.count("EXISTS") == 2


# ── Aggregate (count) leaves: all 6 families ───────────────────────────────────
# wrap_aggregate_count deliberately does NOT reuse wrap_exists's join chains: a
# naive COUNT(*) over e.g. ea_coverage's chain (which LEFT JOINs ea_parameters,
# not unique per EA) would overcount any attack whose covering EA has more
# than one parameter row. The fix is a minimal single-table COUNT per family
# (every family's join table has a composite PK of (correlation, counted
# entity), so no DISTINCT is needed either) — these tests guard that a future
# refactor can't silently reintroduce that fan-out.


@pytest.mark.parametrize(
    ("domain", "field_key", "expected_table"),
    [
        ("attacks", "ea_coverage_count", "ea_covers_attack"),
        ("attacks", "cm_coverage_count", "vulnerability_countermeasures"),
        ("systems", "sys_protocol_count", "system_protocols"),
        ("evaluation_activities", "ea_param_count", "ea_parameters"),
        ("evaluation_activities", "ea_covers_attack_count", "ea_covers_attack"),
        ("countermeasures", "cm_covers_vuln_count", "vulnerability_countermeasures"),
    ],
)
def test_aggregate_count_uses_minimal_single_table_no_extra_joins(domain, field_key, expected_table):
    sql = render(compile_node(cond(field_key, "gt", number=0), domain))
    assert "count(*)" in sql.lower()
    assert expected_table in sql
    assert "JOIN" not in sql.upper(), f"{field_key} should have no joins at all, got: {sql}"


def test_aggregate_count_equals_zero_expresses_no_coverage():
    sql = render(compile_node(cond("ea_coverage_count", "equals", number=0), "attacks"))
    assert "count(*)" in sql.lower()
    assert "= 0" in sql


def test_aggregate_count_between_works_like_a_plain_number_field():
    sql = render(compile_node(cond("ea_coverage_count", "between", number_range=(1, 3)), "attacks"))
    assert "BETWEEN" in sql
    assert "1" in sql and "3" in sql


def test_aggregate_count_composes_with_existing_conditions_in_nested_tree():
    tree = group(
        "AND",
        cond("ea_coverage_count", "between", number_range=(1, 3)),
        group("OR", cond("attack_rating", "is_any_of", values=["High"]), cond("vuln_name", "contains", text="laser")),
    )
    sql = render(compile_node(tree, "attacks"))
    assert " AND " in sql and " OR " in sql
    assert "BETWEEN" in sql
    assert "IN" in sql and "ILIKE" in sql


def test_aggregate_field_incompatible_operator_fails_open_not_crash():
    # Operator is a flat, type-unpartitioned Literal, so a stale/hand-crafted
    # request can send is_empty (or any operator _compile_number_leaf doesn't
    # recognize) against an aggregate field (column=None) — must fall through
    # to the codebase's established "true()" convention, not raise.
    sql = render(compile_node(cond("ea_coverage_count", "is_empty"), "attacks"))
    assert sql == "true"
