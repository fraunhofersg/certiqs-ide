"""Reproducible, hash-signed evaluation report.

A report bundles the campaign inputs (provenance), the per-scenario results, and
derived detection-power / false-alarm ROC-style statistics, then computes a SHA-256
digest over the canonical JSON so the artifact is self-verifying: re-running the
same seeded campaign reproduces the same digest.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from certiqs_sim import __version__
from certiqs_sim.services.seceval.campaign import CampaignSpec, ScenarioResult


@dataclass
class EvaluationReport:
    spec: dict[str, Any]
    scenarios: list[dict[str, Any]]
    summary: dict[str, Any]
    provenance: dict[str, Any]
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "scenarios": self.scenarios,
            "summary": self.summary,
            "provenance": self.provenance,
            "digest": self.digest,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def _canonical_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _summarize(results: list[ScenarioResult]) -> dict[str, Any]:
    """Derive evaluation KPIs: detection power (alarm rate under attack) vs
    false-alarm rate (alarm rate without attack), grouped by countermeasure."""
    by_cm: dict[str, dict[str, list[float]]] = {}
    for r in results:
        bucket = by_cm.setdefault(r.countermeasure, {"attack": [], "clean": []})
        bucket["attack" if r.attack_enabled else "clean"].append(r.alarm_rate)

    detection: dict[str, Any] = {}
    for cm, buckets in by_cm.items():
        att = buckets["attack"]
        clean = buckets["clean"]
        detection[cm] = {
            "detection_power": sum(att) / len(att) if att else None,
            "false_alarm_rate": sum(clean) / len(clean) if clean else None,
        }

    attack_scenarios = [r for r in results if r.attack_enabled]
    worst_eve = max((r.mean_eve_knowledge for r in attack_scenarios), default=0.0)
    return {
        "scenario_count": len(results),
        "detection_by_countermeasure": detection,
        "max_eve_knowledge_under_attack": worst_eve,
        "standards_mapping": {
            "etsi_gs_qkd_016": "detector-manipulation protection-profile evaluation",
            "iso_iec_23837": "implementation-attack security evaluation",
        },
    }


def build_report(spec: CampaignSpec, results: list[ScenarioResult]) -> EvaluationReport:
    scenarios = [r.to_dict() for r in results]
    summary = _summarize(results)
    provenance = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "certiqs_sim_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seeds": spec.seeds,
    }
    spec_dump: dict[str, Any] = spec.model_dump()
    body = {
        "spec": spec_dump,
        "scenarios": scenarios,
        "summary": summary,
    }
    # The digest covers inputs + results but not the wall-clock timestamp, so the
    # same seeded campaign is bit-for-bit reproducible.
    digest = _canonical_digest(body)
    return EvaluationReport(
        spec=spec_dump,
        scenarios=scenarios,
        summary=summary,
        provenance=provenance,
        digest=digest,
    )


__all__ = ["EvaluationReport", "build_report"]
