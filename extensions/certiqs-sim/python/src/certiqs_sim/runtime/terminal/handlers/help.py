"""Help / catalog overview handler."""

from __future__ import annotations

from typing import Any

from certiqs_sim.runtime.terminal.catalog import ServiceCatalog
from certiqs_sim.runtime.terminal.intents import ok


def handle(command: str, catalog: ServiceCatalog) -> dict[str, Any]:
    return ok(
        command,
        {
            "commands": [
                "help | status | suggest [query] | compose <service> <action> [--run]",
                "attack on|off|status|set <k=v…> | attack {JSON}",
                "selftest on|off|status|set [--mode=flag|salt|self_blinding] | selftest {JSON}",
                "params status | params set <k=v…>",
                "provenance list | provenance <epoch> | provenance last | epoch <n>",
                "svc <container_id> <remote-command>",
            ],
            "services": catalog.to_dict_list(),
            "example_prompts": catalog.example_prompts(),
            "note": (
                "Requires an active run for mutating commands. "
                "Changes apply from the next epoch. "
                "Use `suggest` to pick executable commands from available services."
            ),
        },
    )
