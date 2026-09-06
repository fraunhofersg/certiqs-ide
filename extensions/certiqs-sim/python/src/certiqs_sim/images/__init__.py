"""GitHub Container Registry (ghcr.io) catalog discovery."""

from __future__ import annotations

from certiqs_sim.images.discovery import (
    ImageCatalogResult,
    discover_ghcr_catalog,
    registry_auth_guidance,
)

__all__ = [
    "ImageCatalogResult",
    "discover_ghcr_catalog",
    "registry_auth_guidance",
]
