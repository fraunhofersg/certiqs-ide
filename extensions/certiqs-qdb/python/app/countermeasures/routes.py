"""Countermeasure catalogue for the VSCode host. Not present on the original FastAPI surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session

router = APIRouter(prefix="/internal/countermeasures", tags=["countermeasures"])


@router.get("")
async def list_countermeasures(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT
            cm.id,
            cm.name,
            cm.description,
            cm.countermeasure_type,
            cm.module,
            cm.component_type_ids,
            count(vc.vulnerability_id) AS vuln_link_count
        FROM countermeasures cm
        LEFT JOIN vulnerability_countermeasures vc ON vc.countermeasure_id = cm.id
        GROUP BY cm.id
        ORDER BY cm.countermeasure_type, cm.name
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{cm_id}")
async def get_countermeasure(
    cm_id: int,
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = (await session.execute(text("""
        SELECT id, name, description, countermeasure_type, module, component_type_ids
        FROM countermeasures
        WHERE id = CAST(:id AS integer)
        LIMIT 1
    """), {"id": cm_id})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Countermeasure not found")

    links = (await session.execute(text("""
        SELECT
            vc.vulnerability_id,
            v.name AS vulnerability_name,
            vc.defense_effectiveness
        FROM vulnerability_countermeasures vc
        JOIN vulnerabilities v ON v.id = vc.vulnerability_id
        WHERE vc.countermeasure_id = CAST(:id AS integer)
        ORDER BY v.name
    """), {"id": cm_id})).mappings().all()

    types = []
    ids = row["component_type_ids"] or []
    if ids:
        types = (await session.execute(text("""
            SELECT id, name FROM component_types WHERE id = ANY(:ids) ORDER BY name
        """), {"ids": list(ids)})).mappings().all()

    return {
        **dict(row),
        "component_types": [dict(t) for t in types],
        "vulnerability_links": [dict(link) for link in links],
    }
