import time

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import get_settings

ALGORITHM = "HS256"
_SCHEME_PREFIX = "Internal "


class InternalPrincipal:
    __slots__ = ("user_id", "is_admin")

    def __init__(self, user_id: str | None, is_admin: bool) -> None:
        self.user_id = user_id
        self.is_admin = is_admin


def sign_internal_token(user_id: str | None, is_admin: bool) -> str:
    """Mint a short-TTL token asserting an identity already verified by Clerk.

    Mirrored on the Next.js side by `src/lib/internalApi.ts`, which calls this
    only after `auth()`/`isAdmin()` have resolved — this function never itself
    checks identity, only asserts one that was already checked. Exists on the
    Python side purely so tests can mint tokens without a running Next.js
    process; production tokens always originate from Next.js.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": user_id,
        "is_admin": is_admin,
        "iat": now,
        "exp": now + settings.internal_auth_ttl_seconds,
    }
    return jwt.encode(payload, settings.internal_auth_secret, algorithm=ALGORITHM)


async def require_internal_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> InternalPrincipal:
    if authorization is None or not authorization.startswith(_SCHEME_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing internal auth token")

    token = authorization[len(_SCHEME_PREFIX) :]
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.internal_auth_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal auth token") from exc

    return InternalPrincipal(user_id=payload.get("sub"), is_admin=bool(payload.get("is_admin")))
