"""Ports of ../../../src/app/api/qsecdb/systems/{,[id]/,[id]/visibility/}route.ts.

The PATCH handler (resync_system) is the single most complex route in the
whole app — bulk unnest()-based batch upserts, last-write-wins de-duping by
composite key, and a deliberate "preserve the post-processing module across a
full resync" carve-out. Ported as faithfully as possible to the TS structure,
section by section, matching its own section comments so the two stay
diffable side by side.

One deliberate, safe improvement over the TS source: this uses a single
SQLAlchemy transaction per request (commit once at the end) rather than the
TS route's per-statement independent execution (Neon's HTTP driver has no
cross-call transaction by default, and the TS route never wraps calls in one
explicitly) — a pooled connection naturally gives stronger atomicity here
with no behavioral cost on the success path, so there's no reason to
deliberately weaken it to match.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_auth import InternalPrincipal, require_internal_principal
from app.db import get_session
from app.systems.param_coerce import coerce_parameter, resolve_param_group
from app.systems.pivot import pivot

router = APIRouter(prefix="/internal/systems", tags=["systems"])


async def _existing_system_row(session: AsyncSession, system_id: int, principal: InternalPrincipal) -> dict | None:
    """Ownership-or-admin existence check shared by PATCH/DELETE/visibility."""
    if principal.is_admin:
        rows = (await session.execute(
            text("SELECT id FROM systems WHERE id = CAST(:id AS integer) LIMIT 1"), {"id": system_id}
        )).mappings().all()
    else:
        rows = (await session.execute(
            text("SELECT id FROM systems WHERE id = CAST(:id AS integer) AND user_id = :user_id LIMIT 1"),
            {"id": system_id, "user_id": principal.user_id},
        )).mappings().all()
    return dict(rows[0]) if rows else None


@router.get("")
async def list_systems(
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    rows = (await session.execute(text("""
        SELECT id, name, manufacturer, toe_boundary
        FROM public.systems WHERE (user_id = :user_id OR is_public = true) ORDER BY id DESC LIMIT 100
    """), {"user_id": principal.user_id})).mappings().all()
    return [dict(r) for r in rows]


@router.post("")
async def create_system(
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    user_id = principal.user_id

    body = await request.json()
    protocol_ids = body.get("protocolIds") or []
    system_cm_input = body.get("systemCountermeasures") or []
    system_pp_input = body.get("systemPp") or []
    modules_input = body.get("modules") or []
    connections_input = body.get("connections") or []

    sys_row = (await session.execute(text("""
        INSERT INTO systems (
            user_id, name, manufacturer, toe_boundary,
            double_click_handling, basis_choice,
            deployment, detector_accepts_clicks_outside_gate,
            optical_path_direction, local_oscillator_type,
            phase_randomisation_method, reconciliation_algorithm
        )
        VALUES (
            :user_id, :name, :manufacturer, :toe_boundary,
            :double_click_handling, :basis_choice,
            :deployment, :detector_accepts_clicks_outside_gate,
            :optical_path_direction, :local_oscillator_type,
            :phase_randomisation_method, :reconciliation_algorithm
        )
        RETURNING id, created_at
    """), {
        "user_id": user_id, "name": body.get("name"), "manufacturer": body.get("manufacturer"),
        "toe_boundary": body.get("toeBoundary"),
        "double_click_handling": body.get("doubleClickHandling"),
        "basis_choice": body.get("basisChoice"),
        "deployment": body.get("deployment"),
        "detector_accepts_clicks_outside_gate": body.get("detectorAcceptsClicksOutsideGate"),
        "optical_path_direction": body.get("opticalPathDirection"),
        "local_oscillator_type": body.get("localOscillatorType"),
        "phase_randomisation_method": body.get("phaseRandomisationMethod"),
        "reconciliation_algorithm": body.get("reconciliationAlgorithm"),
    })).mappings().first()
    system_id = sys_row["id"]
    system_created_at = sys_row["created_at"]

    # Everything below is batched into one statement per table via
    # `INSERT ... SELECT FROM unnest(...)`, mirroring resync_system's approach
    # further down this file. This route used to issue one statement per row —
    # including two per parameter (once for 'ideal', once for 'characterised') —
    # which meant a realistic system cost ~250 sequential round trips. That is
    # untenable per-request, where the whole handler shares one time budget.
    #
    # Unlike resync_system's batches, these carry `created_at` explicitly: this
    # route deliberately stamps every child row with the parent system's
    # created_at rather than letting each column's DEFAULT now() fire, so the
    # whole system shares one timestamp. Preserved verbatim as a scalar bind.

    if protocol_ids:
        proto_rows_in = [
            {"protocolId": p.get("id"), "isPrimary": p.get("isPrimary") or False}
            for p in protocol_ids
        ]
        pv = pivot(proto_rows_in, "protocolId", "isPrimary")
        await session.execute(text("""
            INSERT INTO system_protocols (system_id, protocol_id, is_primary)
            SELECT CAST(:sid AS integer), x.protocol_id, x.is_primary
            FROM unnest(CAST(:protocol_ids AS int[]), CAST(:is_primaries AS boolean[]))
                AS x(protocol_id, is_primary)
        """), {"sid": system_id, "protocol_ids": pv["protocolId"], "is_primaries": pv["isPrimary"]})

    # Resolve component type names so we can validate/coerce parameters against the
    # canonical spec dictionary (units + value types).
    ct_rows = (await session.execute(text("SELECT id, name FROM component_types"))).mappings().all()
    component_type_name_by_id = {r["id"]: r["name"] for r in ct_rows}

    module_id_map: dict[int, int] = {}
    module_component_id_map: dict[str, int] = {}

    # ── Bulk-insert every module in one batch ────────────────────────────────
    # A plain INSERT ... SELECT FROM unnest(...) RETURNING has no join/order-by/
    # group-by to reshuffle rows, so Postgres returns ids in the same order the
    # arrays were built — mod_rows[i] always corresponds to modules_input[i].
    if modules_input:
        mod_rows_in = [{
            "moduleTypeId": m.get("moduleTypeId"), "name": m.get("name"),
            "firmwareRevision": m.get("firmwareRevision"),
        } for m in modules_input]
        pv = pivot(mod_rows_in, "moduleTypeId", "name", "firmwareRevision")
        mod_rows = (await session.execute(text("""
            INSERT INTO modules (system_id, module_type_id, name, firmware_revision)
            SELECT CAST(:sid AS integer), x.module_type_id, x.name, x.firmware_revision
            FROM unnest(CAST(:module_type_ids AS int[]), CAST(:names AS text[]), CAST(:firmwares AS text[]))
                AS x(module_type_id, name, firmware_revision)
            RETURNING id
        """), {
            "sid": system_id, "module_type_ids": pv["moduleTypeId"],
            "names": pv["name"], "firmwares": pv["firmwareRevision"],
        })).mappings().all()
        for mi in range(len(modules_input)):
            module_id_map[mi] = mod_rows[mi]["id"]

    # ── Bulk-insert module_components across every module, in one batch ──────
    components_to_insert: list[dict] = []
    for mi, m in enumerate(modules_input):
        for ci, c in enumerate(m.get("components") or []):
            if not c.get("componentId"):
                continue  # no catalog entry selected — skip
            components_to_insert.append({"mi": mi, "ci": ci, "c": c, "moduleId": module_id_map[mi]})

    if components_to_insert:
        mc_rows_in = [{
            "moduleId": e["moduleId"], "componentId": e["c"].get("componentId"),
            "instanceName": e["c"].get("instanceName"), "domain": e["c"].get("domain"),
            "branchSide": e["c"].get("branchSide"), "role": e["c"].get("role"),
        } for e in components_to_insert]
        pv = pivot(mc_rows_in, "moduleId", "componentId", "instanceName", "domain", "branchSide", "role")
        mc_rows = (await session.execute(text("""
            INSERT INTO module_components (module_id, component_id, instance_name, domain, branch_side, role, created_at)
            SELECT x.module_id, x.component_id, x.instance_name, x.domain, x.branch_side, x.role,
                   CAST(:created_at AS timestamptz)
            FROM unnest(
                CAST(:module_ids AS int[]), CAST(:component_ids AS int[]), CAST(:instance_names AS text[]),
                CAST(:domains AS text[]), CAST(:branch_sides AS text[]), CAST(:roles AS text[])
            ) AS x(module_id, component_id, instance_name, domain, branch_side, role)
            RETURNING id
        """), {
            "created_at": system_created_at,
            "module_ids": pv["moduleId"], "component_ids": pv["componentId"],
            "instance_names": pv["instanceName"], "domains": pv["domain"],
            "branch_sides": pv["branchSide"], "roles": pv["role"],
        })).mappings().all()
        for idx, entry in enumerate(components_to_insert):
            module_component_id_map[f"{entry['mi']}-{entry['ci']}"] = mc_rows[idx]["id"]

    # ── Flatten parameters for every inserted component into one batched upsert ──
    param_rows_in: list[dict] = []
    for entry in components_to_insert:
        c = entry["c"]
        mc_id = module_component_id_map[f"{entry['mi']}-{entry['ci']}"]
        ct_name = component_type_name_by_id.get(c.get("componentTypeId"))

        # Last-write-wins de-dupe by (paramGroup, key): a single batched statement
        # can't touch the same ON CONFLICT target twice (Postgres error "ON CONFLICT
        # DO UPDATE command cannot affect row a second time"). Collapsing here keeps
        # the same outcome the old per-row loop produced, where a later duplicate
        # simply overwrote the earlier one.
        by_key: dict[str, dict] = {}
        for p in c.get("parameters") or []:
            by_key[f"{resolve_param_group(p.get('paramGroup'))}\x00{p.get('key')}"] = p

        for p in by_key.values():
            coerced = coerce_parameter(p.get("value"), p.get("unit"), p.get("paramGroup"), ct_name, p.get("key"))
            # Seed BOTH variants at create time: 'ideal' is the design/datasheet value
            # the form carries; 'characterised' begins as an identical copy and is later
            # overwritten by the external parser via PATCH .../characterised-parameters.
            for state in ("ideal", "characterised"):
                param_rows_in.append({
                    "mcId": mc_id, "state": state, "paramGroup": coerced.param_group, "key": p.get("key"),
                    "value": p.get("value") or "", "valueText": coerced.value_text,
                    "valueNum": coerced.value_num, "valueBool": coerced.value_bool,
                    "unit": coerced.unit,
                })

    if param_rows_in:
        pv = pivot(param_rows_in, "mcId", "state", "paramGroup", "key", "value", "valueText", "valueNum", "valueBool", "unit")
        await session.execute(text("""
            INSERT INTO component_parameters (module_component_id, state, param_group, key, value, value_text, value_num, value_bool, unit, created_at)
            SELECT x.mc_id, x.state, x.param_group, x.key, x.value, x.value_text, x.value_num, x.value_bool, x.unit,
                   CAST(:created_at AS timestamptz)
            FROM unnest(
                CAST(:mc_ids AS int[]), CAST(:states AS text[]), CAST(:param_groups AS text[]), CAST(:keys AS text[]), CAST(:values AS text[]),
                CAST(:value_texts AS text[]), CAST(:value_nums AS numeric[]), CAST(:value_bools AS boolean[]), CAST(:units AS text[])
            ) AS x(mc_id, state, param_group, key, value, value_text, value_num, value_bool, unit)
            ON CONFLICT (module_component_id, state, param_group, key)
            DO UPDATE SET
                value = EXCLUDED.value, value_text = EXCLUDED.value_text,
                value_num = EXCLUDED.value_num, value_bool = EXCLUDED.value_bool, unit = EXCLUDED.unit
        """), {
            "created_at": system_created_at,
            "mc_ids": pv["mcId"], "states": pv["state"], "param_groups": pv["paramGroup"], "keys": pv["key"], "values": pv["value"],
            "value_texts": pv["valueText"], "value_nums": pv["valueNum"], "value_bools": pv["valueBool"], "units": pv["unit"],
        })

    if system_pp_input:
        # Same last-write-wins collapse as the parameters above, keyed on the
        # ON CONFLICT target (system_id is constant here, so pp_type_id alone).
        pp_by_type: dict[object, dict] = {}
        for pp in system_pp_input:
            pp_by_type[pp.get("ppTypeId")] = {
                "ppTypeId": pp.get("ppTypeId"), "annotation": pp.get("annotation") or None,
            }
        pp_entries = list(pp_by_type.values())
        pv = pivot(pp_entries, "ppTypeId", "annotation")
        await session.execute(text("""
            INSERT INTO system_pp (system_id, pp_type_id, annotation)
            SELECT CAST(:sid AS integer), x.pp_type_id, x.annotation
            FROM unnest(CAST(:pp_type_ids AS int[]), CAST(:annotations AS text[]))
                AS x(pp_type_id, annotation)
            ON CONFLICT (system_id, pp_type_id) DO UPDATE SET annotation = EXCLUDED.annotation
        """), {"sid": system_id, "pp_type_ids": pv["ppTypeId"], "annotations": pv["annotation"]})

    # Insert system countermeasures after modules are created (module_id must exist).
    cm_rows_in: list[dict] = []
    for cm in system_cm_input:
        module_db_id = module_id_map.get(cm.get("moduleIndex"))
        if module_db_id is None:
            continue
        cm_rows_in.append({"moduleDbId": module_db_id, "countermeasureId": cm.get("countermeasureId")})

    if cm_rows_in:
        pv = pivot(cm_rows_in, "moduleDbId", "countermeasureId")
        await session.execute(text("""
            INSERT INTO system_countermeasures (module_id, countermeasure_id)
            SELECT x.module_id, x.countermeasure_id
            FROM unnest(CAST(:module_ids AS int[]), CAST(:cm_ids AS int[])) AS x(module_id, countermeasure_id)
        """), {"module_ids": pv["moduleDbId"], "cm_ids": pv["countermeasureId"]})

    if connections_input:
        conn_rows_in = []
        for conn in connections_input:
            # `is not None` (not a truthy check) — resync_system deliberately differs
            # here and the two routes are kept non-identical on purpose; see the note
            # on its own connections batch below.
            from_key = conn.get("fromComponentKey")
            to_key = conn.get("toComponentKey")
            conn_rows_in.append({
                "fromMc": module_component_id_map.get(from_key) if from_key is not None else None,
                "toMc": module_component_id_map.get(to_key) if to_key is not None else None,
                "fromPort": conn.get("fromPort"), "toPort": conn.get("toPort"),
                "medium": conn.get("medium"), "label": conn.get("label"),
            })
        pv = pivot(conn_rows_in, "fromMc", "toMc", "fromPort", "toPort", "medium", "label")
        await session.execute(text("""
            INSERT INTO connections (system_id, from_module_component_id, to_module_component_id, from_port, to_port, medium, label, created_at)
            SELECT CAST(:sid AS integer), x.from_mc, x.to_mc, x.from_port, x.to_port, x.medium, x.label,
                   CAST(:created_at AS timestamptz)
            FROM unnest(
                CAST(:from_mcs AS int[]), CAST(:to_mcs AS int[]), CAST(:from_ports AS text[]),
                CAST(:to_ports AS text[]), CAST(:mediums AS text[]), CAST(:labels AS text[])
            ) AS x(from_mc, to_mc, from_port, to_port, medium, label)
        """), {
            "sid": system_id, "created_at": system_created_at,
            "from_mcs": pv["fromMc"], "to_mcs": pv["toMc"], "from_ports": pv["fromPort"],
            "to_ports": pv["toPort"], "mediums": pv["medium"], "labels": pv["label"],
        })

    await session.commit()
    return {"id": system_id}


@router.get("/{system_id}")
async def get_system(
    system_id: int,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict | None:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    system_rows = (await session.execute(
        text("""
            SELECT s.*, e.name AS encoding_name, a.name AS architecture_name
            FROM systems s
            LEFT JOIN LATERAL (
                SELECT pf.encoding_id, pf.architecture_id
                FROM system_protocols sp
                JOIN protocols p ON p.id = sp.protocol_id
                JOIN protocol_families pf ON pf.id = p.protocol_family_id
                WHERE sp.system_id = s.id
                ORDER BY sp.is_primary DESC, sp.protocol_id
                LIMIT 1
            ) pf ON true
            LEFT JOIN encodings e ON e.id = pf.encoding_id
            LEFT JOIN architectures a ON a.id = pf.architecture_id
            WHERE s.id = CAST(:id AS integer)
              AND (
                :is_admin
                OR s.user_id = :user_id
                OR s.is_public = true
              )
            LIMIT 1
        """),
        {"id": system_id, "user_id": principal.user_id, "is_admin": principal.is_admin},
    )).mappings().all()
    if not system_rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    system = dict(system_rows[0])

    protocols = (await session.execute(text("""
        SELECT p.id, p.name, pf.name AS family, sp.is_primary
        FROM system_protocols sp
        JOIN protocols p ON p.id = sp.protocol_id
        JOIN protocol_families pf ON pf.id = p.protocol_family_id
        WHERE sp.system_id = CAST(:id AS integer)
    """), {"id": system_id})).mappings().all()

    module_rows = (await session.execute(text("""
        SELECT m.id, m.name, m.firmware_revision, m.module_type_id, mt.name AS module_type
        FROM modules m JOIN module_types mt ON mt.id = m.module_type_id
        WHERE m.system_id = CAST(:id AS integer) ORDER BY m.id
    """), {"id": system_id})).mappings().all()
    module_ids = [m["id"] for m in module_rows]

    component_rows: list = []
    param_rows: list = []
    if module_ids:
        component_rows = (await session.execute(text("""
            SELECT mc.id AS mc_id, mc.module_id, mc.instance_name, mc.domain, mc.branch_side, mc.role,
                   c.id, c.name, c.vendor, c.model, c.serial_number,
                   c.component_type_id, ct.name AS component_type
            FROM module_components mc
            JOIN components c ON c.id = mc.component_id
            JOIN component_types ct ON ct.id = c.component_type_id
            WHERE mc.module_id = ANY(:module_ids)
            ORDER BY mc.module_id, mc.id
        """), {"module_ids": module_ids})).mappings().all()

        mc_ids = [r["mc_id"] for r in component_rows]
        if mc_ids:
            param_rows = (await session.execute(text("""
                SELECT module_component_id, state, param_group, key, value, unit
                FROM component_parameters
                WHERE module_component_id = ANY(:mc_ids)
                ORDER BY module_component_id, state, param_group, key
            """), {"mc_ids": mc_ids})).mappings().all()

    ideal_by_mc: dict[int, list[dict]] = {}
    characterised_by_mc: dict[int, list[dict]] = {}
    for p in param_rows:
        bucket = characterised_by_mc if p["state"] == "characterised" else ideal_by_mc
        bucket.setdefault(p["module_component_id"], []).append(dict(p))

    by_module: dict[int, list[dict]] = {}
    for r in component_rows:
        by_module.setdefault(r["module_id"], []).append({
            **dict(r),
            "parameters": ideal_by_mc.get(r["mc_id"], []),
            "characterisedParameters": characterised_by_mc.get(r["mc_id"], []),
        })

    connections = (await session.execute(text("""
        SELECT cn.medium, cn.label, cn.from_port, cn.to_port,
          mf.name AS from_module, cf.name AS from_component,
          mt2.name AS to_module, ct2.name AS to_component
        FROM connections cn
        LEFT JOIN module_components mcf ON mcf.id = cn.from_module_component_id
        LEFT JOIN modules mf ON mf.id = mcf.module_id
        LEFT JOIN components cf ON cf.id = mcf.component_id
        LEFT JOIN module_components mct ON mct.id = cn.to_module_component_id
        LEFT JOIN modules mt2 ON mt2.id = mct.module_id
        LEFT JOIN components ct2 ON ct2.id = mct.component_id
        WHERE cn.system_id = CAST(:id AS integer) ORDER BY cn.id
    """), {"id": system_id})).mappings().all()

    system_pp_rows = (await session.execute(text("""
        SELECT sp.pp_type_id AS "ppTypeId", sp.annotation, pct.name AS "ppTypeName"
        FROM system_pp sp
        JOIN pp_component_types pct ON pct.id = sp.pp_type_id
        WHERE sp.system_id = CAST(:id AS integer)
        ORDER BY sp.pp_type_id
    """), {"id": system_id})).mappings().all()

    cm_rows: list = []
    if module_ids:
        cm_rows = (await session.execute(text("""
            SELECT
                sc.countermeasure_id,
                sc.module_id,
                m.module_type_id,
                mt.name AS module_type_name,
                cm.name,
                cm.description,
                cm.countermeasure_type,
                cm.module AS cm_modules,
                cm.component_type_ids
            FROM system_countermeasures sc
            JOIN modules m ON m.id = sc.module_id
            JOIN module_types mt ON mt.id = m.module_type_id
            JOIN countermeasures cm ON cm.id = sc.countermeasure_id
            WHERE sc.module_id = ANY(:module_ids)
            ORDER BY sc.module_id, cm.name
        """), {"module_ids": module_ids})).mappings().all()

    return {
        **system,
        "protocols": [dict(r) for r in protocols],
        "modules": [{**dict(m), "components": by_module.get(m["id"], [])} for m in module_rows],
        "connections": [dict(r) for r in connections],
        "systemPp": [
            {"ppTypeId": r["ppTypeId"], "ppTypeName": r["ppTypeName"], "annotation": r["annotation"]}
            for r in system_pp_rows
        ],
        "systemCountermeasures": [dict(r) for r in cm_rows],
    }


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(
    system_id: int,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if await _existing_system_row(session, system_id, principal) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    # Cascade handles everything downstream:
    #   modules -> module_components -> component_parameters
    #   connections, system_protocols, system_countermeasures
    # components rows are shared catalog entries and must not be deleted here.
    await session.execute(text("DELETE FROM systems WHERE id = CAST(:id AS integer)"), {"id": system_id})
    await session.commit()


@router.patch("/{system_id}/visibility")
async def set_system_visibility(
    system_id: int,
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    body = await request.json()
    is_public = body.get("isPublic")
    if not isinstance(is_public, bool):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "isPublic must be a boolean")

    if await _existing_system_row(session, system_id, principal) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    await session.execute(
        text("UPDATE systems SET is_public = :is_public WHERE id = CAST(:id AS integer)"),
        {"is_public": is_public, "id": system_id},
    )
    await session.commit()
    return {"id": system_id, "isPublic": is_public}


@router.patch("/{system_id}")
async def resync_system(
    system_id: int,
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if await _existing_system_row(session, system_id, principal) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    body = await request.json()
    protocol_ids = body.get("protocolIds") or []
    system_cm_input = body.get("systemCountermeasures") or []
    # "in body" (not "is not None"): mirrors TS's `!== undefined` check exactly —
    # a key entirely absent from the JSON means "leave this relation alone",
    # which is different from the key being present (even as an empty list/null).
    system_pp_provided = "systemPp" in body
    system_pp_input = body.get("systemPp") or []
    modules_provided = "modules" in body
    modules_input = body.get("modules")
    connections_input = body.get("connections") or []

    # connections.medium is NOT NULL — reject up front, before any DELETE runs, rather
    # than letting a malformed entry fail the batched insert after existing connections
    # have already been cleared out from under the system.
    if any(not c.get("medium") for c in connections_input):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"error": "Each connection requires a medium"})

    # Ownership (user_id) and visibility (is_public) are intentionally never part of this SET
    # list — an admin editing another user's system must not be able to alter who owns it.
    await session.execute(text("""
        UPDATE systems SET
            name = :name,
            manufacturer = :manufacturer,
            toe_boundary = :toe_boundary,
            double_click_handling = :double_click_handling,
            basis_choice = :basis_choice,
            deployment = :deployment,
            detector_accepts_clicks_outside_gate = :detector_accepts_clicks_outside_gate,
            optical_path_direction = :optical_path_direction,
            local_oscillator_type = :local_oscillator_type,
            phase_randomisation_method = :phase_randomisation_method,
            reconciliation_algorithm = :reconciliation_algorithm
        WHERE id = CAST(:id AS integer)
    """), {
        "id": system_id, "name": body.get("name"), "manufacturer": body.get("manufacturer"),
        "toe_boundary": body.get("toeBoundary"),
        "double_click_handling": body.get("doubleClickHandling"),
        "basis_choice": body.get("basisChoice"),
        "deployment": body.get("deployment"),
        "detector_accepts_clicks_outside_gate": body.get("detectorAcceptsClicksOutsideGate"),
        "optical_path_direction": body.get("opticalPathDirection"),
        "local_oscillator_type": body.get("localOscillatorType"),
        "phase_randomisation_method": body.get("phaseRandomisationMethod"),
        "reconciliation_algorithm": body.get("reconciliationAlgorithm"),
    })

    # Re-sync relational data: delete-and-reinsert (only for fields present in the request body).
    await session.execute(text("DELETE FROM system_protocols WHERE system_id = CAST(:id AS integer)"), {"id": system_id})
    await session.execute(text("DELETE FROM connections WHERE system_id = CAST(:id AS integer)"), {"id": system_id})

    if system_pp_provided:
        # Targeted delete (only stages removed from the list) + upsert — never leaves a gap window.
        keep_ids = [r.get("ppTypeId") for r in system_pp_input]
        if keep_ids:
            await session.execute(
                text("DELETE FROM system_pp WHERE system_id = CAST(:id AS integer) AND pp_type_id != ALL(:keep_ids)"),
                {"id": system_id, "keep_ids": keep_ids},
            )
        else:
            await session.execute(text("DELETE FROM system_pp WHERE system_id = CAST(:id AS integer)"), {"id": system_id})

        if system_pp_input:
            # Last-write-wins de-dupe by ppTypeId: a single batched statement can't touch the
            # same ON CONFLICT target twice, unlike a per-row loop.
            pp_by_type: dict[int, str | None] = {}
            for r in system_pp_input:
                pp_by_type[r.get("ppTypeId")] = r.get("annotation") or None
            pp_rows = [{"ppTypeId": k, "annotation": v} for k, v in pp_by_type.items()]
            pv = pivot(pp_rows, "ppTypeId", "annotation")
            await session.execute(text("""
                INSERT INTO system_pp (system_id, pp_type_id, annotation)
                SELECT CAST(:id AS integer), x.pp_type_id, x.annotation
                FROM unnest(CAST(:pp_type_ids AS int[]), CAST(:annotations AS text[])) AS x(pp_type_id, annotation)
                ON CONFLICT (system_id, pp_type_id) DO UPDATE SET annotation = EXCLUDED.annotation
            """), {"id": system_id, "pp_type_ids": pv["ppTypeId"], "annotations": pv["annotation"]})

    # Resolve the PP module type id and preserve the existing PP module row across re-syncs.
    # This keeps system_countermeasures FKs pointing at the PP module intact even when
    # a client (e.g. the edit form) re-syncs hardware modules without sending PP data.
    pp_module_type_id: int | None = None
    existing_pp_module_id: int | None = None
    if modules_provided:
        pp_mt_rows = (await session.execute(
            text("SELECT id FROM module_types WHERE name = 'POST_PROCESSING' LIMIT 1")
        )).mappings().all()
        pp_module_type_id = pp_mt_rows[0]["id"] if pp_mt_rows else None
        if pp_module_type_id is not None:
            pp_mod_rows = (await session.execute(
                text("SELECT id FROM modules WHERE system_id = CAST(:id AS integer) AND module_type_id = :pp_type LIMIT 1"),
                {"id": system_id, "pp_type": pp_module_type_id},
            )).mappings().all()
            existing_pp_module_id = pp_mod_rows[0]["id"] if pp_mod_rows else None
            # Full-resync contract: any TX/RX module not present in `modulesInput` is deleted
            # here (cascading to its components/parameters/countermeasures), mirroring how
            # protocols/countermeasures/connections above are also fully replaced by whatever
            # this request sends. PP is the sole, deliberate exception (preserved above)
            # because PP-linked countermeasures can be managed without resending PP data.
            await session.execute(
                text("DELETE FROM modules WHERE system_id = CAST(:id AS integer) AND module_type_id != :pp_type"),
                {"id": system_id, "pp_type": pp_module_type_id},
            )
        else:
            await session.execute(text("DELETE FROM modules WHERE system_id = CAST(:id AS integer)"), {"id": system_id})

        # Auto-ensure PP module exists for systems created before this feature.
        if pp_module_type_id is not None and existing_pp_module_id is None:
            new_pp_row = (await session.execute(text("""
                INSERT INTO modules (system_id, module_type_id, name)
                VALUES (CAST(:id AS integer), :pp_type, 'Post-Processing')
                RETURNING id
            """), {"id": system_id, "pp_type": pp_module_type_id})).mappings().first()
            existing_pp_module_id = new_pp_row["id"]

    if protocol_ids:
        # De-dupe by protocol id (last one wins for isPrimary) — system_protocols has a
        # composite primary key, so a repeated id would otherwise abort the whole batch.
        proto_by_id: dict[int, bool] = {}
        for p in protocol_ids:
            proto_by_id[p.get("id")] = p.get("isPrimary") or False
        proto_rows = [{"protocolId": k, "isPrimary": v} for k, v in proto_by_id.items()]
        pv = pivot(proto_rows, "protocolId", "isPrimary")
        await session.execute(text("""
            INSERT INTO system_protocols (system_id, protocol_id, is_primary)
            SELECT CAST(:id AS integer), x.protocol_id, x.is_primary
            FROM unnest(CAST(:protocol_ids AS int[]), CAST(:is_primary AS boolean[])) AS x(protocol_id, is_primary)
            ON CONFLICT (system_id, protocol_id) DO NOTHING
        """), {"id": system_id, "protocol_ids": pv["protocolId"], "is_primary": pv["isPrimary"]})

    ct_rows = (await session.execute(text("SELECT id, name FROM component_types"))).mappings().all()
    component_type_name_by_id = {r["id"]: r["name"] for r in ct_rows}

    module_id_map: dict[int, int] = {}
    module_component_id_map: dict[str, int] = {}

    # ── Bulk-insert modules (excluding the preserved PP module) in one batch ──
    # A plain INSERT ... SELECT FROM unnest(...) RETURNING has no join/order-by/group-by
    # to reshuffle rows, so Postgres returns ids in the same order the arrays were built
    # — mod_rows[i] always corresponds to modules_to_insert[i].
    modules_to_insert: list[dict] = []
    if modules_provided:
        for mi, m in enumerate(modules_input or []):
            # If the wizard sent the PP module entry, map its index to the preserved row and skip insert.
            if pp_module_type_id is not None and m.get("moduleTypeId") == pp_module_type_id:
                if existing_pp_module_id is not None:
                    module_id_map[mi] = existing_pp_module_id
                continue
            modules_to_insert.append({
                "mi": mi, "moduleTypeId": m.get("moduleTypeId"), "name": m.get("name"),
                "firmwareRevision": m.get("firmwareRevision"),
            })

    if modules_to_insert:
        pv = pivot(modules_to_insert, "moduleTypeId", "name", "firmwareRevision")
        mod_rows = (await session.execute(text("""
            INSERT INTO modules (system_id, module_type_id, name, firmware_revision)
            SELECT CAST(:id AS integer), x.module_type_id, x.name, x.firmware_revision
            FROM unnest(CAST(:module_type_ids AS int[]), CAST(:names AS text[]), CAST(:firmwares AS text[]))
                AS x(module_type_id, name, firmware_revision)
            RETURNING id
        """), {
            "id": system_id, "module_type_ids": pv["moduleTypeId"], "names": pv["name"], "firmwares": pv["firmwareRevision"],
        })).mappings().all()
        for idx, entry in enumerate(modules_to_insert):
            module_id_map[entry["mi"]] = mod_rows[idx]["id"]

    # ── Bulk-insert module_components across every module, in one batch ──
    components_to_insert: list[dict] = []
    for entry in modules_to_insert:
        mi = entry["mi"]
        module_id = module_id_map[mi]
        components = (modules_input[mi] or {}).get("components") or []
        for ci, c in enumerate(components):
            if not c.get("componentId"):
                continue
            components_to_insert.append({"mi": mi, "ci": ci, "c": c, "moduleId": module_id})

    if components_to_insert:
        mc_rows_in = [{
            "moduleId": e["moduleId"], "componentId": e["c"].get("componentId"),
            "instanceName": e["c"].get("instanceName"), "domain": e["c"].get("domain"),
            "branchSide": e["c"].get("branchSide"), "role": e["c"].get("role"),
        } for e in components_to_insert]
        pv = pivot(mc_rows_in, "moduleId", "componentId", "instanceName", "domain", "branchSide", "role")
        mc_rows = (await session.execute(text("""
            INSERT INTO module_components (module_id, component_id, instance_name, domain, branch_side, role)
            SELECT x.module_id, x.component_id, x.instance_name, x.domain, x.branch_side, x.role
            FROM unnest(
                CAST(:module_ids AS int[]), CAST(:component_ids AS int[]), CAST(:instance_names AS text[]),
                CAST(:domains AS text[]), CAST(:branch_sides AS text[]), CAST(:roles AS text[])
            ) AS x(module_id, component_id, instance_name, domain, branch_side, role)
            RETURNING id
        """), {
            "module_ids": pv["moduleId"], "component_ids": pv["componentId"],
            "instance_names": pv["instanceName"], "domains": pv["domain"],
            "branch_sides": pv["branchSide"], "roles": pv["role"],
        })).mappings().all()
        for idx, entry in enumerate(components_to_insert):
            module_component_id_map[f"{entry['mi']}-{entry['ci']}"] = mc_rows[idx]["id"]

    # ── Flatten parameters for every inserted component into one batched upsert ──
    param_rows_in: list[dict] = []
    for entry in components_to_insert:
        mi, ci, c = entry["mi"], entry["ci"], entry["c"]
        mc_id = module_component_id_map[f"{mi}-{ci}"]
        ct_name = component_type_name_by_id.get(c.get("componentTypeId"))

        # Last-write-wins de-dupe by (paramGroup, key): a single batched statement can't
        # touch the same ON CONFLICT target twice (Postgres error "ON CONFLICT DO UPDATE
        # command cannot affect row a second time"), so duplicates are collapsed here.
        by_key: dict[str, dict] = {}
        for p in c.get("parameters") or []:
            by_key[f"{resolve_param_group(p.get('paramGroup'))}\x00{p.get('key')}"] = p

        for p in by_key.values():
            coerced = coerce_parameter(p.get("value"), p.get("unit"), p.get("paramGroup"), ct_name, p.get("key"))
            # This route rebuilds TX/RX modules by delete-and-reinsert (see the module DELETE
            # above), which cascades away BOTH states' parameter rows. To keep the "both
            # variants always present" invariant we re-seed 'ideal' AND 'characterised' from
            # the form values — a UI edit resets characterised to match ideal; the external
            # parser (PATCH .../characterised-parameters) re-diverges it afterwards.
            for state in ("ideal", "characterised"):
                param_rows_in.append({
                    "mcId": mc_id, "state": state, "paramGroup": coerced.param_group, "key": p.get("key"), "value": p.get("value") or "",
                    "valueText": coerced.value_text, "valueNum": coerced.value_num,
                    "valueBool": coerced.value_bool, "unit": coerced.unit,
                })

    if param_rows_in:
        pv = pivot(param_rows_in, "mcId", "state", "paramGroup", "key", "value", "valueText", "valueNum", "valueBool", "unit")
        await session.execute(text("""
            INSERT INTO component_parameters (module_component_id, state, param_group, key, value, value_text, value_num, value_bool, unit)
            SELECT x.mc_id, x.state, x.param_group, x.key, x.value, x.value_text, x.value_num, x.value_bool, x.unit
            FROM unnest(
                CAST(:mc_ids AS int[]), CAST(:states AS text[]), CAST(:param_groups AS text[]), CAST(:keys AS text[]), CAST(:values AS text[]),
                CAST(:value_texts AS text[]), CAST(:value_nums AS numeric[]), CAST(:value_bools AS boolean[]), CAST(:units AS text[])
            ) AS x(mc_id, state, param_group, key, value, value_text, value_num, value_bool, unit)
            ON CONFLICT (module_component_id, state, param_group, key)
            DO UPDATE SET
                value = EXCLUDED.value, value_text = EXCLUDED.value_text,
                value_num = EXCLUDED.value_num, value_bool = EXCLUDED.value_bool, unit = EXCLUDED.unit
        """), {
            "mc_ids": pv["mcId"], "states": pv["state"], "param_groups": pv["paramGroup"], "keys": pv["key"], "values": pv["value"],
            "value_texts": pv["valueText"], "value_nums": pv["valueNum"], "value_bools": pv["valueBool"], "units": pv["unit"],
        })

    # Insert system countermeasures after modules are created (module_id must exist).
    cm_by_key: dict[str, dict] = {}
    for r in system_cm_input:
        module_db_id = module_id_map.get(r.get("moduleIndex"))
        if module_db_id is None:
            continue
        cm_by_key[f"{module_db_id}\x00{r.get('countermeasureId')}"] = {
            "moduleDbId": module_db_id, "countermeasureId": r.get("countermeasureId"),
        }
    cm_entries = list(cm_by_key.values())
    if cm_entries:
        pv = pivot(cm_entries, "moduleDbId", "countermeasureId")
        await session.execute(text("""
            INSERT INTO system_countermeasures (module_id, countermeasure_id)
            SELECT x.module_id, x.countermeasure_id
            FROM unnest(CAST(:module_ids AS int[]), CAST(:cm_ids AS int[])) AS x(module_id, countermeasure_id)
            ON CONFLICT (module_id, countermeasure_id) DO NOTHING
        """), {"module_ids": pv["moduleDbId"], "cm_ids": pv["countermeasureId"]})

    if connections_input:
        conn_rows_in = []
        for c in connections_input:
            # Truthy check here (not the POST route's `!= None`) — a deliberate mismatch
            # between the two TS routes that this port preserves rather than harmonizes;
            # in practice fromComponentKey/toComponentKey are never legitimately "" so it
            # has no observable effect, but the two routes are not identical here in the
            # TS source and shouldn't quietly become identical in the port either.
            from_key = c.get("fromComponentKey")
            to_key = c.get("toComponentKey")
            conn_rows_in.append({
                "fromMc": module_component_id_map.get(from_key) if from_key else None,
                "toMc": module_component_id_map.get(to_key) if to_key else None,
                "fromPort": c.get("fromPort"), "toPort": c.get("toPort"),
                "medium": c.get("medium"), "label": c.get("label"),
            })
        pv = pivot(conn_rows_in, "fromMc", "toMc", "fromPort", "toPort", "medium", "label")
        await session.execute(text("""
            INSERT INTO connections (system_id, from_module_component_id, to_module_component_id, from_port, to_port, medium, label)
            SELECT CAST(:id AS integer), x.from_mc, x.to_mc, x.from_port, x.to_port, x.medium, x.label
            FROM unnest(
                CAST(:from_mcs AS int[]), CAST(:to_mcs AS int[]), CAST(:from_ports AS text[]),
                CAST(:to_ports AS text[]), CAST(:mediums AS text[]), CAST(:labels AS text[])
            ) AS x(from_mc, to_mc, from_port, to_port, medium, label)
        """), {
            "id": system_id, "from_mcs": pv["fromMc"], "to_mcs": pv["toMc"], "from_ports": pv["fromPort"],
            "to_ports": pv["toPort"], "mediums": pv["medium"], "labels": pv["label"],
        })

    await session.commit()
    return {"id": system_id}


@router.patch("/{system_id}/characterised-parameters")
async def upsert_characterised_parameters(
    system_id: int,
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Write ONLY the 'characterised' (measured) parameter values for a system.

    This is the integration point for the external parser / re-upload tool: it maps
    each component's real measured values onto the system's stored configuration without
    touching the 'ideal' (design/datasheet) set. Components are addressed by their
    module_components.instance_name (unique per module, and the same handle the export
    pipeline uses). Rows whose instanceName can't be resolved within this system are
    skipped and reported in `skipped`.

    Body: { "parameters": [ { "instanceName", "paramGroup"?, "key", "value", "unit"? }, ... ] }
    """
    if principal.user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")
    if await _existing_system_row(session, system_id, principal) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    body = await request.json()
    params_input = body.get("parameters") or []

    # Resolve instance_name -> (mc_id, component_type_name) for every named component in
    # this system, in one read. instance_name is unique per module (partial unique index),
    # but not necessarily across modules — the export IR already assumes system-wide unique
    # instance names, so we mirror that and take the first match per name.
    rows = (await session.execute(text("""
        SELECT mc.id AS mc_id, mc.instance_name, ct.name AS component_type
        FROM module_components mc
        JOIN modules m ON m.id = mc.module_id
        JOIN components c ON c.id = mc.component_id
        JOIN component_types ct ON ct.id = c.component_type_id
        WHERE m.system_id = CAST(:id AS integer) AND mc.instance_name IS NOT NULL
    """), {"id": system_id})).mappings().all()
    by_instance = {r["instance_name"]: (r["mc_id"], r["component_type"]) for r in rows}

    written = 0
    skipped: list[str] = []
    for p in params_input:
        instance_name = p.get("instanceName")
        resolved = by_instance.get(instance_name)
        if resolved is None:
            skipped.append(str(instance_name))
            continue
        mc_id, ct_name = resolved
        coerced = coerce_parameter(p.get("value"), p.get("unit"), p.get("paramGroup"), ct_name, p.get("key"))
        await session.execute(text("""
            INSERT INTO component_parameters (module_component_id, state, param_group, key, value, value_text, value_num, value_bool, unit)
            VALUES (:mc_id, 'characterised', :param_group, :key, :value, :value_text, :value_num, :value_bool, :unit)
            ON CONFLICT (module_component_id, state, param_group, key)
            DO UPDATE SET
                value = EXCLUDED.value, value_text = EXCLUDED.value_text,
                value_num = EXCLUDED.value_num, value_bool = EXCLUDED.value_bool, unit = EXCLUDED.unit
        """), {
            "mc_id": mc_id, "param_group": coerced.param_group, "key": p.get("key"),
            "value": p.get("value") or "", "value_text": coerced.value_text,
            "value_num": coerced.value_num, "value_bool": coerced.value_bool, "unit": coerced.unit,
        })
        written += 1

    await session.commit()
    return {"id": system_id, "written": written, "skipped": skipped}
