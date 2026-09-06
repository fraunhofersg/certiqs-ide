"""External GHCR worker containers — deploy / start / stop / inspect / logs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from certiqs_sim.config.settings import Settings
from certiqs_sim.containers import get_container_manager
from certiqs_sim.services.api.schemas import (
    ContainerActionResponse,
    ContainerDeployRequest,
    ContainerDeploymentJob,
    ContainerInspectResponse,
    ContainerLogsResponse,
    ContainerServiceStatus,
    ContainerServicesResponse,
    ContainerTerminalCapabilitiesResponse,
    ContainerTerminalPromptRequest,
    ContainerTerminalPromptResponse,
)


def _require_containers(settings: Settings) -> None:
    if not settings.containers_enabled:
        raise HTTPException(status_code=404, detail="Container management API is disabled")


def _require_api_key(settings: Settings, x_api_key: str | None) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _action(raw: dict[str, Any]) -> ContainerActionResponse:
    return ContainerActionResponse(
        id=str(raw.get("id", "")),
        ok=bool(raw.get("ok", True)),
        action=raw.get("action"),
        backend=raw.get("backend"),
        note=raw.get("note"),
        container_id=raw.get("container_id"),
        error=raw.get("error"),
        job_id=raw.get("job_id"),
    )


def create_containers_router(settings: Settings) -> APIRouter:
    # Fresh router per app instance — avoids missing routes when the module-level
    # singleton was imported before newer endpoints existed.
    router = APIRouter(prefix="/api/v1/ops/containers", tags=["containers"])
    manager = get_container_manager()

    def guard() -> None:
        _require_containers(settings)

    def write_guard(x_api_key: str | None = Header(default=None)) -> None:
        guard()
        _require_api_key(settings, x_api_key)

    @router.get("", response_model=ContainerServicesResponse)
    def list_containers() -> ContainerServicesResponse:
        guard()
        services_raw, catalog = manager.list_services()
        services = [ContainerServiceStatus(**row) for row in services_raw]
        return ContainerServicesResponse(
            docker_available=manager.docker_ok(),
            registry=str(catalog.get("registry") or settings.images_registry),
            owner=str(catalog.get("owner") or settings.images_registry_owner or ""),
            owner_kind=str(catalog.get("owner_kind") or ""),
            authenticated=bool(catalog.get("authenticated")),
            catalog_error=catalog.get("error"),
            catalog_warnings=list(catalog.get("warnings") or []),
            services=services,
        )

    @router.post(
        "/{service_id}/deployments",
        response_model=ContainerDeploymentJob,
        dependencies=[Depends(write_guard)],
    )
    def create_deployment(
        service_id: str,
        body: ContainerDeployRequest = Body(default_factory=ContainerDeployRequest),
    ) -> ContainerDeploymentJob:
        try:
            return ContainerDeploymentJob(
                **manager.start_deployment(service_id, pull=body.pull, tag=body.tag)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get(
        "/{service_id}/deployments/latest",
        response_model=ContainerDeploymentJob,
    )
    def latest_deployment(service_id: str) -> ContainerDeploymentJob:
        guard()
        try:
            raw = manager.latest_deployment(service_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if raw is None:
            raise HTTPException(status_code=404, detail="No deployment jobs yet")
        return ContainerDeploymentJob(**raw)

    @router.get(
        "/{service_id}/deployments/{job_id}",
        response_model=ContainerDeploymentJob,
    )
    def get_deployment(service_id: str, job_id: str) -> ContainerDeploymentJob:
        guard()
        try:
            return ContainerDeploymentJob(**manager.get_deployment(service_id, job_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/{service_id}/deploy",
        response_model=ContainerDeploymentJob,
        dependencies=[Depends(write_guard)],
    )
    def deploy_container(
        service_id: str,
        pull: bool | None = Query(None, description="Pull image before deploy (default true)"),
        tag: str | None = Query(None, description="Optional image tag override"),
    ) -> ContainerDeploymentJob:
        """Start an async deployment and return the job (poll deployments endpoints)."""
        try:
            return ContainerDeploymentJob(
                **manager.start_deployment(
                    service_id,
                    pull=True if pull is None else pull,
                    tag=tag,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(
        "/{service_id}/start",
        response_model=ContainerActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def start_container(service_id: str) -> ContainerActionResponse:
        try:
            return _action(manager.start(service_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(
        "/{service_id}/stop",
        response_model=ContainerActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def stop_container(service_id: str) -> ContainerActionResponse:
        try:
            return _action(manager.stop(service_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(
        "/{service_id}/remove",
        response_model=ContainerActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def remove_container(service_id: str) -> ContainerActionResponse:
        try:
            return _action(manager.remove(service_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/{service_id}/logs", response_model=ContainerLogsResponse)
    def container_logs(service_id: str, tail: int = 200) -> ContainerLogsResponse:
        guard()
        try:
            raw = manager.logs(service_id, tail=min(max(tail, 1), 2000))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ContainerLogsResponse(**raw)

    @router.get(
        "/{service_id}/terminal/capabilities",
        response_model=ContainerTerminalCapabilitiesResponse,
    )
    def terminal_capabilities(service_id: str) -> ContainerTerminalCapabilitiesResponse:
        guard()
        try:
            return ContainerTerminalCapabilitiesResponse(
                **manager.terminal_capabilities(service_id)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/{service_id}/terminal",
        response_model=ContainerTerminalPromptResponse,
        dependencies=[Depends(write_guard)],
    )
    def terminal_prompt(
        service_id: str,
        body: ContainerTerminalPromptRequest,
    ) -> ContainerTerminalPromptResponse:
        guard()
        try:
            return ContainerTerminalPromptResponse(
                **manager.terminal_prompt(service_id, body.prompt)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Keep catch-all inspect AFTER more specific /{id}/… routes.
    @router.get("/{service_id}", response_model=ContainerInspectResponse)
    def inspect_container(service_id: str) -> ContainerInspectResponse:
        guard()
        try:
            return ContainerInspectResponse(**manager.inspect(service_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


__all__ = ["create_containers_router"]
