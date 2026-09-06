"""Port of ../../../src/app/api/qsecdb/search/route.ts.

Departs from the TS route's transport shape deliberately: `tree` arrives here
as an already-decoded JSON object in a POST body, not a URL-encoded query
string — `serializeTree.ts` (encode/decode + the "degrade gracefully on a
malformed bookmarked URL" leniency) stays entirely TS/client-side per the
plan; by the time a request reaches this internal-only service, Next.js has
already decoded and validated the tree, so there's nothing here that needs
to replicate that leniency.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.camel_model import CamelModel
from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session
from app.search.compile import (
    SearchAuthError,
    SearchOptions,
    SearchValidationError,
    run_search,
)
from app.search.field_registry import FIELD_REGISTRY
from app.search.types import ConditionGroup, FieldType, SearchDomain

router = APIRouter(prefix="/internal", tags=["search"])


class SearchRequest(CamelModel):
    domain: SearchDomain
    tree: ConditionGroup
    limit: int = 25
    offset: int = 0


@router.post("/search")
async def search(
    body: SearchRequest,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    limit = min(max(body.limit if body.limit > 0 else 25, 1), 100)
    offset = body.offset if body.offset > 0 else 0

    try:
        result = await run_search(
            session, body.domain, body.tree, SearchOptions(principal.user_id, limit, offset)
        )
    except SearchAuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized") from None
    except SearchValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    return {"domain": body.domain, "rows": result.rows, "hasMore": result.has_more}


class FieldOptionsMetadata(CamelModel):
    kind: Literal["static", "lookup"]
    values: list[str] | None = None
    url: str | None = None
    value_key: str | None = None
    label_key: str | None = None


class FieldMetadata(CamelModel):
    key: str
    label: str
    group: str
    type: FieldType
    nullable: bool
    csv_multi_value: bool
    options: FieldOptionsMetadata | None = None


def _field_metadata(f) -> FieldMetadata:
    options = None
    if f.options is not None:
        options = FieldOptionsMetadata(
            kind=f.options.kind,
            values=list(f.options.values) if f.options.values else None,
            url=f.options.url,
            value_key=f.options.value_key,
            label_key=f.options.label_key,
        )
    return FieldMetadata(
        key=f.key,
        label=f.label,
        group=f.group,
        type=f.type,
        nullable=f.nullable,
        csv_multi_value=f.csv_multi_value,
        options=options,
    )


# No DB columns leak into this response (unlike fieldRegistry.ts, which the TS
# frontend can no longer import once its server half is retired) — labels/
# types/options only, safe for the field-picker UI to consume directly.
@router.get("/search/fields")
async def get_search_fields(
    domain: SearchDomain,
    principal: InternalPrincipal = Depends(require_internal_principal),
) -> list[dict]:
    return [_field_metadata(f).model_dump(by_alias=True) for f in FIELD_REGISTRY[domain]]


@router.get("/search/quick")
async def quick_search(
    q: str = "",
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """ILIKE over systems (visibility-scoped) and vulnerabilities. No tree."""
    needle = (q or "").strip()
    if not needle:
        return {"systems": [], "vulnerabilities": []}
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    pattern = f"%{needle}%"
    systems = (await session.execute(text("""
        SELECT id, name, manufacturer, toe_boundary
        FROM systems
        WHERE (user_id = :user_id OR is_public = true)
          AND (name ILIKE :q OR manufacturer ILIKE :q)
        ORDER BY id DESC
        LIMIT 12
    """), {"user_id": principal.user_id, "q": pattern})).mappings().all()

    vulnerabilities = (await session.execute(text("""
        SELECT DISTINCT v.id, v.name, v.short_description, a.attack_type, ac.name AS category
        FROM vulnerabilities v
        LEFT JOIN attacks a ON a.vulnerability_id = v.id
        LEFT JOIN attack_categories ac ON ac.id = a.attack_category_id
        WHERE v.name ILIKE :q
           OR v.short_description ILIKE :q
           OR a.attack_type ILIKE :q
           OR ac.name ILIKE :q
        ORDER BY v.id DESC
        LIMIT 20
    """), {"q": pattern})).mappings().all()

    return {
        "systems": [dict(r) for r in systems],
        "vulnerabilities": [dict(r) for r in vulnerabilities],
    }
