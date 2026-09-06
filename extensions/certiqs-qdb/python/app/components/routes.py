"""Ports of ../../../src/app/api/qsecdb/components{,/defaults}/route.ts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session

router = APIRouter(prefix="/internal/components", tags=["components"])


@router.get("")
async def list_components(
    type_id: int | None = None,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    if type_id is not None:
        rows = (await session.execute(text("""
            SELECT id, name, vendor, model
            FROM components
            WHERE component_type_id = :type_id
            ORDER BY vendor, name
        """), {"type_id": type_id})).mappings().all()
    else:
        rows = (await session.execute(text("""
            SELECT id, name, vendor, model, component_type_id
            FROM components
            ORDER BY component_type_id, vendor, name
        """))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/defaults")
async def get_component_defaults(
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[int, int]:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    # Return the lowest-ID catalog component per component type.
    rows = (await session.execute(text("""
        SELECT component_type_id AS type_id, MIN(id) AS component_id
        FROM components
        GROUP BY component_type_id
    """))).mappings().all()
    return {r["type_id"]: int(r["component_id"]) for r in rows}
