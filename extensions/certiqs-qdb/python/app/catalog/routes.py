"""Ports of the read-only reference/catalog routes under
../../../src/app/api/qsecdb/{attack-categories,component-types,
pp-component-types,protocol-families,protocols,reference-parameters}/route.ts.

All fixed, non-dynamic queries — parameterized text(), same style as
get_system_features.py / assemble.py, no SQLAlchemy Core table mirror needed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session

router = APIRouter(prefix="/internal/catalog", tags=["catalog"])


@router.get("/attack-categories")
async def get_attack_categories(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, name, description FROM attack_categories ORDER BY name")
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/component-types")
async def get_component_types(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT ct.id, ct.name, ct.module_type_id, mt.name AS module_type_name
        FROM component_types ct
        LEFT JOIN module_types mt ON mt.id = ct.module_type_id
        ORDER BY ct.name
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.get("/pp-component-types")
async def get_pp_component_types(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, name FROM pp_component_types ORDER BY id ASC")
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/protocol-families")
async def get_protocol_families(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, name, encoding_id, architecture_id FROM protocol_families ORDER BY name")
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/protocols")
async def get_protocols(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, protocol_family_id, name FROM protocols ORDER BY id ASC LIMIT 100")
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/reference-parameters")
async def get_reference_parameters(
    component_id: int | None = None,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if component_id is None:
        return []
    rows = (await session.execute(text("""
        SELECT param_group, key, value, value_num, value_text, value_bool, unit
        FROM reference_parameters
        WHERE component_id = :component_id
        ORDER BY param_group, key
    """), {"component_id": component_id})).mappings().all()
    return [dict(r) for r in rows]


@router.get("/encodings")
async def get_encodings(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, name, description FROM encodings ORDER BY name")
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/architectures")
async def get_architectures(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, name, description FROM architectures ORDER BY name")
    )).mappings().all()
    return [dict(r) for r in rows]


@router.get("/module-types")
async def get_module_types(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(
        text("SELECT id, name FROM module_types ORDER BY id")
    )).mappings().all()
    return [dict(r) for r in rows]
