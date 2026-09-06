import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.internal_auth import (
    ALGORITHM,
    InternalPrincipal,
    require_internal_principal,
    sign_internal_token,
)


def test_sign_and_verify_round_trip():
    token = sign_internal_token(user_id="user_123", is_admin=True)
    settings = get_settings()
    payload = jwt.decode(token, settings.internal_auth_secret, algorithms=[ALGORITHM])
    assert payload["sub"] == "user_123"
    assert payload["is_admin"] is True


async def test_require_internal_principal_accepts_valid_token():
    token = sign_internal_token(user_id="user_123", is_admin=False)
    principal = await require_internal_principal(authorization=f"Internal {token}")
    assert isinstance(principal, InternalPrincipal)
    assert principal.user_id == "user_123"
    assert principal.is_admin is False


async def test_require_internal_principal_rejects_missing_scheme():
    with pytest.raises(HTTPException) as exc_info:
        await require_internal_principal(authorization="Bearer sometoken")
    assert exc_info.value.status_code == 401


async def test_require_internal_principal_rejects_bad_signature():
    token = sign_internal_token(user_id="user_123", is_admin=False)
    tampered = token[:-4] + ("A" * 4 if not token.endswith("A" * 4) else "B" * 4)
    with pytest.raises(HTTPException) as exc_info:
        await require_internal_principal(authorization=f"Internal {tampered}")
    assert exc_info.value.status_code == 401


async def test_require_internal_principal_rejects_expired_token():
    settings = get_settings()
    now = int(time.time())
    expired = jwt.encode(
        {"sub": "user_123", "is_admin": False, "iat": now - 120, "exp": now - 60},
        settings.internal_auth_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_internal_principal(authorization=f"Internal {expired}")
    assert exc_info.value.status_code == 401


def test_wire_format_matches_hand_built_hs256_jwt():
    """src/lib/internalApi.ts signs tokens by hand (base64url header/payload +
    HMAC-SHA256 via node:crypto), not via a JWT library — this test builds a
    token the same way using only Python's stdlib (no PyJWT on the signing
    side) to prove the wire format PyJWT expects is what the TS side actually
    produces, independent of PyJWT talking to itself."""
    settings = get_settings()
    now = int(time.time())

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(
        json.dumps({"sub": "user_456", "is_admin": True, "iat": now, "exp": now + 60}).encode()
    )
    signature = b64url(
        hmac.new(
            settings.internal_auth_secret.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256,
        ).digest()
    )
    token = f"{header}.{payload}.{signature}"

    decoded = jwt.decode(token, settings.internal_auth_secret, algorithms=[ALGORITHM])
    assert decoded["sub"] == "user_456"
    assert decoded["is_admin"] is True
