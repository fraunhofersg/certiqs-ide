import asyncio

import httpx
import pytest

from app.core.internal_auth import sign_internal_token
from app.main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_requires_no_auth_and_touches_no_db(client: httpx.AsyncClient):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_health_db_rejects_missing_token(client: httpx.AsyncClient):
    res = await client.get("/internal/health/db")
    assert res.status_code == 401


async def test_health_db_rejects_invalid_token(client: httpx.AsyncClient):
    res = await client.get("/internal/health/db", headers={"Authorization": "Internal not-a-real-token"})
    assert res.status_code == 401


@pytest.mark.live_db
async def test_health_db_reaches_neon_with_valid_token(client: httpx.AsyncClient):
    token = sign_internal_token(user_id="user_test", is_admin=False)
    res = await asyncio.wait_for(
        client.get("/internal/health/db", headers={"Authorization": f"Internal {token}"}),
        timeout=10,
    )
    assert res.status_code == 200
    assert res.json()["db"] == 1
