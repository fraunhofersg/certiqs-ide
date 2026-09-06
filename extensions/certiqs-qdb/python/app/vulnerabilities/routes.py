"""Ports of ../../../src/app/api/qsecdb/vulnerabilities{,/[id],/[id]/reference}/route.ts.

The reference-redirect route returns `{"url": ...}` JSON rather than issuing
an HTTP redirect itself — this is an internal-only service (see the plan's
architecture notes), so turning that URL into an actual browser redirect is
the future Next.js proxy route's job, not this one's.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session
from app.qkd.attack_enums import validate_attack_fields
from app.reference.document_urls import get_document_url

router = APIRouter(prefix="/internal/vulnerabilities", tags=["vulnerabilities"])


@router.get("")
async def list_vulnerabilities(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT
            v.id,
            v.name,
            v.short_description,
            a.module,
            a.component,
            a.attack_type,
            a.attack_rating,
            a.targets,
            ac.name AS category,
            (
                SELECT array_remove(array_agg(DISTINCT e.name), NULL)
                FROM vulnerability_applicability va
                LEFT JOIN encodings e ON e.id = va.encoding_id
                WHERE va.vulnerability_id = v.id
            ) AS encodings,
            (
                SELECT array_remove(array_agg(DISTINCT pf.name), NULL)
                FROM vulnerability_applicability va
                LEFT JOIN protocol_families pf ON pf.id = va.protocol_family_id
                WHERE va.vulnerability_id = v.id
            ) AS protocol_families
        FROM vulnerabilities v
        LEFT JOIN attacks a ON a.vulnerability_id = v.id
        LEFT JOIN attack_categories ac ON ac.id = a.attack_category_id
        ORDER BY v.id DESC
        LIMIT 200
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.post("")
async def create_vulnerability(
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    body = await request.json()
    name = body.get("name")
    short_description = body.get("short_description")
    attack = body.get("attack")

    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name is required")

    if attack:
        field_error = validate_attack_fields(attack)
        if field_error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, field_error)

        component = attack.get("component")
        if component:
            tokens = [t.strip() for t in str(component).split(",") if t.strip()]
            if tokens:
                known_rows = (await session.execute(
                    text("SELECT name FROM component_types WHERE name = ANY(:names)"), {"names": tokens}
                )).mappings().all()
                known_names = {r["name"] for r in known_rows}
                invalid = [t for t in tokens if t not in known_names]
                if invalid:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid component value(s): {', '.join(invalid)}")

    vuln_row = (await session.execute(text("""
        INSERT INTO vulnerabilities (name, short_description)
        VALUES (:name, :short_description)
        RETURNING *
    """), {"name": name, "short_description": short_description})).mappings().first()
    vuln = dict(vuln_row)

    if attack and vuln.get("id"):
        await session.execute(text("""
            INSERT INTO attacks (
                vulnerability_id, attack_category_id, module, component, attack_type,
                targets, expertise, opportunity, feasibility, feasibility_assessment, attack_rating,
                subclause, referenced_from
            ) VALUES (
                :vulnerability_id, :attack_category_id, :module, :component, :attack_type,
                :targets, :expertise, :opportunity, :feasibility, :feasibility_assessment, :attack_rating,
                :subclause, :referenced_from
            )
        """), {
            "vulnerability_id": vuln["id"],
            "attack_category_id": attack.get("attack_category_id"),
            "module": attack.get("module"),
            "component": attack.get("component"),
            "attack_type": attack.get("attack_type"),
            "targets": attack.get("targets"),
            "expertise": attack.get("expertise"),
            "opportunity": attack.get("opportunity"),
            "feasibility": attack.get("feasibility"),
            "feasibility_assessment": attack.get("feasibility_assessment"),
            "attack_rating": attack.get("attack_rating"),
            "subclause": attack.get("subclause"),
            "referenced_from": attack.get("referenced_from"),
        })

    await session.commit()
    return vuln


@router.get("/{vuln_id}")
async def get_vulnerability(
    vuln_id: int,
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict | None:
    rows = (await session.execute(
        text("SELECT * FROM vulnerabilities WHERE id = CAST(:id AS integer) LIMIT 1"), {"id": vuln_id}
    )).mappings().all()
    return dict(rows[0]) if rows else None


@router.get("/{vuln_id}/reference")
async def get_vulnerability_reference(
    vuln_id: int,
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (await session.execute(
        text("SELECT subclause, referenced_from FROM attacks WHERE vulnerability_id = CAST(:id AS integer) LIMIT 1"),
        {"id": vuln_id},
    )).mappings().all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vulnerability not found")

    row = rows[0]
    url = await get_document_url(session, row["referenced_from"], row["subclause"])
    if not url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No document reference mapped for this vulnerability")
    return {"url": url}
