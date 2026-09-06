"""Typed pydantic models mirroring the 8-document YAML manifest.

The ``core`` builders produce the live, mutable dataclasses the engine mutates.
These pydantic models are the *validated, typed* view of the manifest and finally
consume the sections the original code parsed-but-ignored — notably the
``07_post_processing.yaml`` error-correction / privacy-amplification settings and
the ``01_protocol.yaml`` finite-key security parameters — which the
post-processing layer needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CoincidenceModel(BaseModel):
    window_ps: float = 1000.0
    matching_policy: str = "nearest_timestamp"
    require_one_click_per_side: bool = True
    multi_click_policy: str = "discard_event"


class SiftingModel(BaseModel):
    keep_same_basis_only: bool = True
    reveal_basis_only: bool = True
    reveal_bit_values: bool = False


class QberEstimationModel(BaseModel):
    sample_fraction: float = 0.1
    z_basis_key_basis: bool = True
    x_basis_parameter_estimation: bool = True


class SecurityParameters(BaseModel):
    epsilon_correct: float = 1e-12
    epsilon_secret: float = 1e-12
    authentication_tag_bits: int = 128


class ProtocolModel(BaseModel):
    name: str = "BBM92"
    family: str = "entanglement_based_qkd"
    coincidence: CoincidenceModel = Field(default_factory=CoincidenceModel)
    sifting: SiftingModel = Field(default_factory=SiftingModel)
    qber_estimation: QberEstimationModel = Field(default_factory=QberEstimationModel)
    security_parameters: SecurityParameters = Field(default_factory=SecurityParameters)


class ErrorCorrectionModel(BaseModel):
    algorithm: str = "ldpc"
    code_rate: float = 0.85
    block_size_bits: int = 65536
    max_iterations: int = 50
    leakage_accounting: bool = True
    # Cascade efficiency factor f_EC applied to the Shannon-limit leakage.
    efficiency: float = 1.1


class PrivacyAmplificationModel(BaseModel):
    algorithm: str = "toeplitz_hash"
    block_size_bits: int = 65536
    seed_source: str = "authenticated_classical_channel"
    finite_key_mode: bool = True


class AuthenticationModel(BaseModel):
    algorithm: str = "universal_hash_mac"
    tag_bits: int = 128


class PostProcessingModel(BaseModel):
    error_correction: ErrorCorrectionModel = Field(default_factory=ErrorCorrectionModel)
    privacy_amplification: PrivacyAmplificationModel = Field(
        default_factory=PrivacyAmplificationModel
    )
    authentication: AuthenticationModel = Field(default_factory=AuthenticationModel)


class ManifestModel(BaseModel):
    """Validated top-level view of a manifest directory."""

    protocol: ProtocolModel = Field(default_factory=ProtocolModel)
    post_processing: PostProcessingModel = Field(default_factory=PostProcessingModel)


def _manifest_to_dict(manifest: Any) -> dict[str, Any]:
    """Translate the schema-2.0 manifest documents into the typed model shape."""
    protocol_doc = dict(manifest.protocol.get("protocol", {}) or {})
    pp_doc = dict(manifest.post_processing.get("post_processing", {}) or {})

    finite_key = protocol_doc.get("finite_key", {}) or {}
    fk_engine = pp_doc.get("finite_key_engine", {}) or {}
    protocol_doc.setdefault(
        "security_parameters",
        {
            "epsilon_correct": finite_key.get(
                "epsilon_correct", fk_engine.get("epsilon_correct", 1e-12)
            ),
            "epsilon_secret": finite_key.get(
                "epsilon_secret", fk_engine.get("epsilon_secret", 1e-12)
            ),
        },
    )

    reconciliation = pp_doc.get("reconciliation", {}) or {}
    if reconciliation:
        pp_doc.setdefault(
            "error_correction",
            {
                "algorithm": str(reconciliation.get("component_class", "ldpc")),
                "max_iterations": reconciliation.get("max_iterations", 50),
                "efficiency": reconciliation.get("reconciliation_efficiency_target", 1.1),
            },
        )
    pa = pp_doc.get("privacy_amplification", {}) or {}
    if "implementation" in pa:
        pp_doc["privacy_amplification"] = {
            "algorithm": str(pa["implementation"]),
            "seed_source": str(pa.get("seed_source", "authenticated_classical_channel")),
            "finite_key_mode": True,
        }
    auth = pp_doc.get("authentication", {}) or {}
    if "scheme" in auth:
        pp_doc["authentication"] = {"algorithm": str(auth["scheme"])}

    return {"protocol": protocol_doc, "post_processing": pp_doc}


def load_manifest_model(source: Any) -> ManifestModel:
    """Build a :class:`ManifestModel` from a directory path or a ``YAMLManifest``."""
    from certiqs_sim.core.manifest import YAMLManifest

    manifest = source
    if isinstance(source, (str, Path)):
        manifest = YAMLManifest.from_directory(Path(source))
    return ManifestModel.model_validate(_manifest_to_dict(manifest))


__all__ = [
    "AuthenticationModel",
    "CoincidenceModel",
    "ErrorCorrectionModel",
    "ManifestModel",
    "PostProcessingModel",
    "PrivacyAmplificationModel",
    "ProtocolModel",
    "QberEstimationModel",
    "SecurityParameters",
    "SiftingModel",
    "load_manifest_model",
]
