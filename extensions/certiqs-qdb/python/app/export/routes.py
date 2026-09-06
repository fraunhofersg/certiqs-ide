"""Port of ../../../src/app/api/qsecdb/systems/[id]/export/{,prepare/}route.ts."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session
from app.export.orchestrator import RunExportInvalid, RunExportSuccess, prepare_export, run_export

router = APIRouter(prefix="/internal/export", tags=["export"])


@router.get("/{system_id}/prepare")
async def get_export_prepare(
    system_id: int,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    result = await prepare_export(session, system_id, principal.user_id)
    if not result.found:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # exclude_none mirrors the TS route's undefined-omission: the source ParamSpec
    # leaves unit/hardMin/hardMax/softMin/softMax undefined when absent, and
    # JSON.stringify drops undefined keys — so the prompt modal's `!== undefined`
    # bound checks must see those keys ABSENT, not present-as-null. `typical` is
    # never null in the catalog, so it is never wrongly dropped here.
    return result.model_dump(by_alias=True, exclude_none=True)


@router.post("/{system_id}")
async def post_export(
    system_id: int,
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    body = await request.json() if await request.body() else {}
    param_values = body.get("paramValues") or {}

    result = await run_export(session, system_id, principal.user_id, param_values)
    if not result.found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    if isinstance(result, RunExportInvalid):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"issues": [asdict(i) for i in result.issues]})

    assert isinstance(result, RunExportSuccess)
    return Response(
        content=result.zip,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-Export-Warnings": str(len(result.warnings)),
        },
    )
