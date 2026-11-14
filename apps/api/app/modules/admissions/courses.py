"""Course registration status (admissions_0003): Admin sets each website course to ``open``,
``coming_soon`` or ``closed``; the company website and course lists read the public map, and new
registrations are accepted only while a course is open (payments on existing registrations stay
allowed).

The status students see is the *effective* one: a course set ``open`` whose fee plan was since
switched off (or has no fee) reads ``closed``, because registration would be refused anyway.
A slug without a row is ``coming_soon`` (the column default).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.time import utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions import rules as R
from app.modules.admissions.models import AdmissionFeePlan, CourseStatus
from app.modules.orgs import public as orgs_public

STATUSES = ("open", "coming_soon", "closed")
DEFAULT = "coming_soon"
CLOSED_DETAIL = "Registration for this course isn't open right now."
NO_FEE_DETAIL = "Set a fee for this course before opening registration."


def plan_open(plan: AdmissionFeePlan | None) -> bool:
    """The fee plan can take registrations (active, with a fee)."""
    return plan is not None and plan.active and plan.fee_paise > 0


def effective(raw: str | None, plan: AdmissionFeePlan | None) -> str:
    st = raw or DEFAULT
    if st == "open" and not plan_open(plan):
        return "closed"
    return st


async def raw_status(session: AsyncSession, slug: str) -> str | None:
    return (
        await ads.execute(session, select(CourseStatus.status).where(CourseStatus.course_slug == slug))
    ).scalar_one_or_none()


async def status_of(session: AsyncSession, slug: str, plan: AdmissionFeePlan | None) -> str:
    return effective(await raw_status(session, slug), plan)


async def require_open(session: AsyncSession, slug: str, plan: AdmissionFeePlan | None) -> None:
    st = await status_of(session, slug, plan)
    if st != "open":
        raise ProblemError("registration_closed", detail=CLOSED_DETAIL, course_status=st)


async def ensure_row(session: AsyncSession, slug: str) -> None:
    """Make a new course slug known to the website map (``coming_soon`` until Admin opens it)."""
    await ads.execute(
        session,
        insert(CourseStatus)
        .values(course_slug=slug, status=DEFAULT)
        .on_conflict_do_nothing(index_elements=["course_slug"]),
    )


async def public_map(session: AsyncSession) -> dict[str, Any]:
    """Every course the admin sees (status rows, fee plans and website-course batches), with its
    effective status — a course without a row is ``coming_soon``. The website and LMS lists rely
    on this map being complete, otherwise they fall back to their own (older) open flags."""
    rows, plans, batches = await _known(session)
    slugs = set(rows) | set(plans) | {s for b in batches if (s := _batch_slug(b)) and R.SLUG_RE.match(s)}
    last: datetime | None = max((r.updated_at for r in rows.values()), default=None)
    return {
        "data": {s: effective(rows[s].status if s in rows else None, plans.get(s)) for s in sorted(slugs)},
        "updated_at": last.isoformat() if last else None,
    }


def _batch_slug(b: Any) -> str | None:
    if getattr(b, "website_course_slug", None):
        return str(b.website_course_slug)
    code = str(b.code or "")
    return code[4:] if code.startswith("web-") else None


async def _known(
    session: AsyncSession,
) -> tuple[dict[str, CourseStatus], dict[str, AdmissionFeePlan], list[Any]]:

    rows = {r.course_slug: r for r in (await ads.execute(session, select(CourseStatus))).scalars()}
    plans = {p.course_slug: p for p in (await ads.execute(session, select(AdmissionFeePlan))).scalars()}
    batches = [
        b
        for b in await orgs_public.list_batches(session, exclude_status="archived", order="created")
        if str(b.code or "").startswith("web-") or b.website_course_slug is not None
    ]
    return rows, plans, batches


async def _item(
    session: AsyncSession,
    slug: str,
    row: CourseStatus | None,
    plan: AdmissionFeePlan | None,
    batches: list[Any],
) -> dict[str, Any]:

    batch = None
    if plan is not None and plan.batch_id is not None:
        batch = await orgs_public.get_batch(session, plan.batch_id)
    if batch is None:
        batch = next((b for b in batches if _batch_slug(b) == slug), None)
    return {
        "course_slug": slug,
        "title": plan.title if plan is not None else (batch.name if batch is not None else slug),
        "status": row.status if row is not None else DEFAULT,
        "effective_status": effective(row.status if row is not None else None, plan),
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
        "fee_paise": plan.fee_paise if plan is not None else None,
        "plan_active": plan_open(plan),
        "batch": {"batch_id": str(batch.id), "name": batch.name} if batch is not None else None,
    }


async def admin_list(session: AsyncSession) -> dict[str, Any]:
    rows, plans, batches = await _known(session)
    slugs = set(rows) | set(plans) | {s for b in batches if (s := _batch_slug(b)) and R.SLUG_RE.match(s)}
    return {"data": [await _item(session, s, rows.get(s), plans.get(s), batches) for s in sorted(slugs)]}


async def set_status(session: AsyncSession, actor: Any, slug: str, status: str) -> dict[str, Any]:
    """Admin changes a course's registration status (audited)."""
    from app.modules.admissions.service import plan_by_slug, vf

    slug = slug.strip().lower()
    if not R.SLUG_RE.match(slug):
        raise vf("slug", "invalid_slug", "Unknown course.")
    if status not in STATUSES:
        raise vf("status", "invalid_status", "Choose Open for registration, Coming soon or Closed.")
    plan = await plan_by_slug(session, slug)
    if status == "open" and not plan_open(plan):
        raise ProblemError("no_fee_plan", detail=NO_FEE_DETAIL)
    row = await ads.get(session, CourseStatus, slug, with_for_update=True)
    before = row.status if row is not None else None
    if row is None:
        row = CourseStatus(course_slug=slug)
        ads.add(session, row)
    row.status, row.updated_at, row.updated_by = status, utcnow(), actor.user_id
    await ads.flush(session)
    await audit(
        session,
        actor.audit_actor(),
        "admissions.course_status.changed",
        "course_status",
        None,
        before={"course_slug": slug, "status": before},
        after={"course_slug": slug, "status": status},
    )
    _, _, batches = await _known(session)
    return await _item(session, slug, row, plan, batches)
