"""FastAPI application factory for certiqs-api.

Versioned REST (``/api/v1``) + WebSocket and SSE streaming, published as an
OpenAPI schema for the Next.js typed client.  The API hosts one in-process twin
run (NetSquid one-per-process); scale-out is via multiple engine processes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from certiqs_sim.bus.base import Subscription
from certiqs_sim.bus.memory import InMemoryBus
from certiqs_sim.config.paths import iter_config_sets, resolve_config_name
from certiqs_sim.config.settings import Settings, get_settings
from certiqs_sim.core.attacks import list_attacks
from certiqs_sim.core.countermeasures import list_countermeasures
from certiqs_sim.core.protocols import list_protocols
from certiqs_sim.persistence.repository import build_repository
from certiqs_sim.runtime.params import (
    ATTACK_PARAM_META,
    BASE_PARAM_META,
    SELFTEST_MODES,
    SELFTEST_PARAM_META,
    default_params_for_config,
)
from certiqs_sim.services.api.manager import RunManager
from certiqs_sim.services.api.ops_router import create_ops_router
from certiqs_sim.runtime.sim_terminal import run_sim_prompt
from certiqs_sim.runtime.terminal import build_service_catalog
from certiqs_sim.services.api.schemas import (
    AcceptedResponse,
    AttackRequest,
    ConfigsResponse,
    HistoryResponse,
    MetaResponse,
    MetricsCatalogResponse,
    ForensicsConfigResponse,
    OptimizationConfigResponse,
    ParamsRequest,
    SelfTestRequest,
    SimTerminalExamplesResponse,
    SimTerminalPromptRequest,
    SimTerminalPromptResponse,
    SimTerminalServiceEntry,
    StartRunRequest,
    StatusResponse,
    TopologyEditsRequest,
    TopologyEditsResponse,
)
from certiqs_sim.services.common import add_health_and_metrics
from certiqs_sim.telemetry.logging import configure_logging, get_logger

_log = get_logger("certiqs.api")


async def _safe_ws_send(ws: WebSocket, message: dict[str, Any]) -> bool:
    try:
        await ws.send_json(message)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


async def _next_stream_message(
    sub: Subscription,
    *,
    coalesce_datapoints: bool,
) -> dict[str, Any] | None:
    message = await sub.queue.get()
    if not coalesce_datapoints or message.get("type") != "datapoint":
        return message

    # Drain backlog but keep the latest datapoint; flush non-datapoint messages in order.
    pending: list[dict[str, Any]] = []
    while True:
        try:
            nxt = sub.queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if nxt.get("type") == "datapoint":
            message = nxt
        else:
            pending.append(nxt)

    for item in pending:
        with contextlib.suppress(asyncio.QueueFull):
            sub.queue.put_nowait(item)
    return message


async def _pump_ws_stream(
    ws: WebSocket,
    sub: Subscription,
    *,
    coalesce_datapoints: bool,
) -> None:
    while True:
        message = await _next_stream_message(sub, coalesce_datapoints=coalesce_datapoints)
        if message is None:
            return
        if not await _safe_ws_send(ws, message):
            return


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    from certiqs_sim.runtime.preload import preload_netsquid

    preload_netsquid()
    configure_logging(
        settings.service_name,
        settings.log_level,
        settings.log_json,
        module_levels=settings.parsed_log_module_levels(),
    )

    from certiqs_sim.bus.factory import build_bus

    bus = build_bus(
        settings.bus_backend,
        nats_url=settings.nats_url,
        redis_url=settings.redis_url,
        ws_queue_max=settings.ws_queue_max,
    )
    repo = build_repository(settings.database_url if settings.persist_datapoints else None)
    manager = RunManager(settings, bus, repo)

    app = FastAPI(
        title="certiqsSim API",
        version="1.0",
        description="Control-plane + streaming API for the certiqsSim QKD Evaluation & Assurance Framework.",
    )
    app.state.settings = settings
    app.state.manager = manager
    app.state.bus = bus

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        if isinstance(bus, InMemoryBus):
            bus.set_loop(asyncio.get_running_loop())
        await bus.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        manager.stop_run(wait=True)
        await bus.close()

    # ── auth (optional) ───────────────────────────────────────────────────
    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and x_api_key != settings.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    add_health_and_metrics(
        app,
        service_name=settings.service_name,
        readiness=lambda: True,
    )

    app.include_router(create_ops_router(settings))
    try:
        from certiqs_sim.services.api.containers_router import create_containers_router
        from certiqs_sim.services.api.images_router import create_images_router

        app.include_router(create_containers_router(settings))
        app.include_router(create_images_router(settings))
    except ImportError:
        _log.info("containers/images routes omitted — optional extras are not installed")

    # ── static metadata ───────────────────────────────────────────────────
    @app.get("/api/v1/meta", response_model=MetaResponse, tags=["meta"])
    def get_meta() -> MetaResponse:
        return MetaResponse(
            base_params=BASE_PARAM_META,
            attack_params=ATTACK_PARAM_META,
            selftest_params=SELFTEST_PARAM_META,
            selftest_modes=SELFTEST_MODES,
            protocols=list_protocols(),
            attacks=list_attacks(),
            countermeasures=list_countermeasures(),
            default_shots_per_window=settings.shots_per_window,
        )

    @app.get("/api/v1/configs", response_model=ConfigsResponse, tags=["meta"])
    def get_configs() -> ConfigsResponse:
        configs = []
        root = settings.config_root
        if root.is_dir():
            for name in iter_config_sets(root):
                child = root / name
                entry: dict[str, Any] = {"name": name}
                try:
                    entry["defaults"] = default_params_for_config(child)
                except Exception as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                configs.append(entry)
        try:
            resolved_default = resolve_config_name(
                root, preferred=settings.default_config
            )
        except FileNotFoundError:
            resolved_default = ""
        return ConfigsResponse(
            config_root=str(root),
            default_config=resolved_default,
            configs=configs,
        )

    @app.get("/api/v1/metrics/catalog", response_model=MetricsCatalogResponse, tags=["meta"])
    def get_metrics_catalog() -> MetricsCatalogResponse:
        return MetricsCatalogResponse(metrics=manager.metrics_catalog())

    @app.get("/api/v1/forensics/config", response_model=ForensicsConfigResponse, tags=["meta"])
    def get_forensics_config(config: str | None = None) -> ForensicsConfigResponse:
        """Anomaly detection / forensics knobs from shared/forensics.yaml."""
        from certiqs_sim.runtime.forensics_config import load_forensics_config

        cfg_dir = manager.active_config_dir()
        if config:
            cfg_dir = _config_dir(config)
        return ForensicsConfigResponse(**load_forensics_config(cfg_dir))

    @app.get(
        "/api/v1/optimization/config",
        response_model=OptimizationConfigResponse,
        tags=["meta"],
    )
    def get_optimization_config(config: str | None = None) -> OptimizationConfigResponse:
        """Practical fibre-length optimization knobs from shared/optimization.yaml."""
        from certiqs_sim.runtime.optimization_config import load_optimization_config

        cfg_dir = manager.active_config_dir()
        if config:
            cfg_dir = _config_dir(config)
        return OptimizationConfigResponse(**load_optimization_config(cfg_dir))

    # ── CA-QKD component layer ────────────────────────────────────────────
    @app.get("/api/v1/components/models", tags=["components"])
    def get_component_models() -> dict[str, Any]:
        """Versioned component-model registry (component_class -> model)."""
        from certiqs_sim.core.components import list_component_models

        return {"models": [spec.as_dict() for spec in list_component_models()]}

    def _config_dir(config: str | None) -> Path:
        try:
            name = resolve_config_name(
                settings.config_root, config, preferred=settings.default_config
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return settings.config_root / name

    @app.get("/api/v1/components/taxonomy", tags=["components"])
    def get_component_taxonomy(config: str | None = None) -> dict[str, Any]:
        """Controlled component classification (categories, subcategories, icons)."""
        from certiqs_sim.core.components.catalog import load_taxonomy

        config_dir = _config_dir(config)
        taxonomy = load_taxonomy(config_dir)
        if taxonomy is None:
            taxonomy = {"taxonomy_id": "unspecified", "name": "No taxonomy", "categories": []}
        return {"component_taxonomy": taxonomy, "config": config_dir.name}

    @app.get("/api/v1/components/files", tags=["components"])
    def get_component_files(config: str | None = None) -> dict[str, Any]:
        """YAML documents available in one config subdirectory under config_root."""
        from certiqs_sim.core.components.catalog import list_config_documents

        config_dir = _config_dir(config)
        payload = list_config_documents(config_dir)
        payload["config"] = config_dir.name
        return payload

    @app.get("/api/v1/components/inventory", tags=["components"])
    def get_component_inventory(config: str | None = None) -> dict[str, Any]:
        """Resolved component inventory for one config set (design-graph view)."""
        from certiqs_sim.core.components.catalog import build_component_inventory

        config_dir = _config_dir(config)
        return build_component_inventory(config_dir)

    @app.get("/api/v1/components/topology", tags=["components"])
    def get_component_topology(config: str | None = None) -> dict[str, Any]:
        """Design-graph topology (nodes + connection edges) for one config set."""
        from certiqs_sim.core.components.topology import build_topology

        config_dir = _config_dir(config)
        return build_topology(config_dir)

    @app.post(
        "/api/v1/components/topology/edits",
        response_model=TopologyEditsResponse,
        tags=["components"],
    )
    def apply_topology_edits(req: TopologyEditsRequest) -> TopologyEditsResponse:
        """Persist connector-move / connection-rewire edits back to config YAML."""
        from certiqs_sim.core.topology.config_edit import (
            ConfigEditError,
            apply_config_edits,
        )

        config_dir = _config_dir(req.config)
        if not req.edits:
            raise HTTPException(status_code=422, detail="no edits provided")
        try:
            result = apply_config_edits(
                config_dir,
                [edit.model_dump(exclude_none=True) for edit in req.edits],
                backup=req.backup,
            )
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if settings.log_control_api:
            _log.info(
                "api_topology_edits",
                config=config_dir.name,
                applied=result["applied"],
                changed=result["changed_files"],
                backup=result["backup_dir"],
            )
        return TopologyEditsResponse(config=config_dir.name, **result)

    # ── run lifecycle ─────────────────────────────────────────────────────
    def _check_run(run_id: str) -> None:
        status = manager.status()
        if status.get("run_id") != run_id:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' is not active")

    def _list_container_rows() -> list[dict[str, Any]]:
        if not settings.containers_enabled:
            return []
        try:
            from certiqs_sim.containers import get_container_manager

            rows, _ = get_container_manager().list_services()
            return list(rows or [])
        except Exception:  # noqa: BLE001 — catalog is best-effort
            return []

    def _run_container_prompt(service_id: str, prompt: str) -> dict[str, Any]:
        if not settings.containers_enabled:
            raise RuntimeError("Containers are disabled")
        from certiqs_sim.containers import get_container_manager

        return get_container_manager().terminal_prompt(service_id, prompt)

    @app.post(
        "/api/v1/runs",
        response_model=StatusResponse,
        tags=["runs"],
        dependencies=[Depends(require_api_key)],
    )
    async def start_run(req: StartRunRequest) -> StatusResponse:
        try:
            status = manager.start_run(req)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if status.get("status") == "error":
            raise HTTPException(status_code=400, detail=status.get("error"))
        if settings.log_control_api:
            _log.info(
                "api_start_run",
                run_id=status.get("run_id"),
                config=req.config_name,
                protocol=req.protocol,
                shots_per_window=req.shots_per_window,
                attack_enabled=req.attack.get("enabled"),
                selftest_enabled=req.selftest.get("enabled"),
            )
        return StatusResponse(**status)

    @app.get("/api/v1/status", response_model=StatusResponse, tags=["runs"])
    def active_status() -> StatusResponse:
        return StatusResponse(**manager.status())

    @app.get("/api/v1/runs/{run_id}/status", response_model=StatusResponse, tags=["runs"])
    def run_status(run_id: str) -> StatusResponse:
        _check_run(run_id)
        return StatusResponse(**manager.status())

    @app.post(
        "/api/v1/runs/{run_id}/stop",
        response_model=StatusResponse,
        tags=["runs"],
        dependencies=[Depends(require_api_key)],
    )
    def stop_run(run_id: str) -> StatusResponse:
        _check_run(run_id)
        if settings.log_control_api:
            _log.info("api_stop_run", run_id=run_id)
        status = manager.stop_run()
        if settings.log_control_api:
            _log.info("api_stop_run_result", run_id=run_id, status=status.get("status"))
        return StatusResponse(**status)

    @app.post(
        "/api/v1/runs/{run_id}/params",
        response_model=AcceptedResponse,
        tags=["control"],
        dependencies=[Depends(require_api_key)],
    )
    def set_params(run_id: str, req: ParamsRequest) -> AcceptedResponse:
        _check_run(run_id)
        if settings.log_control_api:
            _log.info("api_set_params", run_id=run_id, overrides=req.overrides)
        manager.require_worker().submit_params(req.overrides)
        return AcceptedResponse(accepted=req.overrides)

    @app.post(
        "/api/v1/runs/{run_id}/attack",
        response_model=AcceptedResponse,
        tags=["control"],
        dependencies=[Depends(require_api_key)],
    )
    def set_attack(run_id: str, req: AttackRequest) -> AcceptedResponse:
        _check_run(run_id)
        body = req.model_dump()
        if settings.log_control_api:
            _log.info(
                "api_set_attack",
                run_id=run_id,
                enabled=req.enabled,
                eve_eff=req.eve_eff,
                extra_loss=req.extra_loss,
            )
        manager.require_worker().submit_attack(body)
        return AcceptedResponse(accepted=body)

    @app.post(
        "/api/v1/runs/{run_id}/selftest",
        response_model=AcceptedResponse,
        tags=["control"],
        dependencies=[Depends(require_api_key)],
    )
    def set_selftest(run_id: str, req: SelfTestRequest) -> AcceptedResponse:
        _check_run(run_id)
        body = req.model_dump()
        if settings.log_control_api:
            _log.info(
                "api_set_selftest",
                run_id=run_id,
                enabled=req.enabled,
                mode=req.mode,
            )
        manager.require_worker().submit_selftest(body)
        return AcceptedResponse(accepted=body)

    @app.get(
        "/api/v1/runs/{run_id}/terminal/examples",
        response_model=SimTerminalExamplesResponse,
        tags=["control"],
    )
    def sim_terminal_examples(run_id: str) -> SimTerminalExamplesResponse:
        _check_run(run_id)
        catalog = build_service_catalog(list_containers=_list_container_rows)
        attacks = catalog.by_kind("attack")
        cms = catalog.by_kind("countermeasure")
        return SimTerminalExamplesResponse(
            run_id=run_id,
            example_prompts=catalog.example_prompts(),
            services=[SimTerminalServiceEntry(**s.to_dict()) for s in catalog.services],
            attack=attacks[0].id if attacks else "faked_state",
            countermeasure=cms[0].id if cms else "detector_selftest",
        )

    @app.post(
        "/api/v1/runs/{run_id}/terminal",
        response_model=SimTerminalPromptResponse,
        tags=["control"],
        dependencies=[Depends(require_api_key)],
    )
    def sim_terminal_prompt(
        run_id: str, req: SimTerminalPromptRequest
    ) -> SimTerminalPromptResponse:
        _check_run(run_id)
        worker = manager.require_worker()

        def _apply_attack(payload: dict[str, Any]) -> dict[str, Any]:
            worker.submit_attack(payload)
            return payload

        def _apply_selftest(payload: dict[str, Any]) -> dict[str, Any]:
            worker.submit_selftest(payload)
            return payload

        def _apply_params(overrides: dict[str, float]) -> dict[str, float]:
            worker.submit_params(overrides)
            return overrides

        raw = run_sim_prompt(
            req.prompt,
            run_status=worker.get_status(),
            current_attack=worker.get_current_attack(),
            current_selftest=worker.get_current_selftest(),
            apply_attack=_apply_attack,
            apply_selftest=_apply_selftest,
            apply_params=_apply_params,
            run_container_prompt=_run_container_prompt,
            list_containers=_list_container_rows,
            get_history=lambda: worker.get_history(),
            get_settings_for_epoch=worker.get_settings_for_epoch,
        )
        if settings.log_control_api:
            _log.info(
                "api_sim_terminal",
                run_id=run_id,
                prompt=req.prompt,
                ok=raw.get("ok"),
                applied=(raw.get("applied") or {}).get("kind"),
            )
        return SimTerminalPromptResponse(run_id=run_id, prompt=req.prompt, **raw)

    @app.get("/api/v1/runs/{run_id}/history", response_model=HistoryResponse, tags=["runs"])
    def get_history(run_id: str, since: int = -1) -> HistoryResponse:
        _check_run(run_id)
        return HistoryResponse(points=manager.require_worker().get_history(since))

    @app.get("/api/v1/runs/{run_id}/epochs/{epoch}/settings", tags=["provenance"])
    def get_point_settings(run_id: str, epoch: int) -> dict[str, Any]:
        _check_run(run_id)
        snap = manager.require_worker().get_settings_for_epoch(epoch)
        if snap is None:
            raise HTTPException(status_code=404, detail=f"No settings for epoch {epoch}")
        return snap

    # ── streaming: WebSocket + SSE ────────────────────────────────────────
    async def _prime_messages(run_id: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"type": "catalog", "data": manager.metrics_catalog()}]
        status = manager.status()
        if status.get("run_id") == run_id:
            messages.append({"type": "status", "data": status})
            try:
                history = manager.require_worker().get_history()
            except RuntimeError:
                history = []
            # Cap initial sync so reconnects do not flood the browser.
            if len(history) > 500:
                history = history[-500:]
            messages.append({"type": "history", "data": history})
        return messages

    @app.websocket("/api/v1/runs/{run_id}/stream")
    async def stream_ws(ws: WebSocket, run_id: str) -> None:
        await ws.accept()
        subject = f"{settings.bus_subject_prefix}.runs.{run_id}.*"
        sub: Subscription = await bus.subscribe(subject)
        try:
            for msg in await _prime_messages(run_id):
                if not await _safe_ws_send(ws, msg):
                    return
            await _pump_ws_stream(
                ws,
                sub,
                coalesce_datapoints=settings.ws_coalesce_datapoints,
            )
        except WebSocketDisconnect:
            pass
        finally:
            await bus.unsubscribe(sub)

    @app.get("/api/v1/runs/{run_id}/events", tags=["runs"])
    async def stream_sse(run_id: str) -> EventSourceResponse:
        subject = f"{settings.bus_subject_prefix}.runs.{run_id}.*"
        sub = await bus.subscribe(subject)

        async def _event_gen() -> AsyncIterator[dict[str, str]]:
            try:
                for msg in await _prime_messages(run_id):
                    yield {"event": msg["type"], "data": json.dumps(msg["data"])}
                while True:
                    message = await _next_stream_message(
                        sub,
                        coalesce_datapoints=settings.ws_coalesce_datapoints,
                    )
                    if message is None:
                        break
                    yield {
                        "event": message.get("type", "message"),
                        "data": json.dumps(message.get("data", message)),
                    }
            finally:
                await bus.unsubscribe(sub)

        return EventSourceResponse(_event_gen())

    # ── frontend (served at / for convenience in dev) ─────────────────────
    @app.get("/", include_in_schema=False)
    def index() -> Any:
        index_html = settings.frontend_dir / "index.html"
        if index_html.is_file():
            return FileResponse(index_html)
        return JSONResponse({"service": settings.service_name, "docs": "/docs"})

    return app


__all__ = ["create_app"]
