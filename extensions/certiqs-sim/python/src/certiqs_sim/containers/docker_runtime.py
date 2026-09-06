"""Docker CLI helpers for managed external worker containers."""

from __future__ import annotations

import contextlib
import json
import platform as py_platform
import shutil
import subprocess
import time
from typing import Any

import structlog

_log = structlog.get_logger("certiqs.containers.docker")

MANAGED_LABEL = "com.certiqs.managed"
SERVICE_LABEL = "com.certiqs.service"
GRPC_PORT_LABEL = "com.certiqs.grpc_port"
GRPC_CONTAINER_PORT_LABEL = "com.certiqs.grpc_container_port"
IMAGE_REF_LABEL = "com.certiqs.image_ref"
PLATFORM_LABEL = "com.certiqs.platform"
PROFILE_LABEL = "com.certiqs.service_profile"

_MANIFEST_MISS_MARKERS = (
    "no matching manifest",
    "no match for platform in manifest",
)


def docker_available() -> bool:
    return shutil.which("docker") is not None


def host_is_arm64() -> bool:
    machine = (py_platform.machine() or "").lower()
    return machine in {"arm64", "aarch64"}


def resolve_platform(configured: str | None) -> str | None:
    """Resolve Docker ``--platform`` value.

    - ``auto``: ``linux/amd64`` on Apple Silicon (common for GHCR), else native
    - ``native`` / empty: no ``--platform`` flag
    - otherwise: the configured value (e.g. ``linux/amd64``)
    """
    value = (configured or "auto").strip().lower()
    if value in {"", "native", "host"}:
        return None
    if value == "auto":
        return "linux/amd64" if host_is_arm64() else None
    return (configured or "").strip() or None


def is_platform_manifest_error(text: str) -> bool:
    lower = text.lower()
    return any(m in lower for m in _MANIFEST_MISS_MARKERS)


def _run(args: list[str], *, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def image_present(image: str) -> bool:
    if not docker_available():
        return False
    proc = _run(["image", "inspect", image], timeout=15)
    return proc.returncode == 0


def inspect_image(image: str) -> dict[str, Any] | None:
    """Return the first ``docker image inspect`` object, or None."""
    if not docker_available():
        return None
    proc = _run(["image", "inspect", image], timeout=15)
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    return row if isinstance(row, dict) else None


def inspect_image_config(image: str) -> dict[str, Any] | None:
    """Return image ``Config`` (Env / Labels / ExposedPorts) for port discovery."""
    raw = inspect_image(image)
    if not raw:
        return None
    config = raw.get("Config")
    return config if isinstance(config, dict) else None


def inspect_by_name(name: str) -> dict[str, Any] | None:
    if not docker_available():
        return None
    proc = _run(["inspect", name], timeout=15)
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    return row if isinstance(row, dict) else None


def find_managed(service_id: str) -> dict[str, Any] | None:
    if not docker_available():
        return None
    proc = _run(
        [
            "ps",
            "-a",
            "--filter",
            f"label={SERVICE_LABEL}={service_id}",
            "--filter",
            f"label={MANAGED_LABEL}=true",
            "--format",
            "{{.ID}}",
        ],
        timeout=15,
    )
    if proc.returncode != 0:
        return None
    ids = (proc.stdout or "").strip().splitlines()
    if not ids:
        return None
    return inspect_by_name(ids[0].strip())


def pull_image(image: str, *, platform: str | None = None) -> tuple[bool, str]:
    args = ["pull"]
    if platform:
        args.extend(["--platform", platform])
    args.append(image)
    proc = _run(args, timeout=300)
    note = (proc.stdout or proc.stderr or "").strip()[-2000:]
    return proc.returncode == 0, note


def pull_image_streaming(
    image: str,
    *,
    on_line: Any | None = None,
    timeout: float = 600,
    platform: str | None = None,
) -> tuple[bool, str]:
    """Stream ``docker pull`` output line-by-line for deployment progress UI."""
    if not docker_available():
        return False, "Docker CLI is not available"

    def _pull_once(plat: str | None) -> tuple[bool, str]:
        cmd = ["docker", "pull"]
        if plat:
            cmd.extend(["--platform", plat])
        cmd.append(image)
        if on_line and plat:
            on_line(f"Using platform {plat}")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return False, str(exc)

        lines: list[str] = []
        deadline = time.time() + timeout
        assert proc.stdout is not None
        try:
            while True:
                if time.time() > deadline:
                    proc.kill()
                    msg = "docker pull timed out"
                    if on_line:
                        on_line(msg)
                    return False, msg
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
                    continue
                text = line.rstrip()
                lines.append(text)
                if on_line:
                    on_line(text)
            code = proc.wait(timeout=5)
        except Exception as exc:  # noqa: BLE001
            with contextlib.suppress(Exception):
                proc.kill()
            return False, str(exc)

        note = "\n".join(lines)[-2000:]
        return code == 0, note

    ok, note = _pull_once(platform)
    # If pull still fails due to missing arm64 manifest, retry amd64 under emulation.
    if (
        not ok
        and is_platform_manifest_error(note)
        and platform not in {"linux/amd64", "amd64"}
    ):
        if on_line:
            on_line(
                "No arm64 manifest in registry — retrying pull with --platform linux/amd64"
            )
        ok, note = _pull_once("linux/amd64")
    return ok, note


def remove_container(name_or_id: str, *, force: bool = True) -> tuple[bool, str]:
    args = ["rm"]
    if force:
        args.append("-f")
    args.append(name_or_id)
    proc = _run(args, timeout=60)
    note = (proc.stdout or proc.stderr or "").strip()[-1000:]
    return proc.returncode == 0, note


def start_container(name_or_id: str) -> tuple[bool, str]:
    proc = _run(["start", name_or_id], timeout=60)
    note = (proc.stdout or proc.stderr or "").strip()[-1000:]
    return proc.returncode == 0, note


def stop_container(name_or_id: str, *, timeout_s: int = 20) -> tuple[bool, str]:
    proc = _run(["stop", "-t", str(timeout_s), name_or_id], timeout=timeout_s + 30)
    note = (proc.stdout or proc.stderr or "").strip()[-1000:]
    return proc.returncode == 0, note


def container_logs(name_or_id: str, *, tail: int = 200) -> list[str]:
    proc = _run(["logs", "--tail", str(tail), name_or_id], timeout=30)
    if proc.returncode != 0:
        err = (proc.stderr or "Failed to fetch container logs").strip()
        return [err]
    text = "\n".join(x for x in (proc.stdout, proc.stderr) if x)
    return text.splitlines()


def run_container(
    *,
    name: str,
    image: str,
    service_id: str,
    host_grpc_port: int,
    container_grpc_port: int,
    env: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
    platform: str | None = None,
    profile_key: str | None = None,
) -> tuple[bool, str, str | None]:
    existing = inspect_by_name(name)
    if existing:
        remove_container(name, force=True)

    merged_env = {
        "CERTIQS_GRPC_PORT": str(container_grpc_port),
        "GRPC_PORT": str(container_grpc_port),
        **(env or {}),
    }

    args: list[str] = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        f"{MANAGED_LABEL}=true",
        "--label",
        f"{SERVICE_LABEL}={service_id}",
        "--label",
        f"{GRPC_PORT_LABEL}={host_grpc_port}",
        "--label",
        f"{GRPC_CONTAINER_PORT_LABEL}={container_grpc_port}",
        "--label",
        f"{IMAGE_REF_LABEL}={image}",
        "--restart",
        "unless-stopped",
        "-p",
        f"{host_grpc_port}:{container_grpc_port}",
    ]
    if profile_key:
        args.extend(["--label", f"{PROFILE_LABEL}={profile_key}"])
    if platform:
        args.extend(["--platform", platform])
        args.extend(["--label", f"{PLATFORM_LABEL}={platform}"])
    for key, value in (labels or {}).items():
        args.extend(["--label", f"{key}={value}"])
    for key, value in merged_env.items():
        args.extend(["-e", f"{key}={value}"])
    args.append(image)

    proc = _run(args, timeout=120)
    note = (proc.stdout or proc.stderr or "").strip()[-2000:]
    if proc.returncode != 0:
        _log.warning("docker_run_failed", service_id=service_id, note=note)
        return False, note, None
    container_id = (proc.stdout or "").strip().splitlines()[-1].strip() if proc.stdout else None
    return True, note or "started", container_id


