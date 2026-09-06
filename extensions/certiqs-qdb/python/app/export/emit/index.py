"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/emit/index.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Emitter registry — one entry per concern file. Adding/removing a file is a
one-line change here. emit_top_level runs LAST and reads the produced filenames.
"""

from __future__ import annotations

from collections.abc import Callable

from app.export.emit.emitters import (
    EmittedFile,
    emit_alice,
    emit_bob,
    emit_channels,
    emit_cosim,
    emit_digital,
    emit_post_processing,
    emit_protocol,
    emit_source,
    emit_top_level,
)
from app.export.ir import ExportFile, ExportModel, ResolvedConnection

Emitter = Callable[[ExportModel, list[ResolvedConnection]], EmittedFile]

_CONCERN_EMITTERS: list[Emitter] = [
    emit_protocol,        # 01
    emit_source,          # 02
    emit_alice,           # 03
    emit_bob,             # 04
    emit_channels,        # 05
    emit_digital,         # 06
    emit_post_processing,  # 07
    emit_cosim,           # 08
]


def run_emitters(model: ExportModel, connections: list[ResolvedConnection]) -> list[EmittedFile]:
    """Run all emitters and prepend the generated top-level file (00)."""
    concern_files = [e(model, connections) for e in _CONCERN_EMITTERS]
    filenames: list[ExportFile] = [f.filename for f in concern_files]
    top = emit_top_level(model, filenames)
    return [top, *concern_files]
