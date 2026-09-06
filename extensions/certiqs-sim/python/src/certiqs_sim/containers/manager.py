"""Lifecycle manager for external GHCR worker container microservices."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from functools import lru_cache
from typing import Any

from certiqs_sim.config.settings import Settings, get_settings
from certiqs_sim.containers import docker_runtime as docker
from certiqs_sim.containers.deployments import DeploymentJob, get_deployment_store
from certiqs_sim.containers.service_profile import (
    PortDiscoveryError,
    deploy_env_for_profile,
    identity_profile,
    image_leaf,
    resolve_grpc_from_image_config,
    resolve_service_profile,
)
from certiqs_sim.external.client import probe_worker_grpc
from certiqs_sim.external.terminal import fetch_capabilities, run_terminal_prompt
from certiqs_sim.images.discovery import discover_ghcr_catalog


def service_id_for_image(name: str) -> str:
    """Stable URL-safe id. GHCR nested packages use ``/`` in the name."""
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip().lower()).strip("-")
    return slug or "worker"


def container_name_for(service_id: str) -> str:
    # Docker container names max 63 chars; keep a short hash suffix for uniqueness.
    base = f"certiqs-ext-{service_id}"
    if len(base) <= 63:
        return base
    digest = hashlib.sha1(service_id.encode("utf-8")).hexdigest()[:8]
    keep = 63 - 1 - len(digest)
    return f"{base[:keep]}-{digest}"


def host_port_for(service_id: str, *, base: int) -> int:
    digest = hashlib.sha1(service_id.encode("utf-8")).hexdigest()
    offset = int(digest[:4], 16) % 1000
    return base + offset


def _resolve_pull_ref(base_ref: str, tag: str | None) -> str:
    if not tag:
        return base_ref
    if "@" in base_ref:
        return base_ref
    # Nested GHCR names contain ``/``; only split the final ``:tag``.
    if ":" in base_ref.rsplit("/", 1)[-1]:
        return f"{base_ref.rsplit(':', 1)[0]}:{tag}"
    return f"{base_ref}:{tag}"


def _image_matches(img: Any, service_id: str) -> bool:
    name = str(getattr(img, "name", "") or "")
    if service_id_for_image(name) == service_id:
        return True
    if name == service_id:
        return True
    # Accept raw nested names that were only partially normalized.
    if name.replace("/", "-") == service_id:
        return True
    return False


class ContainerManager:
    """Treat GHCR catalog images as deployable external worker microservices."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jobs = get_deployment_store()

    def docker_ok(self) -> bool:
        return docker.docker_available()

    def _catalog_images(self) -> tuple[list[Any], dict[str, Any]]:
        result = discover_ghcr_catalog(
            owner=self.settings.images_registry_owner,
            owner_kind=self.settings.images_registry_owner_kind,
            token=self.settings.images_registry_token,
            registry=self.settings.images_registry,
            include_versions=True,
            max_versions_per_image=max(1, self.settings.images_max_versions),
            cache_ttl_s=self.settings.images_cache_ttl_s,
        )
        meta = {
            "registry": result.registry,
            "owner": result.owner,
            "owner_kind": result.owner_kind,
            "authenticated": result.authenticated,
            "error": result.error,
            "warnings": list(result.warnings),
        }
        return list(result.images), meta

    def list_services(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        images, meta = self._catalog_images()
        services = [self._status_from_image(img) for img in images]
        return services, meta

    def _find_image(self, service_id: str) -> Any:
        images, _ = self._catalog_images()
        for img in images:
            if _image_matches(img, service_id):
                return img
        raise KeyError(f"Unknown container service '{service_id}' (not in GHCR catalog)")

    def status(self, service_id: str) -> dict[str, Any]:
        return self._status_from_image(self._find_image(service_id))

    def _image_override(self, image_name: str) -> str | None:
        """Local image to deploy instead of the catalog's, if one is configured.

        Parsed from ``CERTIQS_CONTAINERS_IMAGE_OVERRIDES`` as
        ``<leaf>=<image ref>`` pairs, e.g. ``rx-povm=certiqs-rx-povm:patched``.
        """
        raw = (self.settings.containers_image_overrides or "").strip()
        if not raw:
            return None
        leaf = image_leaf(image_name)
        for part in raw.split(","):
            key, sep, value = part.strip().partition("=")
            if sep and key.strip().lower() == leaf and value.strip():
                return value.strip()
        return None

    def _port_overrides(self) -> str:
        return self.settings.containers_service_ports or ""

    def _discover_profile(
        self,
        *,
        image_ref: str,
        catalog_name: str,
    ) -> Any:
        """Resolve gRPC bind port from local image metadata (fail closed)."""
        config = docker.inspect_image_config(image_ref)
        if config is None:
            raise PortDiscoveryError(
                f"cannot inspect image '{image_ref}' for gRPC port metadata"
            )
        return resolve_grpc_from_image_config(
            config,
            image_name=catalog_name,
            port_overrides=self._port_overrides(),
        )

    def _profile_for_status(self, img: Any, *, pull_ref: str, image_ok: bool) -> Any:
        """Best-effort port for status UI (None container_port until discoverable)."""
        if image_ok:
            try:
                return self._discover_profile(
                    image_ref=pull_ref,
                    catalog_name=str(img.name),
                )
            except PortDiscoveryError:
                pass
        try:
            return resolve_service_profile(
                str(img.name),
                port_overrides=self._port_overrides(),
            )
        except PortDiscoveryError:
            return identity_profile(
                str(img.name),
                port_overrides=self._port_overrides(),
            )

    def _status_from_image(self, img: Any) -> dict[str, Any]:
        service_id = service_id_for_image(img.name)
        name = container_name_for(service_id)
        host_port = host_port_for(service_id, base=self.settings.containers_grpc_host_port_base)
        docker_ok = self.docker_ok()
        pull_ref = img.pull_ref
        image_ok = docker.image_present(pull_ref) if docker_ok else False
        profile = self._profile_for_status(img, pull_ref=pull_ref, image_ok=image_ok)
        container_port = (
            profile.container_port if getattr(profile, "container_port", 0) else None
        )

        inspect = docker.find_managed(service_id) if docker_ok else None
        if inspect is None and docker_ok:
            inspect = docker.inspect_by_name(name)
        summary = docker.summarize_inspect(inspect)

        labels = summary.get("labels") or {}
        if labels.get(docker.GRPC_PORT_LABEL):
            try:
                host_port = int(labels[docker.GRPC_PORT_LABEL])
            except ValueError:
                pass
        if labels.get(docker.GRPC_CONTAINER_PORT_LABEL):
            try:
                container_port = int(labels[docker.GRPC_CONTAINER_PORT_LABEL])
            except ValueError:
                pass

        available = True
        unavailable_reason: str | None = None
        if not self.settings.images_registry_owner:
            available = False
            unavailable_reason = "GHCR owner not configured (CERTIQS_IMAGES_REGISTRY_OWNER)"
        elif not docker_ok:
            available = False
            unavailable_reason = "Docker CLI is not available on this host"

        state = summary["state"]
        if not available and state == "absent":
            state = "unavailable"

        grpc: dict[str, Any] = {
            "host": self.settings.ops_probe_host,
            "port": host_port,
            "container_port": container_port,
            "addr": f"{self.settings.ops_probe_host}:{host_port}",
            "reachable": False,
            "status": "idle",
            "detail": "Container not running",
            "info": None,
            "metrics": {},
            "service_info": None,
            "contract": None,
        }
        if summary.get("state") == "running":
            grpc = {
                **grpc,
                **probe_worker_grpc(
                    host=self.settings.ops_probe_host,
                    port=host_port,
                ),
                "container_port": container_port,
            }

        docker_health = (summary.get("health") or {}).get("status") if summary.get("health") else None
        grpc_ok = bool(grpc.get("reachable")) and grpc.get("status") not in {
            "unreachable",
            "port_open",
            "idle",
        }
        health = {
            "overall": (
                "healthy"
                if summary.get("state") == "running" and grpc_ok
                else "degraded"
                if summary.get("state") == "running"
                else "stopped"
                if summary.get("exists")
                else "not_deployed"
            ),
            "docker_state": summary.get("state"),
            "docker_health": docker_health,
            "grpc_status": grpc.get("status"),
            "grpc_reachable": bool(grpc.get("reachable")),
            "detail": grpc.get("detail") or unavailable_reason or "",
        }

        versions = []
        for ver in getattr(img, "versions", None) or []:
            if hasattr(ver, "as_dict"):
                versions.append(ver.as_dict())
            elif isinstance(ver, dict):
                versions.append(ver)

        tags: list[str] = list(img.latest_tags or [])
        for ver in versions:
            for t in ver.get("tags") or []:
                if t not in tags:
                    tags.append(str(t))

        job = self._jobs.latest_for(service_id)
        deployment = job.as_dict() if job else None

        latest_digest = getattr(img, "latest_digest", None)
        service_info = grpc.get("service_info") if isinstance(grpc.get("service_info"), dict) else None
        description = (
            (service_info or {}).get("description")
            or img.description
            or f"External worker image from {img.registry}"
        )
        manifest = {
            "name": img.name,
            "full_name": getattr(img, "full_name", None) or f"{img.owner}/{img.name}",
            "pull_ref": pull_ref,
            "registry": img.registry,
            "owner": img.owner,
            "visibility": img.visibility,
            "html_url": img.html_url,
            "tags": tags[:12],
            "latest_digest": latest_digest,
            "versions": versions[:8],
            "image_present": image_ok,
            "profile": profile.key,
            "env_prefix": profile.env_prefix,
        }

        if service_info and service_info.get("endpoints"):
            services_provided = [
                {
                    "id": ep.get("grpc_service", "").rsplit(".", 1)[-1] or f"svc-{idx}",
                    "name": ep.get("grpc_service"),
                    "protocol": "grpc",
                    "package": ".".join(str(ep.get("grpc_service", "")).split(".")[:-1]),
                    "endpoint": f"{self.settings.ops_probe_host}:{host_port}",
                    "methods": list(ep.get("methods") or []),
                    "description": "",
                }
                for idx, ep in enumerate(service_info["endpoints"])
            ]
            runtime_methods = next(
                (
                    list(ep.get("methods") or [])
                    for ep in service_info["endpoints"]
                    if str(ep.get("grpc_service", "")).endswith("ServiceRuntime")
                ),
                ["GetServiceInfo", "GetLiveness", "GetReadiness", "Execute"],
            )
            interface = {
                "protocol": "grpc",
                "package": "qkd.security.theory.common.v1",
                "service": "ServiceRuntime",
                "methods": runtime_methods,
                "role": "external_provider",
                "proto": "proto/qkd/security/theory/common/v1/service_runtime.proto",
                "note": (
                    "Theory containers expose ServiceRuntime (GetServiceInfo) plus "
                    "domain services; certiqs-api is the gRPC client."
                ),
                "reflection_enabled": bool(service_info.get("reflection_enabled")),
                "operations": list(service_info.get("operations") or []),
                "help": list(service_info.get("help") or []),
                "links": dict(service_info.get("links") or {}),
                "documentation_url": service_info.get("documentation_url") or "",
            }
        else:
            services_provided = [
                {
                    "id": "service-runtime",
                    "name": "ServiceRuntime",
                    "protocol": "grpc",
                    "package": "qkd.security.theory.common.v1",
                    "endpoint": f"{self.settings.ops_probe_host}:{host_port}",
                    "methods": [
                        "Execute",
                        "GetLiveness",
                        "GetReadiness",
                        "GetServiceStatus",
                        "GetJobStatus",
                        "GetServiceInfo",
                    ],
                    "description": (
                        "Self-describing runtime control plane "
                        f"(expected container port {container_port})"
                    ),
                }
            ]
            interface = {
                "protocol": "grpc",
                "package": "qkd.security.theory.common.v1",
                "service": "ServiceRuntime",
                "methods": [
                    "Execute",
                    "GetLiveness",
                    "GetReadiness",
                    "GetServiceStatus",
                    "GetJobStatus",
                    "GetServiceInfo",
                ],
                "role": "external_provider",
                "proto": "proto/qkd/security/theory/common/v1/service_runtime.proto",
                "note": (
                    "Probe via GetServiceInfo when running. Legacy WorkerService "
                    "is still accepted as a fallback."
                ),
            }

        return {
            "id": service_id,
            "name": img.name,
            "description": description,
            "image": pull_ref,
            "registry": img.registry,
            "owner": img.owner,
            "visibility": img.visibility,
            "html_url": img.html_url,
            "latest_tags": tags[:12],
            "versions": versions[:8],
            "container_name": name,
            "ports": (
                [f"{host_port}:{container_port}"]
                if container_port
                else [f"{host_port}:?"]
            ),
            "available": available,
            "unavailable_reason": unavailable_reason,
            "docker_available": docker_ok,
            "image_present": image_ok,
            "state": state,
            "container": summary,
            "grpc": grpc,
            "health": health,
            "service_info": service_info,
            "provision": {
                "service_id": service_id,
                "container_name": name,
                "image": pull_ref,
                "registry": img.registry,
                "owner": img.owner,
                "host_port": host_port,
                "container_port": container_port,
                "profile": profile.key,
                "env_prefix": profile.env_prefix,
                "grpc_addr": f"{self.settings.ops_probe_host}:{host_port}",
                "labels": {
                    docker.MANAGED_LABEL: "true",
                    docker.SERVICE_LABEL: service_id,
                },
                "deployed": bool(summary.get("exists")),
                "running": summary.get("state") == "running",
                "image_present": image_ok,
            },
            "manifest": manifest,
            "services_provided": services_provided,
            "deployment": deployment,
            "interface": interface,
        }

    def inspect(self, service_id: str) -> dict[str, Any]:
        return self.status(service_id)

    def logs(self, service_id: str, *, tail: int = 200) -> dict[str, Any]:
        self._find_image(service_id)
        if not self.docker_ok():
            return {"id": service_id, "lines": ["Docker CLI is not available"], "source": "error"}
        name = container_name_for(service_id)
        inspect = docker.find_managed(service_id) or docker.inspect_by_name(name)
        if not inspect:
            return {"id": service_id, "lines": ["Container is not deployed"], "source": "none"}
        cname = (inspect.get("Name") or "").lstrip("/") or name
        return {"id": service_id, "lines": docker.container_logs(cname, tail=tail), "source": "docker"}

    def _endpoint_for(self, service_id: str) -> tuple[Any, dict[str, Any]]:
        status = self.status(service_id)
        if status.get("state") != "running":
            raise RuntimeError(f"Service '{service_id}' is not running")
        host = self.settings.ops_probe_host
        port = int((status.get("grpc") or {}).get("port") or 0)
        if port <= 0:
            raise RuntimeError(f"Service '{service_id}' has no published gRPC port")
        return self._find_image(service_id), {
            "host": host,
            "port": port,
            "addr": f"{host}:{port}",
            "image_name": status.get("name") or service_id,
        }

    def terminal_capabilities(self, service_id: str) -> dict[str, Any]:
        img, endpoint = self._endpoint_for(service_id)
        raw = fetch_capabilities(
            host=endpoint["host"],
            port=endpoint["port"],
            image_name=str(getattr(img, "name", endpoint["image_name"])),
            default_port=self.settings.containers_grpc_container_port,
            port_overrides=self.settings.containers_service_ports,
        )
        return {
            "id": service_id,
            "addr": endpoint["addr"],
            **raw,
        }

    def terminal_prompt(self, service_id: str, prompt: str) -> dict[str, Any]:
        img, endpoint = self._endpoint_for(service_id)
        raw = run_terminal_prompt(
            host=endpoint["host"],
            port=endpoint["port"],
            image_name=str(getattr(img, "name", endpoint["image_name"])),
            prompt=prompt,
            default_port=self.settings.containers_grpc_container_port,
            port_overrides=self.settings.containers_service_ports,
        )
        return {
            "id": service_id,
            "addr": endpoint["addr"],
            "prompt": prompt,
            **raw,
        }

    def get_deployment(self, service_id: str, job_id: str) -> dict[str, Any]:
        self._find_image(service_id)
        job = self._jobs.get(job_id)
        if job is None or job.service_id != service_id:
            raise KeyError(f"Deployment job '{job_id}' not found")
        return job.as_dict()

    def latest_deployment(self, service_id: str) -> dict[str, Any] | None:
        self._find_image(service_id)
        job = self._jobs.latest_for(service_id)
        return job.as_dict() if job else None

    def start_deployment(
        self,
        service_id: str,
        *,
        pull: bool = True,
        tag: str | None = None,
    ) -> dict[str, Any]:
        if not self.docker_ok():
            raise RuntimeError("Docker CLI is not available")
        active = self._jobs.active_for(service_id)
        if active is not None:
            return active.as_dict()

        img = self._find_image(service_id)
        override = self._image_override(img.name)
        if override:
            # A local replacement (e.g. an emulation-patched build) — pulling it
            # would fail, since it exists only on this host.
            image, pull = override, False
        else:
            image = _resolve_pull_ref(img.pull_ref, tag)
        job = self._jobs.create(service_id=service_id, image=image, pull=pull, tag=tag)
        thread = threading.Thread(
            target=self._run_deployment,
            args=(job,),
            name=f"deploy-{service_id}",
            daemon=True,
        )
        thread.start()
        return job.as_dict()

    def _run_deployment(self, job: DeploymentJob) -> None:
        service_id = job.service_id
        try:
            if job.pull:
                job.set_phase("pulling", progress=0.12)
                platform = docker.resolve_platform(self.settings.containers_platform)
                if platform:
                    job.append(f"Pulling image {job.image} (platform {platform}) …")
                else:
                    job.append(f"Pulling image {job.image} …")

                pull_progress = {"seen": 0}

                def _on_line(line: str) -> None:
                    job.append(line)
                    pull_progress["seen"] += 1
                    # Ease progress during long pulls without claiming completion.
                    bump = min(0.70, 0.12 + pull_progress["seen"] * 0.01)
                    if bump > job.progress and job.phase == "pulling":
                        job.progress = bump
                        job.updated_at = time.time()

                ok, note = docker.pull_image_streaming(
                    job.image, on_line=_on_line, platform=platform
                )
                if not ok:
                    hint = ""
                    if docker.is_platform_manifest_error(note):
                        hint = (
                            " Hint: image has no arm64 build. Set "
                            "CERTIQS_CONTAINERS_PLATFORM=linux/amd64 and redeploy "
                            "(Docker Desktop will emulate amd64)."
                        )
                    job.error = f"pull failed: {note}{hint}"
                    job.append(job.error)
                    job.set_phase("failed")
                    return
                job.append("Image pull complete")
            else:
                job.append("Skipping image pull")

            if not docker.image_present(job.image):
                job.error = f"Image '{job.image}' not found locally"
                job.append(job.error)
                job.set_phase("failed")
                return

            catalog_name = service_id
            try:
                catalog_img = self._find_image(service_id)
                catalog_name = str(catalog_img.name)
            except KeyError:
                pass

            job.set_phase("creating")
            job.append(f"Creating container {container_name_for(service_id)}")
            try:
                profile = self._discover_profile(
                    image_ref=job.image,
                    catalog_name=catalog_name,
                )
            except PortDiscoveryError as exc:
                job.error = str(exc)
                job.append(f"Port discovery failed: {exc}")
                job.set_phase("failed")
                return

            host_port = host_port_for(
                service_id, base=self.settings.containers_grpc_host_port_base
            )
            platform = docker.resolve_platform(self.settings.containers_platform)
            env = deploy_env_for_profile(profile)
            job.append(
                f"Publishing {host_port}:{profile.container_port} "
                f"(discovered via {profile.port_source}, profile={profile.key}"
                + (f", service={profile.service_name}" if profile.service_name else "")
                + (f", prefix={profile.env_prefix}" if profile.env_prefix else "")
                + ")"
            )
            ok, note, container_id = docker.run_container(
                name=container_name_for(service_id),
                image=job.image,
                service_id=service_id,
                host_grpc_port=host_port,
                container_grpc_port=profile.container_port,
                env=env,
                platform=platform,
                profile_key=profile.key,
            )
            job.append(note or ("created" if ok else "create failed"))
            if not ok:
                job.error = note or "failed to create container"
                job.set_phase("failed")
                return

            job.container_id = container_id
            job.set_phase("starting")
            job.append("Container started")

            job.set_phase("probing")
            job.append(
                f"Probing gRPC at {self.settings.ops_probe_host}:{host_port} "
                f"(container port {profile.container_port})"
            )
            time.sleep(0.8)
            probe = probe_worker_grpc(host=self.settings.ops_probe_host, port=host_port)
            if probe.get("service_info"):
                info = probe["service_info"]
                job.append(
                    f"GetServiceInfo · {info.get('service_name')} "
                    f"v{info.get('service_version')} · reflection="
                    f"{info.get('reflection_enabled')}"
                )
                for ep in info.get("endpoints") or []:
                    methods = ", ".join(ep.get("methods") or [])
                    job.append(f"  {ep.get('grpc_service')} → [{methods}]")
            elif probe.get("reachable") and probe.get("status") not in {
                "port_open",
                "unreachable",
            }:
                job.append(
                    f"gRPC reachable · status={probe.get('status')} "
                    f"· contract={probe.get('contract') or 'unknown'}"
                )
            else:
                job.append(
                    f"gRPC not ready yet ({probe.get('detail') or 'unreachable'}) — "
                    f"published {host_port}->{profile.container_port}; "
                    "container is running; service may still be booting. "
                    "If this persists, recreate the deployment after fixing image port metadata."
                )

            job.append("Deployment finished")
            job.set_phase("ready")
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job.append(f"ERROR: {exc}")
            job.set_phase("failed")

    def deploy(self, service_id: str, *, pull: bool | None = None) -> dict[str, Any]:
        """Synchronous deploy (legacy). Prefer ``start_deployment`` for progress UI."""
        job = self.start_deployment(service_id, pull=True if pull is None else pull)
        # Wait briefly for completion for sync callers
        deadline = time.time() + 600
        while time.time() < deadline:
            current = self._jobs.get(job["job_id"])
            if current is None:
                break
            if current.phase in {"ready", "failed", "cancelled"}:
                return {
                    "id": service_id,
                    "ok": bool(current.ok),
                    "action": "deploy",
                    "backend": "docker",
                    "note": "\n".join(list(current.lines)[-20:]),
                    "container_id": current.container_id,
                    "error": current.error,
                    "job_id": current.job_id,
                }
            time.sleep(0.4)
        return {
            "id": service_id,
            "ok": False,
            "action": "deploy",
            "backend": "docker",
            "error": "deployment timed out waiting for completion",
            "job_id": job.get("job_id"),
        }

    def start(self, service_id: str) -> dict[str, Any]:
        if not self.docker_ok():
            raise RuntimeError("Docker CLI is not available")
        self._find_image(service_id)
        name = container_name_for(service_id)
        inspect = docker.find_managed(service_id) or docker.inspect_by_name(name)
        if not inspect:
            job = self.start_deployment(service_id, pull=True)
            return {
                "id": service_id,
                "ok": True,
                "action": "start",
                "backend": "docker",
                "note": f"deployment started ({job.get('job_id')})",
                "job_id": job.get("job_id"),
            }
        cname = (inspect.get("Name") or "").lstrip("/") or name
        if (inspect.get("State") or {}).get("Status") == "running":
            return {
                "id": service_id,
                "ok": True,
                "action": "start",
                "backend": "docker",
                "note": "already running",
            }
        ok, note = docker.start_container(cname)
        return {
            "id": service_id,
            "ok": ok,
            "action": "start",
            "backend": "docker",
            "note": note,
            "error": None if ok else note,
        }

    def stop(self, service_id: str) -> dict[str, Any]:
        if not self.docker_ok():
            raise RuntimeError("Docker CLI is not available")
        self._find_image(service_id)
        name = container_name_for(service_id)
        inspect = docker.find_managed(service_id) or docker.inspect_by_name(name)
        if not inspect:
            return {
                "id": service_id,
                "ok": True,
                "action": "stop",
                "backend": "docker",
                "note": "not deployed",
            }
        cname = (inspect.get("Name") or "").lstrip("/") or name
        ok, note = docker.stop_container(cname)
        return {
            "id": service_id,
            "ok": ok,
            "action": "stop",
            "backend": "docker",
            "note": note,
            "error": None if ok else note,
        }

    def remove(self, service_id: str) -> dict[str, Any]:
        if not self.docker_ok():
            raise RuntimeError("Docker CLI is not available")
        self._find_image(service_id)
        name = container_name_for(service_id)
        inspect = docker.find_managed(service_id) or docker.inspect_by_name(name)
        if not inspect:
            return {
                "id": service_id,
                "ok": True,
                "action": "remove",
                "backend": "docker",
                "note": "not deployed",
            }
        cname = (inspect.get("Name") or "").lstrip("/") or name
        # Stop first when running
        if (inspect.get("State") or {}).get("Running"):
            docker.stop_container(cname)
        ok, note = docker.remove_container(cname, force=True)
        return {
            "id": service_id,
            "ok": ok,
            "action": "remove",
            "backend": "docker",
            "note": note,
            "error": None if ok else note,
        }


@lru_cache(maxsize=1)
def get_container_manager() -> ContainerManager:
    return ContainerManager(get_settings())


__all__ = [
    "ContainerManager",
    "container_name_for",
    "get_container_manager",
    "host_port_for",
    "service_id_for_image",
]
