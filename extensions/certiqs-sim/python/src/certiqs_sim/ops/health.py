"""Lightweight health probes for registered services."""

from __future__ import annotations

import socket
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from certiqs_sim.ops.registry import HealthKind, ServiceSpec


def probe_service(spec: ServiceSpec, host: str = "127.0.0.1", timeout: float = 1.5) -> dict[str, Any]:
    if spec.health_kind == "none":
        return {"reachable": None, "ready": None}

    if spec.health_kind == "tcp":
        ok = _tcp_open(host, spec.port, timeout)
        return {"reachable": ok, "ready": ok, "health": "tcp_ok" if ok else "tcp_closed"}

    url = f"http://{host}:{spec.port}{spec.health_path}"
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            ready = resp.status == 200
            return {
                "reachable": True,
                "ready": ready,
                "health": "ok" if ready else f"http_{resp.status}",
                "detail": body[:500],
            }
    except URLError as exc:
        return {"reachable": False, "ready": False, "health": "unreachable", "detail": str(exc.reason)}
    except OSError as exc:
        return {"reachable": False, "ready": False, "health": "error", "detail": str(exc)}


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


__all__ = ["probe_service"]
