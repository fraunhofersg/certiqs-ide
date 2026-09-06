"""Provenance / epoch settings inspection via the prompt terminal."""

from __future__ import annotations

import shlex
from typing import Any

from certiqs_sim.runtime.terminal.intents import TerminalContext, err, ok


def handle(command: str, rest: str, ctx: TerminalContext) -> dict[str, Any]:
    rest_l = (rest or "").strip().lower()

    if rest_l in {"", "list", "status", "show", "epochs"}:
        return _list_epochs(command, ctx)

    try:
        tokens = shlex.split(rest) if rest else []
    except ValueError as exc:
        return err(command, str(exc))

    action = tokens[0].lower() if tokens else ""

    if action in {"list", "status", "show", "epochs"}:
        return _list_epochs(command, ctx)

    if action in {"last", "latest", "current"}:
        return _get_epoch(command, None, ctx, prefer_last=True)

    if action in {"get", "show", "load", "select"}:
        if len(tokens) < 2:
            return err(command, "Usage: provenance get <epoch> | provenance last")
        return _get_epoch(command, tokens[1], ctx)

    # Bare epoch number: `provenance 12` or routed from `epoch 12`
    return _get_epoch(command, action, ctx)


def _list_epochs(command: str, ctx: TerminalContext) -> dict[str, Any]:
    if ctx.get_history is None:
        return err(command, "No active run — start a simulation first")
    history = ctx.get_history() or []
    # Newest first, cap for terminal readability
    rows = [
        {
            "epoch": p.get("epoch"),
            "settings_version": p.get("settings_version"),
            "attack_enabled": p.get("attack_enabled"),
        }
        for p in reversed(history[-40:])
    ]
    return ok(
        command,
        {
            "epochs": rows,
            "count": len(rows),
            "note": "Use: provenance <epoch> | provenance last | provenance get <epoch>",
        },
        note="Select an epoch with `provenance <epoch>` to load settings.",
    )


def _get_epoch(
    command: str,
    epoch_token: str | None,
    ctx: TerminalContext,
    *,
    prefer_last: bool = False,
) -> dict[str, Any]:
    if ctx.get_settings_for_epoch is None:
        return err(command, "No active run — start a simulation first")

    epoch: int | None = None
    if prefer_last or epoch_token in {None, "last", "latest", "current"}:
        if ctx.get_history is None:
            return err(command, "No active run — start a simulation first")
        history = ctx.get_history() or []
        if not history:
            return err(command, "No epochs recorded yet")
        epoch = int(history[-1]["epoch"])
    else:
        try:
            epoch = int(str(epoch_token).strip())
        except (TypeError, ValueError):
            return err(
                command,
                f"Invalid epoch '{epoch_token}'. Try: provenance list | provenance <n>",
            )

    snap = ctx.get_settings_for_epoch(epoch)
    if snap is None:
        return err(command, f"No settings for epoch {epoch}")

    return ok(
        command,
        {"epoch": epoch, "settings": snap},
        note=f"Loaded settings for epoch {epoch}",
        applied={"kind": "provenance", "payload": {"epoch": epoch, "snapshot": snap}},
    )
