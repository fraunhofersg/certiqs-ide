"""Ports of ../../../src/app/api/qsecdb/evaluationActivities{,/[code]/reference}/route.ts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session
from app.reference.document_urls import get_document_url

router = APIRouter(prefix="/internal/evaluation-activities", tags=["evaluation-activities"])


@router.get("")
async def list_evaluation_activities(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT
            id, code, name, description, subclause, referenced_from,
            pass_description, fail_description, threshold_description,
            dependencies, is_iso_mandated
        FROM evaluation_activities
        ORDER BY code
        LIMIT 200
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.post("")
async def create_evaluation_activity(
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    body = await request.json()
    parameters = body.get("parameters")

    ea_row = (await session.execute(text("""
        INSERT INTO evaluation_activities (
            code, name, subclause, referenced_from,
            description, pass_description, fail_description,
            threshold_description, dependencies, is_iso_mandated
        ) VALUES (
            :code, :name, :subclause, :referenced_from,
            :description, :pass_description, :fail_description,
            :threshold_description, :dependencies, :is_iso_mandated
        ) RETURNING *
    """), {
        "code": body.get("code"),
        "name": body.get("name"),
        "subclause": body.get("subclause"),
        "referenced_from": body.get("referenced_from"),
        "description": body.get("description"),
        "pass_description": body.get("pass_description"),
        "fail_description": body.get("fail_description"),
        "threshold_description": body.get("threshold_description"),
        "dependencies": body.get("dependencies"),
        "is_iso_mandated": body.get("is_iso_mandated") if body.get("is_iso_mandated") is not None else True,
    })).mappings().first()
    ea = dict(ea_row)

    if isinstance(parameters, list) and len(parameters) > 0:
        for p in parameters:
            await session.execute(text("""
                INSERT INTO ea_parameters (ea_code, name, symbol, parameter_type, description, constraints)
                VALUES (:ea_code, :name, :symbol, :parameter_type, :description, :constraints)
            """), {
                "ea_code": body.get("code"),
                "name": p.get("name"),
                "symbol": p.get("symbol"),
                "parameter_type": p.get("parameter_type"),
                "description": p.get("description"),
                "constraints": p.get("constraints"),
            })

    await session.commit()
    return ea


@router.get("/{code}/reference")
async def get_evaluation_activity_reference(
    code: str,
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (await session.execute(
        text("SELECT subclause, referenced_from FROM evaluation_activities WHERE code = :code LIMIT 1"),
        {"code": code},
    )).mappings().all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "EA not found")

    row = rows[0]
    url = await get_document_url(session, row["referenced_from"], row["subclause"])
    if not url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No document reference mapped for this subclause")
    return {"url": url}
