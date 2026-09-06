"""Port of ../../../src/lib/reference/referencePages.ts — keep in sync line-by-line."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_document_url(
    session: AsyncSession, referenced_from: str | None, subclause: str | None
) -> str | None:
    if not referenced_from or not subclause:
        return None

    rows = (await session.execute(text("""
        SELECT ds.blob_url, dsc.pdf_page
        FROM document_sources ds
        JOIN document_subclauses dsc ON dsc.document_source_id = ds.id
        WHERE ds.label = :referenced_from AND dsc.subclause = :subclause
        LIMIT 1
    """), {"referenced_from": referenced_from, "subclause": subclause})).mappings().all()

    row = rows[0] if rows else None
    if row is None or row["pdf_page"] is None:
        return None
    return f"{row['blob_url']}#page={row['pdf_page']}"
