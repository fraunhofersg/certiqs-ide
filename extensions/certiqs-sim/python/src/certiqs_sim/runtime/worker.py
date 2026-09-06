"""Continuously-running digital-twin worker.

A single :class:`TwinWorker` thread owns the NetSquid twin and its global engine
(NetSquid is not reentrant, so exactly one twin runs per process).  It drives
``twin.run_window`` in a loop, emitting one DataPoint per reporting window,
forever.  Each DataPoint carries a ``settings_version`` whose full snapshot is
kept (and persisted), giving exact provenance.

Compared with the original monolith this worker adds structured logging,
Prometheus metrics, optional Postgres persistence, and event-bus publication — but
the control model (queue-driven, changes applied between windows) is unchanged.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from certiqs_sim.bus.base import (
    EventBus,
    datapoint_subject,
    sifted_subject,
    status_subject,
)
from certiqs_sim.core.twin import build_twin_from_yaml_directory
from certiqs_sim.persistence.repository import NullRepository, Repository
from certiqs_sim.runtime.metrics_registry import MetricRegistry
from certiqs_sim.runtime.params import (
    apply_attack,
    apply_overrides,
    apply_selftest,
    read_attack_params,
    read_current_params,
    read_selftest_params,
)
from certiqs_sim.telemetry.logging import get_logger
from certiqs_sim.telemetry.metrics import observe_window

_log = get_logger("certiqs.engine")

# An optional hook the engine service installs to post-process each window's
# sifted block into a finite-key secure length before the datapoint is emitted.
PostProcessHook = Callable[[dict[str, Any]], dict[str, Any]]


class TwinWorker(threading.Thread):
    def __init__(
        self,
        config_dir: Path,
        config_name: str,
        *,
        run_id: str = "default",
        protocol: str = "bbm92",
        initial_overrides: dict[str, float] | None = None,
        initial_attack: dict[str, Any] | None = None,
        initial_selftest: dict[str, Any] | None = None,
        shots_per_window: int = 100_000,
        min_period_s: float = 0.0,
        history_max: int = 5000,
        collect_sifted: bool = False,
        bus: EventBus | None = None,
        bus_prefix: str = "certiqs",
        repository: Repository | None = None,
        registry: MetricRegistry | None = None,
        service_name: str = "certiqs-engine",
        post_process: PostProcessHook | None = None,
        log_window_epochs: bool = False,
        log_control: bool = False,
        povm_service_target: str | None = None,
        povm_service_timeout_s: float = 120.0,
        povm_service_strict: bool = False,
        povm_backend: str = "auto",
        povm_local_cutoff_dim: int = 1,
    ) -> None:
        super().__init__(daemon=True, name=f"certiqs-twin-{run_id}")
        self.config_dir = Path(config_dir)
        self.config_name = config_name
        self.run_id = run_id
        self.protocol = protocol
        self.shots_per_window = int(shots_per_window)
        self.min_period_s = float(min_period_s)
        self.collect_sifted = bool(collect_sifted)
        self.registry = registry or MetricRegistry()
        self.bus = bus
        self.bus_prefix = bus_prefix
        self.repo: Repository = repository or NullRepository()
        self.service_name = service_name
        self._post_process = post_process
        self._log_window_epochs = bool(log_window_epochs)
        self._log_control = bool(log_control)
        self._povm_service_target = povm_service_target
        self._povm_service_timeout_s = float(povm_service_timeout_s)
        self._povm_service_strict = bool(povm_service_strict)
        self._povm_backend = str(povm_backend)
        self._povm_local_cutoff_dim = int(povm_local_cutoff_dim)
        self._povm_client: Any = None

        self._control: queue.Queue = queue.Queue()
        self._history: deque[dict[str, Any]] = deque(maxlen=history_max)
        self._settings_registry: dict[int, dict[str, Any]] = {}
        self._settings_version = 0

        self._current_base: dict[str, float] = dict(initial_overrides or {})
        self._current_attack: dict[str, Any] = dict(initial_attack or {"enabled": False})
        self._current_selftest: dict[str, Any] = dict(initial_selftest or {"enabled": False})

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._dirty = False
        self._epoch = 0
        self.status = "initialized"
        self.error: str | None = None
        self.twin: Any = None
        self.started_at: float | None = None

    # ── public, thread-safe control surface ───────────────────────────────
    def submit_params(self, overrides: dict[str, float]) -> None:
        self._control.put(("params", dict(overrides or {})))

    def submit_attack(self, attack_settings: dict[str, Any]) -> None:
        payload = dict(attack_settings or {})
        with self._lock:
            self._current_attack = payload
        self._control.put(("attack", payload))

    def submit_selftest(self, selftest_settings: dict[str, Any]) -> None:
        payload = dict(selftest_settings or {})
        with self._lock:
            self._current_selftest = payload
        self._control.put(("selftest", payload))

    def get_current_attack(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._current_attack)

    def get_current_selftest(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._current_selftest)

    def stop(self) -> None:
        self._stop_event.set()
        if self.status == "running":
            self.status = "stopping"
        self._control.put(("stop", None))
        if self.bus is not None:
            self.bus.publish_sync(
                status_subject(self.bus_prefix, self.run_id),
                {"type": "status", "data": self.get_status()},
            )

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            last = self._history[-1] if self._history else None
            version = self._settings_version
            snap = self._settings_registry.get(version)
        return {
            "run_id": self.run_id,
            "status": self.status,
            "error": self.error,
            "protocol": self.protocol,
            "config_name": self.config_name,
            "shots_per_window": self.shots_per_window,
            "epoch": self._epoch,
            "settings_version": version,
            "current_settings": snap,
            "attack_enabled": bool(self._current_attack.get("enabled")),
            "last_point": last,
            "started_at": self.started_at,
            "history_size": len(self._history),
        }

    def get_history(self, since_epoch: int = -1) -> list[dict[str, Any]]:
        with self._lock:
            return [dp for dp in self._history if dp["epoch"] > since_epoch]

    def get_settings(self, version: int) -> dict[str, Any] | None:
        with self._lock:
            return self._settings_registry.get(int(version))

    def get_settings_for_epoch(self, epoch: int) -> dict[str, Any] | None:
        with self._lock:
            for dp in self._history:
                if dp["epoch"] == epoch:
                    return self._settings_registry.get(dp["settings_version"])
        return None

    # ── worker loop ────────────────────────────────────────────────────────
    def run(self) -> None:
        try:
            self.twin = build_twin_from_yaml_directory(
                self.config_dir / self.config_name, self.protocol
            )
            if self._povm_service_target:
                from certiqs_sim.external.povm_client import attach_povm_backend

                self._povm_client = attach_povm_backend(
                    self.twin,
                    backend=self._povm_backend,
                    target=self._povm_service_target,
                    timeout_s=self._povm_service_timeout_s,
                    strict=self._povm_service_strict,
                    cutoff_dim=self._povm_local_cutoff_dim,
                )
            apply_overrides(self.twin, self._current_base)
            apply_attack(self.twin, self._current_attack)
            apply_selftest(self.twin, self._current_selftest)
            self.repo.create_run(
                self.run_id, self.config_name, self.protocol, self.shots_per_window
            )
            self._register_settings()
            self.status = "running"
            self.started_at = time.time()
            _log.info(
                "twin_started",
                run_id=self.run_id,
                config=self.config_name,
                protocol=self.protocol,
                shots=self.shots_per_window,
            )
        except Exception as exc:
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"
            from certiqs_sim.telemetry.metrics import METRICS

            METRICS.engine_build_errors_total.labels(service=self.service_name).inc()
            _log.error("twin_build_failed", run_id=self.run_id, error=self.error)
            return

        while not self._stop_event.is_set():
            t0 = time.time()
            self._drain_control()
            if self._stop_event.is_set():
                break
            if self._dirty:
                self._register_settings()
                self._dirty = False

            results = self.twin.run_window(
                self.shots_per_window,
                collect_sifted=self.collect_sifted,
                should_stop=self._stop_event.is_set,
            )
            if self._stop_event.is_set():
                break
            if self._post_process is not None:
                try:
                    results = self._post_process(results)
                except Exception as exc:  # post-processing must never crash the engine
                    _log.warning("postprocess_failed", run_id=self.run_id, error=str(exc))

            duration = time.time() - t0
            datapoint = self._make_datapoint(results)

            with self._lock:
                self._history.append(datapoint)
                self._epoch += 1

            observe_window(
                results,
                service=self.service_name,
                run_id=self.run_id,
                protocol=self.protocol,
                duration_seconds=duration,
            )
            self._emit(datapoint, results)
            window_log = _log.info if self._log_window_epochs else _log.debug
            window_log(
                "window_done",
                run_id=self.run_id,
                epoch=datapoint["epoch"],
                qber=results.get("qber"),
                sifted=results.get("sifted_key_bits"),
                secure=results.get("pp_secure_key_bits"),
            )

            if self.min_period_s > 0 and duration < self.min_period_s:
                self._stop_event.wait(self.min_period_s - duration)

        self.status = "stopped"
        self.repo.finish_run(self.run_id, "stopped")
        if self.bus is not None:
            self.bus.publish_sync(
                status_subject(self.bus_prefix, self.run_id),
                {"type": "status", "data": self.get_status()},
            )
        _log.info("twin_stopped", run_id=self.run_id, epochs=self._epoch)

    # ── internals ──────────────────────────────────────────────────────────
    def _drain_control(self) -> None:
        while True:
            try:
                kind, payload = self._control.get_nowait()
            except queue.Empty:
                return
            if kind == "stop":
                self._stop_event.set()
            elif kind == "params":
                if self._log_control:
                    _log.info("control_params_applied", run_id=self.run_id, overrides=payload)
                self._current_base.update(payload)
                apply_overrides(self.twin, payload)
                self._dirty = True
            elif kind == "attack":
                if self._log_control:
                    _log.info(
                        "control_attack_applied",
                        run_id=self.run_id,
                        enabled=payload.get("enabled"),
                        eve_eff=payload.get("eve_eff"),
                    )
                self._current_attack = payload
                apply_attack(self.twin, payload)
                self._dirty = True
            elif kind == "selftest":
                if self._log_control:
                    _log.info(
                        "control_selftest_applied",
                        run_id=self.run_id,
                        enabled=payload.get("enabled"),
                        mode=payload.get("mode"),
                    )
                self._current_selftest = payload
                apply_selftest(self.twin, payload)
                self._dirty = True

    def _register_settings(self) -> None:
        self._settings_version += 1
        snapshot = {
            "version": self._settings_version,
            "run_id": self.run_id,
            "config_name": self.config_name,
            "manifest_sha256": getattr(self.twin, "manifest_sha256", None),
            "protocol": self.protocol,
            "shots_per_window": self.shots_per_window,
            "base": read_current_params(self.twin),
            "attack": read_attack_params(self.twin),
            "selftest": read_selftest_params(self.twin),
            "active_from_epoch": self._epoch,
            "created_wall_time": time.time(),
        }
        with self._lock:
            self._settings_registry[self._settings_version] = snapshot
        self.repo.save_settings_version(self.run_id, self._settings_version, self._epoch, snapshot)

    def _make_datapoint(self, results: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "epoch": self._epoch,
            "epoch_end": results.get("epoch_end"),
            "sim_time_ns": results.get("sim_time_ns"),
            "wall_time": time.time(),
            "settings_version": self._settings_version,
            "attack_enabled": bool(results.get("attack_enabled")),
            "shots": results.get("shots"),
            "metrics": self.registry.extract(results),
        }

    def _emit(self, datapoint: dict[str, Any], results: dict[str, Any]) -> None:
        self.repo.save_datapoint(self.run_id, datapoint)
        if self.bus is None:
            return
        self.bus.publish_sync(
            datapoint_subject(self.bus_prefix, self.run_id),
            {"type": "datapoint", "data": datapoint},
        )
        if self.collect_sifted and results.get("sifted_bits_alice") is not None:
            self.bus.publish_sync(
                sifted_subject(self.bus_prefix, self.run_id),
                {
                    "type": "sifted",
                    "run_id": self.run_id,
                    "epoch": datapoint["epoch"],
                    "settings_version": datapoint["settings_version"],
                    "sifted_bits_alice": results["sifted_bits_alice"],
                    "sifted_bits_bob": results["sifted_bits_bob"],
                    "qber": results.get("qber"),
                },
            )


__all__ = ["PostProcessHook", "TwinWorker"]
