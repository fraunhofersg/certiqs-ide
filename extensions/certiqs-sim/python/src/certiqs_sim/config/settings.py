"""Environment-driven service settings (pydantic-settings).

One settings object drives every service.  Values come from environment variables
prefixed ``CERTIQS_`` (or a ``.env`` file), so the same image runs in dev,
docker-compose, and Kubernetes with configuration injected per environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CERTIQS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── identity / logging ────────────────────────────────────────────────
    service_name: str = "certiqs"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    # Comma-separated logger=LEVEL pairs, e.g. certiqs.engine=WARNING,certiqs.api=INFO
    log_module_levels: str = ""
    # Per-epoch window_done lines are very chatty at INFO; enable only when debugging.
    log_window_epochs: bool = False
    uvicorn_access_log: bool = False
    # Log control-plane API calls (start/stop/params/attack/selftest).
    log_control_api: bool = True

    # ── streaming backpressure ────────────────────────────────────────────
    # Bounded bus queue per WS/SSE subscriber; oldest messages dropped when full.
    ws_queue_max: int = 256
    # When the WS sender falls behind, skip intermediate datapoints and send the latest.
    ws_coalesce_datapoints: bool = True

    # ── config manifests ──────────────────────────────────────────────────
    config_root: Path = Field(default=_REPO_ROOT / "config")
    # Optional preferred config set name; when unset, the first subdirectory under
    # config_root that contains YAML is used. Never auto-creates files.
    default_config: str = ""

    # ── HTTP / API ────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8011
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    api_key: str | None = None  # when set, /api/v1 requires this key

    # ── engine ────────────────────────────────────────────────────────────
    shots_per_window: int = 100_000
    protocol: str = "bbm92"
    min_window_period_s: float = 0.0
    collect_sifted: bool = True  # emit raw sifted blocks for post-processing

    # ── rx-povm theory microservice ───────────────────────────────────────
    # When enabled the receiver's optical POVM is computed by the external
    # rx-povm service instead of the local analytic model. Dark counts, dead
    # time and afterpulsing stay local in both cases.
    povm_service_enabled: bool = False
    #: Which POVM source to use once enabled. ``local`` computes them in-process
    #: with ``receiver_lib``; ``service`` calls the rx-povm container over gRPC;
    #: ``auto`` prefers ``local`` when importable and falls back to ``service``.
    povm_backend: Literal["auto", "local", "service"] = "auto"
    povm_service_target: str = "127.0.0.1:50051"
    povm_service_timeout_s: float = 120.0
    #: Fail the run when no POVM backend is usable instead of silently falling
    #: back to the local analytic model.
    povm_service_strict: bool = False
    #: Fock-space truncation for the in-process backend. The single-photon block
    #: the twin consumes is independent of this, so 1 is sufficient.
    povm_local_cutoff_dim: int = 1

    # ── event backbone ────────────────────────────────────────────────────
    bus_backend: Literal["memory", "nats", "redis"] = "memory"
    nats_url: str = "nats://127.0.0.1:4222"
    redis_url: str = "redis://127.0.0.1:6379/0"
    bus_subject_prefix: str = "certiqs"

    # ── persistence ───────────────────────────────────────────────────────
    database_url: str | None = None  # e.g. postgresql+psycopg://user:pass@db/certiqs
    persist_datapoints: bool = True

    # ── metrics ───────────────────────────────────────────────────────────
    metrics_enabled: bool = True

    # ── platform ops (service supervisor UI) ──────────────────────────────
    ops_enabled: bool = True
    ops_mode: Literal["auto", "local", "docker"] = "auto"
    ops_compose_file: Path = Field(default=_REPO_ROOT / "deploy" / "compose" / "docker-compose.yml")
    ops_probe_host: str = "127.0.0.1"

    # ── GHCR / container image catalog ────────────────────────────────────
    images_catalog_enabled: bool = True
    images_registry: str = "ghcr.io"
    images_registry_owner: str = ""  # GitHub org or username
    images_registry_owner_kind: Literal["auto", "org", "user"] = "auto"
    images_registry_token: str | None = None  # PAT with read:packages (server-side only)
    images_cache_ttl_s: int = 300
    images_include_versions: bool = True
    images_max_versions: int = 5

    # ── External worker containers (from GHCR catalog) ────────────────────
    containers_enabled: bool = True
    # Host port base for mapping each worker's gRPC port (stable offset per image).
    containers_grpc_host_port_base: int = 55051
    # Deprecated: no longer used as a silent default container port.
    # Port comes from image metadata (CERTIQS_SERVICE_PORT / EXPOSE / OCI label)
    # or CERTIQS_CONTAINERS_SERVICE_PORTS overrides.
    containers_grpc_container_port: int = 50051
    # Optional overrides when image metadata is missing/ambiguous:
    # ``lab-bridge:50060,rx-povm:50051``.
    containers_service_ports: str = ""
    # Docker platform for pull/run. ``auto`` uses linux/amd64 on Apple Silicon
    # (many GHCR images are amd64-only). Set ``linux/arm64`` or leave empty for native.
    containers_platform: str = "auto"
    # Deploy a different image than the catalog's, per image leaf name:
    #   ``rx-povm=certiqs-rx-povm:patched,rx-characterization=certiqs-rx-characterization:patched``
    # Needed on arm64 hosts, where the upstream amd64 theory images never bind
    # their port: SciPy generates docstrings at import time by running numerical
    # integration, which does not complete under Rosetta. docker/rx-povm.Dockerfile
    # builds a patched variant. An overridden image is never pulled — it is
    # expected to be local.
    containers_image_overrides: str = ""

    @property
    def frontend_dir(self) -> Path:
        return _REPO_ROOT / "frontend"

    def parsed_log_module_levels(self) -> dict[str, str]:
        levels: dict[str, str] = {}
        for part in self.log_module_levels.split(","):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, level = part.split("=", 1)
            name = name.strip()
            level = level.strip().upper()
            if name and level:
                levels[name] = level
        return levels


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
