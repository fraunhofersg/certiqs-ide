"""Example payloads mirroring theory-service client examples."""

from __future__ import annotations

import hashlib
import struct
from typing import Any

import numpy as np


def _matrix_to_proto(matrix: np.ndarray) -> Any:
    from qkd.security.theory.common.v1 import common_pb2

    arr = np.asarray(matrix, dtype=np.complex128)
    rows, cols = arr.shape
    floats = np.empty(rows * cols * 2, dtype=np.float64)
    floats[0::2] = arr.real.reshape(-1)
    floats[1::2] = arr.imag.reshape(-1)
    payload = struct.pack(f"<{rows * cols * 2}d", *floats.tolist())
    return common_pb2.ComplexMatrix(
        rows=rows,
        columns=cols,
        payload=payload,
        sha256_checksum=hashlib.sha256(payload).digest(),
    )


def ideal_bb84_g_optical(p_z: float = 0.5) -> np.ndarray:
    p_x = 1.0 - p_z
    return np.array(
        [
            [np.sqrt(p_z), 0, np.sqrt(p_x), 0],
            [0, np.sqrt(p_z), 0, np.sqrt(p_x)],
            [np.sqrt(p_x / 2), np.sqrt(p_x / 2), -np.sqrt(p_z / 2), -np.sqrt(p_z / 2)],
            [np.sqrt(p_x / 2), -np.sqrt(p_x / 2), -np.sqrt(p_z / 2), np.sqrt(p_z / 2)],
        ],
        dtype=np.complex128,
    )


def build_ideal_bb84_receiver_model() -> Any:
    """Ideal BB84 receiver model used by theory example clients."""
    from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

    g = ideal_bb84_g_optical()
    return pb.ReceiverModel(
        model_id="ideal-bb84",
        instrument_matrix_g=_matrix_to_proto(g),
        matrix_semantics=pb.INSTRUMENT_MATRIX_SEMANTICS_PRE_DETECTOR_OPTICAL,
        detectors=[
            pb.DetectorParameters(
                outcome=pb.DETECTOR_OUTCOME_SINGLE_CLICK_H,
                detection_efficiency=0.9,
                dark_count_probability=1e-3,
            ),
            pb.DetectorParameters(
                outcome=pb.DETECTOR_OUTCOME_SINGLE_CLICK_V,
                detection_efficiency=0.9,
                dark_count_probability=1e-3,
            ),
            pb.DetectorParameters(
                outcome=pb.DETECTOR_OUTCOME_SINGLE_CLICK_PLUS,
                detection_efficiency=0.9,
                dark_count_probability=1e-3,
            ),
            pb.DetectorParameters(
                outcome=pb.DETECTOR_OUTCOME_SINGLE_CLICK_MINUS,
                detection_efficiency=0.9,
                dark_count_probability=1e-3,
            ),
        ],
        optical_model_identifier="ideal_bb84",
        detector_model_identifier="threshold",
    )


def example_prompts_for_profile(profile_key: str) -> list[dict[str, str]]:
    """Reference prompts for the Terminal PromptInput."""
    common = [
        {
            "title": "GetCapabilities",
            "prompt": "GetCapabilities",
            "description": "Domain capabilities (version, limits, supported options)",
        },
        {
            "title": "GetServiceInfo",
            "prompt": "GetServiceInfo",
            "description": "ServiceRuntime self-description, endpoints, operations",
        },
        {
            "title": "GetLiveness",
            "prompt": "GetLiveness",
            "description": "ServiceRuntime process liveness probe",
        },
        {
            "title": "GetReadiness",
            "prompt": "GetReadiness",
            "description": "ServiceRuntime readiness + blocking reasons",
        },
        {
            "title": "GetServiceStatus",
            "prompt": "GetServiceStatus",
            "description": "Uptime and job counters via ServiceRuntime",
        },
        {
            "title": "help",
            "prompt": "help",
            "description": "List terminal commands and example prompts",
        },
    ]
    if profile_key == "rx-povm":
        common.extend(
            [
                {
                    "title": "ValidateReceiverModel (example)",
                    "prompt": "ValidateReceiverModel --example",
                    "description": "Validate ideal BB84 receiver model (domain RPC)",
                },
                {
                    "title": "Execute ValidateReceiverModel",
                    "prompt": "execute ValidateReceiverModel --example",
                    "description": "Same validation via ServiceRuntime async Execute",
                },
            ]
        )
    elif profile_key == "rx-characterization":
        # Refine the shared GetCapabilities blurb for this service.
        common[0] = {
            "title": "GetCapabilities",
            "prompt": "GetCapabilities",
            "description": "Scan-point limits and supported fit options",
        }
    return common


__all__ = [
    "build_ideal_bb84_receiver_model",
    "example_prompts_for_profile",
    "ideal_bb84_g_optical",
]
