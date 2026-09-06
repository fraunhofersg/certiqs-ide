"""Frozen-snapshot regression test for the search engine (originally the plan's
Phase 2.5 cross-language parity harness). It runs the condition-tree corpus in
search_cases.json through this Python run_search() against a live DB and diffs
the returned row-ID sets against the known-good expectations in
search_expected.json. The corpus is designed so the comparison is meaningful
regardless of what's exactly seeded (e.g. "does an unknown user ID see only
public systems", not "does this specific system appear").

The TS search engine (src/lib/search/compileSearchQuery.ts) that originally
GENERATED these expectations has since been retired — Python is now the sole
source of truth — so search_expected.json is a frozen snapshot with no TS side
left to regenerate it from. If the Python engine changes intentionally, reseed
it by capturing run_search() output directly against the pinned dataset.
(This sandbox has no outbound Postgres access, so the test skips here.)
"""

import json
from pathlib import Path

import pytest

from app.db import get_session
from app.search.compile import SearchOptions, run_search
from app.search.types import ConditionGroup

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Every test here queries the live DB, so the whole module skips when only the
# placeholder DATABASE_URL is set (see conftest.pytest_collection_modifyitems).
pytestmark = pytest.mark.live_db


def _load_cases() -> list[dict]:
    return json.loads((FIXTURES_DIR / "search_cases.json").read_text(encoding="utf-8"))


CASES = _load_cases()

_expected_path = FIXTURES_DIR / "search_expected.json"
if not _expected_path.exists():
    pytest.skip(
        "search_expected.json (frozen snapshot) is missing — it should be "
        "committed alongside search_cases.json; the TS generator that once "
        "produced it has been retired.",
        allow_module_level=True,
    )

EXPECTED = {entry["name"]: entry for entry in json.loads(_expected_path.read_text(encoding="utf-8"))}


@pytest.fixture
async def session():
    async for s in get_session():
        yield s


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
async def test_python_matches_real_ts_search_results(case: dict, session):
    expected = EXPECTED[case["name"]]
    if "error" in expected:
        pytest.skip(f"TS-side fixture recorded an error for {case['name']!r}: {expected['error']}")

    tree = ConditionGroup.model_validate(case["tree"])
    opts = SearchOptions(case.get("userId"), case.get("limit", 25), case.get("offset", 0))

    result = await run_search(session, case["domain"], tree, opts)

    actual_ids = [row["id"] if "id" in row else row["code"] for row in result.rows]
    assert actual_ids == expected["ids"], f"ID mismatch for {case['name']}"
    assert result.has_more == expected["hasMore"], f"hasMore mismatch for {case['name']}"

    if "allPublic" in expected:
        actual_all_public = all(row["isPublic"] for row in result.rows)
        assert actual_all_public == expected["allPublic"], f"visibility-guard mismatch for {case['name']}"


def test_fixture_and_expected_files_cover_the_same_cases():
    assert {c["name"] for c in CASES} == set(EXPECTED)
