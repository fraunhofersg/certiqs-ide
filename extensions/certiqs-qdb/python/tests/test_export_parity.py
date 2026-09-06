"""Snapshot regression harness for the export pipeline (assemble -> build ->
emit): runs this Python implementation against a real seeded system in the live
DB and diffs each emitted file's content against a frozen known-good fixture.

The TS export oracle (`src/lib/export/*`) and its dump script have been retired
— Python is now the sole implementation, so this is a snapshot test rather than
a cross-language parity test. Same arrangement as test_search_parity.py. There
is no longer a script to regenerate the fixture from; to reseed it, capture
`run_emitters(...)` output manually in the format described below.

How the current fixture was established (2026-08): it is Python's own output,
but it was cross-validated against the last TS-generated fixture before being
frozen. Comparing *parsed* YAML (byte equality is meaningless across the two
emitters — see the "cosmetics deferred" note in app/export/emit/yaml_.py), 6 of
9 files were semantically identical and the other 3 differed only in these two
understood ways:

  * splitting_ratio (2 leaves) — TS emitted `50:50` UNQUOTED, which YAML 1.1
    resolves as a sexagesimal integer (50*60+50 = 3050). Python quotes it, so it
    round-trips as the string "50:50". Python is correct here; the old oracle was
    silently corrupting this value.
  * exponent zero-padding (9 leaves) — Python's repr() emits `5e-08` where JS's
    toString() emitted `5e-8`. Both forms lack a decimal point, so a YAML 1.1
    parser loads BOTH as strings rather than floats; this is a long-standing
    trait of the emitted manifests, not something the port introduced. See the
    known issue noted in docs/PYTHON_BACKEND.md.

So the baseline is Python's output, checked to differ from the historical
TS-verified output only where Python is right or where both are equivalent.

Deliberately skips the parameter-resolution/prompt step (collect_missing_
parameters / apply_resolved_values) — that step depends on user-supplied
answers, not on anything the engine derives, so it's outside what this harness
needs to prove. assemble -> build -> emit is the fully deterministic, DB-only
path.

Fixture is keyed by whatever id "BBM92 Co-Simulation System" currently has in
the live DB, not a fixed number — it drifted from 26 to 27 after a reseed. If it
drifts again, check `SELECT id FROM systems WHERE name = 'BBM92 Co-Simulation
System'`, rename the fixture to export_expected_<newId>.json, and update
_FIXTURE_PATH below.

Fixture format: {"systemId", "variants": {"ideal": [files], "characterised":
[files]}} — every system stores both parameter variants and the export emits
one manifest per variant, so the harness diffs each variant independently.
"""

import json
from pathlib import Path

import pytest

from app.db import get_session
from app.export.assemble import get_export_aggregate
from app.export.build import build_model
from app.export.emit.index import run_emitters

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURE_PATH = FIXTURES_DIR / "export_expected_27.json"

# Every test here queries the live DB, so the whole module skips when only the
# placeholder DATABASE_URL is set (see conftest.pytest_collection_modifyitems).
pytestmark = pytest.mark.live_db

if not _FIXTURE_PATH.exists():
    pytest.skip(
        "export_expected_27.json is missing — it is a checked-in frozen snapshot, "
        "so restore it from git rather than regenerating it.",
        allow_module_level=True,
    )

_EXPECTED = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

if "variants" not in _EXPECTED:
    # Guard against a regression to the pre-dual-variant {systemId, files} shape.
    # The fixture sat in that stale shape for a while and silently skipped this
    # whole suite, so fail loudly rather than skipping if it ever comes back.
    raise AssertionError(
        "export_expected_27.json is in the old single-variant {systemId, files} format. "
        "Regenerate it in the dual-variant shape: run get_export_aggregate -> build_model "
        "-> run_emitters for BOTH variants against a live DB and write "
        '{"systemId": 27, "variants": {"ideal": [...], "characterised": [...]}}.'
    )


@pytest.fixture
async def session():
    async for s in get_session():
        yield s


@pytest.mark.parametrize("variant", ["ideal", "characterised"])
async def test_python_export_matches_frozen_snapshot_for_system_27(session, variant):
    system_id = int(_EXPECTED["systemId"])
    agg = await get_export_aggregate(session, system_id, "__export_parity_harness__", variant)
    assert agg is not None, f"system {system_id} not found/visible — check it's still seeded and public"

    built = build_model(agg)
    files = run_emitters(built.model, built.connections)

    actual_by_name = {f.filename: f.content for f in files}
    expected_by_name = {f["filename"]: f["content"] for f in _EXPECTED["variants"][variant]}

    assert set(actual_by_name) == set(expected_by_name)
    for filename, expected_content in expected_by_name.items():
        assert actual_by_name[filename] == expected_content, f"Mismatch in {variant}/{filename}"
