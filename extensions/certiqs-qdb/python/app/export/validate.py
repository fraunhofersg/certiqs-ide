"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/validate.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

§8 Validation — fail-fast, global. Runs after parameter resolution, before any
file is written. Collects ALL issues, then the export aborts if any are errors
(warnings are advisory unless `strict`). Two families: manifest structural
invariants + simulation-parameter type/range checks against the catalog.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from app.export.ir import ExportModel, ResolvedConnection
from app.export.params.catalog import PARAM_CATALOG, STRUCTURAL_RULES, ParamSpec

Level = Literal["error", "warning"]


@dataclass
class Issue:
    level: Level
    code: str
    message: str


def _split_endpoint(token: str) -> tuple[str, str]:
    """Split "<name>.<net>" on the LAST dot — instance names may themselves contain
    a dot (e.g. "central_spdc_source.crystal"), so a naive first-dot split is wrong."""
    i = token.rfind(".")
    return (token, "") if i < 0 else (token[:i], token[i + 1 :])


_CLICK_IN_RE = re.compile(r"click_in\[(\d+)\]")


def validate_model(model: ExportModel, connections: list[ResolvedConnection]) -> list[Issue]:
    issues: list[Issue] = []

    def err(code: str, message: str) -> None:
        issues.append(Issue(level="error", code=code, message=message))

    def warn(code: str, message: str) -> None:
        issues.append(Issue(level="warning", code=code, message=message))

    # ── Family 1: manifest structural invariants ───────────────────────────────

    # require_unique_instance_names
    seen: set[str] = set()
    for inst in model.instances:
        if inst.name in seen:
            err("unique_instance_names", f'duplicate instance name "{inst.name}"')
        seen.add(inst.name)
    if len(model.instances) == 0:
        err("empty", "system has no named component instances to export")

    # require_declared_ports — every endpoint resolves to a declared port/channel leg
    inst_by_name = {i.name: i for i in model.instances}
    channel_by_name = {c.name: c for c in model.channels}

    def check_endpoint(token: str, where: str) -> None:
        name, net = _split_endpoint(token)
        if name in channel_by_name:
            if net not in ("in", "out"):
                warn("declared_ports", f'{where}: channel "{name}" leg "{net}" is not in/out')
            return
        inst = inst_by_name.get(name)
        if inst is None:
            err("declared_ports", f'{where}: endpoint "{token}" references unknown instance "{name}"')
            return
        if net and net not in inst.ports:
            err("declared_ports", f'{where}: net "{net}" not declared on instance "{name}"')

    for c in connections:
        check_endpoint(c.from_, "connection")
        check_endpoint(c.to, "connection")
    for b in model.cosim.bindings:
        check_endpoint(b.from_, "binding")
        check_endpoint(b.to, "binding")

    # require_declared_packet_types (trivial today — template supplies them)
    if len(model.protocol.packet_types) == 0:
        warn("packet_types", "protocol declares no packet types")

    # composition.nodes == subsystem canonical names (emitted from the same source)
    if len(model.nodes) == 0:
        err("nodes", "no composition nodes derived from the system's modules")

    # require_bit_mapping_consistency — bit_mapping == detector `bit`
    detectors = [i for i in model.instances if i.detector]
    for d in detectors:
        meta = d.detector
        if meta.state and isinstance(meta.bit, int):
            mapped = model.protocol.bit_mapping.get(meta.state)
            if mapped is not None and mapped != meta.bit:
                err("bit_mapping", f'detector "{d.name}" bit={meta.bit} disagrees with protocol bit_mapping[{meta.state}]={mapped}')

    # channel_id order == cosim click_in[N] bit order
    for b in model.cosim.bindings:
        m = _CLICK_IN_RE.search(b.to)
        if not m:
            continue
        idx = int(m.group(1))
        name, _net = _split_endpoint(b.from_)
        inst = inst_by_name.get(name)
        ch_id = inst.detector.channel_id if inst and inst.detector else None
        if isinstance(ch_id, int) and ch_id != idx:
            err("bit_mapping", f'binding "{b.from_}"→click_in[{idx}] but detector channel_id={ch_id} (click bit order must match channel_id)')

    # ── Family 2: simulation-parameter checks against the catalog ───────────────
    def check_value(spec: ParamSpec, value: object, loc: str) -> None:
        if value is None:
            return
        if spec.type == "enum":
            if spec.enum_values and str(value) not in spec.enum_values:
                err("param_enum", f'{loc}: "{value}" not one of {", ".join(spec.enum_values)}')
            return
        if spec.type == "boolean":
            if not isinstance(value, bool):
                err("param_type", f"{loc}: expected boolean, got {type(value).__name__}")
            return
        if spec.type == "ratio_array":
            if not isinstance(value, list):
                err("param_type", f"{loc}: expected ratio array")
                return
            total = sum(value)
            if abs(total - 1) > 1e-6:
                err("param_ratio", f"{loc}: ratio array must sum to 1.0 (got {total})")
            return
        n = value if isinstance(value, (int, float)) and not isinstance(value, bool) else _js_number(value)
        if isinstance(n, float) and math.isnan(n):
            err("param_type", f'{loc}: expected number, got "{value}"')
            return
        if spec.hard_min is not None and n < spec.hard_min:
            err("param_range", f"{loc}: {n} below hard minimum {spec.hard_min}")
        if spec.hard_max is not None and n > spec.hard_max:
            err("param_range", f"{loc}: {n} above hard maximum {spec.hard_max}")
        if spec.soft_min is not None and n < spec.soft_min:
            warn("param_soft", f"{loc}: {n} below usual range {spec.soft_min}–{spec.soft_max} (unusual but allowed)")
        if spec.soft_max is not None and n > spec.soft_max:
            warn("param_soft", f"{loc}: {n} above usual range {spec.soft_min}–{spec.soft_max} (unusual but allowed)")

    for spec in PARAM_CATALOG:
        if spec.scope == "instance":
            for inst in model.instances:
                if inst.component != spec.applies_to:
                    continue
                check_value(spec, inst.settings.get(spec.db_key or spec.field), f"{inst.name}.{spec.field}")
        elif spec.scope == "channel":
            for ch in model.channels:
                if ch.type != spec.applies_to:
                    continue
                check_value(spec, ch.params.get(spec.field), f"{ch.name}.{spec.field}")
        elif spec.scope == "protocol":
            check_value(spec, _get_path(model.protocol, spec.path or spec.field), f"protocol.{spec.field}")
        elif spec.scope == "post_processing":
            for stage in model.post_processing:
                if stage.name != spec.applies_to:
                    continue
                check_value(spec, stage.params.get(spec.field), f"{stage.name}.{spec.field}")

    # Structural cross-field rules (e.g. gated detector must declare gate width)
    for rule in STRUCTURAL_RULES:
        for inst in model.instances:
            if inst.component != rule.applies_to:
                continue
            if inst.settings.get(rule.when) == rule.equals:
                v = inst.settings.get(rule.require_non_null)
                if v is None:
                    err("structural", f"{inst.name}: {rule.message}")

    return issues


def _get_path(obj: object, path: str) -> object:
    cur = obj
    for k in path.split("."):
        if cur is None:
            return None
        cur = cur.get(k) if isinstance(cur, dict) else getattr(cur, k, None)
    return cur


def _js_number(value: object) -> float:
    """Mirrors JS `Number(value)` for the shapes reachable here."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return 0.0  # unreachable today (caller already returns early on None) — correct anyway
    try:
        return float(str(value).strip())
    except ValueError:
        return math.nan


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
