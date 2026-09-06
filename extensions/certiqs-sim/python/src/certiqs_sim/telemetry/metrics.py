"""Prometheus metrics for the certiqsSim platform.

Custom gauges/counters mirror the plan's metric catalog: QBER, secret-key bits,
epoch duration, attack activity, self-test alarms, and engine build errors.  Each
service exposes these on ``/metrics``; the engine calls :func:`observe_window`
once per reporting window.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# A dedicated registry keeps process/GC collectors out unless a service opts in.
REGISTRY = CollectorRegistry()

_COMMON_LABELS = ("service", "run_id", "protocol")


class _Metrics:
    """Namespace holding the platform's Prometheus collectors."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.qber = Gauge(
            "certiqs_qber",
            "Quantum bit error rate (last window)",
            _COMMON_LABELS,
            registry=registry,
        )
        self.secret_key_bits_total = Counter(
            "certiqs_secret_key_bits_total",
            "Cumulative secret-key bits produced",
            _COMMON_LABELS,
            registry=registry,
        )
        self.sifted_key_bits_total = Counter(
            "certiqs_sifted_key_bits_total",
            "Cumulative sifted-key bits",
            _COMMON_LABELS,
            registry=registry,
        )
        self.epoch_duration_seconds = Histogram(
            "certiqs_epoch_duration_seconds",
            "Wall-clock duration of a reporting window",
            _COMMON_LABELS,
            registry=registry,
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
        )
        self.epochs_total = Counter(
            "certiqs_epochs_total",
            "Reporting windows completed",
            _COMMON_LABELS,
            registry=registry,
        )
        self.attack_active = Gauge(
            "certiqs_attack_active",
            "1 if an attack is active on the twin",
            _COMMON_LABELS,
            registry=registry,
        )
        self.selftest_alarm = Gauge(
            "certiqs_selftest_alarm",
            "1 if the detector self-test raised an alarm",
            _COMMON_LABELS,
            registry=registry,
        )
        self.eve_knowledge = Gauge(
            "certiqs_eve_knowledge_fraction",
            "Fraction of the sifted key Eve knows",
            _COMMON_LABELS,
            registry=registry,
        )
        self.engine_build_errors_total = Counter(
            "certiqs_engine_build_errors_total",
            "Twin build failures",
            ("service",),
            registry=registry,
        )
        self.postproc_secure_key_bits_total = Counter(
            "certiqs_postproc_secure_key_bits_total",
            "Cumulative secure-key bits after finite-key post-processing",
            _COMMON_LABELS,
            registry=registry,
        )


METRICS = _Metrics(REGISTRY)


def observe_window(
    results: dict[str, Any],
    *,
    service: str,
    run_id: str,
    protocol: str = "bbm92",
    duration_seconds: float | None = None,
) -> None:
    """Update Prometheus collectors from a single window's result dict."""
    labels = {"service": service, "run_id": run_id, "protocol": protocol}

    qber = results.get("qber")
    if qber is not None:
        METRICS.qber.labels(**labels).set(float(qber))

    METRICS.secret_key_bits_total.labels(**labels).inc(float(results.get("secret_key_bits", 0)))
    METRICS.sifted_key_bits_total.labels(**labels).inc(float(results.get("sifted_key_bits", 0)))
    METRICS.epochs_total.labels(**labels).inc()
    METRICS.attack_active.labels(**labels).set(1.0 if results.get("attack_enabled") else 0.0)
    METRICS.selftest_alarm.labels(**labels).set(float(results.get("selftest_alarm", 0) or 0))
    METRICS.eve_knowledge.labels(**labels).set(float(results.get("eve_knowledge_fraction", 0.0)))

    if results.get("pp_secure_key_bits") is not None:
        METRICS.postproc_secure_key_bits_total.labels(**labels).inc(
            float(results["pp_secure_key_bits"])
        )

    if duration_seconds is not None:
        METRICS.epoch_duration_seconds.labels(**labels).observe(float(duration_seconds))


def render_latest_metrics() -> bytes:
    """Render the current metrics in Prometheus text exposition format."""
    return generate_latest(REGISTRY)


CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


__all__ = [
    "CONTENT_TYPE_LATEST",
    "METRICS",
    "REGISTRY",
    "observe_window",
    "render_latest_metrics",
]
