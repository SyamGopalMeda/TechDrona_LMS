"""Register / search parity on Firestore (engage activity list): the Firestore result equals the
same SQL run by SQLite over the fixture rows (``title ILIKE '%term%'`` with the term escaped, type
filter, soft delete, ``created_at DESC``, limit). Emulator only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from tests.engage.test_fs_repo import _activity
from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_registers import ids, sqldb

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


async def test_activity_list_matches_sql(fs: Any) -> None:  # noqa: F811
    from app.modules.engage import service as pg
    from app.modules.engage.repo_firestore import repo

    rp = repo()
    titles = ["Monday Quiz", "monday poll", "100% fun", "snake_case quiz", "Snake Case", "Zed", "Quiz_2"]
    acts = []
    for i in range(14):
        kind = ("quiz", "poll", "word_cloud")[i % 3]
        a = _activity(
            title=titles[i % len(titles)], activity_type=kind, winner_rule="fastest_first" if kind == "quiz" else None,
            created_at=T0 + timedelta(minutes=i), deleted_at=T0 if i % 5 == 4 else None,
        )  # fmt: skip
        await rp.create_activity(a, [])
        acts.append(a)
    db = sqldb(
        {"a": [{"id": a.id, "title": a.title, "type": a.activity_type, "deleted": a.deleted_at is not None,
                "created_at": a.created_at} for a in acts]}
    )  # fmt: skip
    for kind in (None, "quiz", "poll"):
        for q in (None, "quiz", "MONDAY", "100%", "_", "snake_", "nothing"):
            for limit in (3, 200):
                sql, p = "SELECT id FROM a WHERE deleted = 0", []
                if kind:
                    sql, p = sql + " AND type = ?", [*p, kind]
                if q:
                    esc = chr(92)  # backslash: the escape character of service._like
                    sql, p = sql + f" AND lower(title) LIKE lower(?) ESCAPE '{esc}'", [*p, f"%{pg._like(q)}%"]
                want = ids(db, sql + " ORDER BY created_at DESC LIMIT ?", [*p, limit])
                got = await rp.list_activities(activity_type=kind, title_like=q, limit=limit)
                assert [str(a.id) for a in got] == want, (kind, q, limit)
    assert uuid.UUID(want[0]) if want else True
