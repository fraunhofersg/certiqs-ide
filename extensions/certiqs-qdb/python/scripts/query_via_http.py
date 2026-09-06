"""Ad-hoc DB verification when raw Postgres (port 5432) is blocked on the
current network but HTTPS (443) isn't — e.g. a restrictive router/ISP that
lets web traffic through but drops the DB wire protocol port outright.

Talks to the same "SQL over HTTPS" endpoint the frontend's
`@neondatabase/serverless` driver uses (see src/db/index.ts). Shares its
endpoint-derivation and OID-typed decoding with `app/db_http.py` (the
`NEON_HTTP_FALLBACK` session shim), so results come back as typed Python values
(ints, bools, arrays) rather than raw strings. This is a manual-verification
CLI only — the running app / pytest suite go through `app.db.get_session` (which
selects the same HTTP path when `NEON_HTTP_FALLBACK=1`).

Usage:
    ./.venv/Scripts/python.exe scripts/query_via_http.py "SELECT id, name FROM systems LIMIT 5"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from sqlalchemy import text  # noqa: E402

from app.db_http import HttpSession  # noqa: E402

load_dotenv()


async def run_query(query: str) -> None:
    session = HttpSession()
    try:
        result = await session.execute(text(query))
        rows = result.mappings().all()
    finally:
        await session.aclose()
    for row in rows:
        print(row)
    print(f"({len(rows)} row(s))")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    asyncio.run(run_query(sys.argv[1]))
