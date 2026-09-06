"""Auth-gating checks for the Phase 4 routes — in-process (ASGI transport, no
listening socket), and DB-free since these all reject before any query runs."""

import pytest

from app.core.internal_auth import sign_internal_token
from app.main import app


@pytest.fixture
async def client():
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _token(is_admin: bool = False, user_id: str | None = "user_1") -> str:
    return sign_internal_token(user_id=user_id, is_admin=is_admin)


async def test_catalog_routes_require_token(client):
    for path in [
        "/internal/catalog/attack-categories",
        "/internal/catalog/component-types",
        "/internal/catalog/pp-component-types",
        "/internal/catalog/protocol-families",
        "/internal/catalog/protocols",
    ]:
        res = await client.get(path)
        assert res.status_code == 401, path


async def test_reference_parameters_requires_signed_in_user(client):
    token = sign_internal_token(user_id=None, is_admin=False)
    res = await client.get(
        "/internal/catalog/reference-parameters",
        headers={"Authorization": f"Internal {token}"},
    )
    assert res.status_code == 401


async def test_reference_parameters_no_component_id_returns_empty_without_db(client):
    res = await client.get(
        "/internal/catalog/reference-parameters",
        headers={"Authorization": f"Internal {_token()}"},
    )
    assert res.status_code == 200
    assert res.json() == []


async def test_vulnerabilities_post_requires_admin(client):
    res = await client.post(
        "/internal/vulnerabilities",
        json={"name": "Test"},
        headers={"Authorization": f"Internal {_token(is_admin=False)}"},
    )
    assert res.status_code == 403


async def test_vulnerabilities_post_requires_auth(client):
    token = sign_internal_token(user_id=None, is_admin=False)
    res = await client.post(
        "/internal/vulnerabilities", json={"name": "Test"}, headers={"Authorization": f"Internal {token}"}
    )
    assert res.status_code == 401


async def test_evaluation_activities_post_requires_admin(client):
    res = await client.post(
        "/internal/evaluation-activities",
        json={"code": "EA-X"},
        headers={"Authorization": f"Internal {_token(is_admin=False)}"},
    )
    assert res.status_code == 403


async def test_components_requires_signed_in_user(client):
    token = sign_internal_token(user_id=None, is_admin=False)
    res = await client.get("/internal/components", headers={"Authorization": f"Internal {token}"})
    assert res.status_code == 401


async def test_components_defaults_requires_signed_in_user(client):
    token = sign_internal_token(user_id=None, is_admin=False)
    res = await client.get("/internal/components/defaults", headers={"Authorization": f"Internal {token}"})
    assert res.status_code == 401


async def test_applicable_eas_requires_signed_in_user(client):
    token = sign_internal_token(user_id=None, is_admin=False)
    res = await client.get(
        "/internal/qkd/systems/1/applicable-eas", headers={"Authorization": f"Internal {token}"}
    )
    assert res.status_code == 401
