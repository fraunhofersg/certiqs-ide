"""Offline unit tests for the NEON_HTTP_FALLBACK shim (app/db_http.py) — the
statement->$n compilation, outbound param encoding, and OID-typed result
decoding. No network / no DB: these exercise the pure conversion layer that the
HTTP session relies on. The live round-trip is covered by running the parity
suites with NEON_HTTP_FALLBACK=1 (see CLAUDE.md)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, asc, column, select, table, text

from app.db_http import (
    HttpResult,
    _decode_value,
    _parse_array_literal,
    compile_statement,
    encode_param,
    http_endpoint,
)


# ── endpoint derivation ──────────────────────────────────────────────────────


def test_http_endpoint_swaps_first_label_for_api():
    url = "postgresql://u:p@ep-lingering-truth-x.c-2.ap-southeast-1.aws.neon.tech/db?sslmode=require"
    assert http_endpoint(url) == "https://api.c-2.ap-southeast-1.aws.neon.tech/sql"


# ── statement -> $n SQL + positional params ─────────────────────────────────


def test_compile_text_named_binds():
    sql, params = compile_statement(
        text("SELECT id FROM systems WHERE user_id = :uid OR is_public = :pub"),
        {"uid": "u1", "pub": True},
    )
    assert "$1" in sql and "$2" in sql
    assert params == ["u1", "true"]  # bool -> "true", raw-text mode


def test_compile_text_any_list_bind_encodes_pg_array():
    sql, params = compile_statement(
        text("SELECT id FROM module_components WHERE module_id = ANY(:mids)"),
        {"mids": [1, 2, 3]},
    )
    assert "ANY($1)" in sql
    assert params == ["{1,2,3}"]  # list -> Postgres array literal


def test_compile_core_select_with_in_and_literals():
    t = table("systems", column("id"), column("user_id"))
    stmt = (
        select(t.c.id)
        .where(and_(t.c.user_id == "u1", t.c.id.in_([5, 6, 7])))
        .order_by(asc(t.c.id))
        .limit(11)
        .offset(0)
    )
    sql, params = compile_statement(stmt, None)
    assert sql.count("$") == 6  # user_id, limit, offset, + 3 expanded IN binds
    # positional order matches $1..$6: user_id, limit, offset, then IN elements
    assert params == ["u1", "11", "0", "5", "6", "7"]


# ── outbound param encoding ─────────────────────────────────────────────────


def test_encode_param_scalars():
    assert encode_param(None) is None
    assert encode_param(True) == "true"
    assert encode_param(False) == "false"
    assert encode_param(42) == "42"
    assert encode_param(Decimal("1.50")) == "1.50"
    assert encode_param("hi") == "hi"


def test_encode_param_array_and_json():
    assert encode_param([1, 2, 3]) == "{1,2,3}"
    assert encode_param(["a", "b"]) == '{"a","b"}'
    assert encode_param({"k": 1}) == '{"k": 1}'


# ── inbound OID-typed decoding ──────────────────────────────────────────────


def test_decode_scalars_by_oid():
    assert _decode_value("58", 23) == 58          # int4
    assert _decode_value("9007199254740993", 20) == 9007199254740993  # int8
    assert _decode_value("t", 16) is True         # bool
    assert _decode_value("f", 16) is False
    assert _decode_value("1.5", 701) == 1.5       # float8
    assert _decode_value("2.50", 1700) == Decimal("2.50")  # numeric
    assert _decode_value("hello", 25) == "hello"  # text
    assert _decode_value(None, 23) is None


def test_decode_temporal_by_oid():
    assert _decode_value("2026-07-20", 1082) == date(2026, 7, 20)
    assert _decode_value("2026-07-20 10:46:18", 1114) == datetime(2026, 7, 20, 10, 46, 18)


def test_decode_arrays():
    assert _decode_value("{1,2,3}", 1007) == [1, 2, 3]        # int4[]
    assert _decode_value("{DV,CV}", 1009) == ["DV", "CV"]     # text[]
    assert _decode_value("{}", 1007) == []                    # empty


def test_parse_array_literal_quoted_and_null():
    assert _parse_array_literal('{"a,b","c"}', 25) == ["a,b", "c"]
    assert _parse_array_literal("{1,NULL,3}", 23) == [1, None, 3]


# ── result proxy surface ────────────────────────────────────────────────────


def test_http_result_surface():
    r = HttpResult(["id", "name"], [(1, "a"), (2, "b")])
    assert r.mappings().all() == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert r.mappings().first() == {"id": 1, "name": "a"}
    assert r.all() == [(1, "a"), (2, "b")]
    assert r.keys() == ["id", "name"]

    one = HttpResult(["n"], [(58,)])
    assert one.scalar_one() == 58
    assert one.scalar() == 58
    assert HttpResult(["n"], []).scalar_one_or_none() is None
