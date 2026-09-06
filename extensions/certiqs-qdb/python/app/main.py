from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.routes import router as catalog_router
from app.components.routes import router as components_router
from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.countermeasures.routes import router as countermeasures_router
from app.db import dispose_engine, get_session
from app.document_sources.routes import router as document_sources_router
from app.evaluation_activities.routes import router as evaluation_activities_router
from app.export.routes import router as export_router
from app.qkd.routes import router as qkd_router
from app.search.routes import router as search_router
from app.systems.routes import router as systems_router
from app.vulnerabilities.routes import router as vulnerabilities_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Nothing to do on startup: this app runs per-request, so there is no pool
    # worth pre-warming (see app/db.py's NullPool rationale, and the note on
    # dispose_engine about the removed warm_up() probe). Shutdown cleanup is
    # capped at ~500ms after SIGTERM in that environment, so keep it trivial.
    yield
    await dispose_engine()


app = FastAPI(title="qsecdb-backend", lifespan=lifespan)
app.include_router(qkd_router)
app.include_router(search_router)
app.include_router(export_router)
app.include_router(catalog_router)
app.include_router(vulnerabilities_router)
app.include_router(evaluation_activities_router)
app.include_router(countermeasures_router)
app.include_router(components_router)
app.include_router(systems_router)
app.include_router(document_sources_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Unauthenticated liveness probe for infra (load balancer / container
    orchestrator) — no DB access, no auth, so it can't itself fail due to
    either being unavailable."""
    return {"status": "ok"}


@app.get("/internal/health/db")
async def health_db(
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Proves the full round trip: Next.js signs a token -> this route verifies
    it -> a per-request async session runs a real query against Neon. (The
    session is not app-pooled — see app/db.py's NullPool rationale; pooling is
    Neon's pooler endpoint's job.)"""
    result = await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": result.scalar_one(), "user_id": principal.user_id}
