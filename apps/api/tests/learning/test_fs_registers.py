"""Register / search parity on Firestore (learning). Emulator only.

Each Firestore register (filtered and sorted in memory) is compared with the **same SQL run by a
real SQL engine** (SQLite, in memory, ``case_sensitive_like`` on, UUIDs as lower-case text, so
ordering, ``NULLS LAST``, ``LIKE`` wildcards and keyset pages behave as on Postgres) over the same
fixture rows: identical ids, order, page boundaries and totals for every filter combination."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_cert import _s, _save, fs_on  # noqa: F401

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- reference SQL engine


def _v(x: Any) -> Any:
    if isinstance(x, uuid.UUID):
        return str(x)
    if isinstance(x, datetime):
        return x.astimezone(UTC).isoformat()
    if isinstance(x, date):
        return x.isoformat()
    return x


def sqldb(tables: dict[str, list[dict[str, Any]]]) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA case_sensitive_like = ON")
    for name, rows in tables.items():
        cols = sorted({k for r in rows for k in r}) or ["id"]
        db.execute(f"CREATE TABLE {name} ({', '.join(cols)})")
        for r in rows:
            db.execute(
                f"INSERT INTO {name} ({', '.join(r)}) VALUES ({', '.join('?' for _ in r)})",
                [_v(x) for x in r.values()],
            )
    return db


def ids(db: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[str]:
    return [str(r[0]) for r in db.execute(sql, [_v(p) for p in params]).fetchall()]


def pages(fetch: Any, limit: int) -> list[list[str]]:
    """Walk a keyset register the way the route does (``limit + 1`` rows, cursor = last id)."""
    out: list[list[str]] = []
    after = None
    while True:
        rows = fetch(after)
        page, more = rows[:limit], len(rows) > limit
        out.append([str(r) for r in page])
        if not more or not page:
            return out
        after = page[-1]


async def apages(fetch: Any, limit: int) -> list[list[str]]:
    out: list[list[str]] = []
    after = None
    while True:
        rows = await fetch(after)
        page, more = rows[:limit], len(rows) > limit
        out.append([str(r) for r in page])
        if not more or not page:
            return out
        after = uuid.UUID(page[-1]) if isinstance(page[-1], str) else page[-1]


# --------------------------------------------------------------------------- fixtures


def _cert(i: int, user: uuid.UUID, course: uuid.UUID, name: str, revoked: bool, pdf: bool) -> Any:
    from app.modules.learning.models import Certificate

    return Certificate(
        id=uuid.uuid4(), public_code=f"CODE{i:02d}X_Y{i % 3}", user_id=user, organization_id=None, course_id=course,
        course_version_id=uuid.uuid4(), enrolment_id=uuid.uuid4(), name_on_certificate=name, template_version="v1",
        content_hash=b"\x00", issued_at=T0 + timedelta(hours=i // 2), revoked_at=T0 if revoked else None,
        pdf_s3_key="k" if pdf else None,
    )  # fmt: skip


@pytest.fixture
def people(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Users and profiles (identity, another module) behind its public API."""
    from app.modules.identity import public as identity

    users = [
        SimpleNamespace(id=uuid.uuid4(), email="asha.rao@example.com", full_name="Asha Rao"),
        SimpleNamespace(id=uuid.uuid4(), email="RAVI@Example.com", full_name="Ravi K"),
        SimpleNamespace(id=uuid.uuid4(), email=None, full_name="Meena_S"),
        SimpleNamespace(id=uuid.uuid4(), email="no.profile@example.org", full_name=None),
    ]

    async def list_users(session: Any, **kw: Any) -> list[Any]:
        return list(users)

    async def get_profiles(session: Any, uids: Any) -> dict[Any, Any]:
        return {
            u.id: SimpleNamespace(full_name=u.full_name) for u in users if u.id in set(uids) and u.full_name
        }

    async def get_users(session: Any, uids: Any) -> dict[Any, Any]:
        return {u.id: u for u in users if u.id in set(uids)}

    monkeypatch.setattr(identity, "list_users", list_users)
    monkeypatch.setattr(identity, "get_profiles", get_profiles)
    monkeypatch.setattr(identity, "get_users", get_users)
    return users


CERT_SQL = """
SELECT c.id FROM certificates c WHERE 1=1
{course} {status} {term} {after}
ORDER BY c.id DESC LIMIT ?
"""
PEOPLE = (
    "SELECT u.id FROM users u LEFT JOIN profiles p ON p.user_id = u.id "
    "WHERE lower(u.email) LIKE ? OR lower(p.full_name) LIKE ?"
)


