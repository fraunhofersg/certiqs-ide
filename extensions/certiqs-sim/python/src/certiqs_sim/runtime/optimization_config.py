"""Load shared/optimization.yaml practical-link optimization knobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

OPTIMIZATION_REL = Path("shared") / "optimization.yaml"

_DEFAULT: dict[str, Any] = {
    "metric_key": "qber",
    "security_metric_key": "secret_fraction",
    "rate_metric_key": "key_rate_per_pulse",
    "qber_target_mode": "abort",
    "qber_target_fraction": 1.0,
    "min_secret_fraction": 0.05,
    "min_key_rate_per_pulse": 0.0,
    "settle_epochs": 15,
    "step_km": 5.0,
    "fine_step_km": 1.0,
    "approach_band": 0.20,
    "max_length_km": 100.0,
    "length_keys": ["alice_length", "bob_length"],
    "length_mode": "symmetric",
    "backoff_on_breach": True,
    "max_steps": 40,
    "window_epochs": 20,
    "aggregator": "median",
    "min_window_samples": 10,
    "max_rise_slope": 0.0015,
}


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        # Invalid YAML must not take down /optimization/config — fall back to defaults.
        return {}


def load_optimization_config(config_dir: Path | None) -> dict[str, Any]:
    """Return merged optimization config for the active YAML set."""
    out = dict(_DEFAULT)
    if config_dir is None:
        return out
    path = config_dir / OPTIMIZATION_REL
    if not path.is_file():
        return out
    doc = _load_yaml(path)
    body = doc.get("optimization") if isinstance(doc.get("optimization"), dict) else doc
    if not isinstance(body, dict):
        return out
    for key, value in body.items():
        out[key] = value
    return out


__all__ = ["OPTIMIZATION_REL", "load_optimization_config"]
