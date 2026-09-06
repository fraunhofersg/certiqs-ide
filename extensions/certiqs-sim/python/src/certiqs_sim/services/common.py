"""Shared FastAPI helpers: health probes and Prometheus metrics endpoint.

Every service mounts the same ``/healthz`` (liveness), ``/readyz`` (readiness) and
``/metrics`` endpoints so Kubernetes probes and Prometheus scraping are uniform.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Response

from certiqs_sim import __version__
from certiqs_sim.telemetry.metrics import CONTENT_TYPE_LATEST, render_latest_metrics


def add_health_and_metrics(
    app: FastAPI,
    *,
    service_name: str,
    readiness: Callable[[], bool] | None = None,
) -> None:
    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "service": service_name, "version": __version__}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> Response:
        ready = readiness() if readiness is not None else True
        body = {"status": "ready" if ready else "not_ready", "service": service_name}
        return Response(
            content=__import__("json").dumps(body),
            media_type="application/json",
            status_code=200 if ready else 503,
        )

    @app.get("/metrics", tags=["ops"])
    def metrics() -> Response:
        return Response(content=render_latest_metrics(), media_type=CONTENT_TYPE_LATEST)


__all__ = ["add_health_and_metrics"]
