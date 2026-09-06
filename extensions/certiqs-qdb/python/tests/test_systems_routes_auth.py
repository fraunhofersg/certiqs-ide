"""Auth-gating checks for the systems routes — in-process, DB-free (these all
reject before any query runs)."""

import pytest

from app.core.internal_auth import sign_internal_token
from app.main import app


@pytest.fixture
async def client():
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _unauth_token() -> str:
    return sign_internal_token(user_id=None, is_admin=False)


async def test_list_systems_requires_signed_in_user(client):
    res = await client.get("/internal/systems", headers={"Authorization": f"Internal {_unauth_token()}"})
    assert res.status_code == 401


async def test_create_system_requires_signed_in_user(client):
    res = await client.post(
        "/internal/systems", json={"name": "x", "manufacturer": "y"},
        headers={"Authorization": f"Internal {_unauth_token()}"},
    )
    assert res.status_code == 401


async def test_get_system_requires_signed_in_user(client):
    res = await client.get("/internal/systems/1", headers={"Authorization": f"Internal {_unauth_token()}"})
    assert res.status_code == 401


async def test_delete_system_requires_signed_in_user(client):
    res = await client.delete("/internal/systems/1", headers={"Authorization": f"Internal {_unauth_token()}"})
    assert res.status_code == 401


async def test_set_visibility_requires_signed_in_user(client):
    res = await client.patch(
        "/internal/systems/1/visibility", json={"isPublic": True},
        headers={"Authorization": f"Internal {_unauth_token()}"},
    )
    assert res.status_code == 401


async def test_resync_system_requires_signed_in_user(client):
    res = await client.patch(
        "/internal/systems/1", json={"connections": []},
        headers={"Authorization": f"Internal {_unauth_token()}"},
    )
    assert res.status_code == 401


async def test_all_systems_routes_require_a_token_at_all(client):
    for method, path in [
        ("GET", "/internal/systems"),
        ("POST", "/internal/systems"),
        ("GET", "/internal/systems/1"),
        ("DELETE", "/internal/systems/1"),
        ("PATCH", "/internal/systems/1/visibility"),
        ("PATCH", "/internal/systems/1"),
    ]:
        res = await client.request(method, path, json={})
        assert res.status_code == 401, f"{method} {path}"
