"""Rebuild the College Data Portal SQLite DB from its old Litestream replica (one-time migration).

The portal used to run on Cloud Run in the retired Firebase/GCP project `techdrona-colleges-data`,
replicating its SQLite DB with Litestream to gs://techdrona-colleges-data-db/db. Litestream has no
Windows build, so this script does `litestream restore` by hand for ONE generation:

  snapshot (LZ4 frame) -> database file, then each WAL index (its LZ4 segments concatenated in
  offset order) is written as <db>-wal and checkpointed by SQLite. Litestream's bookkeeping tables
  (_litestream_seq, _litestream_lock) are dropped at the end.

Usage (needs `pip install lz4`; read-only on the bucket):
  gcloud storage ls -l -r gs://techdrona-colleges-data-db/db/   # newest generation = newest snapshot
  gcloud storage cp -r gs://techdrona-colleges-data-db/db ./replica
  python scripts/college-data/restore_litestream_snapshot.py ./replica/db/generations/<id> out.db

The output is a consistent, checkpointed file (journal_mode=DELETE, no -wal) that is safe to copy.
Then install it: locally copy to apps/college-data/portal/data/techdrona.db (server stopped, and
delete any old techdrona.db-wal / -shm next to it);
on the VM: `sudo bash infra/gcp-demo/vm.sh portal-import out.db`. See docs/college-data-portal.md.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import lz4.frame  # type: ignore[import-not-found]

SEGMENT = re.compile(r"^([0-9a-f]{8})_([0-9a-f]{8})\.wal\.lz4$")


def restore(generation: Path, out: Path) -> None:
    snaps = sorted((generation / "snapshots").glob("*.snapshot.lz4"))
    if not snaps:
        raise SystemExit(f"no snapshot in {generation}")
    snap = snaps[-1]
    snap_index = int(snap.name.split(".")[0], 16)
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.write_bytes(lz4.frame.decompress(snap.read_bytes()))

    by_index: dict[int, list[tuple[int, Path]]] = {}
    for f in (generation / "wal").glob("*.wal.lz4"):
        m = SEGMENT.match(f.name)
        if m:
            by_index.setdefault(int(m.group(1), 16), []).append((int(m.group(2), 16), f))
    applied = 0
    indexes = sorted(i for i in by_index if i >= snap_index)
    # A gap (missing index or segment) would make SQLite stop at the broken checksum chain and
    # silently drop every later commit: refuse instead.
    if indexes and indexes != list(range(snap_index, indexes[-1] + 1)):
        raise SystemExit(f"WAL indexes are not consecutive from the snapshot ({snap_index}): {indexes}")
    for index in indexes:
        parts = []
        expected = 0
        for offset, p in sorted(by_index[index]):
            if offset != expected:
                raise SystemExit(f"WAL index {index:08x}: segment at offset {offset:#x}, expected {expected:#x} (missing segment)")
            data = lz4.frame.decompress(p.read_bytes())
            parts.append(data)
            expected += len(data)
        wal = b"".join(parts)
        Path(f"{out}-wal").write_bytes(wal)
        con = sqlite3.connect(out)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        applied += 1

    con = sqlite3.connect(out)
    con.execute("DROP TABLE IF EXISTS _litestream_seq")
    con.execute("DROP TABLE IF EXISTS _litestream_lock")
    con.commit()
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("VACUUM")
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    counts = {
        t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        for t in ("colleges", "branches", "contacts", "people", "enrollments", "calls", "followups", "targets", "audit_log")
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
    }
    last = con.execute("SELECT MAX(at) FROM audit_log").fetchone()[0]
    con.close()
    for suffix in ("-wal", "-shm"):
        Path(f"{out}{suffix}").unlink(missing_ok=True)
    print(f"snapshot {snap.name}, WAL indexes applied: {applied}, integrity: {ok}")
    print(f"rows: {counts}")
    print(f"newest audit entry: {last}")
    if ok != "ok":
        raise SystemExit("integrity check FAILED")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    restore(Path(sys.argv[1]), Path(sys.argv[2]))
