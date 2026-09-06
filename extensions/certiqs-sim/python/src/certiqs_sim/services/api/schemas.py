"""Pydantic request/response schemas for the frozen ``/api/v1`` contract.

These models define the OpenAPI schema published for the Next.js frontend's typed
client generation (``openapi-typescript``).  Keeping them explicit (rather than
free-form dicts) is what makes the contract stable and typed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StartRunRequest(BaseModel):
    config_name: str = Field(..., description="YAML config directory name, e.g. 'bbm92-generic'")
    protocol: str = Field("bbm92", description="Protocol plugin id")
    overrides: dict[str, float] = Field(default_factory=dict)
    attack: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    selftest: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    shots_per_window: int = Field(100_000, gt=0)
    run_id: str | None = Field(None, description="Client-supplied id; server generates if omitted")


class ParamsRequest(BaseModel):
    overrides: dict[str, float] = Field(default_factory=dict)


class AttackRequest(BaseModel):
    enabled: bool = False
    eve_eff: float = 0.95
    extra_loss: float = 1.0
    trigger_prob: float = 0.98
    suppression: float = 0.95
    induced_error: float = 0.005
    passive_basis_choice: bool = True


class SelfTestRequest(BaseModel):
    enabled: bool = False
    mode: str = "flag"
    apply_to_detection: bool = True
    n_test_pulses: int = 10
    n_threshold: int = 4
    p_response_unblinded: float = 0.934
    p_response_blinded: float = 0.003
    salt_mean_unblinded: float = 100.0
    salt_mean_blinded: float = 10.0
    salt_threshold: float = 50.0
    selfblind_runs: int = 10
    test_rate_hz: float = 2000.0
    detector_dead_time_ns: float = 1000.0


class AcceptedResponse(BaseModel):
    accepted: dict[str, Any]
    note: str = "Applies from the next epoch."


class TopologyEdit(BaseModel):
    """One connector-move or connection-rewire edit against a config set."""

    kind: str = Field(..., description="'set_connector' or 'rewire_connection'")
    port_id: str | None = Field(None, description="Target port id (set_connector)")
    connector: dict[str, Any] | None = Field(
        None, description="Connector fields to merge: position/size/style/color"
    )
    old: dict[str, str] | None = Field(
        None, description="Existing {from_port,to_port} (rewire_connection)"
    )
    new: dict[str, str] | None = Field(
        None, description="Replacement {from_port,to_port} (rewire_connection)"
    )


class TopologyEditsRequest(BaseModel):
    config: str | None = Field(None, description="Config set name; defaults to active")
    backup: bool = Field(True, description="Back up touched files before writing")
    edits: list[TopologyEdit] = Field(default_factory=list)


class TopologyEditsResponse(BaseModel):
    config: str
    applied: int
    changed_files: list[str]
    backup_dir: str | None = None


class MetaResponse(BaseModel):
    base_params: list[dict[str, Any]]
    attack_params: list[dict[str, Any]]
    selftest_params: list[dict[str, Any]]
    selftest_modes: list[str]
    protocols: list[str]
    attacks: list[str]
    countermeasures: list[str]
    default_shots_per_window: int


class ConfigEntry(BaseModel):
    name: str
    defaults: dict[str, float] | None = None
    error: str | None = None


class ConfigsResponse(BaseModel):
    config_root: str
    default_config: str
    configs: list[ConfigEntry]


class MetricAssessmentBand(BaseModel):
    level: str  # success | warning | danger
    lower: float
    upper: float
    label: str | None = None


class MetricAssessmentLine(BaseModel):
    level: str  # success | warning | danger | default
    y: float
    label: str | None = None
    style: str = "dashed"


class MetricTechnicalRange(BaseModel):
    """Config-driven assessment / security guidance for a metric chart."""

    # Assessment inputs
    nominal: float | None = None
    good_range: list[float] | None = None
    warning_threshold: float | None = None
    abort_threshold: float | None = None
    # Derived overlays
    bands: list[MetricAssessmentBand] = Field(default_factory=list)
    lines: list[MetricAssessmentLine] = Field(default_factory=list)
    # Metadata
    context: str | None = None
    standard: str | None = None
    label: str | None = None
    contributions: dict[str, float] = Field(default_factory=dict)
    # Legacy single-band
    lower: float | None = None
    upper: float | None = None
    kind: str | None = None
    upper_label: str | None = None
    lower_label: str | None = None


class MetricCatalogEntry(BaseModel):
    key: str
    label: str
    unit: str
    kind: str
    default_plot: bool
    technical_range: MetricTechnicalRange | None = None


class MetricsCatalogResponse(BaseModel):
    metrics: list[MetricCatalogEntry]


class ForensicsConfigResponse(BaseModel):
    """Anomaly detection / forensics knobs from shared/forensics.yaml."""

    metric_key: str = "qber"
    expected_qber: float = 0.025
    min_confident_bits: int = 500
    windows: dict[str, int] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    states: dict[str, float] = Field(default_factory=dict)
    max_streak_for_observation: int = 2
    trend_alarm_slope: float = 0.008
    basis_metric_x: str | None = None
    basis_metric_z: str | None = None


class OptimizationConfigResponse(BaseModel):
    """Practical fibre-length optimization knobs from shared/optimization.yaml."""

    metric_key: str = "qber"
    security_metric_key: str = "secret_fraction"
    rate_metric_key: str = "key_rate_per_pulse"
    qber_target_mode: str = "abort"
    qber_target_fraction: float = 1.0
    min_secret_fraction: float = 0.05
    min_key_rate_per_pulse: float = 0.0
    settle_epochs: int = 15
    step_km: float = 5.0
    fine_step_km: float = 1.0
    approach_band: float = 0.20
    max_length_km: float = 100.0
    length_keys: list[str] = Field(default_factory=lambda: ["alice_length", "bob_length"])
    length_mode: str = "symmetric"
    backoff_on_breach: bool = True
    max_steps: int = 40
    window_epochs: int = 20
    aggregator: str = "median"
    min_window_samples: int = 10
    max_rise_slope: float = 0.0015


class StatusResponse(BaseModel):
    run_id: str | None = None
    status: str
    error: str | None = None
    protocol: str | None = None
    config_name: str | None = None
    shots_per_window: int | None = None
    epoch: int | None = None
    settings_version: int | None = None
    current_settings: dict[str, Any] | None = None
    attack_enabled: bool | None = None
    last_point: dict[str, Any] | None = None
    started_at: float | None = None
    history_size: int | None = None


class HistoryResponse(BaseModel):
    points: list[dict[str, Any]]


class OpsPlatformResponse(BaseModel):
    mode: str
    repo_root: str
    compose_file: str
    compose_available: bool
    venv_python: str | None = None
    bus_backend: str
    base_port: int


class OpsServiceStatus(BaseModel):
    id: str
    name: str
    kind: str
    port: int
    description: str
    state: str
    managed_by: str
    self_managed: bool = False
    pid: int | None = None
    uptime_s: float | None = None
    probe: dict[str, Any] = Field(default_factory=dict)
    compose: dict[str, Any] | None = None
    links: dict[str, str | None] = Field(default_factory=dict)


class OpsServicesResponse(BaseModel):
    platform: OpsPlatformResponse
    services: list[OpsServiceStatus]


class OpsActionResponse(BaseModel):
    id: str
    ok: bool
    action: str | None = None
    backend: str | None = None
    note: str | None = None
    pid: int | None = None
    error: str | None = None


class OpsBulkActionResponse(BaseModel):
    results: list[OpsActionResponse]


class OpsLogsResponse(BaseModel):
    id: str
    lines: list[str]
    source: str


class ImageVersionEntry(BaseModel):
    version_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    digest: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    html_url: str | None = None


class ContainerImageEntry(BaseModel):
    name: str
    full_name: str
    registry: str
    pull_ref: str
    visibility: str | None = None
    description: str | None = None
    html_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    owner: str
    owner_kind: str
    latest_tags: list[str] = Field(default_factory=list)
    latest_digest: str | None = None
    version_count: int | None = None
    versions: list[ImageVersionEntry] = Field(default_factory=list)


class ImageRegistryAuthInfo(BaseModel):
    registry: str
    token_configured: bool
    required_scopes: list[str] = Field(default_factory=list)
    recommended_token: str
    env_var: str
    owner_env_var: str
    owner_kind_env_var: str
    best_practices: list[str] = Field(default_factory=list)
    api_docs: str
    list_endpoint: str


class ContainerImageCatalogResponse(BaseModel):
    registry: str
    owner: str
    owner_kind: str
    authenticated: bool
    image_count: int
    images: list[ContainerImageEntry]
    fetched_at: float
    cache_hit: bool = False
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    auth: ImageRegistryAuthInfo


class ContainerGrpcStatus(BaseModel):
    host: str = "127.0.0.1"
    port: int = 0
    container_port: int | None = None
    addr: str = ""
    reachable: bool = False
    status: str = "idle"
    detail: str = ""
    info: dict[str, Any] | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    protocol: str = "grpc"
    service_info: dict[str, Any] | None = None
    contract: str | None = None


class ContainerHealthStatus(BaseModel):
    overall: str = "not_deployed"
    docker_state: str | None = None
    docker_health: str | None = None
    grpc_status: str | None = None
    grpc_reachable: bool = False
    detail: str = ""


class ContainerProvisionInfo(BaseModel):
    service_id: str
    container_name: str
    image: str
    registry: str | None = None
    owner: str | None = None
    host_port: int | None = None
    container_port: int | None = None
    profile: str | None = None
    env_prefix: str | None = None
    grpc_addr: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    deployed: bool = False
    running: bool = False
    image_present: bool = False


class ContainerDeploymentJob(BaseModel):
    job_id: str
    service_id: str
    image: str
    pull: bool = True
    tag: str | None = None
    phase: str
    progress: float = 0.0
    ok: bool | None = None
    error: str | None = None
    container_id: str | None = None
    created_at: float
    updated_at: float
    finished_at: float | None = None
    active: bool = False
    lines: list[str] = Field(default_factory=list)


class ContainerServiceStatus(BaseModel):
    id: str
    name: str
    description: str
    image: str
    registry: str | None = None
    owner: str | None = None
    visibility: str | None = None
    html_url: str | None = None
    latest_tags: list[str] = Field(default_factory=list)
    versions: list[dict[str, Any]] = Field(default_factory=list)
    container_name: str
    ports: list[str] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None
    docker_available: bool = False
    image_present: bool = False
    state: str
    container: dict[str, Any] = Field(default_factory=dict)
    grpc: ContainerGrpcStatus | None = None
    health: ContainerHealthStatus | None = None
    provision: ContainerProvisionInfo | None = None
    manifest: dict[str, Any] = Field(default_factory=dict)
    services_provided: list[dict[str, Any]] = Field(default_factory=list)
    deployment: ContainerDeploymentJob | None = None
    interface: dict[str, Any] = Field(default_factory=dict)
    service_info: dict[str, Any] | None = None


class ContainerServicesResponse(BaseModel):
    docker_available: bool
    registry: str = "ghcr.io"
    owner: str = ""
    owner_kind: str = ""
    authenticated: bool = False
    catalog_error: str | None = None
    catalog_warnings: list[str] = Field(default_factory=list)
    services: list[ContainerServiceStatus]


class ContainerInspectResponse(ContainerServiceStatus):
    pass


class ContainerActionResponse(BaseModel):
    id: str
    ok: bool
    action: str | None = None
    backend: str | None = None
    note: str | None = None
    container_id: str | None = None
    error: str | None = None
    job_id: str | None = None


class ContainerLogsResponse(BaseModel):
    id: str
    lines: list[str]
    source: str


class ContainerDeployRequest(BaseModel):
    pull: bool = True
    tag: str | None = None


class ContainerTerminalPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Terminal command / prompt text")


class SimTerminalPromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Simulation terminal prompt")


class SimTerminalPromptResponse(BaseModel):
    run_id: str
    prompt: str = ""
    ok: bool = False
    command: str = ""
    result: Any = None
    output: str = ""
    note: str = ""
    error: str | None = None
    applied: dict[str, Any] | None = None
    suggestions: list[dict[str, str]] | None = None
    candidates: list[str] | None = None


class SimTerminalServiceEntry(BaseModel):
    id: str
    kind: str
    title: str = ""
    status: str = "available"
    commands: list[str] = Field(default_factory=list)


class SimTerminalExamplesResponse(BaseModel):
    run_id: str | None = None
    example_prompts: list[dict[str, str]] = Field(default_factory=list)
    services: list[SimTerminalServiceEntry] = Field(default_factory=list)
    attack: str = "faked_state"
    countermeasure: str = "detector_selftest"
    note: str = (
        "Prompt Terminal dispatches catalog services (attack, countermeasure, "
        "params, running containers). Use help / suggest / compose."
    )


class ContainerTerminalCapabilitiesResponse(BaseModel):
    id: str
    addr: str = ""
    ok: bool = False
    profile: str | None = None
    capabilities: dict[str, Any] | None = None
    example_prompts: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None


class ContainerTerminalPromptResponse(BaseModel):
    id: str
    addr: str = ""
    prompt: str = ""
    ok: bool = False
    command: str = ""
    result: Any = None
    output: str = ""
    note: str = ""
    error: str | None = None


__all__ = [
    "AcceptedResponse",
    "AttackRequest",
    "ConfigEntry",
    "ConfigsResponse",
    "ContainerActionResponse",
    "ContainerDeployRequest",
    "ContainerDeploymentJob",
    "ContainerGrpcStatus",
    "ContainerHealthStatus",
    "ContainerImageCatalogResponse",
    "ContainerImageEntry",
    "ContainerInspectResponse",
    "ContainerLogsResponse",
    "ContainerProvisionInfo",
    "ContainerServiceStatus",
    "ContainerServicesResponse",
    "ContainerTerminalCapabilitiesResponse",
    "ContainerTerminalPromptRequest",
    "ContainerTerminalPromptResponse",
    "SimTerminalExamplesResponse",
    "SimTerminalPromptRequest",
    "SimTerminalPromptResponse",
    "SimTerminalServiceEntry",
    "HistoryResponse",
    "ImageRegistryAuthInfo",
    "ImageVersionEntry",
    "MetaResponse",
    "MetricAssessmentBand",
    "MetricAssessmentLine",
    "MetricCatalogEntry",
    "MetricTechnicalRange",
    "MetricsCatalogResponse",
    "ForensicsConfigResponse",
    "OpsActionResponse",
    "OpsBulkActionResponse",
    "OpsLogsResponse",
    "OpsPlatformResponse",
    "OpsServiceStatus",
    "OpsServicesResponse",
    "ParamsRequest",
    "SelfTestRequest",
    "StartRunRequest",
    "StatusResponse",
    "TopologyEdit",
    "TopologyEditsRequest",
    "TopologyEditsResponse",
]
