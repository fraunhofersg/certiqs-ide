from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def _to_asyncpg_url(database_url: str) -> str:
    """Adapt a libpq-style Postgres URL (as used by Drizzle/Neon on the TS
    side) to one asyncpg accepts: swap the driver and translate/drop query
    params with no direct asyncpg equivalent.

    SQLAlchemy's asyncpg dialect passes every URL query param straight
    through as a keyword argument to `asyncpg.connect()`. asyncpg has no
    `sslmode` *parameter* (unlike libpq/psycopg) — the equivalent kwarg is
    `ssl`, which accepts the same string values (disable/allow/prefer/
    require/verify-ca/verify-full) via asyncpg's own `SSLMode.parse()`, so
    Neon's `sslmode=require` just needs renaming, not reinterpreting.
    `channel_binding` is libpq/SCRAM-specific with no asyncpg kwarg at all
    and must be dropped or `connect()` raises an unexpected-keyword error.
    """
    scheme, netloc, path, query, fragment = urlsplit(database_url)
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+asyncpg"
    params = dict(parse_qsl(query))
    params.pop("channel_binding", None)
    if "sslmode" in params:
        params["ssl"] = params.pop("sslmode")
    return urlunsplit((scheme, netloc, path, urlencode(params), fragment))


# Serverless connection model (this app runs as a per-request Vercel Function —
# see vercel.json's `services`). Two deliberate choices:
#
#   * NullPool — DATABASE_URL points at Neon's *pooler* endpoint (the `-pooler`
#     host), so connection pooling happens there. Keeping SQLAlchemy's own pool
#     on top would mean two poolers competing, and every concurrently-running
#     function instance holding its own idle connections would exhaust Neon's
#     limit. NullPool opens one connection per session and closes it after.
#     (`pool_pre_ping` is gone with it — pointless when every connection is new.)
#
#   * statement_cache_size=0 — asyncpg uses named prepared statements by
#     default, which break behind PgBouncer in transaction mode (the pooler
#     endpoint's mode): a later request can land on a different backend that has
#     never seen the statement name.
#
# Multi-statement transactions still work normally here — this is a real
# Postgres connection, unlike the NEON_HTTP_FALLBACK path below, which cannot
# hold a transaction across statements.
engine: AsyncEngine = create_async_engine(
    _to_asyncpg_url(get_settings().database_url),
    poolclass=NullPool,
    connect_args={"statement_cache_size": 0},
)

_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    # DEV escape hatch: when raw Postgres (5432) is blocked but HTTPS works,
    # route queries through Neon's /sql endpoint instead of asyncpg. See
    # app/db_http.py. Default off — the asyncpg path below is production.
    if get_settings().neon_http_fallback:
        from app.db_http import get_session_http

        async for session in get_session_http():
            yield session
        return

    async with _session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Closes the engine on shutdown. Effectively a no-op under NullPool (there
    are no idle pooled connections to drop), but kept correct for running this
    app under a long-lived uvicorn process locally.

    Note the previous `warm_up()` startup probe was removed with the move to
    per-request execution: it was a multi-attempt retry loop with exponential
    backoff that could stay alive for minutes, which under a per-request model
    burns billed time on every cold start and gets killed at shutdown anyway.
    Neon's pooler endpoint absorbs compute wake-up instead.
    """
    await engine.dispose()
