"""Extensible output-metric registry.

Each reporting window produces a flat ``{key: value}`` metrics dict driven by this
registry, so a DataPoint never hard-codes which observables exist.  Adding a new
plottable output later is a one-line :class:`MetricSpec` — it then appears
automatically in the metrics-catalog endpoint and becomes selectable in the
frontend, with no schema or pipeline changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricSpec:
    key: str
    label: str
    unit: str = ""
    source: str | None = None
    kind: str = "instant"  # "instant" reads `source`; "cumulative" keeps a running sum
    default_plot: bool = False
    extractor: Callable[[dict[str, Any]], float | None] | None = field(default=None, repr=False)


DEFAULT_METRICS: list[MetricSpec] = [
    MetricSpec("qber", "QBER", "", source="qber", default_plot=True),
    MetricSpec(
        "secret_key_total",
        "Secret key (cumulative)",
        "bits",
        source="secret_key_bits",
        kind="cumulative",
        default_plot=True,
    ),
    MetricSpec("secret_key_bits", "Secret key (per epoch)", "bits", source="secret_key_bits"),
    MetricSpec("sifted_key_bits", "Sifted bits (per epoch)", "bits", source="sifted_key_bits"),
    MetricSpec("secret_fraction", "Secret fraction r", "", source="secret_fraction"),
    MetricSpec("key_rate_per_pulse", "Key rate / pulse", "", source="key_rate_per_pulse"),
    MetricSpec("coincidences", "Coincidences (per epoch)", "", source="coincidences"),
    MetricSpec("bob_detection_rate", "Bob detection rate", "", source="bob_detection_rate"),
    MetricSpec("eve_knowledge_fraction", "Eve knowledge", "", source="eve_knowledge_fraction"),
    MetricSpec("attack_success_prob", "Attack success prob", "", source="attack_success_prob"),
    # Finite-key post-processing outputs (populated by the post-processing layer).
    MetricSpec(
        "pp_secure_key_bits", "Secure key after PP (per epoch)", "bits", source="pp_secure_key_bits"
    ),
    MetricSpec(
        "pp_secure_key_total",
        "Secure key after PP (cumulative)",
        "bits",
        source="pp_secure_key_bits",
        kind="cumulative",
    ),
    MetricSpec("pp_ec_leakage_bits", "EC leakage", "bits", source="pp_ec_leakage_bits"),
    # Detector self-testing countermeasure.
    MetricSpec("selftest_alarm", "Self-test alarm (manipulation)", "", source="selftest_alarm"),
    MetricSpec("selftest_statistic", "Self-test statistic", "", source="selftest_statistic"),
    MetricSpec(
        "selftest_detection_power",
        "Self-test detection power",
        "",
        source="selftest_detection_power",
    ),
    MetricSpec(
        "selftest_false_alarm_prob",
        "Self-test false-alarm prob",
        "",
        source="selftest_false_alarm_prob",
    ),
    MetricSpec("selftest_duty_loss", "Self-test duty loss", "", source="selftest_duty_loss"),
]


class MetricRegistry:
    def __init__(self, specs: list[MetricSpec] | None = None):
        self.specs: list[MetricSpec] = list(specs or DEFAULT_METRICS)
        self._cumulative: dict[str, float] = {}

    def reset(self) -> None:
        self._cumulative.clear()

    def catalog(
        self,
        *,
        technical_ranges: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Emit metric catalog entries, optionally overlaying config technical ranges."""
        from certiqs_sim.runtime.technical_ranges import TechnicalRange

        rows: list[dict[str, Any]] = []
        for s in self.specs:
            entry: dict[str, Any] = {
                "key": s.key,
                "label": s.label,
                "unit": s.unit,
                "kind": s.kind,
                "default_plot": s.default_plot,
                "technical_range": None,
            }
            if technical_ranges and s.key in technical_ranges:
                tr = technical_ranges[s.key]
                if isinstance(tr, TechnicalRange):
                    entry["technical_range"] = tr.to_catalog_dict()
                elif isinstance(tr, dict):
                    entry["technical_range"] = {
                        k: v
                        for k, v in tr.items()
                        if k != "metric_key" and v is not None
                    }
            rows.append(entry)
        return rows

    def extract(self, window_result: dict[str, Any]) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for spec in self.specs:
            if spec.extractor is not None:
                value = spec.extractor(window_result)
            elif spec.kind == "cumulative":
                inc = (window_result.get(spec.source) if spec.source else 0.0) or 0.0
                self._cumulative[spec.key] = self._cumulative.get(spec.key, 0.0) + float(inc)
                value = self._cumulative[spec.key]
            else:
                value = window_result.get(spec.source) if spec.source else None
            out[spec.key] = None if value is None else float(value)
        return out


__all__ = ["DEFAULT_METRICS", "MetricRegistry", "MetricSpec"]
