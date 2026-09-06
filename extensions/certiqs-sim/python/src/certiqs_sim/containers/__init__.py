"""Managed external worker containers (GHCR images + Docker runtime)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from certiqs_sim.containers.manager import ContainerManager

__all__ = ["ContainerManager", "get_container_manager"]


def __getattr__(name: str) -> Any:
    if name == "ContainerManager":
        from certiqs_sim.containers.manager import ContainerManager as _ContainerManager

        return _ContainerManager
    if name == "get_container_manager":
        from certiqs_sim.containers.manager import get_container_manager as _get

        return _get
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
