"""Issued documents on Firestore (``TD_STORE_LEARNING=firestore``), emulator only.

No Postgres: an unbound ``AsyncSession`` carries the fs_store unit of work; ``audit`` (Postgres)
is stubbed and the PDF render is a fixed byte string (the storage adapter is the memory fake).

    TD_TEST_DB_NAME=learning_test .venv/Scripts/python.exe -m pytest --noconftest -p no:cacheprovider \
        -q tests/learning/test_fs_docs.py
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401

PDF = b"%PDF-1.4 fake document"
ACTOR_ID = uuid.uuid4()


class _Store:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def put(self, bucket: str, key: str, data: bytes, ctype: str) -> None:
        self.objects[(bucket, key)] = (data, ctype)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.core.firestore.backend import reset_store_backends
    from app.modules.learning import certificates as certs
    from app.modules.learning import documents as docs

    monkeypatch.setenv("TD_STORE_LEARNING", "firestore")
    reset_store_backends()
    audits: list[str] = []

    async def fake_audit(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> None:
        audits.append(action)

    async def fake_render(doc: Any) -> bytes:
        return PDF

    store = _Store()
    monkeypatch.setattr(docs, "audit", fake_audit)
    monkeypatch.setattr(docs, "render", fake_render)
    monkeypatch.setattr(docs, "_site_url", lambda: "https://lms.example")
    monkeypatch.setattr(certs, "_store", lambda: store)
    monkeypatch.setattr(certs, "_bucket", lambda: "certs")
    yield audits
    monkeypatch.delenv("TD_STORE_LEARNING", raising=False)
    reset_store_backends()


def _s() -> Any:
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession()


class _Actor:
    user_id = ACTOR_ID


async def _ready(session: Any) -> None:
    from app.modules.learning import documents as docs

    await docs.save_settings(
        session, _Actor(), {"company": "Tech Drona", "signatory": "A. Head", "designation": "Director"}
    )


async def _issue(session: Any, name: str = "Asha Rao", email: str = "Asha@Example.com", **kw: Any) -> Any:
    from app.modules.learning import documents as docs

    return await docs.issue_document(
        session,
        _Actor(),
        doc_type="cert_participation",
        recipient={"name": name, "email": email},
        fields={"event": "Hack Day", "event_date": "2026-11-01"},
        issue_date=date(2026, 11, 2),
        **kw,
    )


async def test_settings_singleton(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs
    from app.modules.learning import fs_docs

    assert await docs.load_settings(_s()) == docs.dd.clean_settings({})
    await _ready(_s())
    s = _s()
    await docs.save_settings(s, _Actor(), {"phone": "+91 1"})
    row = await fs_docs.settings_row(_s())
    assert row is not None and row.id == 1 and row.updated_by == ACTOR_ID
    st = await docs.load_settings(_s())
    assert st["signatory"] == "A. Head" and st["phone"] == "+91 1" and not docs.dd.settings_problem(st)
    assert env.count("documents.settings_change") == 2


async def test_templates_override_and_reset(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs

    content = {"subject": "Hello {{first_name}}", "body": "Body text"}
    assert await docs.put_template(_s(), _Actor(), "email", "lor", content) == content
    content2 = {"subject": "Hi", "body": "Other"}
    await docs.put_template(_s(), _Actor(), "email", "lor", content2)
    cat = await docs.templates_catalogue(_s())
    assert cat["emails"]["lor"]["override"] == content2
    assert await docs.template_override(_s(), "email", "lor") == content2
    await docs.reset_template(_s(), _Actor(), "email", "lor")
    assert await docs.template_override(_s(), "email", "lor") is None
    assert (await docs.templates_catalogue(_s()))["emails"]["lor"]["override"] is None


async def test_issue_unique_refs_pdf_and_public_verify(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs
    from app.modules.learning import fs_docs

    await _ready(_s())
    a = await _issue(_s())
    b = await _issue(_s(), name="Ravi K", email="ravi@example.com")
    assert a.ref_no != b.ref_no and a.ref_no.startswith("TD-CP-2026-")
    assert await fs_docs.ref_taken(a.ref_no)
    stored = await fs_docs.document(_s(), a.id)
    assert (
        stored is not None
        and stored.pdf_s3_key
        and bytes(stored.content_hash) == hashlib.sha256(PDF).digest()
    )
    assert stored.file_hashes == [hashlib.sha256(PDF).hexdigest()]
    out = await docs.verify_public(_s(), a.ref_no.lower())
    assert out["status"] == "valid" and out["recipient"] == "Asha Rao" and out["related"] == []
    chk = await docs.check_pdf(_s(), a.ref_no, hashlib.sha256(PDF).hexdigest())
    assert chk == {"match": True, "status": "valid"}
    with pytest.raises(docs.ProblemError):
        await docs.verify_public(_s(), "TD-CP-2026-ZZZZZZ")


async def test_reissue_supersedes_and_second_correction_conflicts(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs
    from app.modules.learning import fs_docs

    await _ready(_s())
    a = await _issue(_s())
    s = _s()
    old = await fs_docs.document(s, a.id)
    new = await docs.reissue(s, _Actor(), old, fields={"event": "Hack Day 2"})
    assert new.replaces_id == a.id and new.origin == "reissue"
    o = await docs.verify_public(_s(), a.ref_no)
    assert o["status"] == "superseded" and o["superseded_by"] == new.ref_no
    n = await docs.verify_public(_s(), new.ref_no)
    assert n["replaces"] == a.ref_no
    stale = await fs_docs.document(_s(), a.id)
    assert stale is not None and stale.status == "superseded"
    stale.status = "valid"  # a concurrent request that read it before the first correction
    with pytest.raises(docs.ProblemError) as e:
        await _issue(_s(), replaces=stale)
    assert e.value.code == "conflict"  # ux_idoc_replaces: one correction per document


async def test_revoke_cancels_unsent_emails(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs
    from app.modules.learning import fs_docs

    await _ready(_s())
    a = await _issue(_s())
    s = _s()
    d = await fs_docs.document(s, a.id)
    row = await docs.queue_email(s, d, origin="manual", status="awaiting")
    assert row is not None and row.status == "awaiting"
    s2 = _s()
    d2 = await fs_docs.document(s2, a.id)
    assert await docs.revoke(s2, _Actor(), d2, "issued in error", public_reason=True)
    assert not await docs.revoke(s2, _Actor(), d2, "again")
    rows = await fs_docs.document_outbox(_s(), [a.id])
    assert [(r.status, r.last_error) for r in rows] == [("cancelled", "document revoked")]
    out = await docs.verify_public(_s(), a.ref_no)
    assert out["status"] == "revoked" and out["revoked_reason"] == "issued in error"


async def test_enrolment_letter_once_and_outbox_once(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs
    from app.modules.learning import fs_docs

    await _ready(_s())
    enr = uuid.uuid4()
    s = _s()
    a = await _issue(s, enrolment_id=enr, origin="enrolment")
    assert await fs_docs.enrolment_letter_exists(enr, "cert_participation")
    assert await docs.queue_email(s, a, origin="enrolment", status="awaiting") is not None
    assert await docs.queue_email(_s(), a, origin="enrolment", status="awaiting") is None
    with pytest.raises(docs.ProblemError) as e:  # ux_idoc_enrolment_auto
        await _issue(_s(), enrolment_id=enr, origin="enrolment")
    assert e.value.code == "conflict"


async def test_register_counts_related_and_certificate_check(fs: Any, env: Any) -> None:  # noqa: F811
    from app.modules.learning import documents as docs
    from app.modules.learning import fs_docs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import Certificate

    await _ready(_s())
    a = await _issue(_s())
    b = await _issue(_s(), email="asha@example.com")
    c = await _issue(_s(), name="Other", email="o@example.com")
    page = await fs_docs.register_page(
        _s(), doc_type=None, status=None, course_id=None, term="asha", ref="asha", after=None, limit=10
    )
    assert [d.id for d in page] == [b.id, a.id]  # id descending (issue order)
    page2 = await fs_docs.register_page(
        _s(), doc_type=None, status="valid", course_id=None, term="", ref="", after=b.id, limit=1
    )
    assert [d.id for d in page2] == [a.id]
    assert await fs_docs.status_counts() == {"valid": 3}
    rel = await docs._related(_s(), a)
    assert [r["ref_no"] for r in rel] == [b.ref_no]  # case-insensitive email, excludes itself
    assert c.ref_no not in {r["ref_no"] for r in rel}

    s = _s()
    cert = Certificate(
        id=uuid.uuid4(), public_code="ABCDEFGHJK23", user_id=uuid.uuid4(), course_id=uuid.uuid4(),
        course_version_id=uuid.uuid4(), enrolment_id=uuid.uuid4(), name_on_certificate="X",
        template_version="v1", content_hash=hashlib.sha256(PDF).digest(), pdf_s3_key="k",
    )  # fmt: skip
    fss.add(s, cert)
    await fss.flush(s)
    assert await docs.check_pdf(_s(), "abcdefghjk23", hashlib.sha256(PDF).hexdigest()) == {
        "match": True,
        "status": "valid",
    }
