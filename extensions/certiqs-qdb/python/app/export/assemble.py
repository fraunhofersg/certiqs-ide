"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/assemble.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Stage 1 — Assemble. One hydrated read of the system aggregate.

This is a dedicated export query (not the [id]/route.ts GET shape): the
exporter needs each connection endpoint's `instance_name` to resolve the
"<instance>.<netName>" tokens the whole IR is built on, and the module's
`firmware_revision` slug (the manifest subsystem name), neither of which the
GET route returns. Kept self-contained here to avoid disturbing the working
edit-form contract. No YAML/IR concerns leak into this layer.

Like get_system_features.py (Phase 1), this uses parameterized `text()`
queries rather than the SQLAlchemy Core table mirror — these queries are
fixed, not dynamically composed, so there's no need for typed Column objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RawParam:
    param_group: str
    key: str
    value: str
    unit: str | None


@dataclass
class RawComponent:
    mc_id: int
    module_id: int
    instance_name: str | None
    domain: str | None
    branch_side: str | None
    role: str | None
    component_type: str
    vendor: str | None
    model: str | None
    parameters: list[RawParam] = field(default_factory=list)


@dataclass
class RawModule:
    id: int
    name: str
    firmware_revision: str | None
    module_type: str
    components: list[RawComponent] = field(default_factory=list)


@dataclass
class RawConnection:
    medium: str
    label: str | None
    from_port: str | None
    to_port: str | None
    from_instance: str | None
    from_module_slug: str | None
    from_domain: str | None
    to_instance: str | None
    to_module_slug: str | None
    to_domain: str | None


@dataclass
class RawSystemPp:
    pp_type_id: int
    pp_type_name: str
    annotation: str | None


@dataclass
class RawProtocol:
    id: int
    name: str
    family: str
    encoding: str | None
    is_primary: bool


@dataclass
class SystemAggregate:
    system: dict
    protocols: list[RawProtocol]
    modules: list[RawModule]
    connections: list[RawConnection]
    system_pp: list[RawSystemPp]


