"""Self-test / countermeasure command handler."""

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

_DEFAULT_SELFTEST: dict[str, Any] = {
    "enabled": False,
    "mode": "flag",
    "apply_to_detection": True,
    "n_test_pulses": 10,
    "n_threshold": 4,
    "p_response_unblinded": 0.934,
    "p_response_blinded": 0.003,
    "salt_mean_unblinded": 100.0,
    "salt_mean_blinded": 10.0,
    "salt_threshold": 50.0,
    "selfblind_runs": 10,
    "test_rate_hz": 2000.0,
    "detector_dead_time_ns": 1000.0,
}


def _validate_selftest(payload: dict[str, Any]) -> dict[str, Any]:
    from certiqs_sim.services.api.schemas import SelfTestRequest

    return SelfTestRequest(**payload).model_dump()


def handle(command: str, rest: str, ctx: TerminalContext) -> dict[str, Any]:
    selftest = {**_DEFAULT_SELFTEST, **(ctx.current_selftest or {})}
    rest_l = rest.lower().strip()

    if rest_l in {"", "status", "show", "get"}:
        return ok(command, {"selftest": selftest})

    json_body = extract_json_object(rest)
    if json_body is not None:
        payload = {**selftest, **json_body}
        try:
            payload = _validate_selftest(payload)
        except Exception as exc:  # noqa: BLE001
            return err(command, f"Invalid selftest payload: {exc}")
        if ctx.apply_selftest is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_selftest(payload)
        return ok(
            command,
            {"accepted": accepted, "selftest": payload},
            note="Countermeasure applies from the next epoch.",
            applied={"kind": "selftest", "payload": payload},
        )

    try:
        tokens = shlex.split(rest) if rest else []
    except ValueError as exc:
        return err(command, str(exc))
    action = tokens[0].lower() if tokens else ""
    kv = parse_kv(tokens[1:] if tokens else [])

    if action in {"on", "enable", "activate", "start"}:
        payload = {**selftest, **kv, "enabled": True}
        try:
            payload = _validate_selftest(payload)
        except Exception as exc:  # noqa: BLE001
            return err(command, f"Invalid selftest params: {exc}")
        if ctx.apply_selftest is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_selftest(payload)
        return ok(
            command,
            {"accepted": accepted, "selftest": payload},
            note="Countermeasure enabled — next epoch",
            applied={"kind": "selftest", "payload": payload},
        )

    if action in {"off", "disable", "deactivate", "stop"}:
        payload = {**selftest, **kv, "enabled": False}
        try:
            payload = _validate_selftest(payload)
        except Exception as exc:  # noqa: BLE001
            return err(command, f"Invalid selftest params: {exc}")
        if ctx.apply_selftest is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_selftest(payload)
        return ok(
            command,
            {"accepted": accepted, "selftest": payload},
            note="Countermeasure disabled — next epoch",
            applied={"kind": "selftest", "payload": payload},
        )

    if action == "set":
        payload = {**selftest, **kv}
        try:
            payload = _validate_selftest(payload)
        except Exception as exc:  # noqa: BLE001
            return err(command, f"Invalid selftest params: {exc}")
        if ctx.apply_selftest is None:
            return err(command, "No active run — start a simulation first")
        accepted = ctx.apply_selftest(payload)
        return ok(
            command,
            {"accepted": accepted, "selftest": payload},
            note="Applies from the next epoch.",
            applied={"kind": "selftest", "payload": payload},
        )

    return err(
        command,
        "Unknown selftest prompt. Try: selftest on --mode=flag | "
        'selftest off | selftest {"enabled": true} | help',
    )
