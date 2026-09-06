"""Port of ../../../src/lib/qkd/getSystemFeatures.ts — keep in sync line-by-line.

Shared by /systems/{id}/applicability and /systems/{id}/applicable-eas: both
routes need the exact same system -> SystemFeatures -> VulnRecord[] pipeline.

Unlike the search compiler (Phase 2), this file's 8 queries are fixed, not
dynamically composed — so it's ported as parameterized `text()` queries
(mirroring the TS source's own raw `sql` tagged-template style) rather than
through the SQLAlchemy Core table mirror that Phase 2 needs for its
composable AND/OR tree.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import QueryParams

from app.core.camel_model import CamelModel
from app.qkd.applicability import (
    Condition,
    DetectorRow,
    ScopeRow,
    SystemFeatures,
    VulnRecord,
    derive_detector_types,
)

# Component type IDs for presence-derived flags (from seed constants).
_ILM_CT_ID = 9
_LASER_CT_ID = 1
# CT 22 = "Entangled Photon Source", CT 23 = "SPDC Nonlinear Crystal"
_ENTANGLED_SOURCE_CT_IDS = {22, 23}


class SystemSummary(CamelModel):
    id: int
    name: str
    manufacturer: str | None


class SystemFeaturesResult(CamelModel):
    system: SystemSummary
    features: SystemFeatures
    vulns: list[VulnRecord]
    # Raw rows some callers need beyond the derived `features` (e.g. for response
    # payloads) — mirrors the TS return shape exactly, including its dict/`any[]` looseness.
    comp_type_rows: list[dict]
    system_cm_rows: list[dict]


async def load_system_features(
    session: AsyncSession,
    system_id: int,
    user_id: str,
    search_params: QueryParams,
) -> SystemFeaturesResult | None:
    sys_rows = (await session.execute(
        text("""
            SELECT id, name, manufacturer,
                   double_click_handling, basis_choice,
                   deployment, detector_accepts_clicks_outside_gate,
                   optical_path_direction, source_type, local_oscillator_type,
                   phase_randomisation_method, reconciliation_algorithm
            FROM systems WHERE id = CAST(:id AS integer) AND (user_id = :user_id OR is_public = true)
            LIMIT 1
        """),
        {"id": system_id, "user_id": user_id},
    )).mappings().all()
    system = sys_rows[0] if sys_rows else None
    if system is None:
        return None

    # Sequential, not concurrent: a single AsyncSession/connection can't safely run
    # overlapping queries (unlike the TS source's Promise.all, which is safe there
    # only because Neon's HTTP driver has no shared connection state per call).
    proto_rows = (await session.execute(text("""
            SELECT p.id AS protocol_id, p.protocol_family_id, p.name AS protocol_name,
                   pf.encoding_id, e.name AS encoding_name, a.name AS architecture_name
            FROM system_protocols sp
            JOIN protocols p ON p.id = sp.protocol_id
            JOIN protocol_families pf ON pf.id = p.protocol_family_id
            LEFT JOIN encodings e ON e.id = pf.encoding_id
            LEFT JOIN architectures a ON a.id = pf.architecture_id
            WHERE sp.system_id = CAST(:id AS integer)
        """), {"id": system_id})).mappings().all()

    mod_type_rows = (await session.execute(text(
        "SELECT DISTINCT module_type_id FROM modules WHERE system_id = CAST(:id AS integer)"
    ), {"id": system_id})).mappings().all()

    comp_type_rows = (await session.execute(text("""
            SELECT DISTINCT c.component_type_id, ct.name AS component_type_name, m.module_type_id
            FROM modules m
            JOIN module_components mc ON mc.module_id = m.id
            JOIN components c ON c.id = mc.component_id
            JOIN component_types ct ON ct.id = c.component_type_id
            WHERE m.system_id = CAST(:id AS integer)
        """), {"id": system_id})).mappings().all()

    detector_rows = (await session.execute(text("""
            SELECT cp.value AS variant_value, ct.name AS component_type
            FROM modules m
            JOIN module_components mc ON mc.module_id = m.id
            JOIN components c ON c.id = mc.component_id
            JOIN component_types ct ON ct.id = c.component_type_id
            LEFT JOIN component_parameters cp
              ON cp.module_component_id = mc.id
              AND cp.key = 'detector_variant'
              AND cp.param_group = 'settings'
            WHERE m.system_id = CAST(:id AS integer)
              AND ct.name IN ('Single-Photon Detector', 'Avalanche Photon Detector', 'Coherent Detector')
        """), {"id": system_id})).mappings().all()

    vuln_rows = (await session.execute(text("""
            SELECT DISTINCT v.id, v.name, v.short_description, a.attack_rating, ac.name AS category,
                   a.module, a.component
            FROM vulnerabilities v
            LEFT JOIN vulnerability_applicability va ON va.vulnerability_id = v.id
            LEFT JOIN attacks a ON a.vulnerability_id = v.id
            LEFT JOIN attack_categories ac ON ac.id = a.attack_category_id
            ORDER BY v.id
        """))).mappings().all()

    scope_rows = (await session.execute(text("""
            SELECT va.vulnerability_id, va.protocol_family_id, va.protocol_id, va.module_type_id,
                   va.component_type_id, va.cross_family_uncertain, va.encoding_id,
                   va.architecture_exclusion_override,
                   pf.name AS protocol_family_name, p.name AS protocol_name,
                   mt.name AS module_type_name, ct.name AS component_type_name
            FROM vulnerability_applicability va
            LEFT JOIN protocol_families pf ON pf.id = va.protocol_family_id
            LEFT JOIN protocols p ON p.id = va.protocol_id
            LEFT JOIN module_types mt ON mt.id = va.module_type_id
            LEFT JOIN component_types ct ON ct.id = va.component_type_id
        """))).mappings().all()

    cond_rows = (await session.execute(text("""
            SELECT vulnerability_id, cond_type, path, value_bool, value_text, value_num, values_text
            FROM vulnerability_conditions
        """))).mappings().all()

    system_cm_rows = (await session.execute(text("""
            SELECT sc.countermeasure_id, sc.module_id, m.module_type_id,
                   mt.name AS module_type_name, c.name, c.description,
                   c.countermeasure_type, c.module AS cm_modules, c.component_type_ids
            FROM system_countermeasures sc
            JOIN modules m ON m.id = sc.module_id
            JOIN module_types mt ON mt.id = m.module_type_id
            JOIN countermeasures c ON c.id = sc.countermeasure_id
            WHERE m.system_id = CAST(:id AS integer)
        """), {"id": system_id})).mappings().all()

    # Derive architecture and encoding_ids from the protocol chain (protocol_families).
    # Order-preserving (dict, not set) to match JS Set's insertion-order iteration,
    # since the fallback-to-first-name branch below is otherwise order-dependent.
    arch_names = list(dict.fromkeys(r["architecture_name"] for r in proto_rows if r["architecture_name"]))
    architecture = (
        "MDI" if "MDI" in arch_names
        else "EB" if "EB" in arch_names
        else (arch_names[0] if arch_names else None)
    )
    # A list, like protocol_family_ids/protocol_ids: a system carrying both a DV and
    # a CV protocol resolves to both encodings, and row_matches tests membership.
    # Taking only the first would drop every scope row on the other encoding.
    encoding_ids = list(dict.fromkeys(
        r["encoding_id"] for r in proto_rows if r["encoding_id"] is not None
    ))

    # source_type is derived from component presence rather than stored manually.
    derived_source_type = (
        "entangled-photon" if any(r["component_type_id"] in _ENTANGLED_SOURCE_CT_IDS for r in comp_type_rows)
        else "weak-coherent" if any(r["component_type_id"] == _LASER_CT_ID for r in comp_type_rows)
        else None
    )

    # Build the system feature vector from the relational model + behavioral columns.
    features = SystemFeatures(
        protocol_ids=[r["protocol_id"] for r in proto_rows],
        protocol_family_ids=list(dict.fromkeys(
            r["protocol_family_id"] for r in proto_rows if r["protocol_family_id"] is not None
        )),
        protocol_names=[r["protocol_name"] for r in proto_rows if r["protocol_name"]],
        module_type_ids=[r["module_type_id"] for r in mod_type_rows],
        component_type_ids=[r["component_type_id"] for r in comp_type_rows],
        component_placements=[
            {"module_type_id": r["module_type_id"], "component_type_id": r["component_type_id"]}
            for r in comp_type_rows
        ],
        double_click_handling=system["double_click_handling"],
        basis_choice=system["basis_choice"],
        detector_types=derive_detector_types([
            DetectorRow(variant_value=r["variant_value"], component_type=r["component_type"])
            for r in detector_rows
        ]),
        deployment=system["deployment"],
        detector_accepts_clicks_outside_gate=system["detector_accepts_clicks_outside_gate"],
        optical_path_direction=system["optical_path_direction"],
        source_type=derived_source_type if derived_source_type is not None else system["source_type"],
        local_oscillator_type=system["local_oscillator_type"],
        phase_randomisation_method=system["phase_randomisation_method"],
        reconciliation_algorithm=system["reconciliation_algorithm"],
        has_intensity_monitor=any(r["component_type_id"] == _ILM_CT_ID for r in comp_type_rows),
        has_decoy_countermeasure=any(r["name"] == "Decoy State Protocol" for r in system_cm_rows),
        architecture=architecture,
        encoding_ids=encoding_ids,
    )

    # ── What-if overrides (query params override the stored features) ──
    def bool_param(k: str) -> bool | None:
        return (search_params.get(k) == "true") if k in search_params else None

    def text_param(k: str) -> str | None:
        return search_params.get(k) if k in search_params else None

    if (v := text_param("doubleClickHandling")) is not None:
        features.double_click_handling = v
    if (v := text_param("basisChoice")) is not None:
        features.basis_choice = v
    if (v := text_param("deployment")) is not None:
        features.deployment = v
    if (v := bool_param("detectorAcceptsClicksOutsideGate")) is not None:
        features.detector_accepts_clicks_outside_gate = v
    if "detectorTypes" in search_params:
        features.detector_types = search_params.get_list("detectorTypes")
    if (v := text_param("opticalPathDirection")) is not None:
        features.optical_path_direction = v
    if (v := text_param("sourceType")) is not None:
        features.source_type = v
    if (v := text_param("localOscillatorType")) is not None:
        features.local_oscillator_type = v
    if (v := text_param("phaseRandomisationMethod")) is not None:
        features.phase_randomisation_method = v
    if (v := text_param("reconciliationAlgorithm")) is not None:
        features.reconciliation_algorithm = v
    if (v := bool_param("hasIntensityMonitor")) is not None:
        features.has_intensity_monitor = v

    # ── Group scope rows + conditions by vulnerability ──
    scope_by_vuln: dict[int, list[ScopeRow]] = {}
    for r in scope_rows:
        scope_by_vuln.setdefault(r["vulnerability_id"], []).append(ScopeRow(
            protocol_family_id=r["protocol_family_id"],
            protocol_id=r["protocol_id"],
            module_type_id=r["module_type_id"],
            component_type_id=r["component_type_id"],
            encoding_id=r["encoding_id"],
            cross_family_uncertain=bool(r["cross_family_uncertain"]),
            architecture_exclusion_override=bool(r["architecture_exclusion_override"]),
            protocol_family_name=r["protocol_family_name"],
            protocol_name=r["protocol_name"],
            module_type_name=r["module_type_name"],
            component_type_name=r["component_type_name"],
        ))

    cond_by_vuln: dict[int, list[Condition]] = {}
    for r in cond_rows:
        cond_by_vuln.setdefault(r["vulnerability_id"], []).append(Condition(
            cond_type=r["cond_type"],
            path=r["path"],
            value_bool=r["value_bool"],
            value_text=r["value_text"],
            value_num=float(r["value_num"]) if r["value_num"] is not None else None,
            values_text=r["values_text"],
        ))

    vulns = [
        VulnRecord(
            vulnerability_id=v["id"],
            name=v["name"],
            short_description=v["short_description"],
            category=v["category"],
            attack_rating=v["attack_rating"],
            module=v["module"],
            component=v["component"],
            scope=scope_by_vuln.get(v["id"], []),
            conditions=cond_by_vuln.get(v["id"], []),
        )
        for v in vuln_rows
    ]

    return SystemFeaturesResult(
        system=SystemSummary(id=system["id"], name=system["name"], manufacturer=system["manufacturer"]),
        features=features,
        vulns=vulns,
        comp_type_rows=[dict(r) for r in comp_type_rows],
        system_cm_rows=[dict(r) for r in system_cm_rows],
    )
