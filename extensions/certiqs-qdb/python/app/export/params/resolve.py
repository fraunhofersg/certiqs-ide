"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/params/resolve.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

§7.2 Collect · prompt · apply.

collect_missing_parameters walks the IR and records the REQUIRED catalog specs
that have no value yet (a present-but-null value counts as PRESENT and is not
flagged). apply_resolved_values coerces the answers to the spec type and
writes them back into the IR in place. Range validity is deferred to §8 so
the user sees all issues at once.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Union

from app.export.ir import ExportModel
from app.export.params.catalog import PARAM_CATALOG, ParamSpec


@dataclass
class InstanceTarget:
    kind: Literal["instance"] = "instance"
    instance: str = ""


@dataclass
class ChannelTarget:
    kind: Literal["channel"] = "channel"
    channel: str = ""


@dataclass
class ProtocolTarget:
    kind: Literal["protocol"] = "protocol"


@dataclass
class PostProcessingTarget:
    kind: Literal["post_processing"] = "post_processing"
    stage: str = ""


Target = Union[InstanceTarget, ChannelTarget, ProtocolTarget, PostProcessingTarget]


@dataclass
class MissingParam:
    location: str  # stable id + write-back target, e.g. "instance:alice_apd_h.efficiency"
    label: str  # human-friendly location for the prompt UI
    spec: ParamSpec
    target: Target  # internal write-back descriptor resolved during collection


def _settings_key(spec: ParamSpec) -> str:
    return spec.db_key or spec.field


_CONFIG_NUMBER_RE_CACHE: dict[str, re.Pattern] = {}


def _parse_config_number(config: str | None, field: str) -> float | None:
    """Pre-parse `field: 0.85` numerics out of a post-processing annotation string."""
    if not config:
        return None
    pattern = _CONFIG_NUMBER_RE_CACHE.get(field)
    if pattern is None:
        pattern = re.compile(rf"{re.escape(field)}\s*[:=]\s*(-?\d*\.?\d+(?:e-?\d+)?)", re.IGNORECASE)
        _CONFIG_NUMBER_RE_CACHE[field] = pattern
    m = pattern.search(config)
    return float(m.group(1)) if m else None


def _get_path(obj: object, path: str) -> object:
    cur = obj
    for k in path.split("."):
        if cur is None:
            return None
        cur = cur.get(k) if isinstance(cur, dict) else getattr(cur, k, None)
    return cur


def collect_missing_parameters(model: ExportModel) -> list[MissingParam]:
    """Records the REQUIRED specs with no value; pre-fills any it can parse from config."""
    missing: list[MissingParam] = []

    for spec in PARAM_CATALOG:
        if not spec.required:
            continue

        if spec.scope == "instance":
            for inst in model.instances:
                if inst.component != spec.applies_to:
                    continue
                if _settings_key(spec) in inst.settings:
                    continue  # present (incl. explicit None)
                missing.append(MissingParam(
                    location=f"instance:{inst.name}.{spec.field}",
                    label=f"{inst.name} · {spec.field}",
                    spec=spec, target=InstanceTarget(instance=inst.name),
                ))
        elif spec.scope == "channel":
            for ch in model.channels:
                if ch.type != spec.applies_to:
                    continue
                if spec.field in ch.params:
                    continue
                missing.append(MissingParam(
                    location=f"channel:{ch.name}.{spec.field}",
                    label=f"{ch.name} · {spec.field}",
                    spec=spec, target=ChannelTarget(channel=ch.name),
                ))
        elif spec.scope == "protocol":
            if _get_path(model.protocol, spec.path or spec.field) is not None:
                continue
            missing.append(MissingParam(
                location=f"protocol:{spec.path or spec.field}",
                label=f"protocol · {spec.field}",
                spec=spec, target=ProtocolTarget(),
            ))
        elif spec.scope == "post_processing":
            for stage in model.post_processing:
                if stage.name != spec.applies_to:
                    continue
                parsed = _parse_config_number(stage.config, spec.field)
                if parsed is not None:
                    stage.params[spec.field] = parsed
                    continue  # supplied by config
                if spec.field in stage.params:
                    continue
                missing.append(MissingParam(
                    location=f"post_processing:{stage.name}.{spec.field}",
                    label=f"{stage.name} · {spec.field}",
                    spec=spec, target=PostProcessingTarget(stage=stage.name),
                ))
    return missing


PromptFn = Callable[[MissingParam], Union[str, Awaitable[str]]]


async def prompt_for_missing(missing: list[MissingParam], ask: PromptFn) -> dict[str, str]:
    """Drive an injected prompt for each gap; blank answer accepts the typical default."""
    answers: dict[str, str] = {}
    for m in missing:
        result = ask(m)
        raw = (await result if isinstance(result, Awaitable) else result).strip()
        answers[m.location] = raw if raw != "" else str(m.spec.typical if m.spec.typical is not None else "")
    return answers


def _coerce(spec: ParamSpec, raw: object) -> object:
    if raw is None or raw == "":
        return spec.typical
    if spec.type == "boolean":
        return raw is True or raw == "true"
    if spec.type == "enum":
        return str(raw)
    if spec.type == "ratio_array":
        return [float(x) for x in re.split(r"[,\s]+", str(raw)) if x]
    if spec.type == "integer":
        return int(str(raw), 10)
    # number | nullable_number
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return raw


def _set_path(obj: object, path: str, value: object) -> None:
    keys = path.split(".")
    cur = obj
    for k in keys[:-1]:
        if isinstance(cur, dict):
            cur = cur.setdefault(k, {})
        else:
            nxt = getattr(cur, k, None)
            if nxt is None:
                nxt = {}
                setattr(cur, k, nxt)
            cur = nxt
    last = keys[-1]
    if isinstance(cur, dict):
        cur[last] = value
    else:
        setattr(cur, last, value)


def apply_resolved_values(
    model: ExportModel,
    missing: list[MissingParam],
    values: dict[str, object],
) -> None:
    """Coerce answers to the spec type and write them back into the IR in place."""
    by_location = {m.location: m for m in missing}
    for location, raw in values.items():
        m = by_location.get(location)
        if m is None:
            continue
        value = _coerce(m.spec, raw)
        t = m.target
        if isinstance(t, InstanceTarget):
            inst = next((i for i in model.instances if i.name == t.instance), None)
            if inst:
                inst.settings[_settings_key(m.spec)] = value
        elif isinstance(t, ChannelTarget):
            ch = next((c for c in model.channels if c.name == t.channel), None)
            if ch:
                ch.params[m.spec.field] = value
        elif isinstance(t, ProtocolTarget):
            _set_path(model.protocol, m.spec.path or m.spec.field, value)
        elif isinstance(t, PostProcessingTarget):
            stage = next((s for s in model.post_processing if s.name == t.stage), None)
            if stage:
                stage.params[m.spec.field] = value
