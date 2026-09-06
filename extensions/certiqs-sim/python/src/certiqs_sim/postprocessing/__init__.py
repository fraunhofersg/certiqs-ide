"""Classical post-processing: sifting audit, QBER sampling, EC, PA, finite-key.

This is the layer the original monolith parsed (``07_post_processing.yaml``) but
never used — key rate there was a closed-form asymptotic estimate.  Here the
sifted blocks are actually error-corrected (Cascade), privacy-amplified (Toeplitz
hashing), and bounded with a finite-key analysis driven by the manifest's epsilon
security parameters.
"""

from __future__ import annotations

from certiqs_sim.postprocessing.error_correction import (
    CascadeResult,
    cascade_correct,
    ec_leakage_bits,
)
from certiqs_sim.postprocessing.finite_key import FiniteKeyResult, finite_key_length
from certiqs_sim.postprocessing.pipeline import (
    PostProcessingConfig,
    PostProcessingResult,
    PostProcessor,
)
from certiqs_sim.postprocessing.privacy_amplification import generate_toeplitz, toeplitz_hash
from certiqs_sim.postprocessing.qber import QberEstimate, estimate_qber
from certiqs_sim.postprocessing.sifting import SiftingAudit, audit_sifted_block

__all__ = [
    "CascadeResult",
    "FiniteKeyResult",
    "PostProcessingConfig",
    "PostProcessingResult",
    "PostProcessor",
    "QberEstimate",
    "SiftingAudit",
    "audit_sifted_block",
    "cascade_correct",
    "ec_leakage_bits",
    "estimate_qber",
    "finite_key_length",
    "generate_toeplitz",
    "toeplitz_hash",
]
