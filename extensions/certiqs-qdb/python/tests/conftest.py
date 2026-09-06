import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Must run before any `app.*` module is imported — app.core.config.Settings() and
# app.db's module-level engine both read these at import time.
#
# Order matters, and it is subtle. app.core.config uses pydantic-settings with
# `env_file=".env"`, and pydantic-settings gives REAL environment variables
# priority over the env file. So an unconditional
# `os.environ.setdefault("DATABASE_URL", <placeholder>)` here does not act as a
# fallback at all — it silently *overrides* the .env value for the whole test
# session, pointing every live-DB test at localhost. That is exactly what used
# to happen: the live-DB suites failed with connection errors that looked like a
# blocked network but were really this placeholder winning.
#
# So: load .env into the environment first, and only fill in placeholders for
# whatever is still missing.
#
# Consequence worth stating plainly: with a configured backend/.env, the suites
# marked `live_db` below run real (read-only) queries against whatever database
# that file names. Without one, DATABASE_URL keeps the placeholder value and
# those suites SKIP rather than fail — see pytest_collection_modifyitems.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_PLACEHOLDER_DATABASE_URL = "postgresql://user:pass@localhost:5432/testdb"

if _ENV_FILE.exists():
    # override=False mirrors the os.environ.setdefault semantics above: real
    # shell env still wins, so `DATABASE_URL=... pytest` can override .env.
    #
    # Wrapped broadly on purpose. A .env written by PowerShell redirection is
    # UTF-16 (with or without a BOM), which load_dotenv fails on with either
    # UnicodeDecodeError or ValueError depending on the exact encoding — at
    # conftest *import* time, which would abort collection of every test in
    # this directory, including the pure-unit ones that never touch a
    # database. An unreadable .env must degrade to "no .env", not take the
    # whole suite down.
    try:
        load_dotenv(_ENV_FILE, override=False, encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"conftest: ignoring unreadable {_ENV_FILE} ({exc.__class__.__name__}: {exc})")

os.environ.setdefault("DATABASE_URL", _PLACEHOLDER_DATABASE_URL)
os.environ.setdefault("INTERNAL_AUTH_SECRET", "test-secret-not-for-production-0123456789")

_LIVE_DB_CONFIGURED = os.environ["DATABASE_URL"] != _PLACEHOLDER_DATABASE_URL


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_db: test issues real queries against the configured DATABASE_URL. "
        "Skipped automatically when only the placeholder URL is set.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip (don't fail) the live-DB suites when no real database is configured.

    Without this, a sandbox/CI box with no backend/.env and no outbound 5432 turns
    every live-DB test red with a connection error, which buries real failures in
    the pure-unit suites.
    """
    if _LIVE_DB_CONFIGURED:
        return
    skip_live_db = pytest.mark.skip(
        reason="no real DATABASE_URL configured (backend/.env absent or unreadable) — "
        "live-DB test skipped",
    )
    for item in items:
        if "live_db" in item.keywords:
            item.add_marker(skip_live_db)
