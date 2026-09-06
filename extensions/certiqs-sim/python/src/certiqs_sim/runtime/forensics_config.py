"""Load shared/forensics.yaml anomaly-detection configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

FORENSICS_REL = Path("shared") / "forensics.yaml"

_DEFAULT: dict[str, Any] = {
    "metric_key": "qber",
    "expected_qber": 0.025,
    "min_confident_bits": 500,
    "windows": {"short": 10, "medium": 60, "long": 180},
    "weights": {
        "range": 0.30,
        "deviation": 0.20,
        "trend": 0.20,
        "persistence": 0.20,
        "basis": 0.10,
    },
    "states": {"observation": 0.25, "warning": 0.50, "alarm": 0.75},
    "max_streak_for_observation": 2,
    "trend_alarm_slope": 0.008,
    "basis_metric_x": None,
    "basis_metric_z": None,
}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def load_forensics_config(config_dir: Path | None) -> dict[str, Any]:
    """Return merged forensics config for the active YAML set."""
    out = dict(_DEFAULT)
    if config_dir is None:
        return out
    path = config_dir / FORENSICS_REL
    if not path.is_file():
        return out
    doc = _load_yaml(path)
    body = doc.get("forensics") if isinstance(doc.get("forensics"), dict) else doc
    if not isinstance(body, dict):
        return out
    for key, value in body.items():
        if key in ("windows", "weights", "states") and isinstance(value, dict):
            merged = dict(out.get(key) or {})
            merged.update(value)
            out[key] = merged
        else:
            out[key] = value
    return out


__all__ = ["FORENSICS_REL", "load_forensics_config"]
