"""Sole implementation of this export stage.

Originally a line-by-line port of src/lib/export/package.ts; that TS oracle has since been
retired, so there is nothing left to keep in sync with.

Stage 6 — Package. Zips the 9 split files (the canonical primary deliverable).
"""

from __future__ import annotations

import io
import re
import zipfile

from app.export.emit.emitters import EmittedFile


def package_zip(groups: list[tuple[str, list[EmittedFile]]]) -> bytes:
    """Bundle one or more variant file-groups into a single zip and return the bytes.

    Each group is (folder_prefix, files); an empty prefix writes at the zip root.
    The export emits both variants, so groups is e.g.
    [("ideal", [...]), ("characterised", [...])] -> ideal/00_toplevel.yaml, etc."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for prefix, files in groups:
            for f in files:
                name = f"{prefix}/{f.filename}" if prefix else f.filename
                zf.writestr(name, f.content)
    return buf.getvalue()


_DISALLOWED_RE = re.compile(r"[^\w\s-]", re.ASCII)
_WHITESPACE_RE = re.compile(r"\s+", re.ASCII)


def safe_name(name: str | None) -> str:
    """A filesystem/URL-safe basename derived from the system name (mirrors exportXlsx)."""
    base = name or "system"
    base = _DISALLOWED_RE.sub("", base).strip()
    base = _WHITESPACE_RE.sub("-", base)
    return base.lower() or "system"
