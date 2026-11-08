"""WS5 security regressions for question banks (docs/wiseman-reference/build/security-review.md):

* SEC-04 (was ``tests/_review_scratch/test_sec_aq_probe.py::test_learner_get_pending_platform_media``):
  a learner GET of a pending platform image whose scan just turned clean used to make the
  learner's session UPDATE a platform row (RLS violation -> 500). The GET is now read-only; the
  ``placement.media_scan_sweep`` job resolves pending images.
* SEC-16: a company bank accepts only published platform questions and shows their published
  version.
* SEC-18: a clean scan is accepted only after the presigned-upload window has closed.
* SEC-19: the platform ``question_banks`` app toggle gates every bank route, incl. resolve.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import system_context
from tests.placement.world import World, question, topic

API = "/api/v1"


class _Scanner:
    is_fake = True
    result: str | None = None

    def immediate_result(self, key: str) -> str | None:
        return self.result


@pytest.fixture
def scanner(monkeypatch: pytest.MonkeyPatch) -> _Scanner:
    from app.modules.media import providers

    s = _Scanner()
    monkeypatch.setattr(providers, "get_scanner", lambda: s)
    return s


async def _upload(client: Any, who: Any) -> str:
    r = await client.post(
        f"{API}/studio/question-media/uploads",
        json={"filename": "g.png", "content_type": "image/png", "size_bytes": 1000},
        headers=who.headers,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["media_id"])


async def _backdate(db: Any, mid: str, seconds: int = 400) -> None:
    await system_context(db, "test.factory")
    await db.execute(
        text("UPDATE question_media SET created_at = created_at - make_interval(secs => :s) WHERE id = :i"),
        {"s": seconds, "i": uuid.UUID(mid)},
    )


async def _scan_status(db: Any, mid: str) -> str:
    await system_context(db, "test.factory")
    return str(
        (
            await db.execute(
                text("SELECT scan_status FROM question_media WHERE id = :i"), {"i": uuid.UUID(mid)}
            )
        ).scalar_one()
    )


async def test_sec04_learner_get_pending_platform_media_is_404_not_500(
    client: Any, db: Any, world: World, scanner: _Scanner
) -> None:
    author, student = world.personas["author"], world.personas["student"]
    mid = await _upload(client, author)  # platform image (organization_id NULL)
    scanner.result = "clean"
    r = await client.get(f"{API}/question-media/{mid}", headers=student.headers, follow_redirects=False)
    assert r.status_code == 404, r.text  # read-only: never a 500 from an RLS write
    assert await _scan_status(db, mid) == "pending"

    from app.modules.placement.tasks import sweep_pending_question_media

    # inside the presign window the sweep leaves it pending (SEC-18) ...
    await system_context(db, "placement.media_scan_sweep")
    assert await sweep_pending_question_media(db) == 0
    # ... afterwards it marks it clean and the learner is redirected to the signed URL
    await _backdate(db, mid)
    await system_context(db, "placement.media_scan_sweep")
    assert await sweep_pending_question_media(db) >= 1
    assert await _scan_status(db, mid) == "clean"
    r = await client.get(f"{API}/question-media/{mid}", headers=student.headers, follow_redirects=False)
    assert r.status_code == 307, r.text


async def test_sec18_infected_is_accepted_at_once_and_never_served(
    client: Any, db: Any, world: World, scanner: _Scanner
) -> None:
    author = world.personas["author"]
    mid = await _upload(client, author)
    scanner.result = "infected"
    r = await client.post(f"{API}/studio/question-media/{mid}/complete", headers=author.headers)
    assert r.json()["scan_status"] == "infected" and r.json()["url"] is None
    scanner.result = "clean"  # a later "clean" never revives an infected image
    await _backdate(db, mid)
    r = await client.post(f"{API}/studio/question-media/{mid}/complete", headers=author.headers)
    assert r.json()["scan_status"] == "infected"
    r = await client.get(f"{API}/question-media/{mid}", headers=author.headers, follow_redirects=False)
    assert r.status_code == 404


async def test_sec16_company_bank_takes_only_published_platform_questions(
    client: Any, db: Any, world: World
) -> None:
    author, reviewer, trainer = (
        world.personas["author"],
        world.personas["reviewer"],
        world.personas["trainer_a"],
    )
    t = await topic(db, "sec16/drafts")
    draft = await question(db, author, reviewer, t, publish=False, stem="Platform draft stem")
    published = await question(db, author, reviewer, t, stem="Platform published stem")
    r = await client.post(
        f"{API}/studio/question-banks", json={"name": "Company bank"}, headers=trainer.headers
    )
    assert r.status_code == 201, r.text
    assert r.json()["organization_id"] == str(world.org_a)  # defaults to the company bank
    bid = r.json()["id"]
    r = await client.post(
        f"{API}/studio/question-banks/{bid}/questions",
        json={"question_ids": [str(draft.question_id)]},
        headers=trainer.headers,
    )
    assert r.status_code == 400 and r.json()["code"] == "validation_failed", r.text
    assert "Platform draft stem" not in r.text
    r = await client.post(
        f"{API}/studio/question-banks/{bid}/questions",
        json={"question_ids": [str(published.question_id)]},
        headers=trainer.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"{API}/studio/question-banks/{bid}/questions", headers=trainer.headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["question_id"] for i in items] == [str(published.question_id)]
    assert items[0]["latest_version"]["question_version_id"] == str(published.qv_id)


async def test_sec19_question_banks_toggle_gates_every_route(client: Any, db: Any, world: World) -> None:
    trainer, author = world.personas["trainer_a"], world.personas["author"]
    r = await client.post(f"{API}/studio/question-banks", json={"name": "Gate"}, headers=trainer.headers)
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    await system_context(db, "test.factory")
    await db.execute(
        text(
            "INSERT INTO app_settings (app_key, enabled) VALUES ('question_banks', false) "
            "ON CONFLICT (app_key) DO UPDATE SET enabled = false"
        )
    )
    for method, path, body in (
        ("get", f"/studio/question-banks/{bid}", None),
        ("patch", f"/studio/question-banks/{bid}", {"name": "x"}),
        ("get", f"/studio/question-banks/{bid}/questions", None),
        ("delete", f"/studio/question-banks/{bid}", None),
        ("get", "/studio/question-banks", None),
        ("post", "/studio/question-banks/resolve", {"question_ids": [str(uuid.uuid4())]}),
    ):
        kw: dict[str, Any] = {"headers": trainer.headers}
        if body is not None:
            kw["json"] = body
        r = await getattr(client, method)(f"{API}{path}", **kw)
        assert r.status_code == 403 and r.json()["code"] == "app_disabled", (method, path, r.text)
    r = await client.post(f"{API}/studio/question-banks", json={"name": "Nope"}, headers=author.headers)
    assert r.status_code == 403 and r.json()["code"] == "app_disabled"


async def test_foreign_organization_id_is_unknown(client: Any, world: World) -> None:
    """Single company: content owners are the platform or the company org only."""
    r = await client.post(
        f"{API}/studio/question-banks",
        json={"name": "Foreign", "organization_id": str(uuid.uuid4())},
        headers=world.personas["author"].headers,
    )
    assert r.status_code == 404, r.text
