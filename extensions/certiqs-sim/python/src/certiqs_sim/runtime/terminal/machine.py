"""Input state machine for the simulation prompt terminal."""

from __future__ import annotations

import re
import shlex
from typing import Any

from certiqs_sim.runtime.terminal.assist import DeterministicAssistor, match_ambiguous
from certiqs_sim.runtime.terminal.catalog import ServiceCatalog, build_service_catalog
from certiqs_sim.runtime.terminal.handlers import (
    attack_handler,
    container_handler,
    help_handler,
    params_handler,
    provenance_handler,
    selftest_handler,
    status_handler,
)
from certiqs_sim.runtime.terminal.intents import TerminalContext, err, ok


class InputStateMachine:
    """Parse → resolve → validate → execute prompt inputs against the service catalog."""

    def __init__(
        self,
        *,
        catalog: ServiceCatalog | None = None,
        assistor: DeterministicAssistor | None = None,
    ) -> None:
        self.catalog = catalog or build_service_catalog()
        self.assistor = assistor or DeterministicAssistor()

    def process(self, prompt: str, ctx: TerminalContext) -> dict[str, Any]:
        text = (prompt or "").strip()
        if not text:
            return err("", "Empty prompt")

        command = text
        lowered = text.lower().strip()

        # ── Meta / assist verbs ───────────────────────────────────────────
        if lowered in {"help", "?", "examples"}:
            return help_handler.handle(command, self.catalog)

        if lowered in {"status", "show", "info"}:
            return status_handler.handle(command, ctx, self.catalog)

        if lowered == "suggest" or lowered.startswith("suggest "):
            query = text[len("suggest") :].strip()
            suggestions = self.assistor.suggest(query, self.catalog)
            payload = [
                {
                    "title": s.title,
                    "prompt": s.prompt,
                    "description": s.description,
                    "service_id": s.service_id,
                    "kind": s.kind,
                }
                for s in suggestions
            ]
            return ok(
                command,
                {"query": query, "suggestions": payload, "count": len(payload)},
                suggestions=[
                    {"title": s.title, "prompt": s.prompt, "description": s.description}
                    for s in suggestions
                ],
                note="Select a prompt and submit it, or use `compose <service> <action>`.",
            )

        if lowered.startswith("compose "):
            return self._compose(command, text[len("compose") :].strip(), ctx)

        # ── Explicit family verbs ─────────────────────────────────────────
        if lowered.startswith("attack"):
            return attack_handler.handle(command, text[len("attack") :].strip(), ctx)

        if lowered.startswith("selftest") or lowered.startswith("self-test"):
            m = re.match(r"^(self-?test)\s*(.*)$", text, flags=re.IGNORECASE)
            rest = (m.group(2) if m else "").strip()
            return selftest_handler.handle(command, rest, ctx)

        if lowered.startswith("params"):
            return params_handler.handle(command, text[len("params") :].strip(), ctx)

        if lowered.startswith("provenance") or lowered.startswith("epoch"):
            if lowered.startswith("provenance"):
                rest = text[len("provenance") :].strip()
            else:
                rest = text[len("epoch") :].strip()
            return provenance_handler.handle(command, rest, ctx)

        if lowered.startswith("svc ") or lowered.startswith("service "):
            return self._svc(command, text, ctx)

        # ── Ambiguous free-form → clarification ───────────────────────────
        candidates = match_ambiguous(text, self.catalog)
        # Only clarify when the phrase looks NL-ish (no known verb) and ≥2 hits
        if len(candidates) >= 2:
            return err(
                command,
                "Ambiguous input — pick an executable command:",
                candidates=candidates,
                suggestions=[
                    {"title": c, "prompt": c, "description": "catalog match"}
                    for c in candidates
                ],
            )

        if len(candidates) == 1:
            # Auto-resolve single clear match by re-entering with the candidate
            return self.process(candidates[0], ctx)

        return err(
            command,
            "Unknown prompt. Try `help`, `suggest`, `attack on`, "
            "`selftest on`, `provenance last`, `params set visibility=0.95`, "
            "or `svc <id> help`.",
        )

    def _compose(self, command: str, intent: str, ctx: TerminalContext) -> dict[str, Any]:
        run = False
        body = intent
        # Trailing --run flag
        if body.endswith("--run"):
            run = True
            body = body[: -len("--run")].strip()
        try:
            tokens = shlex.split(body)
        except ValueError:
            tokens = body.split()
        if tokens and tokens[-1] == "--run":
            run = True
            tokens = tokens[:-1]
            body = " ".join(tokens)

        composed = self.assistor.compose(body, self.catalog)
        if composed.error:
            return err(command, composed.error)

        if not run:
            return ok(
                command,
                {
                    "command": composed.command,
                    "service_id": composed.service_id,
                    "kind": composed.kind,
                    "note": "Add --run to execute",
                },
                suggestions=[
                    {
                        "title": "Run composed",
                        "prompt": composed.command,
                        "description": "Submit this executable command",
                    }
                ],
                note="Composed executable command (not yet run).",
            )

        # Execute the composed command through the same machine
        return self.process(composed.command, ctx)

    def _svc(self, command: str, text: str, ctx: TerminalContext) -> dict[str, Any]:
        try:
            tokens = shlex.split(text)
        except ValueError as exc:
            return err(command, str(exc))
        # svc | service
        if len(tokens) < 3:
            return err(command, "Usage: svc <container_id> <command>")
        service_id = tokens[1]
        remote = " ".join(tokens[2:])
        return container_handler.handle(command, service_id, remote, ctx)


def run_sim_prompt(
    prompt: str,
    *,
    run_status: dict[str, Any] | None,
    current_attack: dict[str, Any] | None,
    current_selftest: dict[str, Any] | None,
    apply_attack: Any = None,
    apply_selftest: Any = None,
    apply_params: Any = None,
    run_container_prompt: Any = None,
    list_containers: Any = None,
    get_history: Any = None,
    get_settings_for_epoch: Any = None,
    catalog: ServiceCatalog | None = None,
) -> dict[str, Any]:
    """Public entrypoint used by the API and unit tests."""
    cat = catalog or build_service_catalog(list_containers=list_containers)
    machine = InputStateMachine(catalog=cat)
    ctx = TerminalContext(
        run_status=run_status,
        current_attack=current_attack,
        current_selftest=current_selftest,
        apply_attack=apply_attack,
        apply_selftest=apply_selftest,
        apply_params=apply_params,
        run_container_prompt=run_container_prompt,
        list_containers=list_containers,
        get_history=get_history,
        get_settings_for_epoch=get_settings_for_epoch,
    )
    return machine.process(prompt, ctx)


def example_prompts(
    *,
    list_containers: Any = None,
    catalog: ServiceCatalog | None = None,
) -> list[dict[str, str]]:
    cat = catalog or build_service_catalog(list_containers=list_containers)
    return cat.example_prompts()


# Backward-compatible alias
EXAMPLE_PROMPTS = example_prompts()


__all__ = [
    "EXAMPLE_PROMPTS",
    "InputStateMachine",
    "example_prompts",
    "run_sim_prompt",
]
