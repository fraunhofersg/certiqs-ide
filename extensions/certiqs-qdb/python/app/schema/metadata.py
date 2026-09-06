"""Shared SQLAlchemy Core MetaData for the query-only schema mirror.

Drizzle remains the source of truth for migrations and seeds — schema
changes are still made by editing `src/db/schema/` and running
`npx drizzle-kit push` there, never here. Table definitions live in
per-table-file modules (systems.py, attacks.py, ...) mirroring the
corresponding `src/db/schema/*.ts` file 1:1 for easy side-by-side diffing;
all of them register against this one `metadata` object.

Add tables/columns incrementally as each migration phase needs them — don't
front-load columns with no caller yet. After adding or changing a table,
run `python scripts/check_schema_drift.py` to confirm it still matches the
live schema.
"""

from sqlalchemy import MetaData

metadata = MetaData()
