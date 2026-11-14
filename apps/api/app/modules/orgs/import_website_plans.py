"""Import the website's batch plans (Firestore ``web_courses``) as LMS batches + batch plans.

Usage (on the server, from ``apps/api``)::

    python -m app.modules.orgs.import_website_plans web_courses-export.json            # dry run
    python -m app.modules.orgs.import_website_plans web_courses-export.json --apply
    python -m app.modules.orgs.import_website_plans web_courses-export.json --offline  # no database

Input: the Firestore REST list response (``{"documents": [{"name": ".../web_courses/<id>",
"fields": {<typed values>}}]}``), as exported from ``web_courses``. Each document is one website
batch plan (``tech drona/src/lib/courseplan.js``):

=====================  ==========================================================================
website                LMS
=====================  ==========================================================================
document id            ``batch_plans.source_ref = 'web_courses/<id>'`` (idempotency key)
title                  ``batches.name``
site_slug              ``batches.website_course_slug``; ``batches.course_id`` = the published LMS
                       catalog course with the same slug, if one exists (else NULL)
start_date ("" = none) ``batches.starts_on`` (NULL when empty)
computed end           ``batches.ends_on`` (NULL without a start date)
status                 ``batches.status``: draft/coming_soon -> planned, running -> active,
                       completed -> completed
hours, days, holidays, ``batch_plans.plan`` (``course_plan.PlanBody``); ``attendance_min`` > 0 ->
weeks/activities,      ``batch_plans.min_attendance_percent``. Lesson ``items`` are not imported
meet_url, class_time,  (content belongs in the LMS catalog course); their count is reported.
registrations_open
=====================  ==========================================================================

The batch code is ``web-<site_slug>`` (``web-<doc id>`` without a slug). ``created_by`` is the
account whose e-mail is the document's ``created_by``, else ``--created-by``.

Idempotent: a document already imported (same ``source_ref``) updates its batch and plan only
where they differ (``--skip-existing`` leaves imported batches alone, e.g. after the cut-over when
the LMS is the source of truth). Dry run by default: nothing is written without ``--apply``.
Runs under ``system_context`` (platform RLS) on ``DATABASE_URL``; every created/updated batch is
audited as ``batch.imported``. With ``TD_STORE_ORGS=firestore`` batches and plans are read and
written through ``orgs.route_store`` (no Postgres session needed); since Firestore has no
rollback, ``--apply`` first runs the import as a dry run and writes only when it has no error
row (the same all-or-nothing result as the Postgres transaction).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.modules.orgs.course_plan import SLUG_RE, PlanBody, compute_schedule

JOB = "orgs.import_website_plans"
STATUS_MAP = {"draft": "planned", "coming_soon": "planned", "running": "active", "completed": "completed"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[\w-]{4,40}$")
_KINDS = {"project", "assignment", "presentation", "assessment", "test", "mock_interview"}


# --------------------------------------------------------------------------- Firestore decoding


def decode_value(v: dict[str, Any]) -> Any:
    """One Firestore REST typed value -> plain Python."""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "referenceValue" in v:
        return v["referenceValue"]
    if "arrayValue" in v:
        return [decode_value(x) for x in (v["arrayValue"] or {}).get("values", [])]
    if "mapValue" in v:
        return decode_fields((v["mapValue"] or {}).get("fields", {}))
    raise ValueError(f"unsupported Firestore value: {sorted(v)}")


def decode_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: decode_value(v) for k, v in (fields or {}).items()}


def load_export(path: str | Path) -> list[tuple[str, dict[str, Any]]]:
    """``[(doc_id, plain fields)]`` from a Firestore REST list export."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = raw.get("documents") if isinstance(raw, dict) else None
    if not isinstance(docs, list):
        raise ValueError('expected a Firestore REST list response: {"documents": [...]}')
    out = []
    for d in docs:
        name = str(d.get("name") or "")
        doc_id = name.rstrip("/").split("/")[-1]
        if not doc_id or "/web_courses/" not in f"/{name}":
            raise ValueError(f"not a web_courses document: {name!r}")
        out.append((doc_id, decode_fields(d.get("fields") or {})))
    return out


# --------------------------------------------------------------------------- mapping


