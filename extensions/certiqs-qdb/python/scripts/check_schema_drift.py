"""Fail loudly if app/schema/metadata.py drifts from the live Postgres schema
(e.g. someone ran `drizzle-kit push` on the TS side and forgot to update the
Python mirror). Run manually for now: `python scripts/check_schema_drift.py`.
Wire into CI once this repo has a CI pipeline.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import MetaData  # noqa: E402

from app.db import engine  # noqa: E402
from app.schema.metadata import metadata as mirrored_metadata  # noqa: E402


async def check() -> int:
    live = MetaData()
    async with engine.connect() as conn:
        await conn.run_sync(live.reflect)

    mismatches: list[str] = []
    for table_name, mirrored_table in mirrored_metadata.tables.items():
        live_table = live.tables.get(table_name)
        if live_table is None:
            mismatches.append(f"{table_name}: missing in live DB")
            continue

        mirrored_cols = {c.name for c in mirrored_table.columns}
        live_cols = {c.name for c in live_table.columns}
        if missing := mirrored_cols - live_cols:
            mismatches.append(f"{table_name}: columns {sorted(missing)} not found in live DB")
        if extra := live_cols - mirrored_cols:
            mismatches.append(f"{table_name}: live DB has undeclared columns {sorted(extra)}")

    if mismatches:
        print("Schema drift detected:")
        for line in mismatches:
            print(f"  - {line}")
        return 1

    print(f"OK - {len(mirrored_metadata.tables)} mirrored table(s) match the live schema.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(check()))
