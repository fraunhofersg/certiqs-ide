"""Load standards-derived metric display guidance from config YAML.

Primary path: ``<config>/shared/technical_ranges.yaml``.

Preferred assessment shape (e.g. QBER)::

    metric_key: qber
    nominal: 0.025
    good_range: [0.01, 0.04]
    warning_threshold: 0.06
    abort_threshold: 0.11

Also accepts legacy ``lower`` / ``upper`` rows and optional monitoring alert bridges.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

TECHNICAL_RANGES_REL = Path("shared") / "technical_ranges.yaml"


@dataclass(frozen=True)
class AssessmentBand:
    """Colored Y-band (success / warning / danger)."""

    level: str  # success | warning | danger
    lower: float
    upper: float
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v is not None}


@dataclass(frozen=True)
class AssessmentLine:
    """Horizontal reference line."""

    level: str  # success | warning | danger | default
    y: float
    label: str | None = None
    style: str = "dashed"  # dashed | solid

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: v for k, v in out.items() if v is not None}


@dataclass(frozen=True)
class TechnicalRange:
    metric_key: str
    # Assessment inputs (optional)
    nominal: float | None = None
    good_range: tuple[float, float] | None = None
    warning_threshold: float | None = None
    abort_threshold: float | None = None
    # Derived / display
    bands: tuple[AssessmentBand, ...] = ()
    lines: tuple[AssessmentLine, ...] = ()
    # Metadata
    context: str | None = None
    standard: str | None = None
    label: str | None = None
    contributions: dict[str, float] = field(default_factory=dict)
    # Legacy single-band fields (still emitted for simple consumers)
    lower: float | None = None
    upper: float | None = None
    kind: str | None = None
    upper_label: str | None = None
    lower_label: str | None = None

    def to_catalog_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "bands": [b.to_dict() for b in self.bands],
            "lines": [ln.to_dict() for ln in self.lines],
        }
        for key in (
            "nominal",
            "good_range",
            "warning_threshold",
            "abort_threshold",
            "context",
            "standard",
            "label",
            "lower",
            "upper",
            "kind",
            "upper_label",
            "lower_label",
        ):
            val = getattr(self, key)
            if val is None:
                continue
            if key == "good_range" and isinstance(val, tuple):
                out[key] = [val[0], val[1]]
            else:
                out[key] = val
        if self.contributions:
            out["contributions"] = dict(self.contributions)
        return out


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _parse_good_range(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    return float(raw[0]), float(raw[1])


def _derive_bands_and_lines(row: dict[str, Any]) -> tuple[
    list[AssessmentBand], list[AssessmentLine], float | None, float | None
]:
    """Build success/warning/danger overlays from assessment or legacy fields."""
    bands: list[AssessmentBand] = []
    lines: list[AssessmentLine] = []

    good = _parse_good_range(row.get("good_range"))
    warning_th = float(row["warning_threshold"]) if row.get("warning_threshold") is not None else None
    abort_th = float(row["abort_threshold"]) if row.get("abort_threshold") is not None else None
    nominal = float(row["nominal"]) if row.get("nominal") is not None else None

    if good is not None or (warning_th is not None and abort_th is not None):
        # Chart bands (higher-is-worse metrics such as QBER):
        #   green  → all values below warning_threshold
        #   orange → warning_threshold .. abort_threshold
        #   red    → everything above abort_threshold (through display ceiling)
        if warning_th is not None and abort_th is not None and abort_th > warning_th:
            display_ceil = 1.0
            bands.append(
                AssessmentBand(
                    level="success",
                    lower=0.0,
                    upper=warning_th,
                    label="OK / below warning",
                )
            )
            bands.append(
                AssessmentBand(
                    level="warning",
                    lower=warning_th,
                    upper=abort_th,
                    label="Warning → approach abort",
                )
            )
            bands.append(
                AssessmentBand(
                    level="danger",
                    lower=abort_th,
                    upper=display_ceil,
                    label="Abort / above threshold",
                )
            )
        elif good is not None:
            # Fallback when abort/warning incomplete: keep good_range as green.
            bands.append(
                AssessmentBand(
                    level="success",
                    lower=good[0],
                    upper=good[1],
                    label="Good / excellent",
                )
            )
            if warning_th is not None and warning_th > good[1]:
                bands.append(
                    AssessmentBand(
                        level="warning",
                        lower=good[1],
                        upper=warning_th,
                        label="Usable → optimize",
                    )
                )
            if abort_th is not None and abort_th > (warning_th or good[1]):
                bands.append(
                    AssessmentBand(
                        level="danger",
                        lower=warning_th if warning_th is not None else good[1],
                        upper=abort_th,
                        label="Marginal → near abort",
                    )
                )

        if nominal is not None:
            lines.append(
                AssessmentLine(
                    level="success",
                    y=nominal,
                    label="nominal",
                    style="dashed",
                )
            )
        if warning_th is not None:
            lines.append(
                AssessmentLine(
                    level="warning", y=warning_th, label="warning", style="dashed"
                )
            )
        if abort_th is not None:
            lines.append(
                AssessmentLine(level="danger", y=abort_th, label="abort", style="dashed")
            )

        lower = 0.0 if warning_th is not None else (good[0] if good else None)
        upper = abort_th if abort_th is not None else (good[1] if good else None)
        return bands, lines, lower, upper

    # Legacy lower/upper → single success band + optional upper line
    if "lower" in row and ("upper" in row or "threshold" in row):
        lower = float(row["lower"])
        upper = float(row["upper"] if "upper" in row else row["threshold"])
        bands.append(
            AssessmentBand(
                level=str(row.get("kind") or "success"),
                lower=lower,
                upper=upper,
                label=row.get("label"),
            )
        )
        lines.append(
            AssessmentLine(
                level="danger" if upper >= 0.1 else "warning",
                y=upper,
                label=row.get("upper_label") or "upper",
                style="dashed",
            )
        )
        if lower > 0:
            lines.append(
                AssessmentLine(
                    level="default",
                    y=lower,
                    label=row.get("lower_label") or "lower",
                    style="dashed",
                )
            )
        return bands, lines, lower, upper

    return bands, lines, None, None


def _range_from_row(row: dict[str, Any]) -> TechnicalRange | None:
    key = str(row.get("metric_key") or "").strip()
    if not key:
        return None

    bands, lines, lower, upper = _derive_bands_and_lines(row)
    if not bands and not lines and lower is None:
        return None

    good = _parse_good_range(row.get("good_range"))
    contribs_raw = row.get("contributions") or {}
    contributions = {
        str(k): float(v)
        for k, v in contribs_raw.items()
        if isinstance(v, (int, float))
    }

    return TechnicalRange(
        metric_key=key,
        nominal=float(row["nominal"]) if row.get("nominal") is not None else None,
        good_range=good,
        warning_threshold=(
            float(row["warning_threshold"])
            if row.get("warning_threshold") is not None
            else None
        ),
        abort_threshold=(
            float(row["abort_threshold"]) if row.get("abort_threshold") is not None else None
        ),
        bands=tuple(bands),
        lines=tuple(lines),
        context=row.get("context"),
        standard=row.get("standard"),
        label=row.get("label"),
        contributions=contributions,
        lower=lower,
        upper=upper,
        kind=str(row.get("kind") or "security"),
        upper_label=row.get("upper_label"),
        lower_label=row.get("lower_label"),
    )


def load_technical_ranges_file(path: Path) -> dict[str, TechnicalRange]:
    if not path.is_file():
        return {}
    doc = _load_yaml(path)
    out: dict[str, TechnicalRange] = {}
    for row in doc.get("technical_ranges") or []:
        if not isinstance(row, dict):
            continue
        tr = _range_from_row(row)
        if tr is not None:
            out[tr.metric_key] = tr
    return out


def load_monitoring_alert_ranges(config_dir: Path) -> dict[str, TechnicalRange]:
    """Optional bridge: alerts with metric_key + lower/upper (or threshold)."""
    out: dict[str, TechnicalRange] = {}
    nodes = config_dir / "nodes"
    if not nodes.is_dir():
        return out
    for mon_path in sorted(nodes.glob("*/monitoring.yaml")):
        doc = _load_yaml(mon_path)
        monitoring = doc.get("monitoring") or {}
        for alert in monitoring.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            row = dict(alert)
            if "metric_key" not in row:
                continue
            # Prefer assessment fields if present; else map threshold → abort-style legacy.
            if "good_range" not in row and "abort_threshold" not in row:
                if "lower" not in row:
                    row["lower"] = 0.0
                if "upper" not in row and "threshold" in row:
                    row["upper"] = row["threshold"]
                if "upper_label" not in row and "threshold" in row:
                    row["upper_label"] = f"{float(row['threshold']):g} abort"
            tr = _range_from_row(row)
            if tr is not None and tr.metric_key not in out:
                out[tr.metric_key] = tr
    return out


def load_technical_ranges(config_dir: Path | None) -> dict[str, TechnicalRange]:
    """Merge shared technical_ranges.yaml over optional monitoring alert bridges."""
    if config_dir is None or not config_dir.is_dir():
        return {}
    ranges = load_monitoring_alert_ranges(config_dir)
    ranges.update(load_technical_ranges_file(config_dir / TECHNICAL_RANGES_REL))
    return ranges


__all__ = [
    "TECHNICAL_RANGES_REL",
    "AssessmentBand",
    "AssessmentLine",
    "TechnicalRange",
    "load_technical_ranges",
    "load_technical_ranges_file",
    "load_monitoring_alert_ranges",
]
