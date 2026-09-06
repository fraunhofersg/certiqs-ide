"""Auth-gating checks for document-sources routes — in-process, DB-free."""

import pytest

from app.core.internal_auth import sign_internal_token
from app.main import app


@pytest.fixture
async def client():
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_document_sources_requires_token(client):
    res = await client.get("/internal/document-sources")
    assert res.status_code == 401


async def test_create_document_source_requires_admin(client):
    token = sign_internal_token(user_id="user_1", is_admin=False)
    res = await client.post(
        "/internal/document-sources",
        json={"label": "x", "blob_url": "https://example.com/x.pdf"},
        headers={"Authorization": f"Internal {token}"},
    )
    assert res.status_code == 403


async def test_create_document_source_requires_label_and_url(client):
    token = sign_internal_token(user_id="user_1", is_admin=True)
    res = await client.post(
        "/internal/document-sources", json={"label": "", "blob_url": ""},
        headers={"Authorization": f"Internal {token}"},
    )
    assert res.status_code == 400


async def test_upload_requires_admin(client):
    token = sign_internal_token(user_id="user_1", is_admin=False)
    res = await client.post(
        "/internal/document-sources/upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers={"Authorization": f"Internal {token}"},
    )
    assert res.status_code == 403


async def test_upload_rejects_non_pdf(client):
    token = sign_internal_token(user_id="user_1", is_admin=True)
    res = await client.post(
        "/internal/document-sources/upload",
        files={"file": ("test.txt", b"not a pdf", "text/plain")},
        headers={"Authorization": f"Internal {token}"},
    )
    assert res.status_code == 400
