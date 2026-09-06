"""Status snapshot handler."""

from __future__ import annotations

from typing import Any

from certiqs_sim.runtime.terminal.catalog import ServiceCatalog
from certiqs_sim.runtime.terminal.handlers import attack as attack_handler
from certiqs_sim.runtime.terminal.handlers import selftest as selftest_handler
from certiqs_sim.runtime.terminal.intents import TerminalContext, ok


def handle(
    command: str,
    ctx: TerminalContext,
    catalog: ServiceCatalog | None = None,
) -> dict[str, Any]:
    attack = {**attack_handler._DEFAULT_ATTACK, **(ctx.current_attack or {})}
    selftest = {**selftest_handler._DEFAULT_SELFTEST, **(ctx.current_selftest or {})}
    payload: dict[str, Any] = {
        "run": ctx.run_status or {},
        "attack": attack,
        "selftest": selftest,
    }
    if catalog is not None:
        payload["services"] = catalog.to_dict_list()
    return ok(command, payload)
