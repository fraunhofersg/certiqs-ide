"""In-process route tests (ASGI transport, no listening socket, no DB server).

validate_tree()/the systems-domain auth check both run before any DB query in
run_search(), so the validation-error and auth-error paths are testable here
without live Neon access. A successful search (real rows returned) needs a
live DB and isn't covered here — see the Phase 2.5 parity harness notes.
"""

import pytest

from app.core.internal_auth import sign_internal_token
from app.main import app


@pytest.fixture
async def client():
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def auth_header() -> dict:
    token = sign_internal_token(user_id="user_1", is_admin=False)
    return {"Authorization": f"Internal {token}"}


# ── /internal/search/fields (no DB at all) ────────────────────────────────────


async def test_search_fields_rejects_missing_token(client):
    res = await client.get("/internal/search/fields", params={"domain": "attacks"})
    assert res.status_code == 401


async def test_search_fields_rejects_invalid_domain(client):
    res = await client.get(
        "/internal/search/fields", params={"domain": "not-a-real-domain"}, headers=auth_header()
    )
    assert res.status_code == 422


async def test_search_fields_returns_attacks_domain_metadata(client):
    res = await client.get("/internal/search/fields", params={"domain": "attacks"}, headers=auth_header())
    assert res.status_code == 200
    fields = res.json()
    assert len(fields) == 33
    vuln_name = next(f for f in fields if f["key"] == "vuln_name")
    assert vuln_name["label"] == "Vulnerability Name"
    assert vuln_name["type"] == "text"
    assert vuln_name["nullable"] is False
    # No raw SQL column object should ever leak into this response.
    assert "column" not in vuln_name


async def test_search_fields_static_options_serialize_correctly(client):
    res = await client.get("/internal/search/fields", params={"domain": "attacks"}, headers=auth_header())
    fields = res.json()
    attack_rating = next(f for f in fields if f["key"] == "attack_rating")
    assert attack_rating["options"]["kind"] == "static"
    assert "High" in attack_rating["options"]["values"]


async def test_search_fields_lookup_options_serialize_correctly(client):
    res = await client.get("/internal/search/fields", params={"domain": "attacks"}, headers=auth_header())
    fields = res.json()
    attack_category = next(f for f in fields if f["key"] == "attack_category")
    assert attack_category["options"]["kind"] == "lookup"
    assert attack_category["options"]["url"] == "/api/qsecdb/attack-categories"


async def test_search_fields_csv_multi_value_flag_present():
    from app.search.field_registry import get_field_def

    assert get_field_def("attacks", "attack_module").csv_multi_value is True
    assert get_field_def("attacks", "attack_rating").csv_multi_value is False


# ── /internal/search: error paths that don't require a live DB ───────────────


def _tree(*, domain="attacks", field="vuln_name", operator="contains", text="x"):
    return {
        "domain": domain,
        "tree": {
            "id": "g1",
            "kind": "group",
            "combinator": "AND",
            "children": [
                {"id": "c1", "kind": "condition", "field": field, "operator": operator, "value": {"text": text}}
            ],
        },
    }


async def test_search_rejects_missing_token(client):
    res = await client.post("/internal/search", json=_tree())
    assert res.status_code == 401


async def test_search_rejects_empty_tree_with_validation_error(client):
    body = {"domain": "attacks", "tree": {"id": "g1", "kind": "group", "combinator": "AND", "children": []}}
    res = await client.post("/internal/search", json=body, headers=auth_header())
    assert res.status_code == 400
    assert "at least one condition" in res.text.lower()


async def test_search_systems_domain_without_user_id_is_unauthorized(client):
    token = sign_internal_token(user_id=None, is_admin=False)
    body = _tree(domain="systems", field="sys_name")
    res = await client.post(
        "/internal/search", json=body, headers={"Authorization": f"Internal {token}"}
    )
    assert res.status_code == 401
