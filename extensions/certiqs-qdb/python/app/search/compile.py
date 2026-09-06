"""The advanced-search query compiler (formerly a line-by-line port of
src/lib/search/compileSearchQuery.ts, which has since been retired — this is
now the sole implementation).

Compiles a ConditionGroup tree into a SQLAlchemy Core where-expression and
runs the resulting query for a given search domain. Each EXISTS condition is
compiled independently (not merged into shared joins), which is what makes
arbitrary nesting composable — see wrap_exists().

Two deliberate departures from the TS source, both behavior-preserving:
- Date leaves use SQLAlchemy's typed `cast(..., Date)` + `timedelta` arithmetic
  instead of raw ::date/interval SQL text — same day-boundary semantics,
  without embedding a column's SQL text inside a string.
- Array literals use `postgresql.array(values, type_=...)` instead of a
  sql.raw()'d type suffix — SQLAlchemy binds every element as a real
  parameter, so there's no analog to the TS version's "pgType must come from
  a closed enum" invariant to preserve here; the injection risk doesn't arise.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    Date,
    Integer,
    Table,
    Text,
    and_,
    asc,
    cast,
    exists,
    false,
    func,
    literal,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, array as pg_array
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.schema.attacks import attack_categories, attacks, vulnerabilities
from app.schema.countermeasures import countermeasures, vulnerability_countermeasures
from app.schema.evaluation_activities import ea_parameters, evaluation_activities
from app.schema.joins import ea_covers_attack
from app.schema.systems import protocol_families, protocols, system_protocols, systems
from app.search.field_registry import ExistsFamily, FieldDef, get_field_def
from app.search.types import (
    MAX_CONDITIONS,
    MAX_DEPTH,
    Condition,
    ConditionGroup,
    ConditionValue,
    Operator,
    SearchDomain,
    count_leaves,
    get_depth,
)


class SearchValidationError(Exception):
    pass


class SearchAuthError(Exception):
    pass


def validate_tree(tree: ConditionGroup) -> None:
    leaf_count = count_leaves(tree)
    if leaf_count == 0:
        raise SearchValidationError("At least one condition is required")
    if leaf_count > MAX_CONDITIONS:
        raise SearchValidationError(f"Too many conditions (max {MAX_CONDITIONS})")
    if get_depth(tree) > MAX_DEPTH:
        raise SearchValidationError(f"Too deeply nested (max {MAX_DEPTH} levels)")


DOMAIN_KEY_COLUMN: dict[SearchDomain, ColumnElement] = {
    "attacks": vulnerabilities.c.id,
    "systems": systems.c.id,
    "evaluation_activities": evaluation_activities.c.code,
    "countermeasures": countermeasures.c.id,
}

_LIKE_ESCAPE_RE = re.compile(r"([\\%_])")
_REGEX_ESCAPE_RE = re.compile(r"([.*+?^${}()|\[\]\\])")


def _escape_like_pattern(text: str) -> str:
    return _LIKE_ESCAPE_RE.sub(r"\\\1", text)


def _csv_token_match(col: ColumnElement, token: str) -> ColumnElement:
    escaped = _REGEX_ESCAPE_RE.sub(r"\\\1", token)
    pattern = rf"(^|,)\s*{escaped}\s*(,|$)"
    return col.op("~*")(pattern)


def _compile_text_leaf(col: ColumnElement, operator: Operator, value: ConditionValue) -> ColumnElement:
    text = _escape_like_pattern(value.text or "")
    if operator == "contains":
        return col.ilike(f"%{text}%")
    if operator == "starts_with":
        return col.ilike(f"{text}%")
    if operator == "equals":
        return col.ilike(text)
    if operator == "not_contains":
        return or_(col.is_(None), not_(col.ilike(f"%{text}%")))
    return true()


def _compile_enum_leaf(col: ColumnElement, field: FieldDef, operator: Operator, value: ConditionValue) -> ColumnElement:
    values = value.values or []

    if field.csv_multi_value:
        if operator == "is_any_of":
            if not values:
                return false()
            return or_(*[_csv_token_match(col, v) for v in values])
        if operator == "is_none_of":
            if not values:
                return true()
            return or_(col.is_(None), not_(or_(*[_csv_token_match(col, v) for v in values])))
        return true()

    if operator == "is_any_of":
        if not values:
            return false()
        return col.in_(values)
    if operator == "is_none_of":
        if not values:
            return true()
        return or_(col.is_(None), not_(col.in_(values)))
    return true()


def _compile_number_leaf(col: ColumnElement, operator: Operator, value: ConditionValue) -> ColumnElement:
    if operator == "equals":
        return col == value.number
    if operator == "gt":
        return col > value.number
    if operator == "gte":
        return col >= value.number
    if operator == "lt":
        return col < value.number
    if operator == "lte":
        return col <= value.number
    if operator == "between":
        lo, hi = value.number_range or (0, 0)
        return col.between(lo, hi)
    return true()


# systems.created_at is timestamptz — day-boundary semantics are made explicit
# rather than relying on the time-of-day component of the stored value.
#
# value.date/date_range arrive as "yyyy-mm-dd" strings (per ConditionValue's
# contract) but SQLAlchemy's Date type needs an actual `date` object to bind
# correctly (asyncpg won't coerce a plain str for a date-typed parameter) —
# parse before casting.
def _compile_date_leaf(col: ColumnElement, operator: Operator, value: ConditionValue) -> ColumnElement:
    if operator == "on":
        return cast(col, Date) == date.fromisoformat(value.date)
    if operator == "before":
        return col < date.fromisoformat(value.date)
    if operator == "after":
        return col >= (date.fromisoformat(value.date) + timedelta(days=1))
    if operator == "date_between":
        d1, d2 = value.date_range or ("", "")
        return and_(col >= date.fromisoformat(d1), col < (date.fromisoformat(d2) + timedelta(days=1)))
    return true()


def _compile_boolean_leaf(col: ColumnElement, operator: Operator) -> ColumnElement:
    if operator == "is_true":
        return col.is_(True)
    if operator == "is_false":
        return col.is_(False)
    return true()


def _array_literal(values: list[Any], pg_type: str) -> ColumnElement:
    element_type = Integer if pg_type == "integer" else Text
    # Explicit cast (not just type_=, which only informs param binding) so the
    # generated SQL is unambiguous about the array's element type, mirroring
    # the TS source's explicit `::type[]` suffix — matching intent, not the
    # sql.raw() mechanism, which SQLAlchemy's typed array() makes unnecessary.
    return cast(pg_array(values, type_=element_type), ARRAY(element_type))


def _compile_array_leaf(col: ColumnElement, field: FieldDef, operator: Operator, value: ConditionValue) -> ColumnElement:
    raw = value.values or []
    pg_type = field.pg_array_type or "text"

    if operator == "array_contains_any":
        if not raw:
            return false()
        values = [int(v) for v in raw] if pg_type == "integer" else raw
        return col.op("&&")(_array_literal(values, pg_type))
    if operator == "array_contains_all":
        if not raw:
            return true()
        values = [int(v) for v in raw] if pg_type == "integer" else raw
        return col.op("@>")(_array_literal(values, pg_type))
    if operator == "array_contains_none":
        if not raw:
            return true()
        values = [int(v) for v in raw] if pg_type == "integer" else raw
        return or_(col.is_(None), not_(col.op("&&")(_array_literal(values, pg_type))))
    return true()


def _array_is_empty(col: ColumnElement) -> ColumnElement:
    return or_(col.is_(None), func.cardinality(col) == 0)


def _array_is_not_empty(col: ColumnElement) -> ColumnElement:
    return and_(col.is_not(None), func.cardinality(col) > 0)


def compile_leaf(field: FieldDef, condition: Condition) -> ColumnElement:
    col = field.column
    operator, value = condition.operator, condition.value

    if operator == "is_empty":
        return _array_is_empty(col) if field.type == "array" else col.is_(None)
    if operator == "is_not_empty":
        return _array_is_not_empty(col) if field.type == "array" else col.is_not(None)

    if field.type == "text":
        return _compile_text_leaf(col, operator, value)
    if field.type == "enum":
        return _compile_enum_leaf(col, field, operator, value)
    if field.type == "number":
        return _compile_number_leaf(col, operator, value)
    if field.type == "date":
        return _compile_date_leaf(col, operator, value)
    if field.type == "boolean":
        return _compile_boolean_leaf(col, operator)
    if field.type == "array":
        return _compile_array_leaf(col, field, operator, value)
    return true()


# Each family's join chain is fixed and domain-specific (one family is only ever
# used from one domain's field list), so no aliasing is needed: none of these
# chains reuse a table name already present in any domain's own base query.
def wrap_exists(family: ExistsFamily, key_column: ColumnElement, predicate: ColumnElement) -> ColumnElement:
    if family == "ea_coverage":
        stmt = (
            select(literal(1))
            .select_from(ea_covers_attack)
            .join(evaluation_activities, evaluation_activities.c.code == ea_covers_attack.c.evaluation_activity_id)
            .join(ea_parameters, ea_parameters.c.ea_code == evaluation_activities.c.code, isouter=True)
            .where(and_(ea_covers_attack.c.attack_vulnerability_id == key_column, predicate))
        )
        return exists(stmt)
    if family == "countermeasure_coverage":
        stmt = (
            select(literal(1))
            .select_from(vulnerability_countermeasures)
            .join(countermeasures, countermeasures.c.id == vulnerability_countermeasures.c.countermeasure_id)
            .where(and_(vulnerability_countermeasures.c.vulnerability_id == key_column, predicate))
        )
        return exists(stmt)
    if family == "protocol":
        stmt = (
            select(literal(1))
            .select_from(system_protocols)
            .join(protocols, protocols.c.id == system_protocols.c.protocol_id)
            .join(protocol_families, protocol_families.c.id == protocols.c.protocol_family_id)
            .where(and_(system_protocols.c.system_id == key_column, predicate))
        )
        return exists(stmt)
    if family == "parameters":
        stmt = (
            select(literal(1))
            .select_from(ea_parameters)
            .where(and_(ea_parameters.c.ea_code == key_column, predicate))
        )
        return exists(stmt)
    if family == "covers_attack":
        stmt = (
            select(literal(1))
            .select_from(ea_covers_attack)
            .join(attacks, attacks.c.vulnerability_id == ea_covers_attack.c.attack_vulnerability_id)
            .join(vulnerabilities, vulnerabilities.c.id == attacks.c.vulnerability_id)
            .join(attack_categories, attack_categories.c.id == attacks.c.attack_category_id, isouter=True)
            .where(and_(ea_covers_attack.c.evaluation_activity_id == key_column, predicate))
        )
        return exists(stmt)
    if family == "vulnerability_coverage":
        stmt = (
            select(literal(1))
            .select_from(vulnerability_countermeasures)
            .join(vulnerabilities, vulnerabilities.c.id == vulnerability_countermeasures.c.vulnerability_id)
            .join(attacks, attacks.c.vulnerability_id == vulnerabilities.c.id, isouter=True)
            .where(and_(vulnerability_countermeasures.c.countermeasure_id == key_column, predicate))
        )
        return exists(stmt)
    raise AssertionError(f"unhandled ExistsFamily: {family}")


# Minimal count source per family: just the join table itself, filtered by its
# correlation column — no join to any *other* table. Every one of these join
# tables has a composite primary key of (correlation_column, counted_entity),
# so a bare COUNT(*) is already an exact, non-inflated count with no DISTINCT
# needed. Deliberately does NOT reuse wrap_exists's chains above: those exist
# so its *predicate* can filter on other tables' columns (e.g. ea_coverage's
# LEFT JOIN to ea_parameters, which is not unique per EA) — a columnless COUNT
# has no use for those joins, and reusing them would silently overcount (e.g.
# an attack covered by one EA with 3 parameter rows would count as 3, not 1).
_AGGREGATE_COUNT_SOURCE: dict[ExistsFamily, tuple[Table, ColumnElement]] = {
    "ea_coverage": (ea_covers_attack, ea_covers_attack.c.attack_vulnerability_id),
    "countermeasure_coverage": (vulnerability_countermeasures, vulnerability_countermeasures.c.vulnerability_id),
    "protocol": (system_protocols, system_protocols.c.system_id),
    "parameters": (ea_parameters, ea_parameters.c.ea_code),
    "covers_attack": (ea_covers_attack, ea_covers_attack.c.evaluation_activity_id),
    "vulnerability_coverage": (vulnerability_countermeasures, vulnerability_countermeasures.c.countermeasure_id),
}


def wrap_aggregate_count(family: ExistsFamily, key_column: ColumnElement) -> ColumnElement:
    if family not in _AGGREGATE_COUNT_SOURCE:
        raise AssertionError(f"unhandled ExistsFamily for aggregate count: {family}")
    table, correlation_column = _AGGREGATE_COUNT_SOURCE[family]
    return select(func.count()).select_from(table).where(correlation_column == key_column).scalar_subquery()


def compile_node(node: Condition | ConditionGroup, domain: SearchDomain) -> ColumnElement:
    if node.kind == "group":
        compiled = [compile_node(c, domain) for c in node.children]
        if not compiled:
            return true() if node.combinator == "AND" else false()
        return and_(*compiled) if node.combinator == "AND" else or_(*compiled)

    field = get_field_def(domain, node.field)
    if field is None:
        return true()  # unknown/stale field key (e.g. old bookmarked URL) — ignore, don't fail the whole query

    # Must be routed before compile_leaf: an aggregate field has column=None,
    # so compile_leaf's unconditional `col = field.column` would crash on any
    # operator (not just the universal is_empty/is_not_empty), since Operator
    # is one flat, type-unpartitioned Literal — nothing stops a stale/crafted
    # request from sending an incompatible operator against this field.
    if field.resolution == "aggregate":
        count_subquery = wrap_aggregate_count(field.family, DOMAIN_KEY_COLUMN[domain])
        return _compile_number_leaf(count_subquery, node.operator, node.value)

    predicate = compile_leaf(field, node)
    if field.resolution == "direct":
        return predicate
    return wrap_exists(field.family, DOMAIN_KEY_COLUMN[domain], predicate)


class SearchOptions:
    __slots__ = ("user_id", "limit", "offset")

    def __init__(self, user_id: str | None, limit: int, offset: int) -> None:
        self.user_id = user_id
        self.limit = limit
        self.offset = offset


class SearchResult:
    __slots__ = ("rows", "has_more")

    def __init__(self, rows: list[dict], has_more: bool) -> None:
        self.rows = rows
        self.has_more = has_more


def _row_to_dict(row: Row, keys: list[str]) -> dict:
    return dict(zip(keys, row, strict=True))


async def run_search(
    session: AsyncSession,
    domain: SearchDomain,
    tree: ConditionGroup,
    opts: SearchOptions,
) -> SearchResult:
    validate_tree(tree)
    tree_sql = compile_node(tree, domain)
    fetch_limit = opts.limit + 1

    if domain == "attacks":
        keys = ["id", "name", "shortDescription", "attackType", "targets", "attackRating", "module", "component", "attackCategory"]
        stmt = (
            select(
                vulnerabilities.c.id,
                vulnerabilities.c.name,
                vulnerabilities.c.short_description,
                attacks.c.attack_type,
                attacks.c.targets,
                attacks.c.attack_rating,
                attacks.c.module,
                attacks.c.component,
                attack_categories.c.name,
            )
            .select_from(vulnerabilities)
            .join(attacks, attacks.c.vulnerability_id == vulnerabilities.c.id, isouter=True)
            .join(attack_categories, attack_categories.c.id == attacks.c.attack_category_id, isouter=True)
            .where(tree_sql)
            .order_by(asc(vulnerabilities.c.id))
            .limit(fetch_limit)
            .offset(opts.offset)
        )
    elif domain == "systems":
        if not opts.user_id:
            raise SearchAuthError("Sign in to search systems")
        visibility_guard = or_(systems.c.user_id == opts.user_id, systems.c.is_public.is_(True))
        keys = ["id", "name", "manufacturer", "toeBoundary", "createdAt", "isPublic"]
        stmt = (
            select(
                systems.c.id,
                systems.c.name,
                systems.c.manufacturer,
                systems.c.toe_boundary,
                systems.c.created_at,
                systems.c.is_public,
            )
            .select_from(systems)
            .where(and_(tree_sql, visibility_guard))
            .order_by(asc(systems.c.id))
            .limit(fetch_limit)
            .offset(opts.offset)
        )
    elif domain == "evaluation_activities":
        keys = ["code", "name", "description", "subclause", "isIsoMandated"]
        stmt = (
            select(
                evaluation_activities.c.code,
                evaluation_activities.c.name,
                evaluation_activities.c.description,
                evaluation_activities.c.subclause,
                evaluation_activities.c.is_iso_mandated,
            )
            .select_from(evaluation_activities)
            .where(tree_sql)
            .order_by(asc(evaluation_activities.c.code))
            .limit(fetch_limit)
            .offset(opts.offset)
        )
    elif domain == "countermeasures":
        keys = ["id", "name", "description", "countermeasureType", "module"]
        stmt = (
            select(
                countermeasures.c.id,
                countermeasures.c.name,
                countermeasures.c.description,
                countermeasures.c.countermeasure_type,
                countermeasures.c.module,
            )
            .select_from(countermeasures)
            .where(tree_sql)
            .order_by(asc(countermeasures.c.id))
            .limit(fetch_limit)
            .offset(opts.offset)
        )
    else:
        raise AssertionError(f"unhandled SearchDomain: {domain}")

    result = await session.execute(stmt)
    rows = [_row_to_dict(row, keys) for row in result.all()]

    has_more = len(rows) > opts.limit
    return SearchResult(rows=rows[: opts.limit] if has_more else rows, has_more=has_more)
