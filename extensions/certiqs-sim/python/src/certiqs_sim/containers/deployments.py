"""In-memory deployment job tracking for external worker containers."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

Phase = Literal[
    "queued",
    "pulling",
    "creating",
    "starting",
    "probing",
    "ready",
    "failed",
    "cancelled",
]

_PHASE_PROGRESS: dict[str, float] = {
    "queued": 0.05,
    "pulling": 0.15,
    "creating": 0.75,
    "starting": 0.85,
    "probing": 0.92,
    "ready": 1.0,
    "failed": 1.0,
    "cancelled": 1.0,
}


@dataclass
class DeploymentJob:
    job_id: str
    service_id: str
    image: str
    pull: bool = True
    tag: str | None = None
    phase: Phase = "queued"
    progress: float = 0.05
    ok: bool | None = None
    error: str | None = None
    container_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=500))

    def append(self, line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        self.lines.append(text)
        self.updated_at = time.time()

    def set_phase(self, phase: Phase, *, progress: float | None = None) -> None:
        self.phase = phase
        self.progress = progress if progress is not None else _PHASE_PROGRESS.get(phase, self.progress)
        self.updated_at = time.time()
        if phase in {"ready", "failed", "cancelled"}:
            self.finished_at = time.time()
            self.ok = phase == "ready"

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "service_id": self.service_id,
            "image": self.image,
            "pull": self.pull,
            "tag": self.tag,
            "phase": self.phase,
            "progress": round(self.progress, 3),
            "ok": self.ok,
            "error": self.error,
            "container_id": self.container_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "active": self.phase not in {"ready", "failed", "cancelled"},
            "lines": list(self.lines),
        }


class DeploymentStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, DeploymentJob] = {}
        self._latest_by_service: dict[str, str] = {}

    def create(
        self,
        *,
        service_id: str,
        image: str,
        pull: bool = True,
        tag: str | None = None,
    ) -> DeploymentJob:
        job = DeploymentJob(
            job_id=str(uuid.uuid4()),
            service_id=service_id,
            image=image,
            pull=pull,
            tag=tag,
        )
        job.append(f"Queued deployment for {service_id}")
        job.append(f"Image: {image}")
        with self._lock:
            self._jobs[job.job_id] = job
            self._latest_by_service[service_id] = job.job_id
        return job

    def get(self, job_id: str) -> DeploymentJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest_for(self, service_id: str) -> DeploymentJob | None:
        with self._lock:
            job_id = self._latest_by_service.get(service_id)
            return self._jobs.get(job_id) if job_id else None

    def active_for(self, service_id: str) -> DeploymentJob | None:
        job = self.latest_for(service_id)
        if job and job.phase not in {"ready", "failed", "cancelled"}:
            return job
        return None


_STORE: DeploymentStore | None = None
_STORE_LOCK = threading.Lock()


def get_deployment_store() -> DeploymentStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = DeploymentStore()
        return _STORE


__all__ = ["DeploymentJob", "DeploymentStore", "Phase", "get_deployment_store"]
