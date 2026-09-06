"""Post-processing microservice: consume sifted blocks, publish secure-key results."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from certiqs_sim.bus.base import postproc_subject
from certiqs_sim.bus.factory import build_bus
from certiqs_sim.bus.memory import InMemoryBus
from certiqs_sim.config.paths import resolve_config_name
from certiqs_sim.config.settings import Settings, get_settings
from certiqs_sim.postprocessing.pipeline import PostProcessor
from certiqs_sim.services.common import add_health_and_metrics
from certiqs_sim.telemetry.logging import configure_logging, get_logger
from certiqs_sim.telemetry.metrics import METRICS

_log = get_logger("certiqs.postproc")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging("certiqs-postproc", settings.log_level, settings.log_json)

    bus = build_bus(settings.bus_backend, nats_url=settings.nats_url, redis_url=settings.redis_url)
    try:
        config_name = resolve_config_name(
            settings.config_root, preferred=settings.default_config
        )
        post = PostProcessor.from_config_dir(settings.config_root / config_name)
    except FileNotFoundError as exc:
        _log.warning("postproc_no_config", reason=str(exc))
        post = PostProcessor()

    app = FastAPI(title="certiqsSim Post-Processing", version="1.0")
    app.state.processed = 0

    add_health_and_metrics(app, service_name="certiqs-postproc")

    async def _consume() -> None:
        subject = f"{settings.bus_subject_prefix}.runs.*.sifted"
        sub = await bus.subscribe(subject)
        _log.info("postproc_subscribed", subject=subject)
        while True:
            msg = await sub.queue.get()
            a = msg.get("sifted_bits_alice")
            b = msg.get("sifted_bits_bob")
            if a is None or b is None:
                continue
            run_id = msg.get("run_id", "unknown")
            epoch = int(msg.get("epoch", 0))
            result = await asyncio.to_thread(post.process, a, b, epoch)
            METRICS.postproc_secure_key_bits_total.labels(
                service="certiqs-postproc", run_id=run_id, protocol=settings.protocol
            ).inc(float(result.secure_key_bits))
            await bus.publish(
                postproc_subject(settings.bus_subject_prefix, run_id),
                {"type": "postproc", "data": {"epoch": epoch, **result.as_metrics()}},
            )
            app.state.processed += 1

    @app.on_event("startup")
    async def _startup() -> None:
        if isinstance(bus, InMemoryBus):
            bus.set_loop(asyncio.get_running_loop())
        await bus.start()
        app.state.task = asyncio.ensure_future(_consume())

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        task = getattr(app.state, "task", None)
        if task is not None:
            task.cancel()
        await bus.close()

    @app.get("/status", tags=["postproc"])
    def status() -> dict[str, Any]:
        return {"status": "running", "processed_blocks": app.state.processed}

    @app.post("/process", tags=["postproc"])
    def process_block(payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronously post-process a sifted block (for testing / ad-hoc use)."""
        a = payload.get("sifted_bits_alice", [])
        b = payload.get("sifted_bits_bob", [])
        seed = int(payload.get("seed", 0))
        return post.process(a, b, seed).as_metrics()

    return app


__all__ = ["create_app"]