@dataclass
class Mapped:
    doc_id: str
    source_ref: str
    name: str
    code: str
    status: str
    website_status: str
    website_course_slug: str | None
    starts_on: date | None
    ends_on: date | None
    plan: PlanBody
    min_attendance_percent: int | None
    created_by_email: str | None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        sched = compute_schedule(self.plan, self.starts_on)
        return {
            "source_ref": self.source_ref,
            "name": self.name,
            "code": self.code,
            "status": f"{self.website_status} -> {self.status}",
            "website_course_slug": self.website_course_slug,
            "starts_on": self.starts_on.isoformat() if self.starts_on else None,
            "ends_on": self.ends_on.isoformat() if self.ends_on else None,
            "weeks": len(self.plan.weeks),
            "scheduled_weeks": sched.weeks_count,
            "sessions": sched.sessions,
            "activities": sum(len(w.activities) for w in self.plan.weeks),
            "min_attendance_percent": self.min_attendance_percent,
            "warnings": self.warnings,
        }


def _num(v: Any, lo: float, hi: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    return round(n, 2) if math.isfinite(n) and lo <= n <= hi else 0


def _str(v: Any, n: int) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


def _fallback_id(doc_id: str, w: int, a: int) -> str:
    return f"w{doc_id[:12]}-{w}-{a}"


def map_document(doc_id: str, f: dict[str, Any]) -> Mapped:
    """One website plan -> LMS batch fields + validated plan (website ``cleanPlan`` rules)."""
    warnings: list[str] = []
    slug = _str(f.get("site_slug"), 80).lower() or None
    if slug and not SLUG_RE.match(slug):
        warnings.append(f"site_slug {slug!r} is not a valid slug; not linked")
        slug = None
    wstatus = str(f.get("status")) if f.get("status") in STATUS_MAP else "draft"
    start_raw = f.get("start_date") or ""
    starts_on = (
        date.fromisoformat(start_raw) if isinstance(start_raw, str) and _DATE.match(start_raw) else None
    )
    if not starts_on:
        warnings.append("no start date: batch dates left empty (set one in the LMS plan)")
    weeks: list[dict[str, Any]] = []
    dropped_items = 0
    seen: set[str] = set()
    for wi, w in enumerate((f.get("weeks") or [])[:104]):
        w = w if isinstance(w, dict) else {}
        topics = w.get("topics")
        if isinstance(topics, str):
            topics = topics.split("\n")
        dropped_items += len(w.get("items") or [])
        acts = []
        for ai, a in enumerate((w.get("activities") or [])[:20]):
            a = a if isinstance(a, dict) else {}
            aid: str = (
                str(a["id"])
                if isinstance(a.get("id"), str) and _ID.match(a["id"])
                else _fallback_id(doc_id, wi, ai)
            )
            if aid in seen:
                aid = _fallback_id(doc_id, wi, ai)
            seen.add(aid)
            due = a.get("due")
            acts.append(
                {
                    "id": aid,
                    "kind": a.get("kind") if a.get("kind") in _KINDS else "assignment",
                    "title": _str(a.get("title"), 160) or "Activity",
                    "due": due if isinstance(due, str) and _DATE.match(due) else None,
                    "required": a.get("required") is not False,
                }
            )
        weeks.append(
            {
                "title": _str(w.get("title"), 160),
                "topics": [_str(t, 200) for t in (topics or []) if _str(t, 200)][:30],
                "activities": acts,
            }
        )
    if dropped_items:
        warnings.append(f"{dropped_items} lesson item(s) not imported (add them to the LMS course)")
    meet = _str(f.get("meet_url"), 500)
    ctime = f.get("class_time") if isinstance(f.get("class_time"), str) else ""
    plan = PlanBody.model_validate(
        {
            "total_hours": _num(f.get("total_hours"), 0, 2000),
            "daily_hours": _num(f.get("daily_hours"), 0, 12),
            "working_days": sorted(
                {
                    int(d)
                    for d in (f.get("working_days") or [])
                    if isinstance(d, (int, float)) and 0 <= int(d) <= 6
                }
            ),
            "holidays": sorted(
                {h for h in (f.get("holidays") or []) if isinstance(h, str) and _DATE.match(h)}
            )[:120],
            "class_time": ctime if re.match(r"^([01]\d|2[0-3]):[0-5]\d$", ctime or "") else None,
            "meet_url": meet if re.match(r"^https://\S+$", meet, re.IGNORECASE) else None,
            "registrations_open": f.get("registrations_open") is True,
            "weeks": weeks,
        }
    )
    att = int(_num(f.get("attendance_min"), 0, 100))
    sched = compute_schedule(plan, starts_on)
    code = re.sub(r"[^A-Za-z0-9._-]", "-", f"web-{slug or doc_id}")[:64]
    creator = (
        f.get("created_by")
        if isinstance(f.get("created_by"), str) and "@" in f.get("created_by", "")
        else None
    )
    return Mapped(
        doc_id=doc_id,
        source_ref=f"web_courses/{doc_id}",
        name=_str(f.get("title"), 200) or f"Website course {doc_id}",
        code=code,
        status=STATUS_MAP[wstatus],
        website_status=wstatus,
        website_course_slug=slug,
        starts_on=starts_on,
        ends_on=sched.end_date,
        plan=plan,
        min_attendance_percent=att or None,
        created_by_email=creator.strip().lower() if creator else None,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- database


async def _course_for_slug(session: Any, slug: str | None) -> uuid.UUID | None:
    if not slug:
        return None
    from app.core.errors import ProblemError
    from app.modules.catalog import service as catalog_svc

    try:
        course, _version = await catalog_svc.public_course_by_slug(session, slug)
    except ProblemError:
        return None
    return course.id


async def _user_id(session: Any, email: str | None) -> uuid.UUID | None:
    if not email:
        return None

    from app.modules.identity import public as identity_public

    u = await identity_public.find_user(session, "email", email.strip().lower())
    return u.id if u is not None else None


async def import_plans(
    session: Any,
    mapped: list[Mapped],
    *,
    apply: bool,
    created_by_email: str | None = None,
    skip_existing: bool = False,
) -> list[dict[str, Any]]:
    """Create or update one batch + plan per website document. Returns one report row each
    (``action``: create | update | unchanged | skip | error). Writes only with ``apply``."""
    from app.core.audit import AuditActor, audit
    from app.core.company import COMPANY_ORG_ID
    from app.core.ids import uuid7
    from app.modules.identity.pgctx import sys_ctx
    from app.modules.orgs import route_store as rs
    from app.modules.orgs.models import Batch, BatchPlan

    await sys_ctx(session, JOB)
    actor = AuditActor.system(JOB)
    fallback_creator = await _user_id(session, created_by_email.lower() if created_by_email else None)
    report: list[dict[str, Any]] = []
    for m in mapped:
        row: dict[str, Any] = m.summary()
        course_id = await _course_for_slug(session, m.website_course_slug)
        row["course_id"] = str(course_id) if course_id else None
        existing = await rs.plan_by_source_ref(session, m.source_ref)
        want_batch: dict[str, Any] = {
            "name": m.name,
            "status": m.status,
            "starts_on": m.starts_on,
            "ends_on": m.ends_on,
            "website_course_slug": m.website_course_slug,
            "course_id": course_id,
        }
        want_plan: dict[str, Any] = {
            "plan": m.plan.stored(),
            "min_attendance_percent": m.min_attendance_percent,
        }
        if existing is not None:
            b = await rs.get_batch(session, existing.batch_id)
            row["batch_id"] = str(existing.batch_id)
            if skip_existing or b is None:
                row["action"] = "skip"
                report.append(row)
                continue
            diff = sorted(
                [k for k, v in want_batch.items() if getattr(b, k) != v]
                + [k for k, v in want_plan.items() if getattr(existing, k) != v]
            )
            if b.status == "archived":
                diff = [d for d in diff if d != "status"]
                b_status_locked = True
            else:
                b_status_locked = False
            row["changes"] = diff
            row["action"] = "update" if diff else "unchanged"
            if apply and diff:
                for k, v in want_batch.items():
                    if k == "status" and b_status_locked:
                        continue
                    setattr(b, k, v)
                for k, v in want_plan.items():
                    setattr(existing, k, v)
                await rs.save_plan(session, b, existing, new=False, batch_changed=True)
                await audit(
                    session,
                    actor,
                    "batch.imported",
                    "batch",
                    b.id,
                    organization_id=b.organization_id,
                    after={"source_ref": m.source_ref, "changes": diff},
                )
            report.append(row)
            continue
        creator = await _user_id(session, m.created_by_email) or fallback_creator
        code = m.code
        if await rs.code_taken(session, COMPANY_ORG_ID, code):
            code = f"{code[:56]}-{m.doc_id[:6]}".lower()
        row["code"] = code
        if creator is None:
            row["action"] = "error"
            row["error"] = "created_by not found: pass --created-by <admin e-mail>"
            report.append(row)
            continue
        row["action"] = "create"
        if apply:
            b = Batch(id=uuid7(), organization_id=COMPANY_ORG_ID, code=code, created_by=creator, **want_batch)
            b = await rs.insert_batch(session, b)
            plan = BatchPlan(
                batch_id=b.id,
                organization_id=b.organization_id,
                source_ref=m.source_ref,
                updated_by=creator,
                **want_plan,
            )
            await rs.save_plan(session, b, plan, new=True, batch_changed=False)
            row["batch_id"] = str(b.id)
            await audit(
                session,
                actor,
                "batch.imported",
                "batch",
                b.id,
                organization_id=b.organization_id,
                after={"source_ref": m.source_ref, "code": code},
            )
        report.append(row)
    return report


# --------------------------------------------------------------------------- CLI


class _null:
    """``async with`` yielding a fixed object (the ``NO_POSTGRES`` request session)."""

    def __init__(self, obj: Any) -> None:
        self.obj = obj

    async def __aenter__(self) -> Any:
        return self.obj

    async def __aexit__(self, *exc: Any) -> None:
        return None


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    p = argparse.ArgumentParser(description="Import website batch plans (web_courses export) as LMS batches")
    p.add_argument("file", help="Firestore REST list export of web_courses (JSON)")
    p.add_argument("--apply", action="store_true", help="write (default: dry run)")
    p.add_argument("--offline", action="store_true", help="parse and map only, no database")
    p.add_argument(
        "--created-by", default=None, help="admin e-mail used when a plan's created_by has no account"
    )
    p.add_argument("--skip-existing", action="store_true", help="leave already imported batches unchanged")
    args = p.parse_args(argv)

    mapped = [map_document(i, f) for i, f in load_export(args.file)]
    if args.offline:
        for m in mapped:
            print(json.dumps({"action": "map", **m.summary()}, ensure_ascii=False))
        print(f"offline: {len(mapped)} plan(s) mapped, nothing written")
        return 0

    async def _run() -> list[dict[str, Any]]:
        from app.core.db import NO_POSTGRES, dispose_engine, get_sessionmaker
        from app.core.firestore.backend import uses_firestore
        from app.core.runtime import postgres_enabled

        if uses_firestore("orgs"):
            from app.core.firestore.lifecycle import close as close_client

            pg = postgres_enabled()
            try:
                async with get_sessionmaker()() if pg else _null(NO_POSTGRES) as s:
                    kw = {"created_by_email": args.created_by, "skip_existing": args.skip_existing}
                    rep = await import_plans(s, mapped, apply=False, **kw)
                    if args.apply and not any(r["action"] == "error" for r in rep):
                        rep = await import_plans(s, mapped, apply=True, **kw)
                    if pg:
                        await s.commit()
                    return rep
            finally:
                await close_client()
                if pg:
                    await dispose_engine()

        try:
            async with get_sessionmaker()() as s:
                try:
                    rep = await import_plans(
                        s,
                        mapped,
                        apply=args.apply,
                        created_by_email=args.created_by,
                        skip_existing=args.skip_existing,
                    )
                except BaseException:
                    await s.rollback()
                    raise
                # all or nothing: any error row (or a dry run) writes nothing
                if args.apply and not any(r["action"] == "error" for r in rep):
                    await s.commit()
                else:
                    await s.rollback()
                return rep
        finally:
            await dispose_engine()

    report = asyncio.run(_run())
    for r in report:
        print(json.dumps(r, ensure_ascii=False, default=str))
    counts: dict[str, int] = {}
    for r in report:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    errors = counts.get("error", 0)
    mode = "applied" if args.apply and not errors else "dry run (nothing written)"
    print(f"{mode}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
