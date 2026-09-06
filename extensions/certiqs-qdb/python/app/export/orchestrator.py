"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/index.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Orchestrator — assemble -> ir -> enrich -> resolve -> validate -> emit -> package.
Two entry points back the API routes: prepare_export (collect the gaps for the
prompt modal) and run_export (apply answers, validate, emit the zip).

Named orchestrator.py rather than index.py (unlike emit/index.py, a plain
submodule) since app/export/__init__.py already serves as this package's own
entry point — a second file literally named index.py here would invite
confusing it with that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.camel_model import CamelModel
from app.export.assemble import get_export_aggregate
from app.export.build import build_model
from app.export.emit.emitters import EmittedFile
from app.export.emit.index import run_emitters
from app.export.package import package_zip, safe_name
from app.export.params.resolve import MissingParam, apply_resolved_values, collect_missing_parameters
from app.export.validate import Issue, has_errors, validate_model


class MissingParamDTO(CamelModel):
    """Serializable shape sent to the client prompt modal (no functions/DB ids)."""

    location: str
    label: str
    field: str
    unit: str | None = None
    type: str
    hard_min: float | None = None
    hard_max: float | None = None
    soft_min: float | None = None
    soft_max: float | None = None
    typical: float | str | bool | None
    required: bool
    description: str
    source: str


def _to_dto(m: MissingParam) -> MissingParamDTO:
    return MissingParamDTO(
        location=m.location, label=m.label, field=m.spec.field, unit=m.spec.unit, type=m.spec.type,
        hard_min=m.spec.hard_min, hard_max=m.spec.hard_max, soft_min=m.spec.soft_min, soft_max=m.spec.soft_max,
        typical=m.spec.typical, required=m.spec.required, description=m.spec.description, source=m.spec.source,
    )


# Both variants are stored on every system and both are emitted into the export zip.
EXPORT_VARIANTS = ("ideal", "characterised")


class PrepareResult(CamelModel):
    found: bool
    system_name: str | None = None
    manifest_name: str | None = None
    missing: list[MissingParamDTO] | None = None


async def prepare_export(session: AsyncSession, system_id: int, user_id: str) -> PrepareResult:
    """Stage up to collection — returns the gaps the modal must prompt for.

    Collects the UNION of missing required params across both variants (deduped by
    location — a gap's location is `<target>.<field>`, independent of which state's
    values fill it), so one prompt round covers whichever variant is missing it."""
    system_name: str | None = None
    manifest_name: str | None = None
    missing_by_location: dict[str, MissingParam] = {}
    for variant in EXPORT_VARIANTS:
        agg = await get_export_aggregate(session, system_id, user_id, variant)
        if agg is None:
            return PrepareResult(found=False)
        system_name = agg.system.get("name")
        built = build_model(agg)
        manifest_name = built.model.manifest_name
        for m in collect_missing_parameters(built.model):
            missing_by_location.setdefault(m.location, m)
    return PrepareResult(
        found=True,
        system_name=system_name,
        manifest_name=manifest_name,
        missing=[_to_dto(m) for m in missing_by_location.values()],
    )


@dataclass
class RunExportNotFound:
    found: Literal[False] = False


@dataclass
class RunExportInvalid:
    issues: list[Issue]
    found: Literal[True] = True
    ok: Literal[False] = False


@dataclass
class RunExportSuccess:
    zip: bytes
    filename: str
    warnings: list[Issue]
    found: Literal[True] = True
    ok: Literal[True] = True


RunResult = Union[RunExportNotFound, RunExportInvalid, RunExportSuccess]


async def run_export(
    session: AsyncSession, system_id: int, user_id: str, param_values: dict[str, object]
) -> RunResult:
    """Full pipeline for BOTH variants: re-assemble, apply answers, validate, emit each
    into its own folder, then zip together (or report errors).

    The same prompt answers (keyed by variant-independent location) are applied to both
    variants' IRs. Validation errors from either variant abort the whole export; warnings
    are merged."""
    system_name: str | None = None
    groups: list[tuple[str, list[EmittedFile]]] = []
    warnings: list[Issue] = []
    for variant in EXPORT_VARIANTS:
        agg = await get_export_aggregate(session, system_id, user_id, variant)
        if agg is None:
            return RunExportNotFound()
        system_name = agg.system.get("name")

        built = build_model(agg)
        missing = collect_missing_parameters(built.model)
        apply_resolved_values(built.model, missing, param_values or {})

        issues = validate_model(built.model, built.connections)
        if has_errors(issues):
            return RunExportInvalid(issues=issues)
        warnings.extend(i for i in issues if i.level == "warning")

        files: list[EmittedFile] = run_emitters(built.model, built.connections)
        groups.append((variant, files))

    zip_bytes = package_zip(groups)
    return RunExportSuccess(
        zip=zip_bytes,
        filename=f"{safe_name(system_name)}-cosim-manifest.zip",
        warnings=warnings,
    )
