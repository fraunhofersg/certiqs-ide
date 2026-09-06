"""HTTP-backed ``AsyncSession`` stand-in for when raw Postgres (TCP 5432) is
blocked on the current network but HTTPS (443) works — routes every
``session.execute()`` through Neon's "SQL over HTTPS" endpoint (``/sql``), the
same endpoint the frontend's ``@neondatabase/serverless`` driver uses, instead
of asyncpg.

Enabled by ``NEON_HTTP_FALLBACK=1`` (see ``app.core.config``). **DEV-ONLY.**

Why this is even possible: the backend's data layer is ~95% hand-written
``text()`` SQL with named ``:binds``; the only SQLAlchemy Core ``select()``
builder (``app.search.compile``) compiles to the same shape. Both are compiled
to ``$1``-style SQL + positional params via SQLAlchemy's asyncpg dialect
(``numeric_dollar`` paramstyle), so a single code path executes everything.

Scope / limitations:
- **Works:** all read paths (applicability, export, search, every GET) and
  single-statement writes (``delete_system``, ``set_system_visibility``). Each
  HTTP call auto-commits server-side.
- **Rejected:** multi-statement ``INSERT ... RETURNING``-then-reuse transactions
  (``create_system``, ``resync_system``, the ``create_*`` routes). Neon's
  one-shot ``/sql`` endpoint has no intra-batch round-trip, so it cannot provide
  the single-transaction atomicity those routes rely on. The *second* mutating
  statement in a session raises loudly (before it runs) rather than silently
  writing partial, non-atomic data. Verifying those paths needs a real 5432
  connection.

Production keeps the asyncpg engine in ``app.db`` (this flag defaults off).

Note: on a machine whose HTTPS is intercepted by antivirus (e.g. Norton's
TLS-scanning root), ``httpx`` needs to trust the OS cert store — that's what the
``pip-system-certs`` dev dependency provides (it auto-activates at interpreter
startup; no import needed here).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import asyncpg as _asyncpg
from sqlalchemy.sql.elements import ClauseElement

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Reused compiler target. asyncpg dialect renders `$1`-style positional params
# (paramstyle "numeric_dollar"), which is exactly what Neon's /sql endpoint
# expects — matching the @neondatabase/serverless driver's own wire format.
_DIALECT = _asyncpg.dialect()

_MUTATING = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE)\b", re.IGNORECASE)


def http_endpoint(database_url: str) -> str:
    """Derive Neon's HTTPS SQL endpoint from a libpq connection URL, mirroring
    the JS driver: swap the first hostname label for ``api.`` and append
    ``/sql`` (e.g. ``ep-x.c-2.aws.neon.tech`` -> ``api.c-2.aws.neon.tech/sql``)."""
    match = re.search(r"@([^/:]+)", database_url)
    if not match:
        raise ValueError("DATABASE_URL has no host component")
    host = match.group(1)
    api_host = re.sub(r"^[^.]+\.", "api.", host, count=1)
    return f"https://{api_host}/sql"


# ── Outbound: Python bind values -> Neon /sql `params[]` entries ──────────────
# With `Neon-Raw-Text-Output: true` every value is sent as text (or null) and
# Postgres coerces `$n` to the target type in context — matching the JS driver.


def _encode_array(value: Sequence[Any]) -> str:
    parts: list[str] = []
    for el in value:
        if el is None:
            parts.append("NULL")
        elif isinstance(el, bool):
            parts.append("true" if el else "false")
        elif isinstance(el, (int, float, Decimal)):
            parts.append(str(el))
        elif isinstance(el, (list, tuple)):
            parts.append(_encode_array(el))
        else:
            s = str(el).replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'"{s}"')
    return "{" + ",".join(parts) + "}"


def encode_param(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return _encode_array(value)
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


# ── Inbound: Neon text cells + type OID -> typed Python values (mimic asyncpg,
# since the backend code was written and tested against asyncpg's typing) ─────

_BOOL_OID = 16
_INT_OIDS = frozenset({20, 21, 23, 26})          # int8, int2, int4, oid
_FLOAT_OIDS = frozenset({700, 701})              # float4, float8
_NUMERIC_OID = 1700
_TS_OIDS = frozenset({1114, 1184})               # timestamp, timestamptz
_DATE_OID = 1082
# array OID -> element OID (only the arrays this schema actually produces)
_ARRAY_ELEM = {
    1000: 16, 1005: 21, 1007: 23, 1016: 20,
    1009: 25, 1015: 1043, 1231: 1700, 1021: 700, 1022: 701,
}


def _decode_scalar(text_val: str, oid: int) -> Any:
    if oid == _BOOL_OID:
        return text_val in ("t", "true", "True")
    if oid in _INT_OIDS:
        return int(text_val)
    if oid in _FLOAT_OIDS:
        return float(text_val)
    if oid == _NUMERIC_OID:
        try:
            return Decimal(text_val)
        except InvalidOperation:
            return text_val
    if oid == _DATE_OID:
        try:
            return date.fromisoformat(text_val)
        except ValueError:
            return text_val
    if oid in _TS_OIDS:
        # Postgres text form is space-separated ("2026-07-20 10:46:18.1+00");
        # normalise to ISO so datetime.fromisoformat accepts it.
        try:
            return datetime.fromisoformat(text_val.replace(" ", "T"))
        except ValueError:
            return text_val
    # text / varchar / name / char / uuid / json / jsonb -> leave as string
    # (asyncpg returns json/jsonb as str by default here too).
    return text_val


def _parse_array_literal(literal: str, elem_oid: int) -> list:
    """Parse a Postgres array output literal (e.g. ``{1,2,3}``, ``{"a","b"}``,
    ``{NULL,...}``, nested ``{{..},{..}}``) into a (possibly nested) list."""
    idx = 0
    n = len(literal)

    def parse_list() -> list:
        nonlocal idx
        assert literal[idx] == "{"
        idx += 1
        out: list = []
        while idx < n and literal[idx] != "}":
            if literal[idx] == ",":
                idx += 1
                continue
            if literal[idx] == "{":
                out.append(parse_list())
            elif literal[idx] == '"':
                idx += 1
                buf: list[str] = []
                while idx < n and literal[idx] != '"':
                    if literal[idx] == "\\":
                        idx += 1
                    buf.append(literal[idx])
                    idx += 1
                idx += 1  # closing quote
                out.append(_decode_scalar("".join(buf), elem_oid))
            else:
                start = idx
                while idx < n and literal[idx] not in ",}":
                    idx += 1
                token = literal[start:idx]
                out.append(None if token == "NULL" else _decode_scalar(token, elem_oid))
        idx += 1  # closing brace
        return out

    if not literal or literal[0] != "{":
        return []
    return parse_list()


def _decode_value(text_val: str | None, oid: int) -> Any:
    if text_val is None:
        return None
    if oid in _ARRAY_ELEM:
        return _parse_array_literal(text_val, _ARRAY_ELEM[oid])
    return _decode_scalar(text_val, oid)


def compile_statement(statement: ClauseElement, parameters: dict | None) -> tuple[str, list]:
    """Compile a ``text()`` clause or Core ``Select`` to ``$1``-style SQL plus a
    positional, wire-encoded param list — the one conversion both statement kinds
    share. Pure/stateless, so it's unit-testable without any network."""
    compiled = statement.compile(
        dialect=_DIALECT, compile_kwargs={"render_postcompile": True}
    )
    full = compiled.construct_params(parameters)
    positional = [encode_param(full[name]) for name in compiled.positiontup]
    return str(compiled), positional


