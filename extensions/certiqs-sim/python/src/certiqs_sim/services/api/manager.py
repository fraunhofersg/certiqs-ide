"""Run manager: owns the (single) in-process twin worker.

NetSquid is non-reentrant — exactly one twin runs per process — so the API
process hosts at most one active run at a time (starting a new one stops the
previous).  Horizontal scale is achieved by running multiple engine *processes*
(the ``certiqs-engine`` service), each with its own run, behind the bus.

The manager installs a post-processing hook so every window's sifted block is
finite-key processed inline, and wires datapoints to the event bus + repository.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from certiqs_sim.bus.base import EventBus
from certiqs_sim.config.settings import Settings
from certiqs_sim.persistence.repository import Repository
from certiqs_sim.postprocessing.pipeline import PostProcessor
from certiqs_sim.runtime.metrics_registry import MetricRegistry
from certiqs_sim.telemetry.logging import get_logger

_log = get_logger("certiqs.api")


class RunManager:
    def __init__(
        self,
        settings: Settings,
        bus: EventBus,
        repository: Repository,
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.repo = repository
        self.worker: Any = None

    @property
    def config_root(self) -> Path:
        return self.settings.config_root

    def _make_post_process_hook(self, config_dir: Path) -> Any:
        post = PostProcessor.from_config_dir(config_dir)
        epoch_counter = {"n": 0}

        def hook(results: dict[str, Any]) -> dict[str, Any]:
            a = results.get("sifted_bits_alice")
            b = results.get("sifted_bits_bob")
            if a is None or b is None:
                return results
            epoch_counter["n"] += 1
            pp = post.process(a, b, seed=epoch_counter["n"])
            results.update(pp.as_metrics())
            # Drop the raw bit arrays from the result kept in history (large).
            results.pop("sifted_bits_alice", None)
            results.pop("sifted_bits_bob", None)
            return results

        return hook

    def start_run(self, req: Any) -> dict[str, Any]:
        config_dir = self.config_root / req.config_name
        if not config_dir.is_dir():
            raise FileNotFoundError(f"Unknown config '{req.config_name}'")

        try:
            from certiqs_sim.core.topology.loader import is_hierarchical_config, load_topology
            from certiqs_sim.core.topology.validate import validate_topology

            if is_hierarchical_config(config_dir):
                errors = validate_topology(load_topology(config_dir))
                if errors:
                    raise ValueError("Topology validation failed: " + "; ".join(errors))
        except ImportError:
            pass

        self.stop_run(wait=True)

        try:
            from certiqs_sim.runtime.worker import TwinWorker
        except ImportError as exc:
            raise RuntimeError(
                "NetSquid is not installed. The control plane is up, but Start simulation needs the engine extra."
            ) from exc

        run_id = req.run_id or uuid.uuid4().hex[:12]
        collect = self.settings.collect_sifted
        self.worker = TwinWorker(
            config_dir=self.config_root,
            config_name=req.config_name,
            run_id=run_id,
            protocol=req.protocol,
            initial_overrides=req.overrides,
            initial_attack=req.attack,
            initial_selftest=req.selftest,
            shots_per_window=req.shots_per_window,
            min_period_s=self.settings.min_window_period_s,
            collect_sifted=collect,
            bus=self.bus,
            bus_prefix=self.settings.bus_subject_prefix,
            repository=self.repo,
            registry=MetricRegistry(),
            service_name=self.settings.service_name,
            post_process=self._make_post_process_hook(config_dir) if collect else None,
            log_window_epochs=self.settings.log_window_epochs,
            log_control=self.settings.log_control_api,
            povm_service_target=(
                self.settings.povm_service_target
                if self.settings.povm_service_enabled
                else None
            ),
            povm_service_timeout_s=self.settings.povm_service_timeout_s,
            povm_service_strict=self.settings.povm_service_strict,
            povm_backend=self.settings.povm_backend,
            povm_local_cutoff_dim=self.settings.povm_local_cutoff_dim,
        )
        self.worker.start()

        status = self.worker.get_status()
        _log.info("run_starting", run_id=run_id, status=status["status"])
        return status

    def stop_run(self, *, wait: bool = False, join_timeout: float = 30.0) -> dict[str, Any]:
        if self.worker is None:
            return {"status": "idle"}

        worker = self.worker
        worker.stop()
        status = worker.get_status()

        if wait:
            worker.join(timeout=join_timeout)
            if not worker.is_alive():
                if self.worker is worker:
                    self.worker = None
            return worker.get_status()

        if worker.is_alive():
            def _reap() -> None:
                worker.join(timeout=join_timeout)
                if self.worker is worker:
                    self.worker = None

            threading.Thread(target=_reap, daemon=True, name=f"reap-{worker.run_id}").start()
            return {**status, "status": "stopping"}

        if self.worker is worker:
            self.worker = None
        return status

    def status(self) -> dict[str, Any]:
        if self.worker is None:
            return {"status": "idle"}
        return self.worker.get_status()

    def require_worker(self) -> TwinWorker:
        if self.worker is None or not self.worker.is_alive():
            raise RuntimeError("Twin is not running")
        return self.worker

    def registry(self) -> MetricRegistry:
        return self.worker.registry if self.worker is not None else MetricRegistry()

    def active_config_dir(self) -> Path | None:
        """Config directory of the running twin, else the resolved default set."""
        from certiqs_sim.config.paths import resolve_config_name

        if self.worker is not None and getattr(self.worker, "config_name", None):
            path = self.config_root / self.worker.config_name
            if path.is_dir():
                return path
        try:
            name = resolve_config_name(
                self.config_root, None, preferred=self.settings.default_config
            )
        except FileNotFoundError:
            return None
        path = self.config_root / name
        return path if path.is_dir() else None

    def metrics_catalog(self) -> list[dict[str, Any]]:
        from certiqs_sim.runtime.technical_ranges import load_technical_ranges

        ranges = load_technical_ranges(self.active_config_dir())
        return self.registry().catalog(technical_ranges=ranges)


__all__ = ["RunManager"]
