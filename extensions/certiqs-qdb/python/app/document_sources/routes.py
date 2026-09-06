"""Ports of ../../../src/app/api/qsecdb/document-sources{,/upload}/route.ts.

The upload route depends on app/blob.py, which is a best-effort, NOT
live-verified port of the Vercel Blob REST contract — see that file's
docstring before relying on this route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blob import upload_document_pdf
from app.core.config import get_settings
from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session

router = APIRouter(prefix="/internal/document-sources", tags=["document-sources"])


@router.get("")
async def list_document_sources(
    _principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (await session.execute(text("""
        SELECT ds.id, ds.label, ds.blob_url, ds.created_at, count(dsc.id) AS subclause_count
        FROM document_sources ds
        LEFT JOIN document_subclauses dsc ON dsc.document_source_id = ds.id
        GROUP BY ds.id
        ORDER BY ds.label
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.post("")
async def create_document_source(
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    body = await request.json()
    label = (body.get("label") or "").strip()
    blob_url = (body.get("blob_url") or "").strip()
    subclauses = body.get("subclauses")

    if not label or not blob_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"error": "label and blob_url are required."})

    try:
        source_row = (await session.execute(text("""
            INSERT INTO document_sources (label, blob_url, uploaded_by)
            VALUES (:label, :blob_url, :uploaded_by)
            RETURNING *
        """), {"label": label, "blob_url": blob_url, "uploaded_by": principal.user_id})).mappings().first()
    except IntegrityError as exc:
        await session.rollback()
        if "document_sources_label_uq" in str(exc.orig):
            raise HTTPException(status.HTTP_409_CONFLICT, {"error": "A document source with this label already exists."}) from None
        raise
    source = dict(source_row)

    if isinstance(subclauses, list):
        for s in subclauses:
            subclause = (s.get("subclause") or "").strip()
            if not subclause:
                continue
            await session.execute(text("""
                INSERT INTO document_subclauses (document_source_id, subclause, pdf_page)
                VALUES (:source_id, :subclause, :pdf_page)
            """), {"source_id": source["id"], "subclause": subclause, "pdf_page": s.get("pdf_page")})

    await session.commit()
    return source


@router.post("/upload")
async def upload_document_source_pdf(
    file: UploadFile = File(...),
    principal: InternalPrincipal = Depends(require_internal_principal),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    if file.content_type != "application/pdf":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"error": "A PDF file is required."})

    token = get_settings().blob_read_write_token
    if not token:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "BLOB_READ_WRITE_TOKEN is not configured")

    content = await file.read()
    url = await upload_document_pdf(content, file.filename or "document.pdf", token)
    return {"url": url}
