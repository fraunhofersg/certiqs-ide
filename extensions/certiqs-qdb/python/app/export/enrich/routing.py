"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/enrich/routing.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

§4 Routing — which entity goes in which file.

The split is finer than TX/RX/NULL, so route on (subsystem key, domain, role)
via data-driven rules rather than a switch on module_type_id. Subsystems are
DERIVED from the modules the system actually has (the central entanglement
source falls out as its own node) — nothing is hardcoded to "two receivers".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.export.ir import ExportFile, SubsystemKey

if TYPE_CHECKING:
    from app.export.assemble import RawModule


def _slugify(s: str) -> str:
    # re.ASCII: JS's \w is ASCII-only by default, unlike Python's Unicode-matching default.
    return re.sub(r"^_+|_+$", "", re.sub(r"[^\w]+", "_", s.lower(), flags=re.ASCII), flags=re.ASCII)


@dataclass
class SubsystemInfo:
    key: SubsystemKey
    name: str  # canonical manifest node name (from module.firmware_revision slug)
    role: str


_SOURCE_RE = re.compile(r"\b(source|central|entangle)")
_ALICE_RE = re.compile(r"alice")
_BOB_RE = re.compile(r"bob")


def subsystem_for_module(mod: RawModule) -> SubsystemInfo:
    """Derive the composition node for a module from its type + firmware slug."""
    name = (mod.firmware_revision or "").strip() or _slugify(mod.name)
    if mod.module_type == "POST_PROCESSING":
        return SubsystemInfo(key="post_processing", name=name or "post_processing", role="post_processing")
    hay = f"{name} {mod.name}".lower()
    if _SOURCE_RE.search(hay):
        return SubsystemInfo(key="source", name=name, role="entanglement_source")
    if _ALICE_RE.search(hay):
        return SubsystemInfo(key="alice", name=name, role="measurement_station")
    if _BOB_RE.search(hay):
        return SubsystemInfo(key="bob", name=name, role="measurement_station")
    return SubsystemInfo(key="unassigned", name=name, role=_slugify(mod.name) or "node")


# Digital roles that belong in the post-processing file rather than 06_digital.
_POSTPROC_ROLE_RE = re.compile(r"(postproc|crypto|privacy|reconcil|error_correct)", re.IGNORECASE)


def file_for_instance(subsystem: SubsystemKey, domain: str, role: str | None) -> ExportFile:
    """Assign an instance to its output file from (subsystem, domain, role)."""
    if domain == "digital":
        if role and _POSTPROC_ROLE_RE.search(role):
            return "07_post_processing.yaml"
        return "06_digital.yaml"
    if subsystem == "source":
        return "02_source_central.yaml"
    if subsystem == "alice":
        return "03_alice_node.yaml"
    if subsystem == "bob":
        return "04_bob_node.yaml"
    return "02_source_central.yaml"
