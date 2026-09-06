"""certiqs-seceval: security-evaluation orchestrator.

Treats evaluation as first-class.  A *campaign* is a matrix of
config × attack-parameter settings × countermeasure settings × seeds, executed
deterministically across the engine, producing a reproducible, hash-signed report
with detection-power / false-alarm statistics.  Outputs map to evaluation-standard
language (ETSI GS QKD 016, ISO/IEC 23837).
"""

from __future__ import annotations

from certiqs_sim.services.seceval.campaign import (
    AttackSetting,
    CampaignSpec,
    CountermeasureSetting,
    ScenarioResult,
    run_campaign,
)
from certiqs_sim.services.seceval.report import EvaluationReport, build_report

__all__ = [
    "AttackSetting",
    "CampaignSpec",
    "CountermeasureSetting",
    "EvaluationReport",
    "ScenarioResult",
    "build_report",
    "run_campaign",
]
