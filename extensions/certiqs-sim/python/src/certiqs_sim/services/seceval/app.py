"""Security-evaluation service: run campaigns and return reproducible reports."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI

from certiqs_sim.config.settings import Settings, get_settings
from certiqs_sim.services.common import add_health_and_metrics
from certiqs_sim.services.seceval.campaign import CampaignSpec, run_campaign
from certiqs_sim.services.seceval.report import build_report
from certiqs_sim.telemetry.logging import configure_logging, get_logger

_log = get_logger("certiqs.seceval")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging("certiqs-seceval", settings.log_level, settings.log_json)

    app = FastAPI(title="certiqsSim Security Evaluation", version="1.0")
    # Only one campaign runs at a time (NetSquid one-twin-per-process).
    app.state.lock = asyncio.Lock()

    add_health_and_metrics(app, service_name="certiqs-seceval")

    @app.post("/api/v1/campaigns/run", tags=["seceval"])
    async def run(spec: CampaignSpec) -> dict[str, Any]:
        async with app.state.lock:
            results = await asyncio.to_thread(run_campaign, spec, settings.config_root)
        report = build_report(spec, results)
        _log.info("campaign_report", name=spec.name, digest=report.digest)
        return report.to_dict()

    @app.get("/api/v1/campaigns/example", tags=["seceval"])
    def example() -> dict[str, Any]:
        return CampaignSpec().model_dump()

    return app


__all__ = ["create_app"]
