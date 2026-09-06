"""Shared types and response helpers for the simulation terminal."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TerminalContext:
    """Runtime bindings for one prompt evaluation."""

    run_status: dict[str, Any] | None = None
    current_attack: dict[str, Any] | None = None
    current_selftest: dict[str, Any] | None = None
    apply_attack: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    apply_selftest: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    apply_params: Callable[[dict[str, float]], dict[str, float]] | None = None
    run_container_prompt: Callable[[str, str], dict[str, Any]] | None = None
    list_containers: Callable[[], list[dict[str, Any]]] | None = None
    get_history: Callable[[], list[dict[str, Any]]] | None = None
    get_settings_for_epoch: Callable[[int], dict[str, Any] | None] | None = None


@dataclass
class SuggestedCommand:
    title: str
    prompt: str
    description: str = ""
    service_id: str = ""
    kind: str = ""


@dataclass
class ComposeResult:
    command: str
    service_id: str = ""
    kind: str = ""
    note: str = ""
    error: str | None = None


@dataclass
class Clarification:
    message: str
    candidates: list[str] = field(default_factory=list)


def ok(
    command: str,
    result: Any,
    *,
    note: str = "",
    applied: dict[str, Any] | None = None,
    suggestions: list[dict[str, str]] | None = None,
    candidates: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ok": True,
        "command": command,
        "result": result,
        "output": (
            result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
        ),
        "note": note,
        "error": None,
        "applied": applied,
    }
    if suggestions is not None:
        row["suggestions"] = suggestions
    if candidates is not None:
        row["candidates"] = candidates
    return row


def err(
    command: str,
    error: str,
    *,
    candidates: list[str] | None = None,
    suggestions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ok": False,
        "command": command,
        "result": None,
        "output": error,
        "note": "",
        "error": error,
        "applied": None,
    }
    if candidates is not None:
        row["candidates"] = candidates
    if suggestions is not None:
        row["suggestions"] = suggestions
    return row


def parse_kv(tokens: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for tok in tokens:
        if tok.startswith("--") and "=" in tok:
            key, raw = tok[2:].split("=", 1)
        elif "=" in tok:
            key, raw = tok.split("=", 1)
        else:
            continue
        key = key.strip().replace("-", "_")
        raw = raw.strip().strip("'\"")
        if raw.lower() in {"true", "false"}:
            out[key] = raw.lower() == "true"
        else:
            try:
                if "." in raw:
                    out[key] = float(raw)
                else:
                    out[key] = int(raw)
            except ValueError:
                out[key] = raw
    return out


def extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


__all__ = [
    "Clarification",
    "ComposeResult",
    "SuggestedCommand",
    "TerminalContext",
    "err",
    "extract_json_object",
    "ok",
    "parse_kv",
]
