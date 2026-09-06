"""Port of ../../src/lib/blob.ts — NOT verified against a live Vercel Blob
endpoint. This sandbox can't reach external hosts and I don't have live docs
access to confirm the current request contract, so this is a best-effort
reconstruction of what `@vercel/blob`'s `put()` does under the hood:

    put(filename, file, { access: "public", contentType: "application/pdf", addRandomSuffix: true })

which (per the SDK's published implementation) issues:

    PUT https://blob.vercel-storage.com/{pathname}
    Authorization: Bearer <BLOB_READ_WRITE_TOKEN>
    x-api-version: <n>
    x-content-type: <mime type>
    x-add-random-suffix: 1
    (body: raw file bytes)

    -> 200 JSON: {"url": "...", "pathname": "...", "contentType": "...", ...}

**Smoke-test this with a real PDF upload before relying on it** — if Vercel's
contract has moved (API version bump, header rename, response shape change),
this will need adjusting against their current docs, which I can't check
from here.
"""

from __future__ import annotations

import httpx

_BLOB_API_VERSION = "7"
_BLOB_BASE_URL = "https://blob.vercel-storage.com"


async def upload_document_pdf(file_bytes: bytes, filename: str, token: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-version": _BLOB_API_VERSION,
        "x-content-type": "application/pdf",
        "x-add-random-suffix": "1",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.put(f"{_BLOB_BASE_URL}/{filename}", content=file_bytes, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data["url"]
