"""Per-image gRPC port / env profiles for extension workers.

Container bind port is discovered from image metadata at deploy time
(OCI label → ``CERTIQS_SERVICE_PORT`` → single ``EXPOSE``). There is no
silent default to 50051 for unknown services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Forward-compatible OCI image label (optional).
OCI_GRPC_PORT_LABEL = "certiqs.ms.grpc.port"


@dataclass(frozen=True)
class ServiceProfile:
    """Container bind port + optional theory-service env prefix."""

    key: str
    container_port: int
    env_prefix: str | None = None
    service_name: str | None = None
    """How the container port was chosen (label|env|expose|override|legacy)."""
    port_source: str = "unknown"


class PortDiscoveryError(ValueError):
    """Image metadata does not yield a unique gRPC container port."""


# Legacy leaf names → env prefix only (ports come from image metadata).
_KNOWN_PREFIX: dict[str, str] = {
    "rx-povm": "RX_POVM",
    "rx-characterization": "RX_CHARACTERIZATION",
}


def image_leaf(image_name: str) -> str:
    """Last path segment of a GHCR package name (before any ``:tag`` / ``@digest``)."""
    name = (image_name or "").strip().lower()
    if "@" in name:
        name = name.split("@", 1)[0]
    # Nested GHCR: owner/repo/leaf — keep only the final segment for matching.
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    if ":" in name:
        name = name.rsplit(":", 1)[0]
    return name


def parse_port_overrides(raw: str | None) -> dict[str, int]:
    """Parse ``rx-povm:50051,lab-bridge:50060`` style overrides."""
    out: dict[str, int] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, port_s = part.rsplit(":", 1)
        key = key.strip().lower()
        try:
            port = int(port_s.strip())
        except ValueError:
            continue
        if key and 1 <= port <= 65535:
            out[key] = port
    return out


def parse_image_env(env_list: Any) -> dict[str, str]:
    """Parse Docker ``Config.Env`` (``KEY=value`` strings) into a dict."""
    out: dict[str, str] = {}
    if not isinstance(env_list, list):
        return out
    for item in env_list:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, _, value = item.partition("=")
        key = key.strip()
        if key:
            out[key] = value
    return out


def parse_exposed_tcp_ports(exposed: Any) -> list[int]:
    """Return sorted unique TCP ports from Docker ``Config.ExposedPorts``."""
    if not isinstance(exposed, dict) or not exposed:
        return []
    ports: set[int] = set()
    for key in exposed:
        text = str(key).strip().lower()
        # Forms: "50060/tcp", "50060/udp", "50060"
        port_s = text.split("/", 1)[0]
        try:
            port = int(port_s)
        except ValueError:
            continue
        if text.endswith("/udp"):
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return sorted(ports)


def _parse_port_value(raw: str | int | None, *, field: str) -> int:
    if raw is None:
        raise PortDiscoveryError(f"{field} is empty")
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise PortDiscoveryError(f"{field} is not a valid port: {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise PortDiscoveryError(f"{field} out of range: {port}")
    return port


def _known_leaf_key(image_name: str) -> str | None:
    """Return matched legacy leaf key (e.g. ``rx-povm``) when name ends with it."""
    leaf = image_leaf(image_name)
    if leaf in _KNOWN_PREFIX:
        return leaf
    for key in _KNOWN_PREFIX:
        if leaf.endswith(f"-{key}") or leaf == key:
            return key
    return None


def legacy_env_prefix_for(image_name: str) -> str | None:
    """Optional THEORY_SERVICE_ENV_PREFIX for known legacy leaves (not used for port)."""
    key = _known_leaf_key(image_name)
    return _KNOWN_PREFIX.get(key) if key else None


def _profile_key(image_name: str) -> str:
    return _known_leaf_key(image_name) or image_leaf(image_name) or "worker"


def _override_port_for(
    image_name: str,
    port_overrides: Mapping[str, int] | str | None,
) -> int | None:
    leaf = image_leaf(image_name)
    overrides = (
        parse_port_overrides(port_overrides)
        if isinstance(port_overrides, str)
        else dict(port_overrides or {})
    )
    if leaf in overrides:
        return overrides[leaf]
    for key, port in overrides.items():
        if leaf.endswith(f"-{key}") or leaf == key:
            return port
    return None


def resolve_grpc_from_image_config(
    config: Mapping[str, Any] | None,
    *,
    image_name: str,
    port_overrides: Mapping[str, int] | str | None = None,
) -> ServiceProfile:
    """Resolve container gRPC port from image Config (fail closed).

    Priority:
    0. Explicit operator override (``CERTIQS_CONTAINERS_SERVICE_PORTS``)
    1. OCI label ``certiqs.ms.grpc.port``
    2. Image env ``CERTIQS_SERVICE_PORT``
    3. Exactly one TCP entry in ``Config.ExposedPorts``
    4. ``PortDiscoveryError`` — never silently default to 50051
    """
    leaf = image_leaf(image_name) or "worker"
    key = _profile_key(image_name)
    cfg = dict(config or {})
    env = parse_image_env(cfg.get("Env"))
    labels = cfg.get("Labels") if isinstance(cfg.get("Labels"), dict) else {}
    labels = {str(k): str(v) for k, v in labels.items() if v is not None}

    service_name = (env.get("CERTIQS_SERVICE") or "").strip() or None
    env_prefix = (env.get("CERTIQS_SERVICE_ENV_PREFIX") or "").strip() or None
    if not env_prefix:
        env_prefix = legacy_env_prefix_for(image_name)

    override = _override_port_for(image_name, port_overrides)
    if override is not None:
        return ServiceProfile(
            key=key,
            container_port=override,
            env_prefix=env_prefix,
            service_name=service_name,
            port_source="override",
        )

    label_raw = labels.get(OCI_GRPC_PORT_LABEL)
    if label_raw is not None and str(label_raw).strip():
        port = _parse_port_value(label_raw, field=OCI_GRPC_PORT_LABEL)
        return ServiceProfile(
            key=key,
            container_port=port,
            env_prefix=env_prefix,
            service_name=service_name,
            port_source="label",
        )

    env_port = env.get("CERTIQS_SERVICE_PORT")
    if env_port is not None and str(env_port).strip():
        port = _parse_port_value(env_port, field="CERTIQS_SERVICE_PORT")
        return ServiceProfile(
            key=key,
            container_port=port,
            env_prefix=env_prefix,
            service_name=service_name,
            port_source="env",
        )

    exposed = parse_exposed_tcp_ports(cfg.get("ExposedPorts"))
    if len(exposed) == 1:
        return ServiceProfile(
            key=key,
            container_port=exposed[0],
            env_prefix=env_prefix,
            service_name=service_name,
            port_source="expose",
        )
    if len(exposed) > 1:
        raise PortDiscoveryError(
            f"image '{image_name}' exposes multiple TCP ports {exposed}; "
            "set CERTIQS_SERVICE_PORT (or label certiqs.ms.grpc.port), or "
            f"CERTIQS_CONTAINERS_SERVICE_PORTS={leaf}:<port>"
        )

    raise PortDiscoveryError(
        f"image '{image_name}' has no gRPC port metadata "
        f"(missing label '{OCI_GRPC_PORT_LABEL}', env CERTIQS_SERVICE_PORT, "
        "and a single EXPOSE). Rebuild the MS image with CERTIQS_SERVICE_PORT, "
        f"or set CERTIQS_CONTAINERS_SERVICE_PORTS={leaf}:<port>"
    )


def resolve_service_profile(
    image_name: str,
    *,
    default_port: int | None = None,
    port_overrides: Mapping[str, int] | str | None = None,
    image_config: Mapping[str, Any] | None = None,
) -> ServiceProfile:
    """Resolve profile from image Config when available; else override-only.

    ``default_port`` is deprecated and ignored (kept for call-site compatibility).
    Without ``image_config``, only an explicit port override succeeds for the port;
    otherwise raises :class:`PortDiscoveryError`.
    """
    del default_port  # never use a silent universal default
    if image_config is not None:
        return resolve_grpc_from_image_config(
            image_config,
            image_name=image_name,
            port_overrides=port_overrides,
        )

    override = _override_port_for(image_name, port_overrides)
    leaf = image_leaf(image_name) or "worker"
    key = _profile_key(image_name)
    if override is not None:
        return ServiceProfile(
            key=key,
            container_port=override,
            env_prefix=legacy_env_prefix_for(image_name),
            port_source="override",
        )
    raise PortDiscoveryError(
        f"cannot resolve gRPC port for '{image_name}' without image inspect "
        f"(set CERTIQS_CONTAINERS_SERVICE_PORTS={leaf}:<port> or pull/inspect the image)"
    )


def identity_profile(
    image_name: str,
    *,
    port_overrides: Mapping[str, int] | str | None = None,
) -> ServiceProfile:
    """Best-effort profile for UI/terminal identity (never raises).

    Port is filled only when an operator override exists; otherwise ``0``
    (callers must dial the published host port from container status).
    """
    override = _override_port_for(image_name, port_overrides)
    return ServiceProfile(
        key=_profile_key(image_name),
        container_port=override if override is not None else 0,
        env_prefix=legacy_env_prefix_for(image_name),
        port_source="override" if override is not None else "identity",
    )


def deploy_env_for_profile(profile: ServiceProfile) -> dict[str, str]:
    """Env vars so worker images bind the published container port."""
    port = str(profile.container_port)
    env = {
        "THEORY_SERVICE_HOST": "0.0.0.0",
        "THEORY_SERVICE_PORT": port,
        "CERTIQS_GRPC_PORT": port,
        "GRPC_PORT": port,
        "CERTIQS_SERVICE_PORT": port,
    }
    if profile.service_name:
        env["CERTIQS_SERVICE"] = profile.service_name
    if profile.env_prefix:
        prefix = profile.env_prefix
        env["THEORY_SERVICE_ENV_PREFIX"] = prefix
        env["CERTIQS_SERVICE_ENV_PREFIX"] = prefix
        env[f"{prefix}_HOST"] = "0.0.0.0"
        env[f"{prefix}_PORT"] = port
        env[f"{prefix}_ENABLE_REFLECTION"] = "true"
    return env


__all__ = [
    "OCI_GRPC_PORT_LABEL",
    "PortDiscoveryError",
    "ServiceProfile",
    "deploy_env_for_profile",
    "identity_profile",
    "image_leaf",
    "legacy_env_prefix_for",
    "parse_exposed_tcp_ports",
    "parse_image_env",
    "parse_port_overrides",
    "resolve_grpc_from_image_config",
    "resolve_service_profile",
]
