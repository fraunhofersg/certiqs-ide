"""Live catalog of simulation-controllable services for the prompt terminal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from certiqs_sim.core.attacks import list_attacks
from certiqs_sim.core.countermeasures import list_countermeasures
from certiqs_sim.runtime.params import BASE_PARAM_META


@dataclass
class ServiceEntry:
    id: str
    kind: str
    title: str
    status: str = "available"
    commands: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "commands": list(self.commands),
        }


@dataclass
class ServiceCatalog:
    services: list[ServiceEntry] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[ServiceEntry]:
        return [s for s in self.services if s.kind == kind]

    def get(self, service_id: str) -> ServiceEntry | None:
        wanted = service_id.lower()
        for s in self.services:
            if s.id.lower() == wanted:
                return s
        return None

    def example_prompts(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for svc in self.services:
            out.extend(svc.examples)
        # Always include meta verbs
        out.extend(
            [
                {
                    "title": "Status",
                    "prompt": "status",
                    "description": "Show run / attack / selftest / services snapshot",
                },
                {
                    "title": "Suggest",
                    "prompt": "suggest",
                    "description": "List executable commands from the live service catalog",
                },
                {
                    "title": "help",
                    "prompt": "help",
                    "description": "List commands and catalog overview",
                },
            ]
        )
        return out

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.services]


def _attack_entry(attack_id: str) -> ServiceEntry:
    return ServiceEntry(
        id=attack_id,
        kind="attack",
        title=f"Attack · {attack_id}",
        status="available",
        commands=[
            "attack on",
            "attack off",
            "attack status",
            "attack set eve_eff=0.9",
            'attack {"enabled": true, "eve_eff": 0.95}',
        ],
        keywords=[
            "attack",
            "blinding",
            "faked_state",
            "faked-state",
            "eve",
            "interceptor",
        ],
        examples=[
            {
                "title": f"Attack on ({attack_id})",
                "prompt": "attack on",
                "description": f"Activate {attack_id}",
            },
            {
                "title": "Attack off",
                "prompt": "attack off",
                "description": "Deactivate the attack",
            },
            {
                "title": "Attack JSON",
                "prompt": 'attack {"enabled": true, "eve_eff": 0.95, "trigger_prob": 0.98}',
                "description": "Structured API-style activate payload",
            },
            {
                "title": "Attack set params",
                "prompt": "attack set eve_eff=0.9 suppression=0.9",
                "description": "Tune parameters without toggling enabled",
            },
        ],
    )


def _countermeasure_entry(cm_id: str) -> ServiceEntry:
    return ServiceEntry(
        id=cm_id,
        kind="countermeasure",
        title=f"Countermeasure · {cm_id}",
        status="available",
        commands=[
            "selftest on --mode=flag",
            "selftest on --mode=salt",
            "selftest on --mode=self_blinding",
            "selftest off",
            "selftest status",
        ],
        keywords=[
            "selftest",
            "self-test",
            "countermeasure",
            "cm",
            "blinding",
            "detector_selftest",
            "salt",
            "flag",
        ],
        examples=[
            {
                "title": "Self-test on (flag)",
                "prompt": "selftest on --mode=flag",
                "description": f"Enable {cm_id} (flag mode)",
            },
            {
                "title": "Self-test self_blinding",
                "prompt": "selftest on --mode=self_blinding",
                "description": "Enable self-blinding countermeasure mode",
            },
            {
                "title": "Self-test off",
                "prompt": "selftest off",
                "description": "Disable detector self-test countermeasure",
            },
        ],
    )


def _params_entry() -> ServiceEntry:
    keys = [str(m["key"]) for m in BASE_PARAM_META]
    commands = ["params status"]
    if keys:
        commands.append("params set visibility=0.95")
        commands.append(f"params set {keys[0]}=0.05")
    return ServiceEntry(
        id="base_params",
        kind="params",
        title="Base simulation parameters",
        status="available",
        commands=commands,
        keywords=["params", "parameters", "visibility", "fibre", "detector", "pair_prob"],
        examples=[
            {
                "title": "Params set visibility",
                "prompt": "params set visibility=0.95",
                "description": "Override base twin parameters (next epoch)",
            },
            {
                "title": "Params status",
                "prompt": "params status",
                "description": "List tunable base parameter keys",
            },
        ],
    )


def _provenance_entry() -> ServiceEntry:
    return ServiceEntry(
        id="provenance",
        kind="provenance",
        title="Epoch provenance / settings",
        status="available",
        commands=[
            "provenance list",
            "provenance last",
            "provenance get 0",
            "epoch last",
        ],
        keywords=[
            "provenance",
            "epoch",
            "settings",
            "snapshot",
            "history",
            "inspect",
        ],
        examples=[
            {
                "title": "List epochs",
                "prompt": "provenance list",
                "description": "Show recent epochs and settings versions",
            },
            {
                "title": "Latest provenance",
                "prompt": "provenance last",
                "description": "Load settings for the latest epoch",
            },
            {
                "title": "Provenance by epoch",
                "prompt": "provenance get 0",
                "description": "Load input settings snapshot for epoch 0",
            },
        ],
    )


def _container_entry(row: dict[str, Any]) -> ServiceEntry:
    service_id = str(row.get("id") or row.get("service_id") or "")
    state = str(row.get("state") or row.get("status") or "unknown")
    running = state == "running"
    commands = [
        f"svc {service_id} GetCapabilities",
        f"svc {service_id} GetServiceInfo",
        f"svc {service_id} help",
    ]
    return ServiceEntry(
        id=service_id,
        kind="container",
        title=f"Container · {service_id}",
        status="running" if running else state,
        commands=commands if running else [f"# start container {service_id} first"],
        keywords=[service_id, "svc", "container", "microservice", "grpc"],
        examples=(
            [
                {
                    "title": f"svc {service_id} caps",
                    "prompt": f"svc {service_id} GetCapabilities",
                    "description": f"Query gRPC capabilities on {service_id}",
                }
            ]
            if running
            else []
        ),
    )


def build_service_catalog(
    *,
    list_containers: Callable[[], list[dict[str, Any]]] | None = None,
) -> ServiceCatalog:
    """Assemble a catalog snapshot from registries + optional running containers."""
    services: list[ServiceEntry] = []

    attacks = list_attacks() or ["faked_state"]
    for name in attacks:
        services.append(_attack_entry(name))

    cms = list_countermeasures() or ["detector_selftest"]
    for name in cms:
        services.append(_countermeasure_entry(name))

    services.append(_params_entry())
    services.append(_provenance_entry())

    if list_containers is not None:
        try:
            for row in list_containers() or []:
                sid = str(row.get("id") or row.get("service_id") or "")
                if sid:
                    services.append(_container_entry(row))
        except Exception:  # noqa: BLE001 — best-effort catalog enrichment
            pass

    return ServiceCatalog(services=services)


__all__ = ["ServiceCatalog", "ServiceEntry", "build_service_catalog"]
