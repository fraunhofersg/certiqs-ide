"""Container microservice command handler (svc <id> <cmd>)."""

from __future__ import annotations

from typing import Any

from certiqs_sim.runtime.terminal.intents import TerminalContext, err, ok


def handle(command: str, service_id: str, remote: str, ctx: TerminalContext) -> dict[str, Any]:
    sid = (service_id or "").strip()
    prompt = (remote or "").strip()
    if not sid:
        return err(command, "Usage: svc <container_id> <command>")
    if not prompt:
        return err(command, f"Usage: svc {sid} <command>  (e.g. GetCapabilities)")

    if ctx.run_container_prompt is None:
        return err(
            command,
            "Container terminal not available (containers disabled or manager missing)",
        )

    try:
        raw = ctx.run_container_prompt(sid, prompt)
    except Exception as exc:  # noqa: BLE001
        return err(command, f"Container prompt failed: {exc}")

    ok_flag = bool(raw.get("ok", True))
    output = raw.get("output") or raw.get("error") or raw
    if not ok_flag:
        return err(command, str(raw.get("error") or output))

    return ok(
        command,
        raw.get("result", raw),
        note=str(raw.get("note") or f"svc {sid}"),
        applied={"kind": "container", "payload": {"id": sid, "prompt": prompt}},
    )
