"""Batch delivery plans without a database (orgs_0005): schedule maths ported from the website
(``courseplan.js computeSchedule``), attendance rules and the website import mapping.

Runs with the normal suite; also runnable alone without Postgres:
``python -m pytest --noconftest tests/orgs/test_course_plan.py``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.orgs.course_plan import (
    PlanBody,
    attendance_block_reason,
    compute_schedule,
    js_weekday,
    schedule_out,
    summarize,
    week_of,
)
from app.modules.orgs.import_website_plans import decode_value, load_export, map_document

MON = date(2026, 11, 2)  # a Monday


def _plan(**kw):
    base = {"total_hours": 20, "daily_hours": 2, "working_days": [1, 2, 3, 4, 5]}
    return PlanBody.model_validate(base | kw)


def test_js_weekday_numbering() -> None:
    assert js_weekday(MON) == 1
    assert js_weekday(date(2026, 11, 8)) == 0  # Sunday


def test_schedule_weekdays_two_weeks() -> None:
    s = compute_schedule(_plan(), MON)
    assert s.sessions == 10 and s.weeks_count == 2
    assert s.weeks[0].days == tuple(date(2026, 11, d) for d in (2, 3, 4, 5, 6))
    assert s.weeks[1].start == date(2026, 11, 9) and s.weeks[1].end == date(2026, 11, 15)
    assert s.end_date == date(2026, 11, 13)
    assert s.hours_planned == 20


def test_holidays_push_the_end_date_and_can_empty_a_week() -> None:
    hol = [date(2026, 11, 3), date(2026, 11, 4)]
    s = compute_schedule(_plan(holidays=hol), MON)
    assert date(2026, 11, 3) not in s.class_dates and len(s.class_dates) == 10
    assert s.end_date == date(2026, 11, 17)  # two days later (Tue of week 3)
    assert s.weeks_count == 3
    # a whole week of holidays: the week exists with no class days
    week2 = [date(2026, 11, d) for d in range(9, 14)]
    s2 = compute_schedule(_plan(total_hours=4, holidays=week2), MON)
    assert [len(w.days) for w in s2.weeks] == [2] and s2.end_date == date(2026, 11, 3)
    s3 = compute_schedule(_plan(total_hours=12, holidays=week2), MON)
    assert [len(w.days) for w in s3.weeks] == [5, 0, 1]


def test_working_days_and_mid_week_start() -> None:
    # Mon/Wed/Fri, 3 h a day, 18 h = 6 sessions, starting on a Wednesday
    p = _plan(total_hours=18, daily_hours=3, working_days=[5, 1, 3, 3])
    assert p.working_days == [1, 3, 5]
    s = compute_schedule(p, date(2026, 11, 4))
    assert [d.isoformat() for d in s.class_dates] == [
        "2026-11-04",
        "2026-11-06",
        "2026-11-09",
        "2026-11-11",
        "2026-11-13",
        "2026-11-16",
    ]
    # weeks run Wed..Tue from the start date
    assert s.weeks[0].start == date(2026, 11, 4) and s.weeks[0].end == date(2026, 11, 10)
    assert [len(w.days) for w in s.weeks] == [3, 3]


def test_no_start_date_counts_weeks_without_dates() -> None:
    s = compute_schedule(_plan(total_hours=56), None)  # 28 sessions / 5 days
    assert s.sessions == 28 and s.weeks_count == 6
    assert s.end_date is None and all(w.start is None and not w.days for w in s.weeks)


def test_empty_plans_have_no_schedule() -> None:
    assert compute_schedule(_plan(total_hours=0), MON).weeks_count == 0
    assert compute_schedule(_plan(working_days=[]), MON).weeks_count == 0
    # partial last session rounds up (website Math.ceil)
    assert compute_schedule(_plan(total_hours=21), MON).sessions == 11


def test_current_week_and_effective_due_dates() -> None:
    p = _plan(
        weeks=[
            {"title": "Basics", "topics": ["HTML", " ", "CSS"], "activities": []},
            {
                "title": "Project",
                "activities": [
                    {"id": "p1-submit", "kind": "project", "title": "Submit"},
                    {
                        "id": "p1-demo",
                        "kind": "presentation",
                        "title": "Demo",
                        "due": "2026-11-20",
                        "required": False,
                    },
                ],
            },
        ]
    )
    s = compute_schedule(p, MON)
    assert week_of(s, date(2026, 11, 1)) == 0
    assert week_of(s, MON) == 1 and week_of(s, date(2026, 11, 15)) == 2
    assert week_of(s, date(2026, 11, 16)) == 0
    out = schedule_out(p, MON, date(2026, 11, 10))
    assert out["current_week"] == 2 and out["end_date"] == "2026-11-13"
    assert out["weeks"][0]["topics"] == ["HTML", "CSS"]
    acts = out["weeks"][1]["activities"]
    assert acts[0]["due_effective"] == "2026-11-13"  # the week's last class
    assert acts[1]["due_effective"] == "2026-11-20"  # its own date
    assert out["required_activities"] == 1


def test_plan_validation() -> None:
    with pytest.raises(ValidationError):
        _plan(working_days=[7])
    with pytest.raises(ValidationError):
        _plan(meet_url="http://meet.example.com/x")
    with pytest.raises(ValidationError):
        _plan(class_time="25:00")
    with pytest.raises(ValidationError):  # duplicate activity ids across weeks
        _plan(
            weeks=[
                {"activities": [{"id": "dup-1", "title": "a"}]},
                {"activities": [{"id": "dup-1", "title": "b"}]},
            ]
        )
    with pytest.raises(ValidationError):  # lesson items are catalog content, not plan data
        _plan(weeks=[{"title": "x", "items": [{"title": "video"}]}])
    assert _plan(holidays=["2026-11-05", "2026-11-05"]).holidays == [date(2026, 11, 5)]


# --------------------------------------------------------------------------- attendance


def test_attendance_summary_counts_late_as_attended() -> None:
    sm = summarize(["P", "L", "A", "P"])
    assert sm.out() == {"present": 2, "late": 1, "absent": 1, "marked": 4, "percent": 75}
    assert summarize([]).percent is None
    assert summarize(["P", "A", "A"]).percent == 33
    assert summarize(["P", "A"]).percent == 50
    assert summarize(["P"] * 5 + ["A"] * 3).percent == 63  # 62.5 rounds half up like Math.round


def test_attendance_gate() -> None:
    low = summarize(["P", "A", "A", "A"])  # 25 %
    assert attendance_block_reason(low, None) is None  # off by default
    assert attendance_block_reason(low, 75) == "Attendance is 25% (at least 75% is needed)"
    assert attendance_block_reason(summarize([]), 75) is None  # never marked: not blocked
    assert attendance_block_reason(summarize(["P", "P", "P", "A"]), 75) is None  # exactly 75 %


# --------------------------------------------------------------------------- website import


def _s(v):
    return {"stringValue": v}


def _i(v):
    return {"integerValue": str(v)}


def _arr(*vals):
    return {"arrayValue": {"values": list(vals)}} if vals else {"arrayValue": {}}


def _map(**fields):
    return {"mapValue": {"fields": fields}}


def _doc(doc_id: str, **over):
    fields = {
        "title": _s("NextGen Career Accelerator 2026"),
        "status": _s("running"),
        "site_slug": _s("nextgen-career-accelerator-2026"),
        "start_date": _s(""),
        "total_hours": _i(20),
        "daily_hours": _i(2),
        "working_days": _arr(_i(1), _i(2), _i(3), _i(4), _i(5)),
        "holidays": _arr(),
        "registrations_open": {"booleanValue": True},
        "created_by": _s("Owner@Example.com"),
        "created_at": {"timestampValue": "2026-10-27T06:47:21.792Z"},
        "weeks": _arr(
            _map(title=_s("Python & Git"), topics=_arr(_s("Month 1: Foundations")), activities=_arr()),
            _map(
                title=_s("Project 1"),
                topics=_arr(),
                activities=_arr(
                    _map(
                        id=_s("ng-p1-submit"),
                        kind=_s("project"),
                        title=_s("Project 1 submission"),
                        due=_s(""),
                        required={"booleanValue": True},
                    ),
                    _map(
                        id=_s("x"),
                        kind=_s("weird"),
                        title=_s(""),
                        due=_s("2026-12-01"),
                        required={"booleanValue": False},
                    ),
                ),
                items=_arr(_map(title=_s("Intro video"))),
            ),
        ),
    }
    fields.update(over)
    return {"name": f"projects/p/databases/(default)/documents/web_courses/{doc_id}", "fields": fields}


def test_decode_firestore_values() -> None:
    assert decode_value(_arr(_i(1), {"doubleValue": 2.5}, {"nullValue": None})) == [1, 2.5, None]
    assert decode_value(_map(a=_s("x"), b=_map(c={"booleanValue": False}))) == {"a": "x", "b": {"c": False}}
    with pytest.raises(ValueError):
        decode_value({"geoPointValue": {}})


def test_map_document_without_start_date(tmp_path: Path) -> None:
    f = tmp_path / "export.json"
    f.write_text(json.dumps({"documents": [_doc("SlhYUKT0yNgby317i1f5")]}), encoding="utf-8")
    [(doc_id, fields)] = load_export(f)
    m = map_document(doc_id, fields)
    assert m.source_ref == "web_courses/SlhYUKT0yNgby317i1f5"
    assert (m.name, m.code, m.status) == (
        "NextGen Career Accelerator 2026",
        "web-nextgen-career-accelerator-2026",
        "active",
    )
    assert m.starts_on is None and m.ends_on is None
    assert m.website_course_slug == "nextgen-career-accelerator-2026"
    assert m.created_by_email == "owner@example.com"
    assert m.min_attendance_percent is None
    assert m.plan.registrations_open is True and m.plan.working_days == [1, 2, 3, 4, 5]
    w2 = m.plan.weeks[1]
    assert [a.id for a in w2.activities] == ["ng-p1-submit", "wSlhYUKT0yNgb-1-1"]
    assert w2.activities[1].kind == "assignment" and w2.activities[1].title == "Activity"
    assert w2.activities[1].due == date(2026, 12, 1) and w2.activities[1].required is False
    assert any("lesson item" in w for w in m.warnings) and any("no start date" in w for w in m.warnings)


def test_map_document_with_dates_and_status_mapping() -> None:
    m = map_document(
        "abcd1234",
        load_fields(
            _doc(
                "abcd1234",
                start_date=_s("2026-11-02"),
                status=_s("coming_soon"),
                holidays=_arr(_s("2026-11-03")),
                attendance_min=_i(75),
            )
        ),
    )
    assert m.status == "planned" and m.starts_on == MON
    assert m.ends_on == date(2026, 11, 16)  # 10 weekday classes, one holiday
    assert m.min_attendance_percent == 75
    assert (
        map_document("abcd1234", load_fields(_doc("abcd1234", status=_s("completed")))).status == "completed"
    )
    assert map_document("abcd1234", load_fields(_doc("abcd1234", status=_s("draft")))).status == "planned"
    bad = map_document("abcd1234", load_fields(_doc("abcd1234", site_slug=_s("Not A Slug!"))))
    assert bad.website_course_slug is None and bad.code == "web-abcd1234"


def load_fields(doc):
    from app.modules.orgs.import_website_plans import decode_fields

    return decode_fields(doc["fields"])


def test_load_export_rejects_other_shapes(tmp_path: Path) -> None:
    f = tmp_path / "x.json"
    f.write_text(json.dumps([{"title": "x"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_export(f)
    f.write_text(json.dumps({"documents": [{"name": "projects/p/databases/(default)/documents/other/1"}]}))
    with pytest.raises(ValueError):
        load_export(f)
