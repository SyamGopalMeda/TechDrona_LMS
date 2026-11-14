"""Import website fee data (``web_fee_plans`` / ``web_fee_accounts`` / ``web_fee_payments``) from a
JSON export into the admissions tables. Idempotent: ids are derived from the website document
ids (uuid5), existing rows are skipped, fee plans that already exist are never overwritten.

    python -m app.modules.admissions.import_cmd export.json [--dry-run]

Export shape (no Firestore credentials needed; produce it with the website's typed JSON dump):

    {"fee_plans": {"<slug>": {...}} | [{"id": "<slug>", ...}],
     "fee_accounts": {"<recordId>": {...}} | [...],
     "fee_payments": {"<paymentId>": {...}} | [...]}

Timestamps may be ISO strings, ``{"_seconds": n}`` / ``{"seconds": n}`` objects or epoch millis.

Mapping notes:
* the website's statuses map 1:1, except ``enrolled``: LMS access is not created by an import, so
  the status is re-derived from the money (usually ``payment_verified``); staff press **Enrol**.
* proof/resume files stayed in Firestore: imported claims keep the file name and hash with a
  ``website-import/<fileId>`` key that cannot be opened from the LMS (view the original in the
  website admin until it is retired).
* the ledger is re-checked at commit (``verified_total`` = sum of verified claims); an
  inconsistent export aborts the whole import.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admissions import datastore as ads
from app.modules.admissions import rules as R

_NS = uuid.UUID("6f1d2b1e-2b5c-4f0c-9a51-0d6b1a7e2c11")


def _docs(v: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(v, dict):
        return [(str(k), d) for k, d in v.items() if isinstance(d, dict)]
    if isinstance(v, list):
        return [(str(d.get("id") or d.get("_id") or ""), d) for d in v if isinstance(d, dict)]
    return []


def _ts(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, dict):
        s = v.get("_seconds", v.get("seconds"))
        return datetime.fromtimestamp(int(s), UTC) if s is not None else None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, UTC)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return None


def _date(v: Any, fallback: datetime) -> date:
    s = str(v or "")
    return date.fromisoformat(s) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else fallback.date()


def _schedule(x: Any) -> list[dict[str, Any]]:
    return [
        {
            "label": str(i.get("label") or ""),
            "amount_paise": int(i.get("amount") or i.get("amount_paise") or 0),
            "due": str(i.get("due") or ""),
        }
        for i in (x or [])
        if isinstance(i, dict)
    ]


def _hex(v: Any) -> str | None:
    s = str(v or "").lower()
    return s if re.fullmatch(r"[0-9a-f]{64}", s) else None


async def run(session: AsyncSession, data: dict[str, Any]) -> dict[str, int]:
    from app.core.db import system_context
    from app.core.ids import uuid7
    from app.modules.admissions.models import (
        AdmissionEvent,
        AdmissionFeePlan,
        AdmissionPaymentClaim,
        AdmissionRegistration,
    )

    await system_context(session, "admissions.import")
    now = datetime.now(UTC)
    out = {"plans": 0, "registrations": 0, "claims": 0, "skipped": 0}
    plans: dict[str, AdmissionFeePlan] = {}
    for slug, d in _docs(data.get("fee_plans")):
        slug = (slug or str(d.get("slug") or "")).lower()
        if not R.SLUG_RE.match(slug):
            out["skipped"] += 1
            continue
        p = (
            await ads.execute(session, select(AdmissionFeePlan).where(AdmissionFeePlan.course_slug == slug))
        ).scalar_one_or_none()
        if p is None:
            t = R.clean_terms(
                fee_paise=int(d.get("fee") or 0),
                allow_instalments=d.get("allow_installments") is True,
                schedule=_schedule(d.get("schedule")),
                min_first_paise=d.get("min_first"),
                access_min_paise=d.get("access_min"),
            )
            p = AdmissionFeePlan(
                id=uuid.uuid5(_NS, f"plan:{slug}"),
                course_slug=slug,
                title=str(d.get("title") or slug)[:160],
                fee_paise=t.fee_paise,
                allow_instalments=t.allow_instalments,
                schedule=[x.as_dict() for x in t.schedule],
                policy=t.policy,
                min_first_paise=t.min_first_paise,
                access_min_paise=t.access_min_paise,
                upi_id=(str(d.get("upi_id") or "").strip() or None),
                payee_name=(str(d.get("payee_name") or "").strip()[:80] or None),
                bank_details=(str(d.get("bank_details") or "").strip()[:600] or None),
                instructions=(str(d.get("instructions") or "").strip()[:800] or None),
                active=False,  # re-open deliberately in Admissions > Fee plans after checking the plan
            )
            if p.upi_id and not R.UPI_ID_RE.match(p.upi_id):
                p.upi_id = None
            ads.add(session, p)
            out["plans"] += 1
        plans[slug] = p
    await ads.flush(session)

    regs: dict[str, AdmissionRegistration] = {}
    for acc_id, d in _docs(data.get("fee_accounts")):
        rid = uuid.uuid5(_NS, f"account:{acc_id}")
        existing = await ads.get(session, AdmissionRegistration, rid)
        if existing is not None:
            regs[acc_id] = existing
            out["skipped"] += 1
            continue
        slug = str(d.get("course_slug") or "").lower()
        plan = (
            plans.get(slug)
            or (
                await ads.execute(
                    session, select(AdmissionFeePlan).where(AdmissionFeePlan.course_slug == slug)
                )
            ).scalar_one_or_none()
        )
        reg_no = R.normalize_reg_no(d.get("reg_no"))
        phone = R.indian_mobile(d.get("phone"))
        email = str(d.get("email") or "").strip().lower()
        if plan is None or reg_no is None or phone is None or "@" not in email:
            out["skipped"] += 1
            continue
        fee = int(d.get("fee") or 0)
        verified = int(d.get("verified_total") or 0)
        created = _ts(d.get("created_at")) or now
        status = str(d.get("status") or "registered")
        r = AdmissionRegistration(
            id=rid,
            reg_no=reg_no,
            fee_plan_id=plan.id,
            course_slug=slug,
            course_title=str(d.get("course_title") or plan.title)[:160],
            name=str(d.get("name") or "-")[:120],
            email=email,
            phone=phone,
            college=str(d.get("college") or "-")[:160],
            branch=str(d.get("branch") or "-")[:60],
            year=str(d.get("year") or "-")[:30],
            fee_paise=fee,
            access_min_paise=min(fee, int(d.get("access_min") or fee)),
            policy="instalments" if d.get("policy") == "installments" else "full",
            allow_instalments=d.get("allow_installments") is True,
            min_first_paise=min(fee, int(d.get("min_first") or d.get("access_min") or fee)),
            schedule=_schedule(d.get("schedule")),
            verified_total_paise=verified,
            balance_paise=fee - verified,
            status="registered",
            status_note=(str(d.get("status_note") or "")[:500] or None),
            open_claims=0,
            consent_text=str(d.get("consent") or "Agreed on the website registration form"),
            consent_at=created,
            source="import",
            created_at=created,
            updated_at=now,
        )
        resume = d.get("resume") or {}
        if isinstance(resume, dict) and resume.get("file_id"):
            r.resume_key = f"website-import/{resume['file_id']}"
            r.resume_name = str(resume.get("name") or "resume")[:120]
            r.resume_type = str(resume.get("type") or "") or None
        r.status = status if status in R.MANUAL_STATUSES else "registered"
        ads.add(session, r)
        regs[acc_id] = r
        out["registrations"] += 1
    await ads.flush(session)

    for pay_id, d in _docs(data.get("fee_payments")):
        cid = uuid.uuid5(_NS, f"payment:{pay_id}")
        reg = regs.get(str(d.get("account_id") or ""))
        if reg is None or await ads.get(session, AdmissionPaymentClaim, cid) is not None:
            out["skipped"] += 1
            continue
        status = str(d.get("status") or "pending")
        if status not in R.CLAIM_STATUSES:
            out["skipped"] += 1
            continue
        submitted = _ts(d.get("submitted_at")) or now
        proof = d.get("proof") or {}
        provider = "admin_entry" if d.get("provider") == "admin_entry" else "manual_upi"
        utr = R.normalize_ref(d.get("utr")) or None
        sha = _hex(proof.get("sha256")) if isinstance(proof, dict) else None
        if provider == "manual_upi" and (not utr or not sha):
            provider = (
                "admin_entry"  # a student claim without its reference/proof data: keep it as a staff entry
            )
        verified_amt = int(d.get("verified_amount") or 0) if status in ("verified", "reversed") else 0
        c = AdmissionPaymentClaim(
            id=cid,
            registration_id=reg.id,
            provider=provider,
            method=str(d.get("method")) if d.get("method") in R.STAFF_METHODS else "other",
            amount_paise=int(d.get("amount") or 0),
            utr=utr,
            paid_on=_date(d.get("paid_on"), submitted),
            note=(str(d.get("note") or "")[:500] or None),
            proof_key=f"website-import/{proof.get('file_id')}"
            if sha and proof.get("file_id")
            else (f"website-import/{pay_id}" if sha else None),
            proof_name=(str(proof.get("name") or "")[:120] or None) if sha else None,
            proof_type=proof.get("type")
            if sha and proof.get("type") in ("image/jpeg", "image/png", "image/webp", "application/pdf")
            else None,
            proof_sha256=sha,
            proof_original_sha256=None,
            status=status,
            verified_amount_paise=verified_amt,
            reviewed_at=_ts(d.get("reviewed_at")) or (submitted if status != "pending" else None),
            review_note=(str(d.get("review_note") or "")[:500] or None),
            submitted_at=submitted,
        )
        ads.add(session, c)
        if status in R.OPEN_CLAIM_STATUSES:
            reg.open_claims = min(R.MAX_OPEN_CLAIMS, reg.open_claims + 1)
        out["claims"] += 1
    for r in regs.values():
        if r.source == "import":
            r.status = R.derive_status(
                current=r.status,
                verified=r.verified_total_paise,
                access_min=r.access_min_paise,
                open_claims=r.open_claims,
                enrolled=False,
                fee=r.fee_paise,
            )
            ads.add(
                session,
                AdmissionEvent(
                    id=uuid7(),
                    registration_id=r.id,
                    action="registration.imported",
                    actor_label="import",
                    detail="Imported from the website fee records",
                    at=now,
                ),
            )
    await ads.flush(session)
    return out


async def _main(path: Path, dry_run: bool) -> dict[str, int]:
    from app.core.db import apply_db_role, get_sessionmaker
    from app.core.models_registry import import_all_models

    import_all_models()
    data = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    async with get_sessionmaker()() as session:
        try:
            await apply_db_role(session)
            out = await run(session, data)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        except BaseException:
            await session.rollback()
            raise
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Import website fee data (JSON export) into the LMS admissions tables."
    )
    p.add_argument("export", type=Path)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    out = asyncio.run(_main(a.export, a.dry_run))
    print(json.dumps({**out, "dry_run": a.dry_run}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
