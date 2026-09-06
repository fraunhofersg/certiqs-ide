"""GHCR / GitHub Packages container catalog discovery.

Uses the GitHub REST Packages API:

- ``GET /orgs/{org}/packages?package_type=container``
- ``GET /users/{username}/packages?package_type=container``
- ``GET /…/packages/container/{name}/versions``

Authentication (when packages are private or listing requires auth):

- Prefer a fine-grained PAT or classic PAT with ``read:packages`` only.
- Store the token in ``CERTIQS_IMAGES_REGISTRY_TOKEN`` (server-side env / secrets).
- Never expose the token to the browser or API responses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

import httpx

OwnerKind = Literal["org", "user", "auto"]

_GITHUB_API = "https://api.github.com"
_USER_AGENT = "certiqs-sim-image-catalog/1.0"

# Simple process-local cache: (owner, kind, has_token) -> (expires_at, result)
_CACHE: dict[tuple[str, str, bool], tuple[float, "ImageCatalogResult"]] = {}


@dataclass
class ImageVersion:
    version_id: int | None
    tags: list[str]
    digest: str | None
    created_at: str | None
    updated_at: str | None
    html_url: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "tags": list(self.tags),
            "digest": self.digest,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "html_url": self.html_url,
        }


@dataclass
class ImageEntry:
    name: str
    full_name: str
    registry: str
    pull_ref: str
    visibility: str | None
    description: str | None
    html_url: str | None
    created_at: str | None
    updated_at: str | None
    owner: str
    owner_kind: str
    latest_tags: list[str] = field(default_factory=list)
    latest_digest: str | None = None
    version_count: int | None = None
    versions: list[ImageVersion] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "registry": self.registry,
            "pull_ref": self.pull_ref,
            "visibility": self.visibility,
            "description": self.description,
            "html_url": self.html_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "owner": self.owner,
            "owner_kind": self.owner_kind,
            "latest_tags": list(self.latest_tags),
            "latest_digest": self.latest_digest,
            "version_count": self.version_count,
            "versions": [v.as_dict() for v in self.versions],
        }


@dataclass
class ImageCatalogResult:
    registry: str
    owner: str
    owner_kind: str
    authenticated: bool
    images: list[ImageEntry]
    fetched_at: float
    cache_hit: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    auth: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry": self.registry,
            "owner": self.owner,
            "owner_kind": self.owner_kind,
            "authenticated": self.authenticated,
            "image_count": len(self.images),
            "images": [img.as_dict() for img in self.images],
            "fetched_at": self.fetched_at,
            "cache_hit": self.cache_hit,
            "error": self.error,
            "warnings": list(self.warnings),
            "auth": dict(self.auth),
        }


def registry_auth_guidance(*, authenticated: bool, owner: str, owner_kind: str) -> dict[str, Any]:
    """Safe, token-free guidance for operators configuring GHCR access."""
    list_path = (
        f"/orgs/{owner}/packages"
        if owner_kind == "org"
        else f"/users/{owner}/packages"
    )
    return {
        "registry": "ghcr.io",
        "token_configured": authenticated,
        "required_scopes": ["read:packages"],
        "recommended_token": "fine-grained personal access token (or classic PAT) with read-only package access",
        "env_var": "CERTIQS_IMAGES_REGISTRY_TOKEN",
        "owner_env_var": "CERTIQS_IMAGES_REGISTRY_OWNER",
        "owner_kind_env_var": "CERTIQS_IMAGES_REGISTRY_OWNER_KIND",
        "best_practices": [
            "Store the token only in server-side environment / secret manager — never in frontend code, git, or browser storage.",
            "Prefer a fine-grained PAT limited to the target org/user with Packages: Read only.",
            "Rotate tokens regularly and revoke unused tokens in GitHub → Settings → Developer settings.",
            "Use a machine/bot account for CI/server access instead of a personal identity when possible.",
            "Do not echo or log the token; API responses never include credential material.",
            "For public packages, listing may work without a token; private packages always require authentication.",
            "Docker pull from GHCR: docker login ghcr.io -u USERNAME --password-stdin <<< \"$CERTIQS_IMAGES_REGISTRY_TOKEN\".",
        ],
        "api_docs": "https://docs.github.com/en/rest/packages/packages",
        "list_endpoint": f"{_GITHUB_API}{list_path}?package_type=container",
    }


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _resolve_owner_kind(
    client: httpx.Client,
    owner: str,
    kind: OwnerKind,
) -> str:
    if kind in ("org", "user"):
        return kind
    # auto: prefer org, fall back to user
    org_resp = client.get(f"{_GITHUB_API}/orgs/{quote(owner)}")
    if org_resp.status_code == 200:
        return "org"
    user_resp = client.get(f"{_GITHUB_API}/users/{quote(owner)}")
    if user_resp.status_code == 200:
        return "user"
    # Default to org for clearer error messages when listing fails
    return "org"


def _list_packages_url(owner: str, owner_kind: str) -> str:
    if owner_kind == "user":
        return f"{_GITHUB_API}/users/{quote(owner)}/packages"
    return f"{_GITHUB_API}/orgs/{quote(owner)}/packages"


def _versions_url(owner: str, owner_kind: str, package_name: str) -> str:
    encoded = quote(package_name, safe="")
    if owner_kind == "user":
        return f"{_GITHUB_API}/users/{quote(owner)}/packages/container/{encoded}/versions"
    return f"{_GITHUB_API}/orgs/{quote(owner)}/packages/container/{encoded}/versions"


def _parse_version(raw: dict[str, Any]) -> ImageVersion:
    meta = raw.get("metadata") or {}
    container = meta.get("container") or {}
    tags = container.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return ImageVersion(
        version_id=raw.get("id"),
        tags=[str(t) for t in tags],
        digest=str(raw["name"]) if raw.get("name") else None,
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        html_url=raw.get("html_url"),
    )


def _normalize_package(
    raw: dict[str, Any],
    *,
    owner: str,
    owner_kind: str,
    registry: str,
    versions: list[ImageVersion],
) -> ImageEntry:
    name = str(raw.get("name") or "")
    latest_tags: list[str] = []
    latest_digest: str | None = None
    if versions:
        latest_tags = list(versions[0].tags)
        latest_digest = versions[0].digest
        # Prefer a version that has tags if the first is untagged
        for ver in versions:
            if ver.tags:
                latest_tags = list(ver.tags)
                latest_digest = ver.digest
                break

    tag = latest_tags[0] if latest_tags else "latest"
    pull_ref = f"{registry}/{owner}/{name}:{tag}"
    return ImageEntry(
        name=name,
        full_name=f"{owner}/{name}",
        registry=registry,
        pull_ref=pull_ref,
        visibility=raw.get("visibility"),
        description=raw.get("description"),
        html_url=raw.get("html_url"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        owner=owner,
        owner_kind=owner_kind,
        latest_tags=latest_tags,
        latest_digest=latest_digest,
        version_count=len(versions) if versions else None,
        versions=versions,
    )


def discover_ghcr_catalog(
    *,
    owner: str,
    owner_kind: OwnerKind = "auto",
    token: str | None = None,
    registry: str = "ghcr.io",
    include_versions: bool = True,
    max_versions_per_image: int = 5,
    cache_ttl_s: int = 300,
    timeout_s: float = 20.0,
) -> ImageCatalogResult:
    """Discover container packages for a GitHub org or user on GHCR."""
    owner = (owner or "").strip()
    token = (token or "").strip() or None
    now = time.time()
    auth = registry_auth_guidance(
        authenticated=bool(token),
        owner=owner or "<owner>",
        owner_kind=owner_kind if owner_kind != "auto" else "org",
    )

    if not owner:
        return ImageCatalogResult(
            registry=registry,
            owner="",
            owner_kind=owner_kind if owner_kind != "auto" else "org",
            authenticated=bool(token),
            images=[],
            fetched_at=now,
            error="CERTIQS_IMAGES_REGISTRY_OWNER is not configured",
            warnings=["Set CERTIQS_IMAGES_REGISTRY_OWNER to a GitHub org or username."],
            auth=auth,
        )

    cache_key = (owner.lower(), owner_kind, bool(token))
    cached = _CACHE.get(cache_key)
    if cached and cached[0] > now:
        result = cached[1]
        result.cache_hit = True
        return result

    warnings: list[str] = []
    images: list[ImageEntry] = []
    resolved_kind = owner_kind if owner_kind != "auto" else "org"
    error: str | None = None

    try:
        with httpx.Client(timeout=timeout_s, headers=_headers(token)) as client:
            resolved_kind = _resolve_owner_kind(client, owner, owner_kind)
            auth = registry_auth_guidance(
                authenticated=bool(token),
                owner=owner,
                owner_kind=resolved_kind,
            )

            list_url = _list_packages_url(owner, resolved_kind)
            resp = client.get(list_url, params={"package_type": "container", "per_page": 100})

            if resp.status_code in (401, 403):
                error = (
                    f"GitHub Packages API returned {resp.status_code}. "
                    "Configure CERTIQS_IMAGES_REGISTRY_TOKEN with a token that has "
                    "read:packages scope (private packages always require auth)."
                )
            elif resp.status_code == 404:
                error = (
                    f"Owner '{owner}' not found as a GitHub {resolved_kind}, "
                    "or packages are not visible without authentication."
                )
            elif resp.status_code >= 400:
                detail = resp.text[:300]
                error = f"GitHub Packages API error {resp.status_code}: {detail}"
            else:
                packages = resp.json()
                if not isinstance(packages, list):
                    error = "Unexpected Packages API response (expected a list)"
                else:
                    for pkg in packages:
                        if not isinstance(pkg, dict):
                            continue
                        name = str(pkg.get("name") or "")
                        if not name:
                            continue
                        versions: list[ImageVersion] = []
                        if include_versions:
                            vresp = client.get(
                                _versions_url(owner, resolved_kind, name),
                                params={"per_page": max_versions_per_image},
                            )
                            if vresp.status_code == 200:
                                raw_versions = vresp.json()
                                if isinstance(raw_versions, list):
                                    versions = [
                                        _parse_version(v)
                                        for v in raw_versions
                                        if isinstance(v, dict)
                                    ][:max_versions_per_image]
                            elif vresp.status_code in (401, 403):
                                warnings.append(
                                    f"Could not list versions for '{name}' "
                                    f"(HTTP {vresp.status_code}); package metadata only."
                                )
                        images.append(
                            _normalize_package(
                                pkg,
                                owner=owner,
                                owner_kind=resolved_kind,
                                registry=registry,
                                versions=versions,
                            )
                        )
    except httpx.TimeoutException:
        error = f"Timed out contacting GitHub API after {timeout_s}s"
    except httpx.HTTPError as exc:
        error = f"HTTP error contacting GitHub API: {exc}"

    if not token and not error:
        warnings.append(
            "No CERTIQS_IMAGES_REGISTRY_TOKEN configured — only publicly "
            "listable packages (if any) are returned."
        )

    result = ImageCatalogResult(
        registry=registry,
        owner=owner,
        owner_kind=resolved_kind,
        authenticated=bool(token),
        images=sorted(images, key=lambda i: i.name.lower()),
        fetched_at=now,
        cache_hit=False,
        error=error,
        warnings=warnings,
        auth=auth,
    )
    if error is None:
        _CACHE[cache_key] = (now + max(cache_ttl_s, 0), result)
    return result


def clear_catalog_cache() -> None:
    _CACHE.clear()


__all__ = [
    "ImageCatalogResult",
    "ImageEntry",
    "ImageVersion",
    "clear_catalog_cache",
    "discover_ghcr_catalog",
    "registry_auth_guidance",
]
