"""FastAPI wrapper around a single continuously-running twin worker.

The engine auto-starts a run from settings on startup and streams datapoints /
sifted blocks to the bus.  It also exposes a minimal control surface so an
operator (or the API gateway) can retune parameters, toggle the attack, or toggle
the countermeasure without restarting the pod.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from certiqs_sim.bus.factory import build_bus
from certiqs_sim.bus.memory import InMemoryBus
from certiqs_sim.config.paths import resolve_config_name
from certiqs_sim.config.settings import Settings, get_settings
from certiqs_sim.persistence.repository import build_repository
from certiqs_sim.postprocessing.pipeline import PostProcessor
from certiqs_sim.runtime.metrics_registry import MetricRegistry
from certiqs_sim.runtime.worker import TwinWorker
from certiqs_sim.services.common import add_health_and_metrics
from certiqs_sim.telemetry.logging import configure_logging, get_logger

_log = get_logger("certiqs.engine")


def _post_process_hook(config_dir: Any) -> Any:
    post = PostProcessor.from_config_dir(config_dir)
    counter = {"n": 0}

    def hook(results: dict[str, Any]) -> dict[str, Any]:
        a = results.get("sifted_bits_alice")
        b = results.get("sifted_bits_bob")
        if a is None or b is None:
            return results
        counter["n"] += 1
        results.update(post.process(a, b, seed=counter["n"]).as_metrics())
        results.pop("sifted_bits_alice", None)
        results.pop("sifted_bits_bob", None)
        return results

    return hook


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        "certiqs-engine",
        settings.log_level,
        settings.log_json,
        module_levels=settings.parsed_log_module_levels(),
    )

    bus = build_bus(
        settings.bus_backend,
        nats_url=settings.nats_url,
        redis_url=settings.redis_url,
        ws_queue_max=settings.ws_queue_max,
    )
    repo = build_repository(settings.database_url if settings.persist_datapoints else None)

    app = FastAPI(title="certiqsSim Engine", version="1.0")
    app.state.worker = None

    add_health_and_metrics(
        app,
        service_name="certiqs-engine",
        readiness=lambda: (
            getattr(app.state, "worker", None) is not None and app.state.worker.status == "running"
        ),
    )

    @app.on_event("startup")
    async def _startup() -> None:
        if isinstance(bus, InMemoryBus):
            bus.set_loop(asyncio.get_running_loop())
        await bus.start()

        try:
            config_name = resolve_config_name(
                settings.config_root, preferred=settings.default_config
            )
        except FileNotFoundError as exc:
            _log.warning("engine_skip_autostart", reason=str(exc))
            return

        config_dir = settings.config_root / config_name
        worker = TwinWorker(
            config_dir=settings.config_root,
            config_name=config_name,
            run_id="engine",
            protocol=settings.protocol,
            shots_per_window=settings.shots_per_window,
            min_period_s=settings.min_window_period_s,
            collect_sifted=settings.collect_sifted,
            bus=bus,
            bus_prefix=settings.bus_subject_prefix,
            repository=repo,
            registry=MetricRegistry(),
            service_name="certiqs-engine",
            post_process=_post_process_hook(config_dir) if settings.collect_sifted else None,
            log_window_epochs=settings.log_window_epochs,
            log_control=settings.log_control_api,
            povm_service_target=(
                settings.povm_service_target if settings.povm_service_enabled else None
            ),
            povm_service_timeout_s=settings.povm_service_timeout_s,
            povm_service_strict=settings.povm_service_strict,
            povm_backend=settings.povm_backend,
            povm_local_cutoff_dim=settings.povm_local_cutoff_dim,
        )
        worker.start()
        app.state.worker = worker
        _log.info("engine_worker_launched", config=config_name)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        worker = getattr(app.state, "worker", None)
        if worker is not None:
            worker.stop()
            worker.join(timeout=10)
        await bus.close()

    @app.get("/status", tags=["engine"])
    def status() -> dict[str, Any]:
        worker = getattr(app.state, "worker", None)
        return worker.get_status() if worker is not None else {"status": "idle"}

    @app.post("/control/params", tags=["engine"])
    def params(overrides: dict[str, float]) -> dict[str, Any]:
        app.state.worker.submit_params(overrides)
        return {"accepted": overrides}

    @app.post("/control/attack", tags=["engine"])
    def attack(settings_body: dict[str, Any]) -> dict[str, Any]:
        app.state.worker.submit_attack(settings_body)
        return {"accepted": settings_body}

    @app.post("/control/selftest", tags=["engine"])
    def selftest(settings_body: dict[str, Any]) -> dict[str, Any]:
        app.state.worker.submit_selftest(settings_body)
        return {"accepted": settings_body}

    return app


__all__ = ["create_app"]
