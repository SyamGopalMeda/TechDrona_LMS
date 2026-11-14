"""``python -m app.core.firestore.backfill <module>... [--verify-only] [--replace]``.

Reads Postgres through ``DATABASE_URL`` (read-only: one transaction that is rolled back) and
writes the Firestore selected by ``FIRESTORE_EMULATOR_HOST`` / ``FIREBASE_PROJECT_ID``.
Exit code 1 when verification finds a difference.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.firestore.backfill import backfill, verify


async def _main(modules: list[str], verify_only: bool, replace: bool) -> int:
    from app.core.db import get_sessionmaker
    from app.core.firestore.client import close_client

    ok = True
    try:
        async with get_sessionmaker()() as session:
            async with session.begin():
                for m in modules:
                    if not verify_only:
                        written = await backfill(session, m, replace=replace)
                        print(json.dumps({"module": m, "written": written}))
                    for rep in await verify(session, m):
                        ok &= rep.ok
                        print(json.dumps({"module": m, **rep.as_dict()}))
                await session.rollback()
    finally:
        await close_client()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.core.firestore.backfill")
    ap.add_argument("modules", nargs="+")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--replace", action="store_true", help="delete each collection first (reseed)")
    a = ap.parse_args(argv)
    return asyncio.run(_main(a.modules, a.verify_only, a.replace))


if __name__ == "__main__":
    sys.exit(main())
