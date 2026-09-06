"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/params/catalog.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

§7.1 Simulation-parameter catalog.

Declarative registry of every promptable physical simulation parameter. Ranges
are grounded ENGINEERING ENVELOPES from published QKD / telecom hardware — NOT
vendor guarantees, which is why out-of-SOFT-range is a warning (not a failure):
a real device may legitimately sit near an edge. Only params a QSecDB system is
unlikely to already carry are `required` (and thus prompted); structural design
choices (crystal_type, bell_state, ...) are validated but never prompted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ParamType = Literal["number", "integer", "enum", "boolean", "ratio_array", "nullable_number"]
ParamScope = Literal["instance", "channel", "protocol", "post_processing"]


@dataclass
class ParamSpec:
    scope: ParamScope
    # component-type slug (instance) · channel type (channel) · stage name (post_processing) · "" (protocol).
    applies_to: str
    field: str  # manifest field name emitted into the YAML
    type: ParamType
    typical: float | str | bool | None
    required: bool
    description: str
    source: str
    db_key: str | None = None  # DB settings key the existing value is read from (instance scope); defaults to `field`
    path: str | None = None  # dotted path within the protocol block (protocol scope)
    unit: str | None = None
    hard_min: float | None = None
    hard_max: float | None = None
    soft_min: float | None = None
    soft_max: float | None = None
    enum_values: list[str] | None = None


# Component-type slugs (slugify of component_types.name).
_DETECTOR = "single_photon_detector"
_SPDC_SRC = "entangled_photon_source"
_PBS = "polarisation_component"

PARAM_CATALOG: list[ParamSpec] = [
    # ── Detector ──────────────────────────────────────────────────────────────
    ParamSpec(
        scope="instance", applies_to=_DETECTOR, field="efficiency", db_key="detection_efficiency",
        type="number", hard_min=0, hard_max=1, soft_min=0.02, soft_max=0.98, typical=0.8, required=True,
        description="Detection efficiency — probability of a click given an incident photon.",
        source="InGaAs/InP APD ~0.05-0.55, Si APD <=~0.76, SNSPD ~0.6-0.98 (NIST; arXiv:1412.1586)",
    ),
    ParamSpec(
        scope="instance", applies_to=_DETECTOR, field="dark_count_hz", db_key="dark_count_rate",
        type="number", hard_min=0, hard_max=1e7, soft_min=1e-3, soft_max=1e5, typical=100, required=True, unit="Hz",
        description="Dark-count rate — spurious clicks with no incident photon.",
        source="SNSPD <1e-3/s, Si APD ~50-100 Hz, free-running InGaAs 1e3-1e5 (NIST pub 32694)",
    ),
    ParamSpec(
        # No db_key: the DB stores `timing_jitter` in SECONDS whereas this manifest field
        # is in picoseconds — auto-reading the seconds value would validate it against a
        # ps range and mislabel it. Left un-mapped so it only checks an explicit ps value.
        scope="instance", applies_to=_DETECTOR, field="jitter_ps_rms",
        type="number", hard_min=0, hard_max=5000, soft_min=1, soft_max=1000, typical=50, required=False, unit="ps",
        description="Timing jitter (RMS) of the registered arrival time.",
        source="SNSPD <3 ps, Si APD best ~20 ps, APD tens-hundreds ps (NIST)",
    ),
    ParamSpec(
        scope="instance", applies_to=_DETECTOR, field="afterpulse_prob", db_key="afterpulse_probability",
        type="number", hard_min=0, hard_max=1, soft_min=0, soft_max=0.15, typical=0.01, required=False,
        description="Afterpulse probability from charge trapping after a prior detection.",
        source="SNSPD ~0; cooled Si APD <0.35%; GHz InGaAs ~7-10% (arXiv:2007.12768, 1412.1586)",
    ),
    # ── SPDC entangled source ──────────────────────────────────────────────────
    ParamSpec(
        scope="instance", applies_to=_SPDC_SRC, field="pair_generation_probability_per_pulse",
        type="number", hard_min=0, hard_max=1, soft_min=1e-4, soft_max=0.1, typical=0.01, required=True,
        description="Pair-generation probability per pump pulse (keep <=0.1 so multi-pair emission stays negligible).",
        source="arXiv:1409.3025, 0710.5390",
    ),
    ParamSpec(
        scope="instance", applies_to=_SPDC_SRC, field="intrinsic_visibility",
        type="number", hard_min=0, hard_max=1, soft_min=0.8, soft_max=0.999, typical=0.97, required=True,
        description="Intrinsic two-photon interference visibility of the source.",
        source="arXiv:2204.10571 (>0.97 typical locally)",
    ),
    # ── Polarising beam splitter (basis analyzer) ──────────────────────────────
    ParamSpec(
        scope="instance", applies_to=_PBS, field="extinction_ratio_db", db_key="extinction_ratio",
        type="number", hard_min=0, hard_max=60, soft_min=15, soft_max=40, typical=25, required=False, unit="dB",
        description="Polarising-beamsplitter extinction ratio.",
        source="commodity PBS range",
    ),
    ParamSpec(
        scope="instance", applies_to=_PBS, field="polarization_leakage_prob",
        type="number", hard_min=0, hard_max=0.5, soft_min=0, soft_max=0.05, typical=0.003, required=False,
        description="Polarisation leakage probability from finite extinction (QBER contribution).",
        source="finite extinction -> QBER contribution",
    ),
    # ── Quantum channel (fibre) ────────────────────────────────────────────────
    ParamSpec(
        scope="channel", applies_to="quantum", field="attenuation_db_per_km",
        type="number", hard_min=0, hard_max=5, soft_min=0.15, soft_max=0.4, typical=0.2, required=True, unit="dB/km",
        description="Fibre attenuation at the operating wavelength.",
        source="G.652.D SMF ~0.18-0.25 dB/km @1550 nm (ITU-T G.652)",
    ),
    ParamSpec(
        scope="channel", applies_to="quantum", field="pmd_ps",
        type="number", hard_min=0, hard_max=1000, soft_min=0, soft_max=100, typical=5, required=False, unit="ps",
        description="Polarisation-mode dispersion of the fibre span.",
        source="G.652.D PMD <=0.20 ps/sqrt(km) (arXiv:1903.12260)",
    ),
    # ── Post-processing (error correction) ─────────────────────────────────────
    ParamSpec(
        scope="post_processing", applies_to="Error Correction", field="code_rate",
        type="number", hard_min=0, hard_max=1, soft_min=0.4, soft_max=0.95, typical=0.85, required=True,
        description="LDPC reconciliation code rate (efficiency vs QBER).",
        source="reconciliation efficiency vs QBER",
    ),
    # ── Protocol (coincidence window) ──────────────────────────────────────────
    ParamSpec(
        scope="protocol", applies_to="", field="window_ps", path="coincidence.window_ps",
        type="number", hard_min=1, hard_max=1e6, soft_min=100, soft_max=5000, typical=1000, required=False, unit="ps",
        description="Coincidence window — accidentals vs true-pair trade-off.",
        source="accidentals vs true-pair trade-off",
    ),
]


@dataclass
class StructuralRule:
    """Structural cross-field rule: gated detectors must declare a non-null gate width."""

    applies_to: str  # component slug
    when: str  # settings key
    equals: object
    require_non_null: str  # settings key that must then be non-null
    message: str


STRUCTURAL_RULES: list[StructuralRule] = [
    StructuralRule(
        applies_to=_DETECTOR, when="detector_variant", equals="APD (gated)", require_non_null="gate_width",
        message='detector_variant "APD (gated)" requires a non-null gate_width',
    ),
]
