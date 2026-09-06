"""Platform supervisor: local subprocesses + Docker Compose infrastructure."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from certiqs_sim.config.settings import Settings, get_settings
from certiqs_sim.ops.health import probe_service
from certiqs_sim.ops.registry import ServiceSpec, build_service_catalog, service_by_id
from certiqs_sim.telemetry.logging import get_logger

_log = get_logger("certiqs.ops")

OpsMode = Literal["local", "docker"]
ServiceState = Literal["running", "stopped", "starting", "stopping", "unreachable", "self"]


@dataclass
class ManagedProcess:
    spec: ServiceSpec
    popen: subprocess.Popen[str] | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    started_at: float | None = None


class PlatformSupervisor:
    """Start/stop certiqs services and probe PaaS infrastructure."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._repo_root = Path(settings.config_root).resolve().parents[0]
        self._compose_file = settings.ops_compose_file
        self._lock = threading.RLock()
        self._processes: dict[str, ManagedProcess] = {}
        self._log_threads: dict[str, threading.Thread] = {}

    @property
    def mode(self) -> OpsMode:
        if self.settings.ops_mode != "auto":
            return self.settings.ops_mode  # type: ignore[return-value]
        if Path("/.dockerenv").exists():
            return "docker"
        return "local"

    def platform_info(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "repo_root": str(self._repo_root),
            "compose_file": str(self._compose_file),
            "compose_available": self._compose_file.is_file() and shutil.which("docker") is not None,
            "venv_python": str(self._venv_python()) if self._venv_python() else None,
            "bus_backend": self.settings.bus_backend,
            "base_port": self.settings.port,
        }

    def list_services(self) -> list[dict[str, Any]]:
        catalog = build_service_catalog(self.settings.port)
        compose_states = self._compose_ps() if self._compose_available() else {}
        out: list[dict[str, Any]] = []
        for spec in catalog:
            out.append(self._service_status(spec, compose_states.get(spec.compose_name or "")))
        return out

    def start(self, service_id: str) -> dict[str, Any]:
        spec = service_by_id(service_id, self.settings.port)
        if spec.self_managed:
            raise ValueError(f"Service '{service_id}' is the current API process")
        if spec.kind == "infra":
            return self._compose_action(spec, "start")
        return self._start_local(spec)

    def stop(self, service_id: str) -> dict[str, Any]:
        spec = service_by_id(service_id, self.settings.port)
        if spec.self_managed:
            raise ValueError(f"Service '{service_id}' is the current API process")
        if spec.kind == "infra":
            return self._compose_action(spec, "stop")
        return self._stop_local(spec)

    def start_all(self, *, apps_only: bool = False) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for spec in build_service_catalog(self.settings.port):
            if spec.self_managed:
                continue
            if apps_only and spec.kind != "app":
                continue
            try:
                results.append(self.start(spec.id))
            except Exception as exc:
                results.append({"id": spec.id, "ok": False, "error": str(exc)})
        return results

    def stop_all(self, *, apps_only: bool = False) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for spec in reversed(build_service_catalog(self.settings.port)):
            if spec.self_managed:
                continue
            if apps_only and spec.kind != "app":
                continue
            try:
                results.append(self.stop(spec.id))
            except Exception as exc:
                results.append({"id": spec.id, "ok": False, "error": str(exc)})
        return results

    def get_logs(self, service_id: str, *, tail: int = 200) -> dict[str, Any]:
        spec = service_by_id(service_id, self.settings.port)
        if spec.kind == "infra" and self._compose_available():
            return {
                "id": service_id,
                "lines": self._compose_logs(spec, tail=tail),
                "source": "docker",
            }
        with self._lock:
            proc = self._processes.get(service_id)
            lines = list(proc.logs)[-tail:] if proc else []
        return {"id": service_id, "lines": lines, "source": "process"}

    # ── internals ────────────────────────────────────────────────────────
    def _service_status(self, spec: ServiceSpec, compose_row: dict[str, Any]) -> dict[str, Any]:
        probe = probe_service(spec, host=self.settings.ops_probe_host)
        state: ServiceState
        managed_by = "none"
        pid: int | None = None
        uptime_s: float | None = None

        if spec.self_managed:
            state = "self"
            managed_by = "self"
        elif spec.kind == "infra" and compose_row:
            cstate = str(compose_row.get("State", "")).lower()
            managed_by = "docker"
            if "running" in cstate:
                state = "running"
            elif cstate:
                state = "stopped"
            else:
                state = "unreachable" if not probe["reachable"] else "stopped"
        elif spec.kind == "app":
            local = self._local_running(spec)
            managed_by = "process" if local else ("probe" if probe["reachable"] else "none")
            if local:
                state = "running"
                with self._lock:
                    mp = self._processes.get(spec.id)
                    if mp and mp.popen:
                        pid = mp.popen.pid
                        uptime_s = time.time() - mp.started_at if mp.started_at else None
            elif probe["reachable"]:
                state = "running"
            else:
                state = "stopped"
        else:
            state = "running" if probe["reachable"] else "stopped"
            managed_by = "docker" if compose_row else "probe"

        return {
            "id": spec.id,
            "name": spec.name,
            "kind": spec.kind,
            "port": spec.port,
            "description": spec.description,
            "state": state,
            "managed_by": managed_by,
            "self_managed": spec.self_managed,
            "pid": pid,
            "uptime_s": round(uptime_s, 1) if uptime_s is not None else None,
            "probe": probe,
            "compose": compose_row or None,
            "links": {
                "health": f"http://127.0.0.1:{spec.port}{spec.health_path}"
                if spec.health_kind == "http"
                else None,
                "metrics": f"http://127.0.0.1:{spec.port}/metrics"
                if spec.kind == "app"
                else None,
            },
        }

    def _venv_python(self) -> Path | None:
        candidate = self._repo_root / ".venv" / "bin" / "python"
        return candidate if candidate.is_file() else None

    def _compose_available(self) -> bool:
        return self._compose_file.is_file() and shutil.which("docker") is not None

    def _compose_cmd(self, *args: str) -> list[str]:
        return ["docker", "compose", "-f", str(self._compose_file), *args]

    def _compose_ps(self) -> dict[str, dict[str, Any]]:
        if not self._compose_available():
            return {}
        try:
            proc = subprocess.run(
                self._compose_cmd("ps", "--format", "json"),
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self._repo_root,
            )
            if proc.returncode != 0:
                return {}
            rows: dict[str, dict[str, Any]] = {}
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    name = row.get("Service") or row.get("Name", "")
                    rows[str(name)] = row
                except json.JSONDecodeError:
                    continue
            return rows
        except (subprocess.TimeoutExpired, OSError) as exc:
            _log.warning("compose_ps_failed", error=str(exc))
            return {}

    def _compose_action(self, spec: ServiceSpec, action: Literal["start", "stop"]) -> dict[str, Any]:
        if not self._compose_available():
            raise RuntimeError("Docker Compose is not available")
        name = spec.compose_name or spec.id
        args = ("up", "-d", name) if action == "start" else ("stop", name)
        proc = subprocess.run(
            self._compose_cmd(*args),
            capture_output=True,
            text=True,
            timeout=120,
            cwd=self._repo_root,
        )
        ok = proc.returncode == 0
        return {
            "id": spec.id,
            "ok": ok,
            "action": action,
            "backend": "docker",
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
        }

    def _compose_logs(self, spec: ServiceSpec, *, tail: int) -> list[str]:
        name = spec.compose_name or spec.id
        proc = subprocess.run(
            self._compose_cmd("logs", "--tail", str(tail), name),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=self._repo_root,
        )
        if proc.returncode != 0:
            return [proc.stderr or "Failed to fetch docker logs"]
        return proc.stdout.splitlines()

    def _local_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("CERTIQS_HOST", "127.0.0.1")
        env.setdefault("CERTIQS_PORT", str(self.settings.port))
        env.setdefault("CERTIQS_BUS_BACKEND", self.settings.bus_backend)
        if self.settings.nats_url:
            env.setdefault("CERTIQS_NATS_URL", self.settings.nats_url)
        if self.settings.database_url:
            env.setdefault("CERTIQS_DATABASE_URL", self.settings.database_url)
        return env

    def _start_local(self, spec: ServiceSpec) -> dict[str, Any]:
        if not spec.command:
            raise ValueError(f"No local command for {spec.id}")
        if self._local_running(spec):
            return {"id": spec.id, "ok": True, "action": "start", "backend": "process", "note": "already_running"}

        py = self._venv_python()
        if py is None:
            raise RuntimeError("Project .venv not found — run ./scripts/setup.sh first")

        bin_dir = py.parent
        argv: list[str]
        if spec.command[0].startswith("certiqs-"):
            exe = bin_dir / spec.command[0]
            if not exe.is_file():
                raise RuntimeError(f"CLI not found: {exe}")
            argv = [str(exe), *spec.command[1:]]
        else:
            argv = [str(py), *spec.command]

        proc = subprocess.Popen(
            argv,
            cwd=self._repo_root,
            env=self._local_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        mp = ManagedProcess(spec=spec, popen=proc, started_at=time.time())
        with self._lock:
            self._processes[spec.id] = mp
            self._start_log_reader(spec.id, proc, mp.logs)
        _log.info("service_started", service=spec.id, pid=proc.pid)
        return {"id": spec.id, "ok": True, "action": "start", "backend": "process", "pid": proc.pid}

    def _stop_local(self, spec: ServiceSpec) -> dict[str, Any]:
        with self._lock:
            mp = self._processes.get(spec.id)
            if mp is None or mp.popen is None:
                return {"id": spec.id, "ok": True, "action": "stop", "backend": "process", "note": "not_managed"}
            proc = mp.popen
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        with self._lock:
            self._processes.pop(spec.id, None)
        _log.info("service_stopped", service=spec.id)
        return {"id": spec.id, "ok": True, "action": "stop", "backend": "process"}

    def _local_running(self, spec: ServiceSpec) -> bool:
        with self._lock:
            mp = self._processes.get(spec.id)
            if mp and mp.popen and mp.popen.poll() is None:
                return True
            if mp and mp.popen and mp.popen.poll() is not None:
                self._processes.pop(spec.id, None)
        return False

    def _start_log_reader(
        self,
        service_id: str,
        proc: subprocess.Popen[str],
        buffer: deque[str],
    ) -> None:
        if proc.stdout is None:
            return

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                buffer.append(line.rstrip("\n"))

        thread = threading.Thread(target=_reader, daemon=True, name=f"log-{service_id}")
        thread.start()
        self._log_threads[service_id] = thread


@lru_cache(maxsize=1)
def get_supervisor() -> PlatformSupervisor:
    return PlatformSupervisor(get_settings())


__all__ = ["PlatformSupervisor", "get_supervisor", "OpsMode", "ServiceState"]