async def get_export_aggregate(
    session: AsyncSession, system_id: int, user_id: str, variant: str = "characterised"
) -> SystemAggregate | None:
    """Hydrated aggregate read for a single system, scoped to the caller's visibility.
    Returns None if the system does not exist or the user cannot see it.

    `variant` selects which parameter set ('ideal' | 'characterised') hydrates each
    component — every system stores both. The export emits one manifest per variant."""
    system_rows = (await session.execute(
        text("SELECT * FROM systems WHERE id = CAST(:id AS integer) AND (user_id = :user_id OR is_public = true) LIMIT 1"),
        {"id": system_id, "user_id": user_id},
    )).mappings().all()
    system = dict(system_rows[0]) if system_rows else None
    if system is None:
        return None

    protocol_rows = (await session.execute(text("""
        SELECT p.id, p.name, pf.name AS family, e.name AS encoding, sp.is_primary
        FROM system_protocols sp
        JOIN protocols p ON p.id = sp.protocol_id
        JOIN protocol_families pf ON pf.id = p.protocol_family_id
        LEFT JOIN encodings e ON e.id = pf.encoding_id
        WHERE sp.system_id = CAST(:id AS integer)
        ORDER BY sp.is_primary DESC, p.id
    """), {"id": system_id})).mappings().all()

    module_rows = (await session.execute(text("""
        SELECT m.id, m.name, m.firmware_revision, mt.name AS module_type
        FROM modules m JOIN module_types mt ON mt.id = m.module_type_id
        WHERE m.system_id = CAST(:id AS integer) ORDER BY m.id
    """), {"id": system_id})).mappings().all()

    module_ids = [m["id"] for m in module_rows]

    component_rows: list = []
    param_rows: list = []
    if module_ids:
        component_rows = (await session.execute(text("""
            SELECT mc.id AS mc_id, mc.module_id, mc.instance_name, mc.domain, mc.branch_side, mc.role,
                   ct.name AS component_type, c.vendor, c.model
            FROM module_components mc
            JOIN components c ON c.id = mc.component_id
            JOIN component_types ct ON ct.id = c.component_type_id
            WHERE mc.module_id = ANY(:module_ids)
            ORDER BY mc.module_id, mc.id
        """), {"module_ids": module_ids})).mappings().all()

        mc_ids = [r["mc_id"] for r in component_rows]
        if mc_ids:
            param_rows = (await session.execute(text("""
                SELECT module_component_id, param_group, key, value, unit
                FROM component_parameters
                WHERE module_component_id = ANY(:mc_ids) AND state = :variant
                ORDER BY module_component_id, param_group, key
            """), {"mc_ids": mc_ids, "variant": variant})).mappings().all()

    params_by_mc: dict[int, list[RawParam]] = {}
    for p in param_rows:
        params_by_mc.setdefault(p["module_component_id"], []).append(
            RawParam(param_group=p["param_group"], key=p["key"], value=p["value"], unit=p["unit"])
        )

    components_by_module: dict[int, list[RawComponent]] = {}
    for r in component_rows:
        components_by_module.setdefault(r["module_id"], []).append(RawComponent(
            mc_id=r["mc_id"], module_id=r["module_id"], instance_name=r["instance_name"],
            domain=r["domain"], branch_side=r["branch_side"], role=r["role"],
            component_type=r["component_type"], vendor=r["vendor"], model=r["model"],
            parameters=params_by_mc.get(r["mc_id"], []),
        ))

    connection_rows = (await session.execute(text("""
        SELECT cn.medium, cn.label, cn.from_port, cn.to_port,
          mcf.instance_name AS from_instance, mf.firmware_revision AS from_module_slug, mcf.domain AS from_domain,
          mct.instance_name AS to_instance, mt2.firmware_revision AS to_module_slug, mct.domain AS to_domain
        FROM connections cn
        LEFT JOIN module_components mcf ON mcf.id = cn.from_module_component_id
        LEFT JOIN modules mf ON mf.id = mcf.module_id
        LEFT JOIN module_components mct ON mct.id = cn.to_module_component_id
        LEFT JOIN modules mt2 ON mt2.id = mct.module_id
        WHERE cn.system_id = CAST(:id AS integer) ORDER BY cn.id
    """), {"id": system_id})).mappings().all()

    system_pp_rows = (await session.execute(text("""
        SELECT sp.pp_type_id, pct.name AS pp_type_name, sp.annotation
        FROM system_pp sp
        JOIN pp_component_types pct ON pct.id = sp.pp_type_id
        WHERE sp.system_id = CAST(:id AS integer)
        ORDER BY sp.pp_type_id
    """), {"id": system_id})).mappings().all()

    return SystemAggregate(
        system=system,
        protocols=[
            RawProtocol(id=p["id"], name=p["name"], family=p["family"], encoding=p["encoding"], is_primary=p["is_primary"])
            for p in protocol_rows
        ],
        modules=[
            RawModule(
                id=m["id"], name=m["name"], firmware_revision=m["firmware_revision"], module_type=m["module_type"],
                components=components_by_module.get(m["id"], []),
            )
            for m in module_rows
        ],
        connections=[
            RawConnection(
                medium=c["medium"], label=c["label"], from_port=c["from_port"], to_port=c["to_port"],
                from_instance=c["from_instance"], from_module_slug=c["from_module_slug"], from_domain=c["from_domain"],
                to_instance=c["to_instance"], to_module_slug=c["to_module_slug"], to_domain=c["to_domain"],
            )
            for c in connection_rows
        ],
        system_pp=[
            RawSystemPp(pp_type_id=p["pp_type_id"], pp_type_name=p["pp_type_name"], annotation=p["annotation"])
            for p in system_pp_rows
        ],
    )
