"""Campaign specification + deterministic runner.

A campaign expands to a matrix of scenarios (attack setting × countermeasure
setting × seed).  Each scenario builds a fresh twin (``build_twin_from_yaml_directory``
resets the NetSquid engine), runs a fixed number of windows with a fixed seed, and
aggregates evaluation statistics: mean QBER, Eve knowledge, and — crucially — the
self-test detection power (alarm rate under attack) and false-alarm rate
(alarm rate without attack).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from certiqs_sim.core.attacks import get_attack_factory
from certiqs_sim.core.countermeasures import get_countermeasure_factory
from certiqs_sim.core.twin import build_twin_from_yaml_directory
from certiqs_sim.runtime.params import apply_overrides
from certiqs_sim.telemetry.logging import get_logger

_log = get_logger("certiqs.seceval")


class AttackSetting(BaseModel):
    name: str = "faked_state"
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None

    def display(self) -> str:
        if self.label:
            return self.label
        return "baseline" if not self.enabled else self.name


class CountermeasureSetting(BaseModel):
    name: str = "detector_selftest"
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None

    def display(self) -> str:
        if self.label:
            return self.label
        if not self.enabled:
            return "none"
        return f"{self.name}:{self.params.get('mode', 'flag')}"


class CampaignSpec(BaseModel):
    name: str = "campaign"
    description: str = ""
    config_name: str = "bbm92-generic"
    protocol: str = "bbm92"
    shots_per_window: int = 60_000
    windows: int = 8
    base_overrides: dict[str, float] = Field(default_factory=dict)
    attacks: list[AttackSetting] = Field(
        default_factory=lambda: [AttackSetting(enabled=False, label="baseline"), AttackSetting()]
    )
    countermeasures: list[CountermeasureSetting] = Field(
        default_factory=lambda: [CountermeasureSetting()]
    )
    seeds: list[int] = Field(default_factory=lambda: [11])

    @classmethod
    def from_yaml(cls, path: Path) -> CampaignSpec:
        import yaml

        with Path(path).open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(data)


@dataclass
class ScenarioResult:
    attack: str
    countermeasure: str
    seed: int
    attack_enabled: bool
    windows: int
    mean_qber: float | None
    mean_eve_knowledge: float
    mean_secure_key_bits: float
    alarm_rate: float
    alarms: list[int] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attack": self.attack,
            "countermeasure": self.countermeasure,
            "seed": self.seed,
            "attack_enabled": self.attack_enabled,
            "windows": self.windows,
            "mean_qber": self.mean_qber,
            "mean_eve_knowledge": self.mean_eve_knowledge,
            "mean_secure_key_bits": self.mean_secure_key_bits,
            "alarm_rate": self.alarm_rate,
            "alarms": self.alarms,
            "detail": self.detail,
        }


def _run_scenario(
    config_dir: Path,
    protocol: str,
    base_overrides: dict[str, float],
    attack: AttackSetting,
    countermeasure: CountermeasureSetting,
    shots: int,
    windows: int,
    seed: int,
) -> ScenarioResult:
    twin = build_twin_from_yaml_directory(config_dir, protocol)
    apply_overrides(twin, base_overrides)

    attack_params = {**attack.params, "enabled": attack.enabled}
    get_attack_factory(attack.name)(twin, attack_params)

    cm_params = {**countermeasure.params, "enabled": countermeasure.enabled}
    get_countermeasure_factory(countermeasure.name)(twin, cm_params)

    np.random.seed(seed)
    random.seed(seed)

    qbers: list[float] = []
    eve: list[float] = []
    secure: list[float] = []
    alarms: list[int] = []
    detection_powers: list[float] = []
    false_alarm_probs: list[float] = []

    for _ in range(windows):
        r = twin.run_window(shots)
        if r.get("qber") is not None:
            qbers.append(float(r["qber"]))
        eve.append(float(r.get("eve_knowledge_fraction", 0.0)))
        secure.append(float(r.get("secret_key_bits", 0)))
        alarms.append(int(r.get("selftest_alarm", 0) or 0))
        if r.get("selftest_detection_power") is not None:
            detection_powers.append(float(r["selftest_detection_power"]))
        if r.get("selftest_false_alarm_prob") is not None:
            false_alarm_probs.append(float(r["selftest_false_alarm_prob"]))

    mean_qber = float(np.mean(qbers)) if qbers else None
    return ScenarioResult(
        attack=attack.display(),
        countermeasure=countermeasure.display(),
        seed=seed,
        attack_enabled=attack.enabled,
        windows=windows,
        mean_qber=mean_qber,
        mean_eve_knowledge=float(np.mean(eve)) if eve else 0.0,
        mean_secure_key_bits=float(np.mean(secure)) if secure else 0.0,
        alarm_rate=float(np.mean(alarms)) if alarms else 0.0,
        alarms=alarms,
        detail={
            "mean_detection_power": float(np.mean(detection_powers)) if detection_powers else None,
            "mean_false_alarm_prob": float(np.mean(false_alarm_probs))
            if false_alarm_probs
            else None,
        },
    )


def run_campaign(spec: CampaignSpec, config_root: Path) -> list[ScenarioResult]:
    """Execute every scenario in the campaign matrix, sequentially and reproducibly."""
    config_dir = Path(config_root) / spec.config_name
    if not config_dir.is_dir():
        raise FileNotFoundError(f"Unknown config '{spec.config_name}' under {config_root}")

    results: list[ScenarioResult] = []
    combos = list(product(spec.attacks, spec.countermeasures, spec.seeds))
    _log.info("campaign_started", name=spec.name, scenarios=len(combos))
    for attack, cm, seed in combos:
        res = _run_scenario(
            config_dir,
            spec.protocol,
            spec.base_overrides,
            attack,
            cm,
            spec.shots_per_window,
            spec.windows,
            seed,
        )
        _log.info(
            "scenario_done",
            attack=res.attack,
            countermeasure=res.countermeasure,
            seed=seed,
            mean_qber=res.mean_qber,
            alarm_rate=res.alarm_rate,
        )
        results.append(res)
    return results


__all__ = [
    "AttackSetting",
    "CampaignSpec",
    "CountermeasureSetting",
    "ScenarioResult",
    "run_campaign",
]
