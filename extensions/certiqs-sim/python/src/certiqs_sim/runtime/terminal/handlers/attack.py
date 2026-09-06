"""Attack command handler (faked_state and future attack registry entries)."""

from __future__ import annotations

import shlex
from typing import Any

from certiqs_sim.runtime.terminal.intents import (
    TerminalContext,
    err,
    extract_json_object,
    ok,
    parse_kv,
)

_DEFAULT_ATTACK: dict[str, Any] = {
    "enabled": False,
    "eve_eff": 0.95,
    "extra_loss": 1.0,
    "trigger_prob": 0.98,
    "suppression": 0.95,
    "induced_error": 0.005,
    "passive_basis_choice": True,
}


def _validate_attack(payload: dict[str, Any]) -> dict[str, Any]:
    from certiqs_sim.services.api.schemas import AttackRequest

    return AttackRequest(**payload).model_dump()


def handle(command: str, rest: str, ctx: TerminalContext) -> dict[str, Any]:
    attack = {**_DEFAULT_ATTACK, **(ctx.current_attack or {})}
    rest_l = rest.lower().strip()

    if rest_l in {"", "status", "show", "get"}:
        return ok(command, {"attack": attack})

    json_body = extract_json_object(rest)
    if json_body is not None:
        payload = {**attack, **json_body}
        try:
            payload = _validate_attack(payload)
        except Exception as exc:  # noqa: BLE001
            return err(command, f"Invalid attack payload: {exc}")
        if ctx.apply_attack is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_attack(payload)
        return ok(
            command,
            {"accepted": accepted, "attack": payload},
            note="Applies from the next epoch.",
            applied={"kind": "attack", "payload": payload},
        )

    if rest_l in {"on", "enable", "enabled", "activate", "start"}:
        payload = {**attack, "enabled": True}
        if ctx.apply_attack is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_attack(payload)
        return ok(
            command,
            {"accepted": accepted, "attack": payload},
            note="Attack activated — next epoch",
            applied={"kind": "attack", "payload": payload},
        )

    if rest_l in {"off", "disable", "disabled", "deactivate", "stop"}:
        payload = {**attack, "enabled": False}
        if ctx.apply_attack is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_attack(payload)
        return ok(
            command,
            {"accepted": accepted, "attack": payload},
            note="Attack deactivated — next epoch",
            applied={"kind": "attack", "payload": payload},
        )

    if rest_l.startswith("set ") or rest_l.startswith("on ") or rest_l.startswith("off "):
        try:
            tokens = shlex.split(rest)
        except ValueError as exc:
            return err(command, str(exc))
        action = tokens[0].lower() if tokens else ""
        kv = parse_kv(tokens[1:])
        payload = {**attack, **kv}
        if action in {"on", "enable", "activate"}:
            payload["enabled"] = True
        elif action in {"off", "disable", "deactivate"}:
            payload["enabled"] = False
        try:
            payload = _validate_attack(payload)
        except Exception as exc:  # noqa: BLE001
            return err(command, f"Invalid attack params: {exc}")
        if ctx.apply_attack is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_attack(payload)
        return ok(
            command,
            {"accepted": accepted, "attack": payload},
            note="Applies from the next epoch.",
            applied={"kind": "attack", "payload": payload},
        )

    return err(
        command,
        "Unknown attack prompt. Try: attack on | attack off | "
        'attack {"enabled": true} | attack set eve_eff=0.9 | help',
    )
