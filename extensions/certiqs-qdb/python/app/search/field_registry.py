"""Canonical list of searchable fields for each advanced-search domain (formerly
a line-by-line port of src/lib/search/fieldRegistry.ts, which has since been
retired — this is now the sole source of truth; the field-picker UI reads it
via the /internal/search/fields metadata endpoint).

Each field describes how it resolves to SQL: "direct" fields sit on the
domain's base query; "exists" fields live behind a correlated EXISTS subquery
grouped by ExistsFamily (see compile.py for the actual join chains and
compilation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Column

from app.schema.attacks import attack_categories, attacks, vulnerabilities
from app.schema.countermeasures import countermeasures, vulnerability_countermeasures
from app.schema.evaluation_activities import ea_parameters, evaluation_activities
from app.schema.joins import ea_covers_attack
from app.schema.systems import protocol_families, protocols, system_protocols, systems
from app.search import enums
from app.search.types import FieldType, SearchDomain

ExistsFamily = Literal[
    "ea_coverage",
    "countermeasure_coverage",
    "protocol",
    "parameters",
    "covers_attack",
    "vulnerability_coverage",
]


@dataclass
class FieldOptions:
    kind: Literal["static", "lookup"]
    values: tuple[str, ...] | None = None
    url: str | None = None
    value_key: str | None = None
    label_key: str | None = None


@dataclass
class FieldDef:
    key: str
    label: str
    group: str
    type: FieldType
    nullable: bool
    resolution: Literal["direct", "exists", "aggregate"]
    column: Column | None = None
    family: ExistsFamily | None = None
    csv_multi_value: bool = False
    pg_array_type: Literal["integer", "text"] | None = None  # required for type "array"; compiler defaults to "text"
    options: FieldOptions | None = None

    def __post_init__(self) -> None:
        if self.resolution in ("exists", "aggregate") and self.family is None:
            raise AssertionError(f"{self.key}: resolution={self.resolution!r} requires a family")
        if self.resolution == "aggregate" and self.column is not None:
            raise AssertionError(f"{self.key}: resolution='aggregate' fields must not set column")


def _static_options(values: tuple[str, ...]) -> FieldOptions:
    return FieldOptions(kind="static", values=values)


# Default value_key is "name" because most lookup-backed fields filter directly
# against a text/name column (e.g. attacks.component, attack_categories.name,
# protocols.name) rather than a numeric FK — pass value_key="id" explicitly for
# the rare field (cm_component_types) that stores a real integer FK array.
def _lookup_options(url: str, value_key: str = "name", label_key: str = "name") -> FieldOptions:
    return FieldOptions(kind="lookup", url=url, value_key=value_key, label_key=label_key)


# ── Attacks / Vulnerabilities ──────────────────────────────────────────────
# Base: vulnerabilities LEFT JOIN attacks LEFT JOIN attack_categories. Key: vulnerabilities.id.
_ATTACKS_FIELDS: list[FieldDef] = [
    FieldDef("vuln_name", "Vulnerability Name", "Vulnerability", "text", False, "direct", vulnerabilities.c.name),
    FieldDef("vuln_description", "Description", "Vulnerability", "text", True, "direct", vulnerabilities.c.short_description),
    FieldDef("attack_module", "Module", "Attack", "enum", True, "direct", attacks.c.module, csv_multi_value=True, options=_static_options(enums.MODULES)),
    FieldDef("attack_component", "Component", "Attack", "enum", True, "direct", attacks.c.component, csv_multi_value=True, options=_lookup_options("/internal/catalog/component-types")),
    FieldDef("attack_equipment", "Equipment", "Attack", "enum", True, "direct", attacks.c.equipment, options=_static_options(enums.EQUIPMENT_OPTIONS)),
    FieldDef("attack_targets", "Targets", "Attack", "text", True, "direct", attacks.c.targets),
    FieldDef("attack_type", "Attack Type", "Attack", "enum", True, "direct", attacks.c.attack_type, options=_static_options(enums.ATTACK_TYPES)),
    FieldDef("attack_expertise", "Expertise Required", "Attack", "enum", True, "direct", attacks.c.expertise, options=_static_options(enums.EXPERTISE_OPTIONS)),
    FieldDef("attack_knowledge_of_toe", "Knowledge of TOE", "Attack", "text", True, "direct", attacks.c.knowledge_of_toe),
    FieldDef("attack_opportunity", "Opportunity", "Attack", "enum", True, "direct", attacks.c.opportunity, options=_static_options(enums.OPPORTUNITY_OPTIONS)),
    FieldDef("attack_feasibility", "Feasibility", "Attack", "enum", True, "direct", attacks.c.feasibility, options=_static_options(enums.FEASIBILITY_OPTIONS)),
    FieldDef("attack_feasibility_assessment", "Feasibility Assessment", "Attack", "text", True, "direct", attacks.c.feasibility_assessment),
    FieldDef("attack_rating", "Attack Rating", "Attack", "enum", True, "direct", attacks.c.attack_rating, options=_static_options(enums.ATTACK_RATINGS)),
    FieldDef("attack_subclause", "Subclause", "Attack", "text", True, "direct", attacks.c.subclause),
    FieldDef("attack_referenced_from", "Referenced From", "Attack", "text", True, "direct", attacks.c.referenced_from),
    FieldDef("attack_category", "Category", "Attack", "enum", True, "direct", attack_categories.c.name, options=_lookup_options("/internal/catalog/attack-categories")),

    # Exists family: ea_coverage — the "attacks related to EAs with parameter X" example lives here.
    FieldDef("ea_code", "EA Code", "Evaluation Activity Coverage", "text", True, "exists", evaluation_activities.c.code, family="ea_coverage"),
    FieldDef("ea_name", "EA Name", "Evaluation Activity Coverage", "text", True, "exists", evaluation_activities.c.name, family="ea_coverage"),
    FieldDef("ea_description", "EA Description", "Evaluation Activity Coverage", "text", True, "exists", evaluation_activities.c.description, family="ea_coverage"),
    FieldDef("ea_is_iso_mandated", "EA is ISO-mandated", "Evaluation Activity Coverage", "boolean", False, "exists", evaluation_activities.c.is_iso_mandated, family="ea_coverage"),
    FieldDef("ea_coverage_rationale", "Coverage Rationale", "Evaluation Activity Coverage", "text", True, "exists", ea_covers_attack.c.rationale, family="ea_coverage"),
    FieldDef("ea_parameter_name", "EA Parameter Name", "Evaluation Activity Coverage", "text", True, "exists", ea_parameters.c.name, family="ea_coverage"),
    FieldDef("ea_parameter_symbol", "EA Parameter Symbol", "Evaluation Activity Coverage", "text", True, "exists", ea_parameters.c.symbol, family="ea_coverage"),
    FieldDef("ea_parameter_type", "EA Parameter Type", "Evaluation Activity Coverage", "enum", True, "exists", ea_parameters.c.parameter_type, family="ea_coverage", options=_static_options(enums.PARAMETER_TYPES)),
    FieldDef("ea_parameter_description", "EA Parameter Description", "Evaluation Activity Coverage", "text", True, "exists", ea_parameters.c.description, family="ea_coverage"),
    FieldDef("ea_parameter_constraints", "EA Parameter Constraints", "Evaluation Activity Coverage", "text", True, "exists", ea_parameters.c.constraints, family="ea_coverage"),
    FieldDef("ea_coverage_count", "Number of EAs Covering", "Evaluation Activity Coverage", "number", False, "aggregate", None, family="ea_coverage"),

    # Exists family: countermeasure_coverage
    FieldDef("cm_coverage_name", "Countermeasure Name", "Countermeasure Coverage", "text", True, "exists", countermeasures.c.name, family="countermeasure_coverage"),
    FieldDef("cm_coverage_description", "Countermeasure Description", "Countermeasure Coverage", "text", True, "exists", countermeasures.c.description, family="countermeasure_coverage"),
    FieldDef("cm_coverage_type", "Countermeasure Type", "Countermeasure Coverage", "enum", True, "exists", countermeasures.c.countermeasure_type, family="countermeasure_coverage", options=_static_options(enums.COUNTERMEASURE_TYPES)),
    FieldDef("cm_coverage_module", "Countermeasure Module", "Countermeasure Coverage", "enum", True, "exists", countermeasures.c.module, family="countermeasure_coverage", options=_static_options(enums.MODULES)),
    FieldDef("cm_coverage_defense_effectiveness", "Defense Effectiveness", "Countermeasure Coverage", "array", True, "exists", vulnerability_countermeasures.c.defense_effectiveness, family="countermeasure_coverage", pg_array_type="text", options=_static_options(enums.DEFENSE_EFFECTIVENESS)),
    FieldDef("cm_coverage_count", "Number of Countermeasures Covering", "Countermeasure Coverage", "number", False, "aggregate", None, family="countermeasure_coverage"),
]

# ── Systems ─────────────────────────────────────────────────────────────────
# Base: systems only. Key: systems.id.
_SYSTEMS_FIELDS: list[FieldDef] = [
    FieldDef("sys_name", "Name", "System", "text", False, "direct", systems.c.name),
    FieldDef("sys_manufacturer", "Manufacturer", "System", "text", False, "direct", systems.c.manufacturer),
    FieldDef("sys_toe_boundary", "TOE Boundary", "System", "text", True, "direct", systems.c.toe_boundary),
    FieldDef("sys_hardware_revision", "Hardware Revision", "System", "text", True, "direct", systems.c.hardware_revision),
    FieldDef("sys_created_at", "Date Created", "System", "date", False, "direct", systems.c.created_at),
    FieldDef("sys_is_public", "Is Public", "System", "boolean", False, "direct", systems.c.is_public),
    FieldDef("sys_detector_accepts_clicks_outside_gate", "Accepts Clicks Outside Gate", "Behavior Profile", "boolean", True, "direct", systems.c.detector_accepts_clicks_outside_gate),
    FieldDef("sys_double_click_handling", "Double-Click Handling", "Behavior Profile", "enum", True, "direct", systems.c.double_click_handling, options=_static_options(enums.DOUBLE_CLICK_HANDLING)),
    FieldDef("sys_basis_choice", "Basis Choice", "Behavior Profile", "enum", True, "direct", systems.c.basis_choice, options=_static_options(enums.BASIS_CHOICE)),
    FieldDef("sys_deployment", "Deployment", "Behavior Profile", "enum", True, "direct", systems.c.deployment, options=_static_options(enums.DEPLOYMENT)),
    FieldDef("sys_optical_path_direction", "Optical Path Direction", "Behavior Profile", "enum", True, "direct", systems.c.optical_path_direction, options=_static_options(enums.OPTICAL_PATH_DIRECTION)),
    FieldDef("sys_source_type", "Source Type", "Behavior Profile", "text", True, "direct", systems.c.source_type),
    FieldDef("sys_local_oscillator_type", "Local Oscillator Type", "Behavior Profile", "enum", True, "direct", systems.c.local_oscillator_type, options=_static_options(enums.LOCAL_OSCILLATOR_TYPE)),
    FieldDef("sys_phase_randomisation_method", "Phase Randomisation", "Behavior Profile", "enum", True, "direct", systems.c.phase_randomisation_method, options=_static_options(enums.PHASE_RANDOMISATION_METHOD)),
    FieldDef("sys_reconciliation_algorithm", "Reconciliation Algorithm", "Behavior Profile", "enum", True, "direct", systems.c.reconciliation_algorithm, options=_static_options(enums.RECONCILIATION_ALGORITHM)),

    # Exists family: protocol
    FieldDef("sys_protocol_name", "Protocol", "Protocol", "enum", True, "exists", protocols.c.name, family="protocol", options=_lookup_options("/internal/catalog/protocols")),
    FieldDef("sys_protocol_family_name", "Protocol Family", "Protocol", "enum", True, "exists", protocol_families.c.name, family="protocol", options=_lookup_options("/internal/catalog/protocol-families")),
    FieldDef("sys_protocol_is_primary", "Is Primary Protocol", "Protocol", "boolean", False, "exists", system_protocols.c.is_primary, family="protocol"),
    FieldDef("sys_protocol_count", "Number of Protocols", "Protocol", "number", False, "aggregate", None, family="protocol"),
]

# ── Evaluation Activities ───────────────────────────────────────────────────
# Base: evaluation_activities only. Key: evaluation_activities.code.
_EVALUATION_ACTIVITIES_FIELDS: list[FieldDef] = [
    FieldDef("ea_code_direct", "Code", "Evaluation Activity", "text", False, "direct", evaluation_activities.c.code),
    FieldDef("ea_name_direct", "Name", "Evaluation Activity", "text", False, "direct", evaluation_activities.c.name),
    FieldDef("ea_description_direct", "Description", "Evaluation Activity", "text", True, "direct", evaluation_activities.c.description),
    FieldDef("ea_pass_description", "Pass Description", "Evaluation Activity", "text", True, "direct", evaluation_activities.c.pass_description),
    FieldDef("ea_fail_description", "Fail Description", "Evaluation Activity", "text", True, "direct", evaluation_activities.c.fail_description),
    FieldDef("ea_threshold_description", "Threshold Description", "Evaluation Activity", "text", True, "direct", evaluation_activities.c.threshold_description),
    FieldDef("ea_dependencies", "Dependencies", "Evaluation Activity", "text", True, "direct", evaluation_activities.c.dependencies),
    FieldDef("ea_is_iso_mandated_direct", "Is ISO-mandated", "Evaluation Activity", "boolean", False, "direct", evaluation_activities.c.is_iso_mandated),
    FieldDef("ea_subclause", "Subclause", "Evaluation Activity", "text", False, "direct", evaluation_activities.c.subclause),
    FieldDef("ea_referenced_from", "Referenced From", "Evaluation Activity", "text", False, "direct", evaluation_activities.c.referenced_from),

    # Exists family: parameters (this EA's own experimental parameters)
    FieldDef("ea_param_name", "Parameter Name", "Parameters", "text", True, "exists", ea_parameters.c.name, family="parameters"),
    FieldDef("ea_param_symbol", "Parameter Symbol", "Parameters", "text", True, "exists", ea_parameters.c.symbol, family="parameters"),
    FieldDef("ea_param_type", "Parameter Type", "Parameters", "enum", True, "exists", ea_parameters.c.parameter_type, family="parameters", options=_static_options(enums.PARAMETER_TYPES)),
    FieldDef("ea_param_description", "Parameter Description", "Parameters", "text", True, "exists", ea_parameters.c.description, family="parameters"),
    FieldDef("ea_param_constraints", "Parameter Constraints", "Parameters", "text", True, "exists", ea_parameters.c.constraints, family="parameters"),
    FieldDef("ea_param_count", "Number of Parameters", "Parameters", "number", False, "aggregate", None, family="parameters"),

    # Exists family: covers_attack (reverse-lookup — which attacks/vulnerabilities this EA covers)
    FieldDef("ea_covers_vuln_name", "Covered Vulnerability Name", "Attack Coverage", "text", True, "exists", vulnerabilities.c.name, family="covers_attack"),
    FieldDef("ea_covers_vuln_description", "Covered Vulnerability Description", "Attack Coverage", "text", True, "exists", vulnerabilities.c.short_description, family="covers_attack"),
    FieldDef("ea_covers_attack_type", "Covered Attack Type", "Attack Coverage", "enum", True, "exists", attacks.c.attack_type, family="covers_attack", options=_static_options(enums.ATTACK_TYPES)),
    FieldDef("ea_covers_attack_rating", "Covered Attack Rating", "Attack Coverage", "enum", True, "exists", attacks.c.attack_rating, family="covers_attack", options=_static_options(enums.ATTACK_RATINGS)),
    FieldDef("ea_covers_attack_category", "Covered Attack Category", "Attack Coverage", "enum", True, "exists", attack_categories.c.name, family="covers_attack", options=_lookup_options("/internal/catalog/attack-categories")),
    FieldDef("ea_covers_rationale", "Coverage Rationale", "Attack Coverage", "text", True, "exists", ea_covers_attack.c.rationale, family="covers_attack"),
    FieldDef("ea_covers_attack_count", "Number of Attacks Covered", "Attack Coverage", "number", False, "aggregate", None, family="covers_attack"),
]

# ── Countermeasures ──────────────────────────────────────────────────────────
# Base: countermeasures only. Key: countermeasures.id.
_COUNTERMEASURES_FIELDS: list[FieldDef] = [
    FieldDef("cm_name", "Name", "Countermeasure", "text", False, "direct", countermeasures.c.name),
    FieldDef("cm_description", "Description", "Countermeasure", "text", True, "direct", countermeasures.c.description),
    FieldDef("cm_type", "Type", "Countermeasure", "enum", False, "direct", countermeasures.c.countermeasure_type, options=_static_options(enums.COUNTERMEASURE_TYPES)),
    FieldDef("cm_module", "Module", "Countermeasure", "enum", True, "direct", countermeasures.c.module, options=_static_options(enums.MODULES)),
    FieldDef("cm_component_types", "Component Types", "Countermeasure", "array", True, "direct", countermeasures.c.component_type_ids, pg_array_type="integer", options=_lookup_options("/internal/catalog/component-types", "id", "name")),

    # Exists family: vulnerability_coverage (reverse-lookup — which vulnerabilities this countermeasure defends against)
    FieldDef("cm_covers_vuln_name", "Covered Vulnerability Name", "Vulnerability Coverage", "text", True, "exists", vulnerabilities.c.name, family="vulnerability_coverage"),
    FieldDef("cm_covers_vuln_description", "Covered Vulnerability Description", "Vulnerability Coverage", "text", True, "exists", vulnerabilities.c.short_description, family="vulnerability_coverage"),
    FieldDef("cm_covers_attack_type", "Covered Attack Type", "Vulnerability Coverage", "enum", True, "exists", attacks.c.attack_type, family="vulnerability_coverage", options=_static_options(enums.ATTACK_TYPES)),
    FieldDef("cm_covers_attack_rating", "Covered Attack Rating", "Vulnerability Coverage", "enum", True, "exists", attacks.c.attack_rating, family="vulnerability_coverage", options=_static_options(enums.ATTACK_RATINGS)),
    FieldDef("cm_covers_defense_effectiveness", "Defense Effectiveness", "Vulnerability Coverage", "array", True, "exists", vulnerability_countermeasures.c.defense_effectiveness, family="vulnerability_coverage", options=_static_options(enums.DEFENSE_EFFECTIVENESS)),
    FieldDef("cm_covers_vuln_count", "Number of Vulnerabilities Covered", "Vulnerability Coverage", "number", False, "aggregate", None, family="vulnerability_coverage"),
]

FIELD_REGISTRY: dict[SearchDomain, list[FieldDef]] = {
    "attacks": _ATTACKS_FIELDS,
    "systems": _SYSTEMS_FIELDS,
    "evaluation_activities": _EVALUATION_ACTIVITIES_FIELDS,
    "countermeasures": _COUNTERMEASURES_FIELDS,
}


def get_field_def(domain: SearchDomain, key: str) -> FieldDef | None:
    return next((f for f in FIELD_REGISTRY[domain] if f.key == key), None)


def get_fields_by_group(domain: SearchDomain) -> dict[str, list[FieldDef]]:
    result: dict[str, list[FieldDef]] = {}
    for f in FIELD_REGISTRY[domain]:
        result.setdefault(f.group, []).append(f)
    return result
