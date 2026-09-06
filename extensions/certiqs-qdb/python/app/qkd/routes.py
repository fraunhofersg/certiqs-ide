"""Port of ../../../src/app/api/qsecdb/systems/[id]/applicability/route.ts.

Split into a pure `build_applicability_response()` (all the countermeasure
enrichment logic, directly unit-testable with no DB) and a thin route
handler that does the two I/O calls and delegates to it — the TS source
interleaves both in one handler, but there's no DB-mocking gain from
mirroring that structure exactly here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session
from app.qkd.applicability import evaluate_applicability
from app.qkd.attack_enums import parse_module_field
from app.qkd.get_system_features import SystemFeaturesResult, load_system_features

router = APIRouter(prefix="/internal/qkd", tags=["qkd"])

# Mirrors src/lib/modules.ts MODULE_SHORT_TO_DISPLAY.
MODULE_SHORT_TO_DISPLAY: dict[str, str] = {
    "TX": "Transmitter",
    "RX": "Receiver",
    "PP": "Post-processing",
    "POST_PROCESSING": "Post-processing",
}


def build_applicability_response(
    system_id: int,
    loaded: SystemFeaturesResult,
    vuln_cm_rows: Sequence[Mapping[str, Any]],
) -> dict:
    system, features, vulns = loaded.system, loaded.features, loaded.vulns
    comp_type_rows, system_cm_rows = loaded.comp_type_rows, loaded.system_cm_rows

    # ── Build countermeasure mappings ──
    # Map: cm_id -> set of DISPLAY module names where it's installed on this system.
    system_cm_modules: dict[int, set[str]] = {}
    for r in system_cm_rows:
        s = system_cm_modules.setdefault(r["countermeasure_id"], set())
        s.add(MODULE_SHORT_TO_DISPLAY.get(r["module_type_name"], r["module_type_name"]))

    def cm_covers_module(cm_id: int, attack_module: str | None) -> bool:
        installed_in = system_cm_modules.get(cm_id)
        if not installed_in:
            return False
        # attack_module may name several modules joined with ", " (e.g.
        # "Transmitter, Post-processing" — see attack_enums.parse_module_field).
        # A countermeasure counts as implemented if it's installed in ANY of
        # them. An unset or unparseable module (including the legacy "Both"
        # sentinel, no longer a valid MODULES value) imposes no restriction —
        # same "don't know what it targets, so don't exclude" policy as
        # applicability.targets_only().
        tokens, error = parse_module_field(attack_module)
        if tokens is None or error:
            return True
        return any(t in installed_in for t in tokens)

    cm_by_vuln: dict[int, list[dict]] = {}
    for r in vuln_cm_rows:
        cm_by_vuln.setdefault(r["vulnerability_id"], []).append({
            "countermeasureId": r["countermeasure_id"],
            "name": r["name"],
            "description": r["description"],
            "defenseEffectiveness": (
                r["defense_effectiveness"] if isinstance(r["defense_effectiveness"], list) else None
            ),
        })

    result = evaluate_applicability(features, vulns)

    # ── Enrich applicable with countermeasure data ──
    applicable_with_cm = []
    for a in result.applicable:
        cms = cm_by_vuln.get(a.vulnerability_id, [])
        entry = a.model_dump(by_alias=True)
        entry["countermeasures"] = cms
        entry["implementedCountermeasures"] = [
            cm for cm in cms if cm_covers_module(cm["countermeasureId"], a.module)
        ]
        applicable_with_cm.append(entry)

    # ── Enrich cross_family_unknown with countermeasure data ──
    cross_family_with_cm = []
    for a in result.cross_family_unknown:
        entry = a.model_dump(by_alias=True)
        entry["countermeasures"] = cm_by_vuln.get(a.vulnerability_id, [])
        cross_family_with_cm.append(entry)

    return {
        "systemId": system_id,
        "system": system.model_dump(by_alias=True),
        "featuresUsed": {
            "doubleClickHandling": features.double_click_handling,
            "basisChoice": features.basis_choice,
            "detectorTypes": features.detector_types,
            "deployment": features.deployment,
            "detectorAcceptsClicksOutsideGate": features.detector_accepts_clicks_outside_gate,
            "opticalPathDirection": features.optical_path_direction,
            "sourceType": features.source_type,
            "localOscillatorType": features.local_oscillator_type,
            "phaseRandomisationMethod": features.phase_randomisation_method,
            "reconciliationAlgorithm": features.reconciliation_algorithm,
            "hasIntensityMonitor": features.has_intensity_monitor,
            "hasDecoyCountermeasure": features.has_decoy_countermeasure,
        },
        "systemComponentTypeNames": [
            r["component_type_name"] for r in comp_type_rows if r["component_type_name"]
        ],
        # Deliberately snake_case, matching the TS route's raw DB-row passthrough —
        # NOT run through the camelCase alias like the rest of this response.
        "systemCountermeasures": [
            {
                "countermeasure_id": r["countermeasure_id"],
                "module_id": r["module_id"],
                "module_type_id": r["module_type_id"],
                "module_type_name": r["module_type_name"],
                "name": r["name"],
                "description": r["description"],
                "countermeasure_type": r["countermeasure_type"],
                "cm_modules": r["cm_modules"],
                "component_type_ids": r["component_type_ids"],
            }
            for r in system_cm_rows
        ],
        "applicable": applicable_with_cm,
        "unevaluated": [v.model_dump(by_alias=True) for v in result.unevaluated],
        "crossFamilyUnknown": cross_family_with_cm,
        "excluded": [v.model_dump(by_alias=True) for v in result.excluded],
        "noScopeMatch": [v.model_dump(by_alias=True) for v in result.no_scope_match],
        "conditionsFailed": [v.model_dump(by_alias=True) for v in result.conditions_failed],
    }


@router.get("/systems/{system_id}/applicability")
async def get_system_applicability(
    system_id: int,
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    # vuln_cm_rows is only needed by this route (not by /applicable-eas), so it's
    # fetched alongside the shared system/feature load rather than folded into it.
    vuln_cm_rows = (await session.execute(text("""
        SELECT vc.vulnerability_id, vc.countermeasure_id, c.name, c.description,
               vc.defense_effectiveness
        FROM vulnerability_countermeasures vc
        JOIN countermeasures c ON c.id = vc.countermeasure_id
    """))).mappings().all()

    loaded = await load_system_features(session, system_id, principal.user_id, request.query_params)
    if loaded is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "System not found")

    return build_applicability_response(system_id, loaded, vuln_cm_rows)


# ── /applicable-eas ───────────────────────────────────────────────────────────
# Port of ../../../src/app/api/qsecdb/systems/[id]/applicable-eas/route.ts.

_RATING_SCORE: dict[str, int] = {
    "Beyond High": 50, "High": 40, "Moderate": 30, "Enhanced Basic": 20, "Basic": 10, "Vulnerability": 5,
}


@router.get("/systems/{system_id}/applicable-eas")
async def get_applicable_eas(
    system_id: int,
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    loaded = await load_system_features(session, system_id, principal.user_id, request.query_params)
    if loaded is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "System not found")

    features, vulns = loaded.features, loaded.vulns
    result = evaluate_applicability(features, vulns)
    applicable_vuln_ids = [a.vulnerability_id for a in result.applicable]

    ea_rows = []
    if applicable_vuln_ids:
        ea_rows = (await session.execute(text("""
            SELECT eca.evaluation_activity_id AS code,
                   eca.attack_vulnerability_id AS vuln_id,
                   eca.rationale,
                   ea.name, ea.description, ea.subclause, ea.referenced_from,
                   v.name AS attack_name,
                   a.attack_rating
            FROM ea_covers_attack eca
            JOIN evaluation_activities ea ON ea.code = eca.evaluation_activity_id
            JOIN vulnerabilities v ON v.id = eca.attack_vulnerability_id
            LEFT JOIN attacks a ON a.vulnerability_id = eca.attack_vulnerability_id
            WHERE eca.attack_vulnerability_id = ANY(:vuln_ids)
            ORDER BY eca.evaluation_activity_id, eca.attack_vulnerability_id
        """), {"vuln_ids": applicable_vuln_ids})).mappings().all()

    # EA 6.2-6.4 apply unconditionally to any system with at least one protocol.
    always_apply_rows = []
    if features.protocol_ids:
        always_apply_rows = (await session.execute(text("""
            SELECT code, name, description, subclause, referenced_from
            FROM evaluation_activities
            WHERE subclause IN ('6.2', '6.3', '6.4')
            ORDER BY subclause
        """))).mappings().all()

    if not ea_rows and not always_apply_rows:
        return []

    ea_map: dict[str, dict] = {}

    for row in ea_rows:
        ea = ea_map.setdefault(row["code"], {
            "code": row["code"], "name": row["name"], "description": row["description"],
            "subclause": row["subclause"], "referencedFrom": row["referenced_from"],
            "score": 0, "equipment": [], "applicableAttacks": [],
        })
        rating_score = _RATING_SCORE.get(row["attack_rating"] or "", 5)
        ea["score"] += rating_score
        ea["applicableAttacks"].append({
            "vulnerabilityId": row["vuln_id"], "name": row["attack_name"],
            "attackRating": row["attack_rating"], "rationale": row["rationale"],
        })

    # Ensure EA 6.2-6.4 are always present for systems with protocols.
    for row in always_apply_rows:
        ea_map.setdefault(row["code"], {
            "code": row["code"], "name": row["name"], "description": row["description"],
            "subclause": row["subclause"], "referencedFrom": row["referenced_from"],
            "score": 0, "equipment": [], "applicableAttacks": [],
        })

    # Attach equipment to each EA.
    ea_codes = list(ea_map.keys())
    equip_rows = []
    if ea_codes:
        equip_rows = (await session.execute(text("""
            SELECT ee.evaluation_activity_code AS ea_code,
                   e.id, e.name, e.category, ee.required_for
            FROM ea_equipment ee
            JOIN equipment e ON e.id = ee.equipment_id
            WHERE ee.evaluation_activity_code = ANY(:ea_codes)
            ORDER BY e.category NULLS LAST, e.name
        """), {"ea_codes": ea_codes})).mappings().all()

    for row in equip_rows:
        ea = ea_map.get(row["ea_code"])
        if ea:
            ea["equipment"].append({
                "id": row["id"], "name": row["name"], "category": row["category"],
                "requiredFor": row["required_for"],
            })

    # Python's sorted() is stable, matching JS's Array.prototype.sort() (stable
    # since ES2019) — ties preserve original insertion order in both.
    return sorted(ea_map.values(), key=lambda ea: ea["score"], reverse=True)