async def test_certificate_register_search_and_pages(fs: Any, fs_on: Any, people: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_cert

    c1, c2 = uuid.uuid4(), uuid.uuid4()
    names = ["Asha Rao", "asha r", "Ravi K", "Meena_S", "MeenaXS", "Zed", None]
    certs = [
        _cert(
            i, people[i % 4].id, (c1, c2)[i % 2], names[i % len(names)] or "Nameless", i % 5 == 0, i % 3 == 0
        )
        for i in range(23)
    ]
    await _save(*certs)
    db = sqldb(
        {
            "certificates": [
                {
                    "id": c.id,
                    "user_id": c.user_id,
                    "course_id": c.course_id,
                    "name": c.name_on_certificate,
                    "code": c.public_code,
                    "revoked_at": c.revoked_at,
                    "pdf": c.pdf_s3_key,
                }
                for c in certs
            ],
            "users": [{"id": u.id, "email": u.email} for u in people],
            "profiles": [{"user_id": u.id, "full_name": u.full_name} for u in people if u.full_name],
        }
    )

    def expected(course: Any, status: Any, term: str, after: Any, limit: int) -> list[str]:
        params: list[Any] = []
        parts = {"course": "", "status": "", "term": "", "after": ""}
        if course:
            parts["course"], params = "AND c.course_id = ?", [*params, course]
        if status == "valid":
            parts["status"] = "AND c.revoked_at IS NULL"
        elif status == "revoked":
            parts["status"] = "AND c.revoked_at IS NOT NULL"
        if term:
            like = f"%{term}%"
            parts["term"] = f"AND (lower(c.name) LIKE ? OR lower(c.code) LIKE ? OR c.user_id IN ({PEOPLE}))"
            params += [like, like, like, like]
        if after:
            parts["after"], params = "AND c.id < ?", [*params, after]
        return ids(db, CERT_SQL.format(**parts), [*params, limit + 1])

    cases = [
        (None, None, ""),
        (c1, None, ""),
        (None, "valid", ""),
        (c2, "revoked", ""),
        (None, None, "asha"),  # name + e-mail + full name
        (None, None, "ravi@"),  # case-insensitive e-mail
        (None, None, "meena_s"),  # '_' is a wildcard in the SQL: matches "meenaxs" too
        (None, None, "%"),  # matches everything (NULL columns never match)
        (None, None, "x_y1"),  # code fragment with a wildcard
        (None, "valid", "example.org"),
        (None, None, "nobody-here"),
    ]
    for course, status, term in cases:
        for limit in (4, 50):

            async def fetch(
                after: Any, c: Any = course, st: Any = status, t: str = term, n: int = limit
            ) -> list[Any]:
                rows = await fs_cert.certificate_page(
                    _s(), course_id=c, status=st, term=t, after=after, limit=n
                )
                return [r.id for r in rows]

            got = await apages(fetch, limit)
            want = pages(lambda after, course=course, status=status, term=term, limit=limit: expected(
                course, status, term, after, limit), limit)  # fmt: skip
            assert got == want, (course, status, term, limit)


async def test_certificate_summary_counts(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_cert

    course = uuid.uuid4()
    certs = [
        _cert(i, uuid.uuid4(), course if i % 3 else uuid.uuid4(), "N", i % 4 == 0, i % 2 == 0)
        for i in range(13)
    ]
    await _save(*certs)
    db = sqldb(
        {
            "c": [
                {"id": c.id, "course_id": c.course_id, "revoked_at": c.revoked_at, "pdf": c.pdf_s3_key}
                for c in certs
            ]
        }
    )
    for cid in (None, course):
        where = "WHERE course_id = ?" if cid else "WHERE 1=1"
        p = [cid] if cid else []
        total = db.execute(f"SELECT count(*) FROM c {where}", [_v(x) for x in p]).fetchone()[0]
        revoked = db.execute(
            f"SELECT count(*) FROM c {where} AND revoked_at IS NOT NULL", [_v(x) for x in p]
        ).fetchone()[0]
        no_pdf = db.execute(
            f"SELECT count(*) FROM c {where} AND revoked_at IS NULL AND pdf IS NULL", [_v(x) for x in p]
        ).fetchone()[0]
        rows = await fs_cert.certificates(_s(), cid)
        assert len(rows) == total
        assert sum(1 for c in rows if c.revoked_at is not None) == revoked
        assert sum(1 for c in rows if c.revoked_at is None and c.pdf_s3_key is None) == no_pdf


async def test_outbox_queue_filters_and_pages(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_cert
    from app.modules.learning.cert_models import CertificateOutbox
    from app.modules.learning.doc_models import IssuedDocument

    ca, cb = uuid.uuid4(), uuid.uuid4()
    certs = [_cert(i, uuid.uuid4(), (ca, cb)[i % 2], "N", False, True) for i in range(6)]
    docs = [
        IssuedDocument(
            id=uuid.uuid4(), doc_type="offer_course", ref_no=f"TD-AL-2026-ABCD{i}{i}", recipient_name="R",
            recipient_email="r@example.com", course_id=(ca, None)[i % 2], issue_date=date(2026, 11, 1),
            template_version="v1",
        )
        for i in range(4)
    ]  # fmt: skip
    await _save(*certs, *docs)
    statuses = ["awaiting", "pending", "sent", "failed", "cancelled"]
    rows = [
        CertificateOutbox(id=uuid.uuid4(), certificate_id=c.id, user_id=c.user_id, status=statuses[i % 5], origin="rule")
        for i, c in enumerate(certs)
    ] + [
        CertificateOutbox(id=uuid.uuid4(), document_id=d.id, to_email="r@example.com", status=statuses[(i + 2) % 5], origin="manual")
        for i, d in enumerate(docs)
    ]  # fmt: skip
    await _save(*rows)
    db = sqldb(
        {
            "o": [{"id": o.id, "certificate_id": o.certificate_id, "document_id": o.document_id, "status": o.status} for o in rows],
            "c": [{"id": c.id, "course_id": c.course_id} for c in certs],
            "d": [{"id": d.id, "course_id": d.course_id} for d in docs],
        }
    )  # fmt: skip

    def expected(status: Any, course: Any, kind: Any, after: Any, limit: int) -> list[str]:
        sql = "SELECT o.id FROM o LEFT JOIN c ON c.id = o.certificate_id LEFT JOIN d ON d.id = o.document_id WHERE 1=1"
        p: list[Any] = []
        if status:
            sql, p = sql + " AND o.status = ?", [*p, status]
        if course:
            sql, p = sql + " AND (c.course_id = ? OR d.course_id = ?)", [*p, course, course]
        if kind == "certificate":
            sql += " AND o.certificate_id IS NOT NULL"
        elif kind == "document":
            sql += " AND o.document_id IS NOT NULL"
        if after:
            sql, p = sql + " AND o.id < ?", [*p, after]
        return ids(db, sql + " ORDER BY o.id DESC LIMIT ?", [*p, limit + 1])

    for status in (None, "sent", "awaiting"):
        for course in (None, ca):
            for kind in (None, "certificate", "document"):
                for limit in (2, 50):

                    async def fetch(
                        after: Any,
                        status: Any = status,
                        course: Any = course,
                        kind: Any = kind,
                        limit: int = limit,
                    ) -> list[Any]:
                        page = await fs_cert.outbox_page(
                            _s(), status=status, course_id=course, kind=kind, after=after, limit=limit
                        )
                        return [o.id for o, _c, _d in page]

                    got = await apages(fetch, limit)
                    want = pages(
                        lambda after, s=status, c=course, k=kind, n=limit: expected(s, c, k, after, n), limit
                    )
                    assert got == want, (status, course, kind, limit)


async def test_due_list_order_filters_limit(
    fs: Any,  # noqa: F811
    fs_on: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    people: Any,
) -> None:
    from app.modules.learning import fs_cert
    from app.modules.learning.models import Enrolment
    from app.modules.orgs import public as orgs

    ended, running = uuid.uuid4(), uuid.uuid4()
    batches = {
        ended: SimpleNamespace(id=ended, name="Old", ends_on=date(2026, 10, 1)),
        running: SimpleNamespace(id=running, name="Now", ends_on=date(2027, 1, 1)),
    }

    async def get_batches(session: Any, bids: Any) -> dict[Any, Any]:
        return {b: batches[b] for b in bids if b in batches}

    monkeypatch.setattr(orgs, "get_batches", get_batches)
    course = uuid.uuid4()
    same_time = T0 + timedelta(days=3)
    enrs = []
    for i in range(16):
        status = ("active", "completed", "withdrawn", "completed")[i % 4]
        enrs.append(
            Enrolment(
                id=uuid.uuid4(), user_id=people[i % 4].id if i < 4 else uuid.uuid4(), course_id=course if i % 5 else uuid.uuid4(),
                course_version_id=uuid.uuid4(), source="free", status=status,
                batch_id=(ended, running, None)[i % 3],
                completed_at=None if status != "completed" else (same_time if i % 2 else T0 + timedelta(hours=i)),
            )
        )  # fmt: skip
    certified = enrs[1]
    cert = _cert(98, certified.user_id, certified.course_id, "N", False, True)
    cert.enrolment_id = certified.id  # certificate_by_enrolment: this enrolment is done
    await _save(*enrs, cert)

    db = sqldb(
        {
            "e": [{"id": e.id, "course_id": e.course_id, "status": e.status, "batch_id": e.batch_id, "completed_at": e.completed_at} for e in enrs],
            "b": [{"id": b.id, "ends_on": b.ends_on} for b in batches.values()],
            "cert": [{"enrolment_id": certified.id}],
        }
    )  # fmt: skip
    today = date(2026, 11, 12)

    def expected(cid: Any, ended_only: bool, limit: int) -> list[str]:
        ended_sql = "(b.ends_on IS NOT NULL AND b.ends_on < ?)"
        sql = (
            "SELECT e.id FROM e LEFT JOIN cert ON cert.enrolment_id = e.id LEFT JOIN b ON b.id = e.batch_id "
            "WHERE cert.enrolment_id IS NULL AND e.status IN ('active','completed') AND "
            + (ended_sql if ended_only else f"(e.status = 'completed' OR {ended_sql})")
        )
        p: list[Any] = [today]
        if cid:
            sql, p = sql + " AND e.course_id = ?", [*p, cid]
        return ids(db, sql + " ORDER BY e.completed_at DESC NULLS LAST, e.id DESC LIMIT ?", [*p, limit])

    for cid in (None, course):
        for ended_only in (False, True):
            for limit in (3, 500):
                got = await fs_cert.due_rows(
                    _s(), course_id=cid, batch_ended_only=ended_only, today=today, limit=limit
                )
                assert [str(r[0].id) for r in got] == expected(cid, ended_only, limit), (
                    cid,
                    ended_only,
                    limit,
                )


async def test_document_register_search_pages_counts(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import docdefs as dd
    from app.modules.learning import fs_docs
    from app.modules.learning.doc_models import IssuedDocument

    course = uuid.uuid4()
    names = ["Ananya Reddy", "ananya_r", "Kiran", "Kiran%Kumar", "Zoya"]
    docs = [
        IssuedDocument(
            id=uuid.uuid4(), doc_type=("offer_course", "internship_letter")[i % 2],
            ref_no=f"TD-{('AL', 'IL')[i % 2]}-2026-{chr(65 + i)}{chr(66 + i)}CDEF"[:18], recipient_name=names[i % 5],
            recipient_email=f"{names[i % 5].replace('%', '').replace(' ', '.').lower()}@Example.com",
            course_id=course if i % 3 == 0 else None, issue_date=date(2026, 11, 1), template_version="v1",
            status=("valid", "revoked", "superseded")[i % 3],
        )
        for i in range(17)
    ]  # fmt: skip
    await _save(*docs)
    db = sqldb(
        {"d": [{"id": d.id, "doc_type": d.doc_type, "status": d.status, "course_id": d.course_id, "name": d.recipient_name,
                "email": d.recipient_email, "ref": d.ref_no} for d in docs]}
    )  # fmt: skip

    def expected(doc_type: Any, status: Any, cid: Any, term: str, after: Any, limit: int) -> list[str]:
        sql, p = "SELECT id FROM d WHERE 1=1", []
        if doc_type:
            sql, p = sql + " AND doc_type = ?", [*p, doc_type]
        if status:
            sql, p = sql + " AND status = ?", [*p, status]
        if cid:
            sql, p = sql + " AND course_id = ?", [*p, cid]
        if term:
            ref = dd.normalise_ref(term).lower()
            sql += " AND (lower(name) LIKE ? OR lower(email) LIKE ? OR lower(ref) LIKE ?)"
            p += [f"%{term}%", f"%{term}%", f"%{ref}%"]
        if after:
            sql, p = sql + " AND id < ?", [*p, after]
        return ids(db, sql + " ORDER BY id DESC LIMIT ?", [*p, limit + 1])

    cases = [
        (None, None, None, ""),
        ("offer_course", None, None, ""),
        (None, "valid", course, ""),
        (None, None, None, "ananya"),
        (None, None, None, "ananya_r"),  # wildcard '_'
        (None, None, None, "kiran%k"),  # wildcard '%'
        (None, None, None, "example.com"),
        (None, None, None, "td-al"),
    ]
    for doc_type, status, cid, term in cases:
        for limit in (3, 50):
            ref = dd.normalise_ref(term).lower() if term else ""

            async def fetch(
                after: Any,
                dt: Any = doc_type,
                st: Any = status,
                c: Any = cid,
                t: str = term,
                r: str = ref,
                n: int = limit,
            ) -> list[Any]:
                rows = await fs_docs.register_page(
                    _s(), doc_type=dt, status=st, course_id=c, term=t, ref=r, after=after, limit=n
                )
                return [d.id for d in rows]

            got = await apages(fetch, limit)
            want = pages(
                lambda after, a=doc_type, b=status, c=cid, t=term, n=limit: expected(a, b, c, t, after, n),
                limit,
            )
            assert got == want, (doc_type, status, cid, term, limit)
    counts = dict(db.execute("SELECT status, count(*) FROM d GROUP BY status").fetchall())
    assert await fs_docs.status_counts() == counts


async def test_learner_and_staff_lists_order(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import fs_enrol
    from app.modules.learning.models import Assignment, Enrolment

    user = uuid.uuid4()
    batch = uuid.uuid4()
    same = T0 + timedelta(days=1)
    enrs = [
        Enrolment(id=uuid.uuid4(), user_id=user if i < 6 else uuid.uuid4(), course_id=uuid.uuid4(),
                  course_version_id=uuid.uuid4(), source="free", status="active",
                  batch_id=batch if i % 2 else None, last_activity_at=(None, same, T0 + timedelta(hours=i))[i % 3])
        for i in range(12)
    ]  # fmt: skip
    certs = [_cert(i, user, uuid.uuid4(), "N", False, True) for i in range(5)]
    for c in certs[:3]:
        c.issued_at = same  # ties broken by id
    assigns = [
        Assignment(id=uuid.uuid4(), organization_id=None, title=f"A{i}", instructions_md="x", submission_type="text",
                   max_score=10, allowed_file_types=["pdf"], created_by=uuid.uuid4(), batch_id=(batch, None)[i % 2],
                   course_id=None, status=("active", "archived")[i % 3 == 0],
                   due_at=(None, T0 + timedelta(days=i))[i % 2])
        for i in range(9)
    ]  # fmt: skip
    await _save(*enrs, *certs, *assigns)
    db = sqldb(
        {
            "e": [{"id": e.id, "user_id": e.user_id, "batch_id": e.batch_id, "last": e.last_activity_at} for e in enrs],
            "c": [{"id": c.id, "user_id": c.user_id, "issued_at": c.issued_at} for c in certs],
            "a": [{"id": a.id, "batch_id": a.batch_id, "status": a.status, "due_at": a.due_at} for a in assigns],
        }
    )  # fmt: skip
    mine = await fs_enrol.my_enrolments(_s(), user)
    assert [str(e.id) for e in mine] == ids(
        db, "SELECT id FROM e WHERE user_id = ? ORDER BY last DESC NULLS LAST, id DESC", [user]
    )
    mc = await fs_enrol.my_certificates(_s(), user)
    assert [str(c.id) for c in mc] == ids(
        db, "SELECT id FROM c WHERE user_id = ? ORDER BY issued_at DESC, id DESC", [user]
    )

    async def fetch(after: Any) -> list[Any]:
        return [
            e.id
            for e in await fs_enrol.enrolment_page(_s(), batch_id=None, course_id=None, after=after, limit=2)
        ]

    got = await apages(fetch, 2)
    want = pages(
        lambda after: ids(
            db,
            "SELECT id FROM e WHERE batch_id IS NOT NULL"
            + (" AND id > ?" if after else "")
            + " ORDER BY id LIMIT 3",
            [after] if after else [],
        ),
        2,
    )
    assert got == want
    for status in (None, "active"):
        staff = await fs_enrol.staff_assignment_candidates(
            _s(),
            user_id=user,
            platform=True,
            batches=set(),
            courses=set(),
            batch_id=batch,
            course_id=None,
            status=status,
        )
        sql = (
            "SELECT id FROM a WHERE batch_id = ?"
            + (" AND status = ?" if status else "")
            + " ORDER BY id DESC"
        )
        assert [str(a.id) for a in staff] == ids(db, sql, [batch, status] if status else [batch])
    elig = fs_enrol.order_due_nulls_last(list(assigns))
    assert [str(a.id) for a in elig][: sum(1 for a in assigns if a.due_at)] == ids(
        db, "SELECT id FROM a WHERE due_at IS NOT NULL ORDER BY due_at"
    )