# ── Result proxy: enough of SQLAlchemy's Result surface for the call sites ────


class _Mappings:
    __slots__ = ("_dicts",)

    def __init__(self, dicts: list[dict]) -> None:
        self._dicts = dicts

    def all(self) -> list[dict]:
        return self._dicts

    def first(self) -> dict | None:
        return self._dicts[0] if self._dicts else None


class HttpResult:
    """Mimics the subset of ``sqlalchemy.Result`` the backend uses:
    ``.mappings().all()/.first()``, ``.all()`` (positional tuples + ``.keys()``),
    and the scalar accessors (only ``.scalar_one()`` is used in-tree today)."""

    __slots__ = ("_cols", "_rows")

    def __init__(self, cols: list[str], rows: list[tuple]) -> None:
        self._cols = cols
        self._rows = rows

    def mappings(self) -> _Mappings:
        return _Mappings([dict(zip(self._cols, row, strict=True)) for row in self._rows])

    def all(self) -> list[tuple]:
        return self._rows

    def first(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def keys(self) -> list[str]:
        return self._cols

    def scalar(self) -> Any:
        return self._rows[0][0] if self._rows else None

    def scalar_one(self) -> Any:
        if len(self._rows) != 1:
            raise ValueError(f"scalar_one() expected exactly one row, got {len(self._rows)}")
        return self._rows[0][0]

    def scalar_one_or_none(self) -> Any:
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise ValueError(f"scalar_one_or_none() expected at most one row, got {len(self._rows)}")
        return self._rows[0][0]


class HttpSession:
    """Drop-in for the narrow ``AsyncSession`` surface the routes use, backed by
    Neon's HTTPS ``/sql`` endpoint. One ``httpx.AsyncClient`` per request-scoped
    session; each ``execute`` is an independent, auto-committing round trip."""

    def __init__(self) -> None:
        settings = get_settings()
        self._conn = settings.database_url
        self._endpoint = http_endpoint(self._conn)
        self._client = httpx.AsyncClient(timeout=30.0)
        self._did_write = False  # guards multi-statement (non-atomic) writes

    async def execute(self, statement: ClauseElement, parameters: dict | None = None) -> HttpResult:
        sql, params = compile_statement(statement, parameters)

        if _MUTATING.match(sql):
            if self._did_write:
                raise RuntimeError(
                    "Multi-statement write transactions aren't supported under "
                    "NEON_HTTP_FALLBACK (Neon's one-shot /sql endpoint can't hold "
                    "a transaction across statements). This route needs a real "
                    "Postgres (5432) connection — unset NEON_HTTP_FALLBACK."
                )
            self._did_write = True

        resp = await self._client.post(
            self._endpoint,
            json={"query": sql, "params": params},
            headers={
                "Neon-Connection-String": self._conn,
                "Neon-Raw-Text-Output": "true",
                "Neon-Array-Mode": "true",
            },
        )
        if resp.status_code >= 400:
            # Surface Neon's structured error message when present.
            detail = resp.text
            try:
                body = resp.json()
                detail = body.get("message", detail)
            except (json.JSONDecodeError, ValueError):
                pass
            raise RuntimeError(f"Neon /sql error (HTTP {resp.status_code}): {detail}")

        body = resp.json()
        fields = body.get("fields", [])
        cols = [f["name"] for f in fields]
        oids = [f["dataTypeID"] for f in fields]
        rows = [
            tuple(_decode_value(cell, oids[i]) for i, cell in enumerate(row))
            for row in body.get("rows", [])
        ]
        return HttpResult(cols, rows)

    async def commit(self) -> None:
        # Each /sql call already auto-committed; nothing to flush. Reset the
        # single-write guard so a subsequent independent write may proceed.
        self._did_write = False

    async def rollback(self) -> None:
        # Cannot undo already-committed HTTP statements — surface it rather than
        # pretend. (Single-statement write routes don't roll back on success.)
        logger.warning("rollback() is a no-op under NEON_HTTP_FALLBACK — prior /sql statements already committed")
        self._did_write = False

    async def close(self) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()


async def get_session_http() -> AsyncIterator[HttpSession]:
    """FastAPI dependency mirroring ``app.db.get_session`` but yielding an
    HTTP-backed session. Selected by ``app.db.get_session`` when the flag is on."""
    session = HttpSession()
    try:
        yield session
    finally:
        await session.aclose()
