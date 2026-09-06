"""The applicability rules engine — sole implementation (the TypeScript oracle
this was originally ported from has been retired; see docs/APPLICABILITY_ENGINE_METHODOLOGY.md).

Purely calculated by technical scope match (encoding / protocol family / protocol /
module type / component type the system actually has) AND behavioral conditions
(decoy state, detector type, ...). Attack rating is currently FIXED metadata.

Stage 2 of the pipeline: pure computation, no DB access. Stage 1 (the relational
read that builds SystemFeatures) lives in get_system_features.py.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal

from app.core.camel_model import CamelModel
from app.qkd.attack_enums import parse_module_field

logger = logging.getLogger(__name__)


# ── Types ─────────────────────────────────────────────────────────────────────


class ComponentPlacement(CamelModel):
    module_type_id: int
    component_type_id: int


class SystemFeatures(CamelModel):
    # Derived from the relational model (what the system actually contains).
    protocol_ids: list[int]
    protocol_family_ids: list[int]
    protocol_names: list[str]
    module_type_ids: list[int]
    component_type_ids: list[int]
    # Per-instance (module, component) pairs — lets row_matches() confirm a shared
    # component (e.g. Beam Splitter, Phase Modulator) is installed in the specific
    # module a scope row requires, rather than treating "has that module" and "has
    # that component" as independent facts.
    component_placements: list[ComponentPlacement]
    # Behavioral / detector profile columns on `systems` (None = unknown).
    double_click_handling: str | None = None
    basis_choice: str | None = None
    detector_types: list[str] | None = None
    deployment: str | None = None
    detector_accepts_clicks_outside_gate: bool | None = None
    optical_path_direction: str | None = None
    source_type: str | None = None
    local_oscillator_type: str | None = None
    phase_randomisation_method: str | None = None
    reconciliation_algorithm: str | None = None
    # Derived from component type presence (not stored in DB).
    has_intensity_monitor: bool | None = None
    # Derived from system_countermeasures: true when "Decoy State Protocol" is installed.
    has_decoy_countermeasure: bool | None = None
    # Encoding and architecture derived from protocol chain
    # (protocol_families.encoding_id/architecture_id).
    # "PM" | "MDI" | "EB" | None — used for domain exclusion rules (MDI receiver, EB transmitter).
    architecture: str | None = None
    # Every distinct protocol_families.encoding_id the system's protocols resolve
    # to — used in row_matches to check encoding scope. A LIST, not a scalar: a
    # system may carry both a DV and a CV protocol, and encoding is now the primary
    # scope axis on nearly every vulnerability, so collapsing to one value would
    # silently drop the other half of the catalogue into `no_scope_match`.
    encoding_ids: list[int] = []


class ScopeRow(CamelModel):
    protocol_family_id: int | None = None
    protocol_id: int | None = None
    module_type_id: int | None = None
    component_type_id: int | None = None
    # Encoding-level scope: None = wildcard (DV and CV); non-None restricts to one encoding.
    encoding_id: int | None = None
    # When true this row is a cross-protocol-family "secondary" row: the vulnerability is
    # documented primarily for another family but the BSI report notes possible extension.
    # Matches via these rows route to cross_family_unknown, not applicable.
    cross_family_uncertain: bool = False
    # When true, the EB/MDI architecture exclusion is bypassed for this row.
    architecture_exclusion_override: bool = False
    # Display names (joined in by the route; ignored by matching).
    protocol_family_name: str | None = None
    protocol_name: str | None = None
    module_type_name: str | None = None
    component_type_name: str | None = None


CondType = Literal["flagEquals", "flagNotEquals", "setIntersects", "numericGte", "numericLte"]


class Condition(CamelModel):
    cond_type: CondType
    path: str  # systems feature column name, e.g. "basis_choice"
    value_bool: bool | None = None
    value_text: str | None = None
    value_num: float | None = None
    values_text: list[str] | None = None


class VulnRecord(CamelModel):
    vulnerability_id: int
    name: str
    short_description: str | None = None
    category: str | None = None
    attack_rating: str | None = None
    scope: list[ScopeRow]
    conditions: list[Condition]
    module: str | None = None
    component: str | None = None


class ApplicableVulnerability(CamelModel):
    vulnerability_id: int
    name: str
    short_description: str | None
    category: str | None
    attack_rating: str | None
    module: str | None
    component: str | None
    matched_protocols: list[str]
    matched_components: list[str]
    matched_conditions: list[str]


class UnevaluatedVulnerability(CamelModel):
    vulnerability_id: int
    name: str
    missing: list[str]  # feature paths the system is missing data for


# Vulnerabilities that matched scope only via cross-family-uncertain rows.
# Conditions were checked and passed, but the protocol family is not the primary one
# documented in the BSI report — applicability is uncertain.
class CrossFamilyUnknownVulnerability(CamelModel):
    vulnerability_id: int
    name: str
    short_description: str | None
    category: str | None
    attack_rating: str | None
    module: str | None
    matched_protocols: list[str]
    matched_components: list[str]


# Vulnerabilities excluded by a hard domain rule (e.g. receiver attacks on MDI systems).
# These are surfaced so auditors know which attacks were considered and why they were excluded.
class ExcludedVulnerability(CamelModel):
    vulnerability_id: int
    name: str
    attack_rating: str | None
    reason: str


# Vulnerabilities that matched no scope row for this system — silently dropped before,
# now surfaced for whitebox testing / debugging.
class NoScopeMatchVulnerability(CamelModel):
    vulnerability_id: int
    name: str
    short_description: str | None
    attack_rating: str | None
    module: str | None
    component: str | None


# Vulnerabilities that matched scope, had all condition data present, but a behavioral
# condition evaluated to false (as opposed to "missing", which routes to unevaluated).
# Surfaces which condition failed so the UI can attribute it to a specific what-if toggle.
class ConditionFailedVulnerability(CamelModel):
    vulnerability_id: int
    name: str
    attack_rating: str | None
    reason: str  # human-readable, from describe_condition()
    failed_path: str  # raw condition path, e.g. "double_click_handling"


class EvaluationResult(CamelModel):
    applicable: list[ApplicableVulnerability]
    unevaluated: list[UnevaluatedVulnerability]
    cross_family_unknown: list[CrossFamilyUnknownVulnerability]
    excluded: list[ExcludedVulnerability]
    no_scope_match: list[NoScopeMatchVulnerability]
    conditions_failed: list[ConditionFailedVulnerability]


# Map a stored condition `path` (snake_case column name) to a SystemFeatures field.
# In the TS source this bridges snake_case DB paths to camelCase JS field names
# (e.g. "double_click_handling" -> "doubleClickHandling"); every Python attribute
# below is already snake_case, so each entry happens to be a no-op here. Kept
# explicit anyway so this stays line-for-line auditable against applicability.ts
# and so a future path that genuinely needs remapping has an obvious place to go.
PATH_TO_FIELD: dict[str, str] = {
    "double_click_handling": "double_click_handling",
    "basis_choice": "basis_choice",
    "detector_types": "detector_types",
    "deployment": "deployment",
    "detector_accepts_clicks_outside_gate": "detector_accepts_clicks_outside_gate",
    "optical_path_direction": "optical_path_direction",
    "source_type": "source_type",
    "local_oscillator_type": "local_oscillator_type",
    "phase_randomisation_method": "phase_randomisation_method",
    "reconciliation_algorithm": "reconciliation_algorithm",
    "has_intensity_monitor": "has_intensity_monitor",
    "has_decoy_countermeasure": "has_decoy_countermeasure",
}


def resolve_feature(features: SystemFeatures, path: str) -> object:
    attr = PATH_TO_FIELD.get(path, path)
    return getattr(features, attr, None)


def is_missing(v: object) -> bool:
    return v is None or (isinstance(v, list) and len(v) == 0)


# ── JS-parity helpers ─────────────────────────────────────────────────────────
# describe_condition()/evaluate_condition() replicate specific JS runtime
# semantics (??, ===, String(), Number()) that Python's own operators don't
# match by default — see the docstring on each helper for the exact divergence.


def _first_not_none(*values: object) -> object:
    """Mirrors JS `a ?? b ?? c`: first operand that isn't null/undefined,
    unlike Python `or`, which would also skip falsy-but-present values like
    `False` or `0`."""
    for v in values:
        if v is not None:
            return v
    return None


def _js_str(value: object) -> str:
    """Mirrors JS template-literal stringification: `String(null)` is "null"
    (not Python's "None"), booleans are lowercase, and a mathematically
    integral float loses its trailing ".0" (JS has one numeric type)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _strict_eq(a: object, b: object) -> bool:
    """Mirrors JS `===`: unlike Python's `==`, `True != 1` and `False != 0`."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _js_number(value: object) -> float:
    """Mirrors JS `Number(value)` for the value shapes that can actually reach
    here. Only called from evaluate_condition() on values that already passed
    is_missing() upstream, so None/undefined never reach this function —
    the null-vs-undefined coercion difference (Number(null)=0 vs
    Number(undefined)=NaN) is therefore not a case that occurs in practice."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return 0.0
        try:
            return float(stripped)
        except ValueError:
            return math.nan
    if isinstance(value, list) and len(value) == 1:
        return _js_number(value[0])
    return math.nan


# ── Scope matching ────────────────────────────────────────────────────────────
# Primary rows (cross_family_uncertain falsy) are tested first.
# Cross-family rows are only consulted when no primary row matched.
# Within each group: OR across rows, AND within a row, None dimension = wildcard.
# Zero scope rows total = system-wide (always matches, primary path).


def row_matches(features: SystemFeatures, row: ScopeRow) -> bool:
    if row.encoding_id is not None and row.encoding_id not in features.encoding_ids:
        return False
    if row.protocol_family_id is not None and row.protocol_family_id not in features.protocol_family_ids:
        return False
    if row.protocol_id is not None and row.protocol_id not in features.protocol_ids:
        return False

    if row.module_type_id is not None and row.component_type_id is not None:
        # Both dimensions given: a shared (module-agnostic) component type must
        # actually be installed in the required module — "system has an RX
        # module" and "system has a Beam Splitter somewhere" are not sufficient
        # on their own (docs/COMPONENT_MODULE_PLACEMENT.md, Rule 3).
        installed_in_module = any(
            p.module_type_id == row.module_type_id and p.component_type_id == row.component_type_id
            for p in features.component_placements
        )
        if not installed_in_module:
            return False
    else:
        if row.module_type_id is not None and row.module_type_id not in features.module_type_ids:
            return False
        if row.component_type_id is not None and row.component_type_id not in features.component_type_ids:
            return False
    return True


_SYSTEM_WIDE_LABEL = "system-wide"


def extract_labels(rows: list[ScopeRow]) -> tuple[list[str], list[str]]:
    protocols: dict[str, None] = {}
    components: dict[str, None] = {}
    for r in rows:
        if r.protocol_name:
            protocols[r.protocol_name] = None
        if r.protocol_family_name:
            protocols[r.protocol_family_name] = None
        if r.component_type_name:
            components[r.component_type_name] = None
        if r.module_type_name:
            components[r.module_type_name] = None
    return list(protocols), list(components)


def _component_labels(rows: list[ScopeRow]) -> tuple[list[str], list[str]]:
    """extract_labels, but a match that pins no module and no component still
    gets the "system-wide" chip the UI renders. A vulnerability like
    "Hardware-software Trojans" is scoped by a row whose module/component
    columns are both NULL (it owns a real row so it can be encoding-scoped and
    can carry an architecture override), and without this it would render with
    an empty matched-components list instead."""
    protocols, components = extract_labels(rows)
    return protocols, components or [_SYSTEM_WIDE_LABEL]


@dataclass
class ScopeMatch:
    matched: bool
    protocols: list[str]
    components: list[str]
    is_cross_family: bool
    matched_rows: list[ScopeRow] = field(default_factory=list)


def scope_matches(features: SystemFeatures, scope: list[ScopeRow]) -> ScopeMatch:
    if len(scope) == 0:
        return ScopeMatch(matched=True, protocols=[], components=[_SYSTEM_WIDE_LABEL], is_cross_family=False)

    # Primary rows first.
    primary_rows = [r for r in scope if not r.cross_family_uncertain]
    matched_primary = [r for r in primary_rows if row_matches(features, r)]
    if matched_primary:
        protocols, components = _component_labels(matched_primary)
        return ScopeMatch(
            matched=True, protocols=protocols, components=components,
            is_cross_family=False, matched_rows=matched_primary,
        )

    # Fall back to cross-family rows only if no primary row matched.
    cross_rows = [r for r in scope if r.cross_family_uncertain]
    matched_cross = [r for r in cross_rows if row_matches(features, r)]
    if matched_cross:
        protocols, components = _component_labels(matched_cross)
        return ScopeMatch(
            matched=True, protocols=protocols, components=components,
            is_cross_family=True, matched_rows=matched_cross,
        )

    return ScopeMatch(matched=False, protocols=[], components=[], is_cross_family=False)


# ── Condition evaluation ────────────────────────────────────────────────────────


def describe_condition(cond: Condition) -> str:
    if cond.cond_type == "flagEquals":
        expected = _first_not_none(cond.value_bool, cond.value_text, cond.value_num)
        return f"{cond.path} = {_js_str(expected)}"
    if cond.cond_type == "flagNotEquals":
        expected = _first_not_none(cond.value_bool, cond.value_text, cond.value_num)
        return f"{cond.path} ≠ {_js_str(expected)}"
    if cond.cond_type == "setIntersects":
        values = cond.values_text or []
        return f"{cond.path} ∋ {{{', '.join(values)}}}"
    if cond.cond_type == "numericGte":
        return f"{cond.path} ≥ {_js_str(cond.value_num)}"
    if cond.cond_type == "numericLte":
        return f"{cond.path} ≤ {_js_str(cond.value_num)}"
    return cond.path


def evaluate_condition(features: SystemFeatures, cond: Condition) -> bool:
    value = resolve_feature(features, cond.path)
    if cond.cond_type == "flagEquals":
        expected = _first_not_none(cond.value_bool, cond.value_text, cond.value_num)
        return _strict_eq(value, expected)
    if cond.cond_type == "flagNotEquals":
        expected = _first_not_none(cond.value_bool, cond.value_text, cond.value_num)
        return not _strict_eq(value, expected)
    if cond.cond_type == "setIntersects":
        if not isinstance(value, list):
            return False
        want = cond.values_text or []
        return any(w in value for w in want)
    if cond.cond_type == "numericGte":
        n = _js_number(value)
        return not math.isnan(n) and cond.value_num is not None and n >= _js_number(cond.value_num)
    if cond.cond_type == "numericLte":
        n = _js_number(value)
        return not math.isnan(n) and cond.value_num is not None and n <= _js_number(cond.value_num)
    return False


# ── Detector-type derivation from component-level data ───────────────────────
# Maps the stored `detector_variant` setting (from Single-Photon Detector spec)
# and bare component-type names to the canonical detector_types strings the
# applicability engine understands.
#
# An APD is described by TWO independent axes and the BSI catalogue attacks each
# of them separately:
#   gating    — "gated-APD" vs "free-running-APD"   (BSI 4.13 vs 4.6/4.17)
#   quenching — "actively-quenched-APD" vs "passively-quenched-APD"  (BSI 4.14 vs 4.12)
# A variant string therefore maps to a TUPLE of tags, one per axis it pins down.
# When a variant leaves the quenching axis unspecified — as plain
# "APD (free-running)" does — BOTH quenching tags are emitted, because a real APD
# is always one or the other and we cannot tell which: the operator should see
# both candidate attacks rather than silently neither.
# Gating is not expanded that way: "APD (gated)" pins gating explicitly, and a
# gated APD is quenched by its gate, which BSI 4.13 already covers as its own attack.

VARIANT_TO_DET_TYPE: dict[str, tuple[str, ...]] = {
    # Gated APD — gating pinned, quenching moot (the gate does the quenching).
    "APD (gated)": ("gated-APD",),
    "Gated APD": ("gated-APD",),
    "Gated mode APD": ("gated-APD",),
    "Avalanche Photodiode (gated)": ("gated-APD",),
    # Free-running APD, quenching mode NOT stated — emit both quenching tags.
    "APD (free-running)": ("free-running-APD", "actively-quenched-APD", "passively-quenched-APD"),
    "Free-running APD": ("free-running-APD", "actively-quenched-APD", "passively-quenched-APD"),
    # Free-running APD, passively quenched. BSI Table 4.12's subcomponent is
    # "Passively-quenched or negative-feedback APD", so negative feedback lands here.
    "APD (free-running, passively quenched)": ("free-running-APD", "passively-quenched-APD"),
    "Passively quenched APD": ("free-running-APD", "passively-quenched-APD"),
    "Negative feedback APD": ("free-running-APD", "passively-quenched-APD"),
    # Free-running APD, actively quenched. BSI 4.17 describes actively-quenched
    # APDs as a free-running sub-case, hence both tags.
    "APD (free-running, actively quenched)": ("free-running-APD", "actively-quenched-APD"),
    "APD (actively quenched)": ("free-running-APD", "actively-quenched-APD"),
    "Actively quenched APD": ("free-running-APD", "actively-quenched-APD"),
    # Self-differencing APD
    "SD APD": ("SD-APD",),
    "Self-differencing APD": ("SD-APD",),
    # SNSPD
    "SNSPD": ("SNSPD",),
    "Superconducting nanowire single-photon detector": ("SNSPD",),
    # TES
    "TES": ("TES",),
    "Transition-edge sensor": ("TES",),
    "Transition Edge Sensor": ("TES",),
    # CV-QKD coherent receivers
    "Homodyne detector": ("homodyne",),
    "Balanced homodyne detector": ("homodyne",),
    "Heterodyne detector": ("heterodyne",),
    "Dual quadrature detector": ("heterodyne",),
}

# Bare component types (no detector_variant set) that still pin their axis down
# well enough to tag. "Coherent Detector" is here because its three tags are not
# in conflict: every seeded CV condition accepts any of them (BSI 4.55 asks only
# for "a coherent receiver"), so emitting all three states "some coherent
# detection scheme", not "all three schemes at once".
COMP_TYPE_TO_DET_TYPE: dict[str, tuple[str, ...]] = {
    "Coherent Detector": ("coherent", "homodyne", "heterodyne"),
}

# Component types that pin NOTHING down on their own. The legacy "Avalanche
# Photon Detector" type is the whole set: its four candidate tags (gated /
# free-running / actively-quenched / passively-quenched) are mutually exclusive,
# and emitting them all made four contradictory detector-control attacks —
# BSI 4.12, 4.13, 4.14, 4.17 — report as confirmed-applicable simultaneously on
# one physical detector. So contribute no tag at all: with nothing else to go on
# the system's detector_types stays empty, which routes every detector-gated
# vulnerability to `unevaluated` ("we don't know") rather than to a false
# positive. Setting `detector_variant` on the component resolves it.
UNRESOLVED_DETECTOR_COMP_TYPES = frozenset({"Avalanche Photon Detector"})


class DetectorRow(CamelModel):
    variant_value: str | None
    component_type: str


def derive_detector_types(rows: list[DetectorRow]) -> list[str] | None:
    """Derive a `detector_types` string list from the detector components the
    system actually contains. Input rows come from a JOIN of module_components
    -> components -> component_types, LEFT-JOINed with the `detector_variant`
    component_parameter row (None if not set).

    Returns None when the system has no recognised detector components at all
    (keeps the applicability engine in "unevaluated" mode rather than hiding
    any condition that tests detector_types).
    """
    types: dict[str, None] = {}

    def add(tags: tuple[str, ...]) -> None:
        for tag in tags:
            types[tag] = None

    for row in rows:
        variant_value, component_type = row.variant_value, row.component_type

        # An explicit variant wins for EVERY component type, not just
        # Single-Photon Detector. Checking the component type first would silently
        # discard a detector_variant stored on a legacy "Avalanche Photon Detector"
        # or "Coherent Detector" row — the most specific fact we have about it.
        if variant_value and variant_value in VARIANT_TO_DET_TYPE:
            add(VARIANT_TO_DET_TYPE[variant_value])
            continue

        if variant_value:
            logger.warning(
                '[applicability] Unknown detector_variant: "%s" - add it to VARIANT_TO_DET_TYPE',
                variant_value,
            )

        if component_type in COMP_TYPE_TO_DET_TYPE:
            add(COMP_TYPE_TO_DET_TYPE[component_type])
        elif component_type == "Single-Photon Detector":
            # A bare SPD is not necessarily an APD (it could be an SNSPD/TES), so
            # it claims only the generic tag.
            types["SPD"] = None
        elif component_type in UNRESOLVED_DETECTOR_COMP_TYPES:
            logger.warning(
                '[applicability] "%s" component has no detector_variant set - its detector-'
                "control vulnerabilities will report as unevaluated until one is chosen",
                component_type,
            )
    return list(types) if types else None


# ── Component synonym normalization ──────────────────────────────────────────
# Maps lowercase free-text values from attacks.component -> canonical component_types.name.
# A value may be a single string or a list for one-to-many expansion (e.g. generic
# "detector" expands to both SPD and APD so it appears under either filter chip).
COMPONENT_SYNONYMS: dict[str, str | list[str]] = {
    # -> Single-Photon Detector (SNSPD, generic SPD)
    "single photon detector": "Single-Photon Detector",
    "single-photon detector": "Single-Photon Detector",
    "spd": "Single-Photon Detector",
    "snspd": "Single-Photon Detector",
    "superconducting nanowire single-photon detector": "Single-Photon Detector",
    "superconducting nanowire single photon detector": "Single-Photon Detector",
    # -> Avalanche Photon Detector (APD subtypes)
    "apd": "Avalanche Photon Detector",
    "avalanche photodiode": "Avalanche Photon Detector",
    "avalanche photon detector": "Avalanche Photon Detector",
    "gated apd": "Avalanche Photon Detector",
    "passively-quenched or negative-feedback apd": "Avalanche Photon Detector",
    "actively-quenched apd": "Avalanche Photon Detector",
    "self-differencing apd": "Avalanche Photon Detector",
    # -> both SPD and APD — generic detection terms that cover either detector type
    "detector module": ["Single-Photon Detector", "Avalanche Photon Detector"],
    "detection module": ["Single-Photon Detector", "Avalanche Photon Detector"],
    "detector": ["Single-Photon Detector", "Avalanche Photon Detector"],
    "photodiode": ["Single-Photon Detector", "Avalanche Photon Detector"],
    # -> Coherent Detector
    "coherent detector": "Coherent Detector",
    "homodyne detector": "Coherent Detector",
    "heterodyne detector": "Coherent Detector",
    "balanced detector": "Coherent Detector",
    # BSI 4.55's subcomponent line reads "Balanced homodyne detector, beamsplitter"
    "balanced homodyne detector": "Coherent Detector",
    "dc balancing": "Coherent Detector",
    "lo monitor": "Injected Light Monitor",
    "local oscillator monitor": "Injected Light Monitor",
    # -> Laser Source
    "laser": "Laser Source",
    "laser source": "Laser Source",
    "laser diode": "Laser Source",
    "light source": "Laser Source",
    "photon source": "Laser Source",
    "pulsed laser": "Laser Source",
    "cw laser": "Laser Source",
    "attenuated laser": "Laser Source",
    # -> Phase Modulator
    "phase modulator": "Phase Modulator",
    "pm": "Phase Modulator",
    # -> Intensity Modulator
    "intensity modulator": "Intensity Modulator",
    "im": "Intensity Modulator",
    # -> both Phase Modulator and Intensity Modulator — generic modulator terms
    "optical modulator": ["Phase Modulator", "Intensity Modulator"],
    "quadrature modulator": ["Phase Modulator", "Intensity Modulator"],
    # BSI 4.54's subcomponent line — the Gaussian modulator is an amplitude+phase pair
    "modulation system": ["Phase Modulator", "Intensity Modulator"],
    # -> Attenuator
    "voa": "Attenuator",
    "variable optical attenuator": "Attenuator",
    "attenuator": "Attenuator",
    # -> Beam Splitter
    "beam splitter": "Beam Splitter",
    "beamsplitter": "Beam Splitter",
    "bs": "Beam Splitter",
    "fiber coupler": "Beam Splitter",
    "fibre coupler": "Beam Splitter",
    # -> Polarisation Component
    "polariser": "Polarisation Component",
    "polarizer": "Polarisation Component",
    "polarisation component": "Polarisation Component",
    "polarization component": "Polarisation Component",
    "pbs": "Polarisation Component",
    "polarising beam splitter": "Polarisation Component",
    "polarizing beam splitter": "Polarisation Component",
    # -> Polarization Controller
    "polarisation controller": "Polarization Controller",
    "polarization controller": "Polarization Controller",
    # -> Optical Isolator
    "optical isolator": "Optical Isolator",
    "isolator": "Optical Isolator",
    "faraday isolator": "Optical Isolator",
    "circulator": "Optical Isolator",
    # -> Injected Light Monitor
    "injected light monitor": "Injected Light Monitor",
    "ilm": "Injected Light Monitor",
    # -> Time-Digital Converter
    "time-digital converter": "Time-Digital Converter",
    "time digital converter": "Time-Digital Converter",
    "tdc": "Time-Digital Converter",
    # -> Coincidence Matcher
    "coincidence matcher": "Coincidence Matcher",
    "coincidence logic": "Coincidence Matcher",
    # -> PP software stages (canonical names from pp_component_types; synonyms handle case/typo variants)
    "public announcements": "Public Announcements",
    "error correction": "Error Correction",
    "error verification": "Error Verification",
    "privacy amplification": "Privacy Amplification",
    "privacy amplifcation": "Privacy Amplification",
    "parameter estimation": "Parameter Estimation",
    "sifting": "Sifting",
    "information reconciliation": "Error Correction",
    "reconciliation": "Error Correction",
    # -> all hardware component types — EM radiation leaks from any active hardware element
    "any component emitting electromagnetic radiation": [
        "Laser Source", "Phase Modulator", "Intensity Modulator", "Attenuator",
        "Beam Splitter", "Polarisation Component", "Single-Photon Detector",
        "Avalanche Photon Detector", "Coherent Detector", "Optical Isolator",
        "Time-Digital Converter",
    ],
}


def normalize_component_terms(component: str | None) -> list[str]:
    """Split a comma-separated attacks.component string and map each term to its
    canonical component_types.name(s). A synonym may expand to multiple names
    (e.g. "detection module" -> SPD + APD). Unknown terms fall back to their
    original value so novel component names still appear in the filter."""
    if not component:
        return []
    result: dict[str, None] = {}
    for raw in component.split(","):
        t = raw.strip()
        if not t:
            continue
        mapped = COMPONENT_SYNONYMS.get(t.lower())
        expanded = mapped if isinstance(mapped, list) else [mapped or t]
        for name in expanded:
            result[name] = None
    return list(result)


# ── Top-level evaluation ──────────────────────────────────────────────────────


def targets_only(module: str | None, wanted: str) -> bool:
    """True when `attacks.module` names `wanted` and nothing else.

    `attacks.module` is free text holding either one canonical module or several
    joined with ", " (see attack_enums.parse_module_field). The architecture
    exclusions must fire only for attacks that target the excluded module
    *exclusively* — "Transmitter, Receiver" still has a receiver half that a
    Transmitter-based exclusion has no business removing.

    An unset or unparseable module excludes nothing (we don't know what it targets).
    Unparseable is logged: the column is hand-maintained (seed-attack-references.ts
    writes multi-token values like "Transmitter, Post-processing"), so a typo there
    would otherwise disable the architecture exclusions with no trace.
    """
    tokens, error = parse_module_field(module)
    if error:
        logger.warning(
            '[applicability] Unparseable attacks.module value "%s" (%s) - architecture '
            "exclusions cannot be applied to it",
            module,
            error,
        )
        return False
    if not tokens:
        return False
    return set(tokens) == {wanted}


def evaluate_applicability(features: SystemFeatures, vulns: list[VulnRecord]) -> EvaluationResult:
    applicable: list[ApplicableVulnerability] = []
    unevaluated: list[UnevaluatedVulnerability] = []
    cross_family_unknown: list[CrossFamilyUnknownVulnerability] = []
    excluded: list[ExcludedVulnerability] = []
    no_scope_match: list[NoScopeMatchVulnerability] = []
    conditions_failed: list[ConditionFailedVulnerability] = []

    # MDI and EB are architecture dimensions derived from protocol_families.architecture_id.
    # None architecture (system has no protocol yet, or legacy) -> no exclusions applied.
    is_mdi = features.architecture == "MDI"
    is_eb = features.architecture == "EB"

    for v in vulns:
        # Scope must match before architecture exclusion — we need matched_rows to check overrides.
        scope = scope_matches(features, v.scope)
        if not scope.matched:
            no_scope_match.append(NoScopeMatchVulnerability(
                vulnerability_id=v.vulnerability_id,
                name=v.name,
                short_description=v.short_description,
                attack_rating=v.attack_rating,
                module=v.module,
                component=v.component,
            ))
            continue

        # MDI: receiver attacks don't apply (measurement device is an untrusted third party).
        # EB: transmitter attacks don't apply (the photon source is an external shared
        # resource — EB systems are source-device-independent), REGARDLESS of which
        # components the transmitter happens to contain.
        #
        # Both rules fire only when the attack targets that module EXCLUSIVELY. An attack
        # listing several modules (e.g. "Transmitter, Receiver" for laser-damage on
        # detectors) keeps applying through its other half.
        if is_mdi and targets_only(v.module, "Receiver"):
            if not any(r.architecture_exclusion_override for r in scope.matched_rows):
                excluded.append(ExcludedVulnerability(
                    vulnerability_id=v.vulnerability_id,
                    name=v.name,
                    attack_rating=v.attack_rating,
                    reason="Receiver attack — not applicable to MDI systems",
                ))
                continue
        if is_eb and targets_only(v.module, "Transmitter"):
            if not any(r.architecture_exclusion_override for r in scope.matched_rows):
                excluded.append(ExcludedVulnerability(
                    vulnerability_id=v.vulnerability_id,
                    name=v.name,
                    attack_rating=v.attack_rating,
                    reason="Transmitter attack — not applicable to EB systems",
                ))
                continue

        # Conditions referencing feature data the system doesn't have -> surface as unevaluated.
        # This applies regardless of whether the match was primary or cross-family.
        missing = [c.path for c in v.conditions if is_missing(resolve_feature(features, c.path))]
        if missing:
            unevaluated.append(UnevaluatedVulnerability(
                vulnerability_id=v.vulnerability_id,
                name=v.name,
                missing=list(dict.fromkeys(missing)),
            ))
            continue

        # Evaluate all conditions.
        matched_conditions: list[str] = []
        failed_condition: Condition | None = None
        for c in v.conditions:
            if evaluate_condition(features, c):
                matched_conditions.append(describe_condition(c))
            else:
                failed_condition = c
                break

        if failed_condition is not None:
            conditions_failed.append(ConditionFailedVulnerability(
                vulnerability_id=v.vulnerability_id,
                name=v.name,
                attack_rating=v.attack_rating,
                reason=describe_condition(failed_condition),
                failed_path=failed_condition.path,
            ))
            continue

        # Route to cross_family_unknown when the scope match was achieved only via
        # cross-family rows.
        if scope.is_cross_family:
            cross_family_unknown.append(CrossFamilyUnknownVulnerability(
                vulnerability_id=v.vulnerability_id,
                name=v.name,
                short_description=v.short_description,
                category=v.category,
                attack_rating=v.attack_rating,
                module=v.module,
                matched_protocols=scope.protocols,
                matched_components=scope.components,
            ))
            continue

        applicable.append(ApplicableVulnerability(
            vulnerability_id=v.vulnerability_id,
            name=v.name,
            short_description=v.short_description,
            category=v.category,
            attack_rating=v.attack_rating,
            module=v.module,
            component=v.component,
            matched_protocols=scope.protocols,
            matched_components=scope.components,
            matched_conditions=matched_conditions,
        ))

    return EvaluationResult(
        applicable=applicable,
        unevaluated=unevaluated,
        cross_family_unknown=cross_family_unknown,
        excluded=excluded,
        no_scope_match=no_scope_match,
        conditions_failed=conditions_failed,
    )
