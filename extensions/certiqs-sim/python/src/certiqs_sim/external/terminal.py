"""Text/prompt terminal for interacting with external theory gRPC services."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from google.protobuf.json_format import MessageToDict

from certiqs_sim.containers.service_profile import ServiceProfile, identity_profile
from certiqs_sim.external.examples import (
    build_ideal_bb84_receiver_model,
    example_prompts_for_profile,
)


def _msg_dict(message: Any) -> dict[str, Any]:
    return MessageToDict(message, preserving_proto_field_name=True)


def _ok(command: str, result: Any, *, note: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "result": result,
        "output": json.dumps(result, indent=2, default=str) if not isinstance(result, str) else result,
        "note": note,
        "error": None,
    }


def _err(command: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "result": None,
        "output": error,
        "note": "",
        "error": error,
    }


def _channel(host: str, port: int):
    import grpc

    return grpc.insecure_channel(f"{host}:{port}")


def _runtime_stub(channel: Any):
    from qkd.security.theory.common.v1 import service_runtime_pb2_grpc

    return service_runtime_pb2_grpc.ServiceRuntimeStub(channel)


def _get_capabilities(channel: Any, profile: ServiceProfile, *, timeout: float) -> dict[str, Any]:
    if profile.key == "rx-characterization":
        from qkd.security.theory.rxcharacterization.v1 import (
            rx_characterization_pb2 as pb,
        )
        from qkd.security.theory.rxcharacterization.v1 import (
            rx_characterization_pb2_grpc as pbg,
        )

        stub = pbg.RxCharacterizationServiceStub(channel)
        resp = stub.GetCapabilities(pb.GetCapabilitiesRequest(), timeout=timeout)
        return {
            "service": "qkd.security.theory.rxcharacterization.v1.RxCharacterizationService",
            "method": "GetCapabilities",
            "response": _msg_dict(resp),
        }

    if profile.key == "rx-povm":
        from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb
        from qkd.security.theory.rxpovm.v1 import rx_povm_pb2_grpc as pbg

        stub = pbg.RxPovmServiceStub(channel)
        resp = stub.GetCapabilities(pb.GetCapabilitiesRequest(), timeout=timeout)
        return {
            "service": "qkd.security.theory.rxpovm.v1.RxPovmService",
            "method": "GetCapabilities",
            "response": _msg_dict(resp),
        }

    # Unknown image: do not assume it speaks a domain contract. Every service
    # built on the shared entrypoints implements ServiceRuntime, so ask that
    # instead — guessing RxPovmService here made template images (which have no
    # such service) report a confusing failure rather than describing themselves.
    import grpc

    from qkd.security.theory.common.v1 import service_runtime_pb2 as runtime_pb

    try:
        resp = _runtime_stub(channel).GetServiceInfo(
            runtime_pb.GetServiceInfoRequest(), timeout=timeout
        )
        return {
            "service": "qkd.security.theory.common.v1.ServiceRuntime",
            "method": "GetServiceInfo",
            "note": f"{profile.key} has no domain GetCapabilities; "
            "showing ServiceRuntime self-description",
            "response": _msg_dict(resp),
        }
    except grpc.RpcError:
        pass

    # The microservice-template images implement certiqs.ms.common.v1.ServiceRuntime
    # rather than the theory package, so the stub above returns UNIMPLEMENTED.
    # Reflection is enabled by default on both families and needs no stub.
    services = _reflect_services(channel, timeout=timeout)
    if services:
        return {
            "service": "grpc.reflection.v1alpha.ServerReflection",
            "method": "ListServices",
            "note": f"{profile.key} implements no known GetCapabilities contract; "
            "listing its gRPC services via reflection",
            "response": {"services": services},
        }

    raise RuntimeError(
        f"{profile.key} implements no known GetCapabilities or ServiceRuntime contract, "
        "and gRPC reflection is unavailable. Enable reflection on the image, or add it "
        "to the known-service profiles."
    )


def _reflect_services(channel: Any, *, timeout: float) -> list[str]:
    """List the gRPC services a server exposes, or [] when reflection is off."""
    try:
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
    except ImportError:
        return []

    import grpc

    try:
        stub = reflection_pb2_grpc.ServerReflectionStub(channel)
        request = reflection_pb2.ServerReflectionRequest(list_services="")
        found: list[str] = []
        for response in stub.ServerReflectionInfo(iter([request]), timeout=timeout):
            for service in response.list_services_response.service:
                if service.name:
                    found.append(service.name)
        return found
    except grpc.RpcError:
        return []


def _validate_example(channel: Any, *, timeout: float) -> dict[str, Any]:
    from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb
    from qkd.security.theory.rxpovm.v1 import rx_povm_pb2_grpc as pbg

    stub = pbg.RxPovmServiceStub(channel)
    model = build_ideal_bb84_receiver_model()
    resp = stub.ValidateReceiverModel(
        pb.ValidateReceiverModelRequest(receiver_model=model),
        timeout=timeout,
    )
    return {
        "service": "qkd.security.theory.rxpovm.v1.RxPovmService",
        "method": "ValidateReceiverModel",
        "response": _msg_dict(resp),
    }


def _execute_validate_example(channel: Any, *, timeout: float) -> dict[str, Any]:
    from qkd.security.theory.common.v1 import service_runtime_pb2 as runtime_pb
    from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

    stub = _runtime_stub(channel)
    model = build_ideal_bb84_receiver_model()
    payload = pb.ValidateReceiverModelRequest(receiver_model=model).SerializeToString()
    request_id = uuid.uuid4().hex
    submitted = stub.Execute(
        runtime_pb.ExecuteRequest(
            request_id=request_id,
            operation="ValidateReceiverModel",
            payload=payload,
        ),
        timeout=min(timeout, 15.0),
    )
    job_id = submitted.job_id
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        status = stub.GetJobStatus(
            runtime_pb.GetJobStatusRequest(job_id=job_id), timeout=5.0
        )
        if status.state in (
            runtime_pb.JOB_STATE_SUCCEEDED,
            runtime_pb.JOB_STATE_FAILED,
            runtime_pb.JOB_STATE_CANCELLED,
        ):
            break
        time.sleep(0.2)
    if status is None:
        raise TimeoutError(f"Job {job_id} did not return a status")

    result: dict[str, Any] = {
        "service": "qkd.security.theory.common.v1.ServiceRuntime",
        "method": "Execute",
        "operation": "ValidateReceiverModel",
        "request_id": request_id,
        "job": _msg_dict(status),
    }
    if status.state == runtime_pb.JOB_STATE_SUCCEEDED and status.result_payload:
        decoded = pb.ValidateReceiverModelResponse.FromString(status.result_payload)
        result["decoded_result"] = _msg_dict(decoded)
    return result


def _help_text(profile: ServiceProfile) -> dict[str, Any]:
    prompts = example_prompts_for_profile(profile.key)
    return {
        "profile": profile.key,
        "commands": [
            "help",
            "GetCapabilities | caps",
            "GetServiceInfo | info",
            "GetLiveness | liveness",
            "GetReadiness | readiness",
            "GetServiceStatus | status",
            "ValidateReceiverModel --example  (rx-povm)",
            "execute ValidateReceiverModel --example  (ServiceRuntime)",
            "examples",
        ],
        "example_prompts": prompts,
        "note": (
            "Type a command or click an example prompt. "
            "ServiceRuntime and domain RPCs share the same published gRPC port."
        ),
    }


def run_terminal_prompt(
    *,
    host: str,
    port: int,
    image_name: str,
    prompt: str,
    timeout: float = 30.0,
    default_port: int = 50051,
    port_overrides: str = "",
) -> dict[str, Any]:
    """Execute a terminal prompt against a running worker."""
    text = (prompt or "").strip()
    if not text:
        return _err("", "Empty prompt")

    del default_port  # dial uses published host port; identity is leaf/prefix only
    profile = identity_profile(image_name, port_overrides=port_overrides)
    command = text
    lowered = text.lower()

    if lowered in {"help", "?", "examples"}:
        return _ok(command, _help_text(profile))

    try:
        import grpc  # noqa: F401
    except ImportError:
        return _err(command, "grpcio not installed (pip install 'certiqs-sim[external]')")

    channel = _channel(host, port)
    try:
        from qkd.security.theory.common.v1 import service_runtime_pb2 as runtime_pb

        stub = _runtime_stub(channel)

        if lowered in {"getcapabilities", "capabilities", "caps", "capability"}:
            return _ok(command, _get_capabilities(channel, profile, timeout=timeout))

        if lowered in {"getserviceinfo", "serviceinfo", "info"}:
            info = stub.GetServiceInfo(runtime_pb.GetServiceInfoRequest(), timeout=timeout)
            return _ok(command, {
                "service": "qkd.security.theory.common.v1.ServiceRuntime",
                "method": "GetServiceInfo",
                "response": _msg_dict(info),
            })

        if lowered in {"getliveness", "liveness", "live"}:
            resp = stub.GetLiveness(runtime_pb.GetLivenessRequest(), timeout=timeout)
            return _ok(command, {
                "service": "qkd.security.theory.common.v1.ServiceRuntime",
                "method": "GetLiveness",
                "response": _msg_dict(resp),
            })

        if lowered in {"getreadiness", "readiness", "ready"}:
            resp = stub.GetReadiness(runtime_pb.GetReadinessRequest(), timeout=timeout)
            return _ok(command, {
                "service": "qkd.security.theory.common.v1.ServiceRuntime",
                "method": "GetReadiness",
                "response": _msg_dict(resp),
            })

        if lowered in {"getservicestatus", "servicestatus", "status"}:
            resp = stub.GetServiceStatus(runtime_pb.GetServiceStatusRequest(), timeout=timeout)
            return _ok(command, {
                "service": "qkd.security.theory.common.v1.ServiceRuntime",
                "method": "GetServiceStatus",
                "response": _msg_dict(resp),
            })

        if re.match(r"^validatereceivermodel(\s+--example)?$", lowered):
            if profile.key != "rx-povm":
                return _err(
                    command,
                    "ValidateReceiverModel --example is available on rx-povm only",
                )
            return _ok(command, _validate_example(channel, timeout=timeout))

        exec_match = re.match(
            r"^execute\s+validatereceivermodel(\s+--example)?$",
            lowered,
        )
        if exec_match:
            if profile.key != "rx-povm":
                return _err(
                    command,
                    "execute ValidateReceiverModel --example is available on rx-povm only",
                )
            return _ok(
                command,
                _execute_validate_example(channel, timeout=timeout),
                note="Submitted via ServiceRuntime.Execute and polled GetJobStatus",
            )

        return _err(
            command,
            "Unknown prompt. Try `help` or click an example (GetCapabilities, GetServiceInfo, …).",
        )
    except Exception as exc:  # noqa: BLE001
        return _err(command, f"{type(exc).__name__}: {exc}")
    finally:
        channel.close()


def fetch_capabilities(
    *,
    host: str,
    port: int,
    image_name: str,
    timeout: float = 5.0,
    default_port: int = 50051,
    port_overrides: str = "",
) -> dict[str, Any]:
    """Fetch GetCapabilities (+ example prompts) for the Terminal tab."""
    del default_port
    profile = identity_profile(image_name, port_overrides=port_overrides)
    examples = example_prompts_for_profile(profile.key)
    try:
        channel = _channel(host, port)
        try:
            caps = _get_capabilities(channel, profile, timeout=timeout)
            return {
                "ok": True,
                "profile": profile.key,
                "capabilities": caps,
                "example_prompts": examples,
                "error": None,
            }
        finally:
            channel.close()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "profile": profile.key,
            "capabilities": None,
            "example_prompts": examples,
            "error": f"{type(exc).__name__}: {exc}",
        }


__all__ = ["fetch_capabilities", "run_terminal_prompt"]
