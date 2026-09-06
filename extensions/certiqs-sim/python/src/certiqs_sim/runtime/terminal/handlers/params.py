"""Base simulation params command handler."""

from __future__ import annotations

import shlex
from typing import Any

from certiqs_sim.runtime.params import BASE_PARAM_META
from certiqs_sim.runtime.terminal.intents import TerminalContext, err, ok, parse_kv


def handle(command: str, rest: str, ctx: TerminalContext) -> dict[str, Any]:
    rest_l = rest.lower().strip()
    keys = [str(m["key"]) for m in BASE_PARAM_META]

    if rest_l in {"", "status", "show", "get", "keys"}:
        return ok(
            command,
            {
                "keys": keys,
                "meta": BASE_PARAM_META,
                "note": "Use: params set visibility=0.95 pair_prob=0.05",
            },
        )

    try:
        tokens = shlex.split(rest) if rest else []
    except ValueError as exc:
        return err(command, str(exc))

    action = tokens[0].lower() if tokens else ""
    if action != "set":
        return err(
            command,
            "Unknown params prompt. Try: params status | params set visibility=0.95",
        )

    kv = parse_kv(tokens[1:])
    if not kv:
        return err(command, "No key=value pairs. Example: params set visibility=0.95")

    unknown = [k for k in kv if k not in keys]
    if unknown:
        return err(command, f"Unknown param keys: {', '.join(unknown)}. Known: {', '.join(keys)}")

    overrides: dict[str, float] = {}
    for k, v in kv.items():
        try:
            overrides[k] = float(v)
        except (TypeError, ValueError):
            return err(command, f"Param '{k}' must be numeric, got {v!r}")

    if ctx.apply_params is None:
        return err(command, "No active run — start a simulation first")

    accepted = ctx.apply_params(overrides)
    return ok(
        command,
        {"accepted": accepted, "overrides": overrides},
        note="Params apply from the next epoch.",
        applied={"kind": "params", "payload": overrides},
    )
