"""Container image catalog API — GHCR / GitHub Packages discovery."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from certiqs_sim.config.settings import Settings
from certiqs_sim.images.discovery import clear_catalog_cache, discover_ghcr_catalog
from certiqs_sim.services.api.schemas import (
    ContainerImageCatalogResponse,
    ContainerImageEntry,
    ImageRegistryAuthInfo,
    ImageVersionEntry,
)

router = APIRouter(prefix="/api/v1/images", tags=["images"])


def _require_images(settings: Settings) -> None:
    if not settings.images_catalog_enabled:
        raise HTTPException(status_code=404, detail="Image catalog API is disabled")


def create_images_router(settings: Settings) -> APIRouter:
    @router.get("/catalog", response_model=ContainerImageCatalogResponse)
    def get_image_catalog(
        refresh: bool = Query(False, description="Bypass cache and re-query GitHub"),
        include_versions: bool | None = Query(
            None, description="Override CERTIQS_IMAGES_INCLUDE_VERSIONS"
        ),
    ) -> ContainerImageCatalogResponse:
        _require_images(settings)
        if refresh:
            clear_catalog_cache()

        result = discover_ghcr_catalog(
            owner=settings.images_registry_owner,
            owner_kind=settings.images_registry_owner_kind,
            token=settings.images_registry_token,
            registry=settings.images_registry,
            include_versions=(
                settings.images_include_versions
                if include_versions is None
                else include_versions
            ),
            max_versions_per_image=settings.images_max_versions,
            cache_ttl_s=settings.images_cache_ttl_s,
        )

        images = [
            ContainerImageEntry(
                name=img.name,
                full_name=img.full_name,
                registry=img.registry,
                pull_ref=img.pull_ref,
                visibility=img.visibility,
                description=img.description,
                html_url=img.html_url,
                created_at=img.created_at,
                updated_at=img.updated_at,
                owner=img.owner,
                owner_kind=img.owner_kind,
                latest_tags=img.latest_tags,
                latest_digest=img.latest_digest,
                version_count=img.version_count,
                versions=[ImageVersionEntry(**v.as_dict()) for v in img.versions],
            )
            for img in result.images
        ]
        return ContainerImageCatalogResponse(
            registry=result.registry,
            owner=result.owner,
            owner_kind=result.owner_kind,
            authenticated=result.authenticated,
            image_count=len(images),
            images=images,
            fetched_at=result.fetched_at,
            cache_hit=result.cache_hit,
            error=result.error,
            warnings=result.warnings,
            auth=ImageRegistryAuthInfo(**result.auth),
        )

    return router


__all__ = ["create_images_router"]
