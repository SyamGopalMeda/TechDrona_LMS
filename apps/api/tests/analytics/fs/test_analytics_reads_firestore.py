"""Analytics slice 1 on Firestore: the read interfaces other modules call (topic mastery,
security feeds, H11 learning activity). No Postgres; identity on Firestore for eligibility."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.analytics import public as ap
from app.modules.analytics import store_specs as s
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import Consent, User

FS_MODULES = ("analytics", "identity")
pytestmark = pytest.mark.usefixtures("fs_env")


async def _user(*, synthetic: bool = False, minor: bool = False) -> Any:
    uid = uuid7()
    now = clock.now()
    u = User(
        id=uid,
        email=f"u{uid.hex[-10:]}@example.com",
        email_verified_at=now,
        status="active",
        is_minor=minor,
        age_verified_at=now,
        age_verification_method="self_declared",
        is_synthetic=synthetic,
        privacy_tier="minor" if minor else "adult",
    )
    return await idp.create_user(NO_POSTGRES, u)


async def _put(cls: Any, mp_table: str, rows: list[dict[str, Any]]) -> None:
    from app.core.firestore.backfill import mappings

    mp = next(m for m in mappings("analytics") if m.table == mp_table)
    await ScopedStore.system("firestore.backfill").import_documents(
        mp.collection, [(mp.doc_id(r), mp.transform(r)) for r in rows]
    )


async def test_topic_mastery_matches_sql_shape() -> None:
    u = uuid7()
    t1, t2 = sorted([uuid7(), uuid7()], key=str)
    now = datetime.now(UTC)
    base = {
        "user_id": u,
        "band": "developing",
        "n_eff": Decimal("3.5"),
        "attempts": 4,
        "last_practiced_at": now,
        "model_version": "elo-1",
        "weighted_accuracy": Decimal("0.75"),
        "wa_num": Decimal("3"),
        "wa_den": Decimal("4"),
        "updated_at": now,
    }
    await _put(
        s.TopicRow,
        "topic_mastery",
        [
            {**base, "topic_id": t2, "theta": Decimal("0.0")},
            {**base, "topic_id": t1, "theta": Decimal("1.0")},
        ],
    )
    views = await ap.get_topic_mastery(NO_POSTGRES, u)
    assert [v.topic_id for v in views] == [t1, t2]
    assert views[1].mastery == 0.5 and views[0].mastery == round(1 / (1 + 2.718281828459045**-1), 4)
    assert views[0].n_eff == 3.5 and views[0].attempts == 4 and views[0].model_version == "elo-1"
    only = await ap.get_topic_mastery(NO_POSTGRES, u, [t2])
    assert [v.topic_id for v in only] == [t2]
    assert await ap.get_topic_mastery(NO_POSTGRES, uuid7()) == []


async def test_security_feeds_respect_eligibility() -> None:
    adult, minor = await _user(), await _user(minor=True)
    d0 = date(2026, 11, 1)
    feed = {
        "active_devices": 2,
        "multi_device_overlap_s": 30,
        "max_concurrent_active_page_instances": 2,
        "active_hours_bitmap": 7,
        "implausible_day": False,
        "plausibility_violations": {"a": [1]},
        "clock_jump_count": 0,
        "large_skew_count": 0,
        "feed_version": "v1",
        "computed_at": datetime.now(UTC),
    }
    await _put(
        s.SecurityFeedRow,
        "security_activity_feed_daily",
        [
            {**feed, "user_id": who.id, "activity_date": d0 + timedelta(days=i)}
            for who in (adult, minor)
            for i in range(3)
        ],
    )
    # no security_monitoring consent yet: nothing
    assert await ap.get_activity_summary(NO_POSTGRES, adult.id, d0, d0 + timedelta(days=5)) == []
    # test fixture write (identity owns the consent flow): its Firestore repository directly
    await idp._repo().add_consent(
        Consent(
            id=uuid7(),
            user_id=adult.id,
            purpose="security_monitoring",
            action="granted",
            notice_version="v1",
            created_at=clock.now(),
        )
    )
    days = await ap.get_activity_summary(NO_POSTGRES, adult.id, d0, d0 + timedelta(days=1))
    assert [x.activity_date for x in days] == [d0, d0 + timedelta(days=1)]
    assert days[0].plausibility_violations == {"a": [1]} and days[0].active_devices == 2
    assert await ap.get_activity_summary(NO_POSTGRES, minor.id, d0, d0 + timedelta(days=5)) == []

    t0 = datetime(2026, 11, 1, 10, 0, 7, tzinfo=UTC)
    dev = uuid.UUID(int=1)
    hb = {"kind": "engaged", "privacy_tier": "adult", "device_id": dev, "auth_session_id": None}
    from app.modules.analytics import fs_raw

    await fs_raw.insert_batch(
        adult.id,
        t0,
        [
            {
                **hb,
                "event_id": uuid7(),
                "event_ts": t0,
                "effective_at": t0,
                "user_id": adult.id,
                "state_bits": 7,
            },
            {
                **hb,
                "event_id": uuid7(),
                "event_ts": t0,
                "effective_at": t0 + timedelta(seconds=30),
                "user_id": adult.id,
                "state_bits": 7,
            },
            {
                **hb,
                "event_id": uuid7(),
                "event_ts": t0,
                "effective_at": t0 + timedelta(minutes=6),
                "user_id": adult.id,
                "state_bits": 0,
            },
        ],
        [],
    )
    b = await ap.get_engaged_buckets(NO_POSTGRES, adult.id, t0 - timedelta(hours=1), t0 + timedelta(hours=1))
    assert [(x.bucket_5min.minute, x.activity_kind) for x in b] == [
        (0, "interactive"),
        (5, "hidden_playback"),
    ]


async def test_learning_activity_excludes_synthetic_and_groups() -> None:
    real, bot = await _user(), await _user(synthetic=True)
    rows = []
    for who, d, m2 in (
        (real, date(2026, 11, 2), 600),
        (real, date(2026, 11, 3), 0),
        (bot, date(2026, 11, 2), 900),
    ):
        rows.append(
            {
                "user_id": who.id,
                "activity_date": d,
                "entity_kind": "_total",
                "entity_id": None,
                "m2_active_s": m2,
                "m5_learning_s": m2 // 2,
                "computed_at": datetime.now(UTC),
            }
        )
    await _put(s.DailyRow, "daily_learning_aggregates", rows)
    days = await ap.get_learning_activity(NO_POSTGRES, date(2026, 11, 1), date(2026, 11, 30))
    assert [(x.period_start, x.active_learners, x.engaged_minutes) for x in days] == [
        (date(2026, 11, 2), 1, 10),
        (date(2026, 11, 3), 0, 0),
    ]
    weeks = await ap.get_learning_activity(
        NO_POSTGRES, date(2026, 11, 1), date(2026, 11, 30), granularity="week"
    )
    assert [(x.period_start, x.active_learners, x.learning_minutes) for x in weeks] == [
        (date(2026, 11, 2), 1, 5)
    ]