def summarize_inspect(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {
            "exists": False,
            "state": "absent",
            "status": None,
            "container_id": None,
            "image": None,
            "started_at": None,
            "finished_at": None,
            "health": None,
            "ports": {},
            "labels": {},
        }
    state = raw.get("State") or {}
    config = raw.get("Config") or {}
    network = raw.get("NetworkSettings") or {}
    health = state.get("Health") or {}
    status = str(state.get("Status") or "unknown")
    running = bool(state.get("Running"))
    mapped_state = "running" if running else status
    ports: dict[str, Any] = {}
    for key, bindings in (network.get("Ports") or {}).items():
        ports[str(key)] = bindings
    return {
        "exists": True,
        "state": mapped_state,
        "status": state.get("Status"),
        "container_id": (raw.get("Id") or "")[:12] or None,
        "image": config.get("Image"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "exit_code": state.get("ExitCode"),
        "health": {
            "status": health.get("Status"),
            "failing_streak": health.get("FailingStreak"),
            "log": (health.get("Log") or [])[-3:],
        }
        if health
        else None,
        "ports": ports,
        "labels": config.get("Labels") or {},
        "name": (raw.get("Name") or "").lstrip("/"),
    }


__all__ = [
    "GRPC_CONTAINER_PORT_LABEL",
    "GRPC_PORT_LABEL",
    "IMAGE_REF_LABEL",
    "MANAGED_LABEL",
    "PLATFORM_LABEL",
    "PROFILE_LABEL",
    "SERVICE_LABEL",
    "container_logs",
    "docker_available",
    "find_managed",
    "host_is_arm64",
    "image_present",
    "inspect_by_name",
    "inspect_image",
    "inspect_image_config",
    "is_platform_manifest_error",
    "pull_image",
    "pull_image_streaming",
    "remove_container",
    "resolve_platform",
    "run_container",
    "start_container",
    "stop_container",
    "summarize_inspect",
]
