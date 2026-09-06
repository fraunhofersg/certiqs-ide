"""Deterministic (and future LLM) assist for terminal command selection."""

from __future__ import annotations

import shlex
from typing import Protocol

from certiqs_sim.runtime.terminal.catalog import ServiceCatalog
from certiqs_sim.runtime.terminal.intents import ComposeResult, SuggestedCommand


class Assistor(Protocol):
    """Translate a free-form query into executable terminal commands."""

    def suggest(self, query: str, catalog: ServiceCatalog) -> list[SuggestedCommand]: ...

    def compose(self, intent: str, catalog: ServiceCatalog) -> ComposeResult: ...


class DeterministicAssistor:
    """Keyword / template matching against the live service catalog.

    Designed as a drop-in for a future OpenAI-backed Assistor
    (``CERTIQS_TERMINAL_ASSIST=openai``).
    """

    def suggest(self, query: str, catalog: ServiceCatalog) -> list[SuggestedCommand]:
        q = (query or "").strip().lower()
        out: list[SuggestedCommand] = []
        for svc in catalog.services:
            hay = " ".join(
                [svc.id, svc.kind, svc.title, *svc.keywords, *svc.commands]
            ).lower()
            if q and q not in hay and not any(tok in hay for tok in q.split()):
                continue
            for ex in svc.examples:
                out.append(
                    SuggestedCommand(
                        title=ex.get("title") or ex.get("prompt", svc.id),
                        prompt=ex.get("prompt", ""),
                        description=ex.get("description", ""),
                        service_id=svc.id,
                        kind=svc.kind,
                    )
                )
            if not svc.examples:
                for cmd in svc.commands[:3]:
                    if cmd.startswith("#"):
                        continue
                    out.append(
                        SuggestedCommand(
                            title=cmd,
                            prompt=cmd,
                            description=svc.title,
                            service_id=svc.id,
                            kind=svc.kind,
                        )
                    )
        seen: set[str] = set()
        unique: list[SuggestedCommand] = []
        for item in out:
            if not item.prompt or item.prompt in seen:
                continue
            seen.add(item.prompt)
            unique.append(item)
        return unique

    def compose(self, intent: str, catalog: ServiceCatalog) -> ComposeResult:
        text = (intent or "").strip()
        if not text:
            return ComposeResult(command="", error="Empty compose intent")

        try:
            tokens = shlex.split(text)
        except ValueError as exc:
            return ComposeResult(command="", error=str(exc))

        if not tokens:
            return ComposeResult(command="", error="Empty compose intent")

        service_tok = tokens[0].lower()
        action = tokens[1].lower() if len(tokens) > 1 else "status"
        extras = tokens[2:] if len(tokens) > 2 else []

        svc = catalog.get(service_tok)
        if svc is None:
            kind_map = {
                "attack": "attack",
                "cm": "countermeasure",
                "countermeasure": "countermeasure",
                "selftest": "countermeasure",
                "params": "params",
                "param": "params",
                "provenance": "provenance",
                "epoch": "provenance",
                "svc": "container",
                "container": "container",
            }
            kind = kind_map.get(service_tok)
            if kind:
                matches = catalog.by_kind(kind)
                if len(matches) == 1:
                    svc = matches[0]
                elif len(matches) > 1 and kind == "container" and len(tokens) > 1:
                    svc = catalog.get(action)
                    if svc is not None:
                        action = extras[0].lower() if extras else "GetCapabilities"
                        extras = extras[1:]
                elif not matches:
                    return ComposeResult(
                        command="",
                        error=f"No services of kind '{kind}' in catalog",
                    )
                else:
                    ids = ", ".join(m.id for m in matches)
                    return ComposeResult(
                        command="",
                        error=f"Ambiguous service '{service_tok}'. Choose: {ids}",
                    )
            else:
                return ComposeResult(
                    command="",
                    error=f"Unknown service '{service_tok}'. Try `suggest` or `help`.",
                )

        assert svc is not None
        kv = " ".join(extras)

        if svc.kind == "attack":
            if action in {"on", "off", "status"}:
                cmd = f"attack {action}"
            elif action == "set":
                cmd = f"attack set {kv}".rstrip()
            else:
                cmd = f"attack {action}" + (f" {kv}" if kv else "")
            return ComposeResult(command=cmd, service_id=svc.id, kind=svc.kind)

        if svc.kind == "countermeasure":
            if action in {"on", "off", "status"}:
                cmd = f"selftest {action}" + (f" {kv}" if kv else "")
            elif action == "set":
                cmd = f"selftest set {kv}".rstrip()
            else:
                cmd = f"selftest {action}" + (f" {kv}" if kv else "")
            return ComposeResult(command=cmd, service_id=svc.id, kind=svc.kind)

        if svc.kind == "params":
            if action == "status":
                return ComposeResult(
                    command="params status", service_id=svc.id, kind=svc.kind
                )
            if action == "set":
                return ComposeResult(
                    command=f"params set {kv}".rstrip(),
                    service_id=svc.id,
                    kind=svc.kind,
                )
            return ComposeResult(
                command=f"params {action}" + (f" {kv}" if kv else ""),
                service_id=svc.id,
                kind=svc.kind,
            )

        if svc.kind == "provenance":
            if action in {"list", "status", "last", "latest"}:
                return ComposeResult(
                    command=f"provenance {action if action != 'latest' else 'last'}",
                    service_id=svc.id,
                    kind=svc.kind,
                )
            if action in {"get", "load", "select"}:
                return ComposeResult(
                    command=f"provenance get {kv}".rstrip(),
                    service_id=svc.id,
                    kind=svc.kind,
                )
            # bare epoch number as action
            return ComposeResult(
                command=f"provenance {action}",
                service_id=svc.id,
                kind=svc.kind,
            )

        if svc.kind == "container":
            remote = action if action not in {"run", "exec"} else (
                extras[0] if extras else "help"
            )
            rest = " ".join(extras[1:] if action in {"run", "exec"} else extras)
            cmd = f"svc {svc.id} {remote}" + (f" {rest}" if rest else "")
            return ComposeResult(command=cmd.strip(), service_id=svc.id, kind=svc.kind)

        return ComposeResult(command="", error=f"Unsupported kind '{svc.kind}'")


def match_ambiguous(query: str, catalog: ServiceCatalog) -> list[str]:
    """Return executable candidates when a free-form phrase matches multiple services."""
    q = (query or "").strip().lower()
    if not q:
        return []
    tokens = set(q.replace("-", " ").split())
    hits: list[str] = []
    for svc in catalog.services:
        keys = {k.lower() for k in svc.keywords} | {svc.id.lower(), svc.kind.lower()}
        if tokens & keys:
            for cmd in svc.commands:
                if not cmd.startswith("#"):
                    hits.append(cmd)
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:12]


__all__ = [
    "Assistor",
    "DeterministicAssistor",
    "match_ambiguous",
]
