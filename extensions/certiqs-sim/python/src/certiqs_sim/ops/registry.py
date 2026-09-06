"""Canonical service catalog for certiqsSim (apps + PaaS infrastructure)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ServiceKind = Literal["app", "infra"]
HealthKind = Literal["http", "tcp", "none"]


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    id: str
    name: str
    kind: ServiceKind
    port: int
    description: str
    health_kind: HealthKind = "http"
    health_path: str = "/healthz"
    compose_name: str | None = None
    """Docker Compose service name (when using compose backend)."""
    command: tuple[str, ...] | None = None
    """Local subprocess argv tail (after python/entrypoint)."""
    self_managed: bool = False
    """True for the current API process — start/stop not supported via ops."""


def build_service_catalog(base_port: int = 8011) -> list[ServiceSpec]:
    return [
        ServiceSpec(
            id="api",
            name="certiqs-api",
            kind="app",
            port=base_port,
            description="Control plane — REST, WebSocket, ops gateway",
            self_managed=True,
        ),
        ServiceSpec(
            id="engine",
            name="certiqs-engine",
            kind="app",
            port=base_port + 1,
            description="NetSquid twin worker (one twin per process)",
            command=("certiqs-engine",),
        ),
        ServiceSpec(
            id="postproc",
            name="certiqs-postproc",
            kind="app",
            port=base_port + 2,
            description="Classical post-processing consumer",
            command=("certiqs-postproc",),
        ),
        ServiceSpec(
            id="seceval",
            name="certiqs-seceval",
            kind="app",
            port=base_port + 3,
            description="Security-evaluation campaigns (HTTP mode)",
            command=("certiqs-seceval", "--serve"),
        ),
        ServiceSpec(
            id="nats",
            name="nats",
            kind="infra",
            port=4222,
            description="Event bus (NATS JetStream)",
            health_kind="tcp",
            compose_name="nats",
        ),
        ServiceSpec(
            id="postgres",
            name="postgres",
            kind="infra",
            port=5432,
            description="PostgreSQL persistence",
            health_kind="tcp",
            compose_name="postgres",
        ),
        ServiceSpec(
            id="prometheus",
            name="prometheus",
            kind="infra",
            port=9090,
            description="Metrics scrape + TSDB",
            health_path="/-/healthy",
            compose_name="prometheus",
        ),
        ServiceSpec(
            id="grafana",
            name="grafana",
            kind="infra",
            port=3000,
            description="Dashboards (Compose stack)",
            health_path="/api/health",
            compose_name="grafana",
        ),
    ]


def service_by_id(service_id: str, base_port: int = 8011) -> ServiceSpec:
    for spec in build_service_catalog(base_port):
        if spec.id == service_id:
            return spec
    raise KeyError(service_id)


__all__ = ["ServiceKind", "HealthKind", "ServiceSpec", "build_service_catalog", "service_by_id"]
