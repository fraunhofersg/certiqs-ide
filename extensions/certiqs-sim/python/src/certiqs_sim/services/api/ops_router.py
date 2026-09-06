"""Platform operations API — service lifecycle, health, logs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from certiqs_sim.config.settings import Settings
from certiqs_sim.ops import get_supervisor
from certiqs_sim.services.api.schemas import (
    OpsActionResponse,
    OpsBulkActionResponse,
    OpsLogsResponse,
    OpsPlatformResponse,
    OpsServicesResponse,
    OpsServiceStatus,
)

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


def _require_ops(settings: Settings) -> None:
    if not settings.ops_enabled:
        raise HTTPException(status_code=404, detail="Platform ops API is disabled")


def _require_api_key(settings: Settings, x_api_key: str | None) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _action_from_result(raw: dict[str, Any]) -> OpsActionResponse:
    return OpsActionResponse(
        id=str(raw.get("id", "")),
        ok=bool(raw.get("ok", True)),
        action=raw.get("action"),
        backend=raw.get("backend"),
        note=raw.get("note"),
        pid=raw.get("pid"),
        error=raw.get("error"),
    )


def create_ops_router(settings: Settings) -> APIRouter:
    sup = get_supervisor()

    def ops_guard() -> None:
        _require_ops(settings)

    def write_guard(x_api_key: str | None = Header(default=None)) -> None:
        ops_guard()
        _require_api_key(settings, x_api_key)

    @router.get("/platform", response_model=OpsPlatformResponse)
    def platform() -> OpsPlatformResponse:
        ops_guard()
        return OpsPlatformResponse(**sup.platform_info())

    @router.get("/services", response_model=OpsServicesResponse)
    def list_services() -> OpsServicesResponse:
        ops_guard()
        info = sup.platform_info()
        services = [OpsServiceStatus(**row) for row in sup.list_services()]
        return OpsServicesResponse(platform=OpsPlatformResponse(**info), services=services)

    @router.post(
        "/services/{service_id}/start",
        response_model=OpsActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def start_service(service_id: str) -> OpsActionResponse:
        try:
            return _action_from_result(sup.start(service_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(
        "/services/{service_id}/stop",
        response_model=OpsActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def stop_service(service_id: str) -> OpsActionResponse:
        try:
            return _action_from_result(sup.stop(service_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(
        "/services/start-all",
        response_model=OpsBulkActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def start_all(apps_only: bool = True) -> OpsBulkActionResponse:
        results = [_action_from_result(r) for r in sup.start_all(apps_only=apps_only)]
        return OpsBulkActionResponse(results=results)

    @router.post(
        "/services/stop-all",
        response_model=OpsBulkActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def stop_all(apps_only: bool = True) -> OpsBulkActionResponse:
        results = [_action_from_result(r) for r in sup.stop_all(apps_only=apps_only)]
        return OpsBulkActionResponse(results=results)

    @router.post(
        "/stack/start",
        response_model=OpsBulkActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def start_stack() -> OpsBulkActionResponse:
        """Start infra (docker) then all app services."""
        infra = [_action_from_result(r) for r in sup.start_all(apps_only=False)]
        apps = [_action_from_result(r) for r in sup.start_all(apps_only=True)]
        return OpsBulkActionResponse(results=infra + apps)

    @router.post(
        "/stack/stop",
        response_model=OpsBulkActionResponse,
        dependencies=[Depends(write_guard)],
    )
    def stop_stack() -> OpsBulkActionResponse:
        apps = [_action_from_result(r) for r in sup.stop_all(apps_only=True)]
        infra = [_action_from_result(r) for r in sup.stop_all(apps_only=False)]
        return OpsBulkActionResponse(results=apps + infra)

    @router.get("/services/{service_id}/logs", response_model=OpsLogsResponse)
    def service_logs(service_id: str, tail: int = 200) -> OpsLogsResponse:
        ops_guard()
        try:
            raw = sup.get_logs(service_id, tail=min(max(tail, 1), 2000))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return OpsLogsResponse(**raw)

    return router


__all__ = ["create_ops_router", "router"]
