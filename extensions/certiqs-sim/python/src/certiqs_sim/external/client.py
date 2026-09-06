"""gRPC client helpers — main application calls external worker containers."""

from __future__ import annotations

import socket
from typing import Any, Callable


_SERVICE_STATE_NAMES = {
    0: "unspecified",
    1: "starting",
    2: "serving",
    3: "draining",
    4: "stopped",
}

# grpc.health.v1.HealthCheckResponse.ServingStatus
_GRPC_HEALTH_SERVING = 1
_GRPC_HEALTH_NOT_SERVING = 2
_GRPC_HEALTH_SERVICE_UNKNOWN = 3


def _tcp_reachable(host: str, port: int, *, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _service_info_dict(info: Any) -> dict[str, Any]:
    state = int(getattr(info, "state", 0) or 0)
    return {
        "service_name": info.service_name or "",
        "service_version": info.service_version or "",
        "description": info.description or "",
        "documentation_url": info.documentation_url or "",
        "help": list(info.help),
        "endpoints": [
            {
                "grpc_service": ep.grpc_service,
                "methods": list(ep.methods),
            }
            for ep in info.endpoints
        ],
        "operations": [
            {"name": op.name, "description": op.description or ""} for op in info.operations
        ],
        "reflection_enabled": bool(info.reflection_enabled),
        "state": _SERVICE_STATE_NAMES.get(state, str(state)),
        "state_code": state,
        "uptime_seconds": float(info.uptime_seconds or 0.0),
        "checked_at": info.checked_at or "",
        "links": dict(info.links),
    }


def _probe_service_runtime(channel: Any, *, timeout: float) -> dict[str, Any] | None:
    """Probe theory ``ServiceRuntime`` via GetLiveness / GetReadiness.

    Optionally enriches with GetServiceInfo when available.
    """
    from certiqs_sim.external.theory import service_runtime_pb2, service_runtime_pb2_grpc

    stub = service_runtime_pb2_grpc.ServiceRuntimeStub(channel)
    live = stub.GetLiveness(
        service_runtime_pb2.GetLivenessRequest(), timeout=timeout
    )
    if not bool(getattr(live, "alive", False)):
        return {
            "status": "unhealthy",
            "detail": "ServiceRuntime GetLiveness alive=false"
            + (f" ({live.service_name})" if getattr(live, "service_name", "") else ""),
            "info": {
                "service_name": getattr(live, "service_name", "") or "",
                "version": "",
                "image": "",
                "metadata": {},
            },
            "metrics": {},
            "service_info": None,
            "contract": "qkd.security.theory.common.v1.ServiceRuntime/GetLiveness",
        }

    ready = stub.GetReadiness(
        service_runtime_pb2.GetReadinessRequest(), timeout=timeout
    )
    service_name = (
        getattr(ready, "service_name", "")
        or getattr(live, "service_name", "")
        or ""
    )
    blocking = list(getattr(ready, "blocking_reasons", []) or [])
    is_ready = bool(getattr(ready, "ready", False))

    result: dict[str, Any] = {
        "status": "healthy" if is_ready else "starting",
        "detail": (
            f"{service_name} ready".strip()
            if is_ready
            else (
                f"{service_name} alive but not ready"
                + (f": {', '.join(blocking)}" if blocking else "")
            ).strip()
        ),
        "info": {
            "service_name": service_name,
            "version": "",
            "image": "",
            "metadata": {"alive": "true", "ready": str(is_ready).lower()},
        },
        "metrics": {},
        "service_info": None,
        "contract": "qkd.security.theory.common.v1.ServiceRuntime",
    }

    # Optional self-description — must not fail the probe if unimplemented.
    try:
        info = stub.GetServiceInfo(
            service_runtime_pb2.GetServiceInfoRequest(), timeout=timeout
        )
        payload = _service_info_dict(info)
        result["service_info"] = payload
        result["info"] = {
            "service_name": payload["service_name"] or service_name,
            "version": payload["service_version"],
            "image": "",
            "metadata": {
                "reflection_enabled": str(payload["reflection_enabled"]).lower(),
                "documentation_url": payload["documentation_url"],
                "alive": "true",
                "ready": str(is_ready).lower(),
            },
        }
        result["metrics"] = {"uptime_seconds": payload["uptime_seconds"]}
        if is_ready and payload.get("state") == "serving":
            result["status"] = "healthy"
        if payload.get("description"):
            result["detail"] = payload["description"]
    except Exception:  # noqa: BLE001
        pass

    return result


def _probe_grpc_health(channel: Any, *, timeout: float) -> dict[str, Any] | None:
    """Standard ``grpc.health.v1.Health/Check`` (used by lab-bridge and many MS images)."""
    try:
        from grpc_health.v1 import health_pb2, health_pb2_grpc
    except ImportError as exc:
        raise RuntimeError(
            "grpcio-health-checking not installed "
            "(pip install 'certiqs-sim[external]')"
        ) from exc

    stub = health_pb2_grpc.HealthStub(channel)
    # Empty service name = overall server health.
    resp = stub.Check(health_pb2.HealthCheckRequest(service=""), timeout=timeout)
    status_code = int(getattr(resp, "status", 0) or 0)
    if status_code == _GRPC_HEALTH_SERVING:
        status = "healthy"
        detail = "grpc.health.v1 SERVING"
    elif status_code == _GRPC_HEALTH_NOT_SERVING:
        status = "unhealthy"
        detail = "grpc.health.v1 NOT_SERVING"
    elif status_code == _GRPC_HEALTH_SERVICE_UNKNOWN:
        status = "unknown"
        detail = "grpc.health.v1 SERVICE_UNKNOWN"
    else:
        status = "unknown"
        detail = f"grpc.health.v1 status={status_code}"
    return {
        "status": status,
        "detail": detail,
        "info": {
            "service_name": "",
            "version": "",
            "image": "",
            "metadata": {"grpc_health_status": str(status_code)},
        },
        "metrics": {},
        "service_info": None,
        "contract": "grpc.health.v1.Health",
    }


def _probe_worker_service(channel: Any, *, timeout: float) -> dict[str, Any] | None:
    """Legacy ``certiqs.external.v1.WorkerService`` health (optional last resort)."""
    from certiqs_sim.external.v1 import worker_pb2, worker_pb2_grpc

    stub = worker_pb2_grpc.WorkerServiceStub(channel)
    health = stub.Health(worker_pb2.HealthRequest(), timeout=timeout)
    result: dict[str, Any] = {
        "status": health.status or "unknown",
        "detail": health.detail or "",
        "metrics": dict(health.metrics),
        "info": None,
        "service_info": None,
        "contract": "certiqs.external.v1.WorkerService",
    }
    try:
        info = stub.GetInfo(worker_pb2.InfoRequest(), timeout=timeout)
        result["info"] = {
            "service_name": info.service_name,
            "version": info.version,
            "image": info.image,
            "metadata": dict(info.metadata),
        }
    except Exception:  # noqa: BLE001
        pass
    return result


def _probe_reflection(channel: Any, *, timeout: float) -> dict[str, Any] | None:
    """Last-resort probe: ask the server to list its services via reflection.

    Neither known contract covers every image. The theory workers implement
    ``qkd.security.theory.common.v1.ServiceRuntime`` while the microservice
    template images implement ``certiqs.ms.common.v1.ServiceRuntime`` — the same
    idea under a different package, so a stub for one returns UNIMPLEMENTED
    against the other and the container looks dead when it is healthy.

    Reflection is enabled by default in both entrypoint families and is a
    standard gRPC service, so listing works whatever the image speaks.
    """
    try:
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
    except ImportError:
        return None

    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    request = reflection_pb2.ServerReflectionRequest(list_services="")
    services: list[str] = []
    for response in stub.ServerReflectionInfo(iter([request]), timeout=timeout):
        for service in response.list_services_response.service:
            if service.name:
                services.append(service.name)
    if not services:
        return None

    domain = [
        s
        for s in services
        if not s.startswith(("grpc.reflection", "grpc.health"))
        and not s.endswith("ServiceRuntime")
    ]
    return {
        "status": "healthy",
        "contract": "grpc.reflection",
        "detail": "Reflection listing (no known ServiceRuntime contract): "
        + ", ".join(domain or services),
        "service_info": {
            "service_name": (domain or services)[0],
            "service_version": "",
            "description": "Identified by gRPC reflection",
            "documentation_url": "",
            "help": [],
            # Same shape as _service_info_dict so downstream consumers can treat
            # a reflected listing exactly like a ServiceRuntime response.
            "endpoints": [{"grpc_service": name, "methods": []} for name in services],
        },
    }


def probe_worker_grpc(
    *,
    host: str = "127.0.0.1",
    port: int,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Probe an external container's gRPC surface on the published host port.

    Order:
    1. ``ServiceRuntime`` GetLiveness / GetReadiness (+ optional GetServiceInfo)
    2. ``grpc.health.v1.Health/Check``
    3. Legacy ``WorkerService/Health``
    4. gRPC reflection listing (last resort)

    ``reachable`` means *a gRPC contract answered* — it is deliberately **not**
    set by the TCP check. Docker's port proxy accepts connections on a
    published port even when nothing inside the container is listening, so a
    container that starts but never binds would otherwise look healthy while
    every RPC fails. ``tcp_open`` carries the transport-level result separately.

    Does not choose ports — caller must pass the mapped host port from image
    discovery (``CERTIQS_SERVICE_PORT`` / EXPOSE).
    """
    addr = f"{host}:{port}"
    base: dict[str, Any] = {
        "addr": addr,
        "reachable": False,
        "tcp_open": False,
        "protocol": "grpc",
        "status": "unreachable",
        "detail": "",
        "info": None,
        "metrics": {},
        "service_info": None,
        "contract": None,
    }
    if not _tcp_reachable(host, port, timeout=min(timeout, 1.0)):
        base["detail"] = "gRPC port not accepting connections"
        return base

    base["tcp_open"] = True
    try:
        import grpc
    except ImportError:
        base["status"] = "port_open"
        base["detail"] = "TCP open (install certiqs-sim[external] for full gRPC probe)"
        return base

    probes: tuple[Callable[..., dict[str, Any] | None], ...] = (
        _probe_service_runtime,
        _probe_grpc_health,
        _probe_worker_service,
        _probe_reflection,
    )
    errors: list[str] = []
    channel = grpc.insecure_channel(addr)
    try:
        for probe_fn in probes:
            name = getattr(probe_fn, "__name__", probe_fn.__class__.__name__)
            try:
                hit = probe_fn(channel, timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
                continue
            if hit:
                base.update(hit)
                # A contract answered — only now is the service actually usable.
                base["reachable"] = True
                return base
    finally:
        channel.close()

    base["status"] = "port_open"
    if errors:
        base["detail"] = (
            "TCP port is open but no gRPC service answered — the container is "
            f"running without a bound server. Last error: {errors[-1]}"
        )
    else:
        base["detail"] = "TCP open; no known gRPC contract answered"
    return base


__all__ = ["probe_worker_grpc"]
