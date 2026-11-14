"""Question banks API (WISEMAN-FEATURES qbank build): named banks, bank membership, the
cross-module resolve used by the "Import questions from a bank" picker, bulk import via prompt,
Generate with AI (drafts only) and question images.

Permissions: bank reads/writes and imports need ``question.create`` for the bank's organization
(None = platform bank; batch-scoped trainer grants count for the batch's organization, as in
PLC-04/05). Code items additionally need ``coding_problem.manage`` and, when they carry hidden
test cases, ``coding_test_case.hidden.read`` in the same scope. Every write is audit-logged;
creates accept an ``Idempotency-Key`` (required for the bulk import).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.audit import audit
from app.core.auth import require_active_principal
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, utcnow
from app.modules.ai.service import require_app_enabled
from app.modules.placement import bank as qbank
from app.modules.placement import banks, bulk_import
from app.modules.placement.models import QuestionBank, QuestionMedia
from app.modules.placement.policies import company_owner, require_in_org, resolve_owner
from app.modules.placement.rls import bind_principal
from app.modules.placement.schemas import (
    BankAddQuestions,
    BankCreate,
    BankPatch,
    GenerateIn,
    ImportIn,
    ImportPromptIn,
    ImportValidateIn,
    MediaUploadIn,
    ResolveIn,
)

qbank_studio = authenticated_router(
    prefix="/studio", tags=["placement-question-banks"], dependencies=[Depends(bind_principal)]
)
qbank_media = authenticated_router(tags=["placement-question-banks"], dependencies=[Depends(bind_principal)])

PERM = "question.create"
MEDIA_PREFIX = "content/question_image/"
PRESIGN_SKEW_SECONDS = 30


def _nopg(session: Any) -> Any:
    """The request session, or ``None`` without Postgres (``db.NO_POSTGRES`` is falsy): core
    ``idempotent`` then keeps no Postgres savepoint (it checks ``session is not None``)."""
    return session or None


async def _idem(
    request: Request, session: Any, principal: Principal, fn: Any, *, required: bool, status: int = 200
) -> JSONResponse:
    async def op() -> IdemResult:
        return IdemResult(body=await fn(), status=status)

    return await idempotent(
        request, _nopg(session), user_id=principal.user_id, operation=op, required=required
    )


async def _require_app(session: Any) -> None:
    """SEC-19: the platform ``question_banks`` app toggle gates every question-bank route."""
    await require_app_enabled(session, app_key="question_banks")


async def _bank_for(request: Request, session: Any, principal: Principal, bank_id: uuid.UUID) -> QuestionBank:
    await _require_app(session)
    b = await banks.get_bank(session, bank_id)
    await require_in_org(request, session, principal, PERM, b.organization_id)
    return b


async def _coding_perms(
    request: Request, principal: Principal, org: uuid.UUID | None, items: list[bulk_import.NormItem]
) -> None:
    if not any(n.kind == "code" for n in items):
        return
    from app.modules.coding.policies import check_permission, scope_for

    await check_permission(request, principal, "coding_problem.manage", scope_for(org))
    if bulk_import.needs_hidden_permission(items):
        await check_permission(request, principal, "coding_test_case.hidden.read", scope_for(org))


# --------------------------------------------------------------------------- banks


@qbank_studio.get("/question-banks", openapi_extra={"x-td-idle": "neutral"})
async def qbk_01_list_banks(
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    q: str | None = Query(default=None, min_length=1, max_length=120),
    subject: str | None = Query(default=None, max_length=120),
    types: str | None = Query(default=None, max_length=200, pattern=r"^[a-z_]+(,[a-z_]+)*$"),
    organization_id: uuid.UUID | None = None,
    sort: str = Query(default="newest", pattern="^(newest|name|updated)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    from app.modules.placement.router import _bank_orgs

    await _require_app(session)
    orgs = await _bank_orgs(request, session, principal, PERM)
    if organization_id is not None:
        company_owner(organization_id)
        if organization_id not in orgs:
            raise ProblemError("permission_denied", permission=PERM)
        orgs = [organization_id]
    return await banks.list_banks(
        session,
        organization_ids=orgs,
        text_query=q,
        subject=subject,
        types=types.split(",") if types else None,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@qbank_studio.post("/question-banks", status_code=201)
async def qbk_02_create_bank(
    request: Request,
    body: BankCreate,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    await _require_app(session)
    body.organization_id = await resolve_owner(request, session, principal, PERM, body.organization_id)

    async def fn() -> dict[str, Any]:
        b = await banks.create_bank(session, principal, body)
        await audit(
            session,
            principal,
            "question_bank.created",
            "question_bank",
            b.id,
            organization_id=b.organization_id,
            after={"name": b.name, "subject": b.subject},
        )
        return banks.bank_out(b)

    return await _idem(request, session, principal, fn, required=False, status=201)


@qbank_studio.get("/question-banks/{bank_id}")
async def qbk_03_get_bank(
    request: Request,
    bank_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    return await banks.bank_detail(session, await _bank_for(request, session, principal, bank_id))


@qbank_studio.patch("/question-banks/{bank_id}")
async def qbk_04_patch_bank(
    request: Request,
    bank_id: uuid.UUID,
    body: BankPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    b = await _bank_for(request, session, principal, bank_id)
    before = {"name": b.name, "subject": b.subject}
    await banks.patch_bank(session, b, body)
    await audit(
        session,
        principal,
        "question_bank.changed",
        "question_bank",
        b.id,
        organization_id=b.organization_id,
        before=before,
        after={"name": b.name, "subject": b.subject},
    )
    return await banks.bank_detail(session, b)


@qbank_studio.delete("/question-banks/{bank_id}")
async def qbk_05_delete_bank(
    request: Request,
    bank_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    b = await _bank_for(request, session, principal, bank_id)
    await banks.delete_bank(session, b)
    await audit(
        session, principal, "question_bank.deleted", "question_bank", b.id, organization_id=b.organization_id
    )
    return {"id": str(b.id), "deleted": True}


@qbank_studio.get("/question-banks/{bank_id}/questions", openapi_extra={"x-td-idle": "neutral"})
async def qbk_06_bank_questions(
    request: Request,
    bank_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    type: str | None = Query(default=None, max_length=200, pattern=r"^[a-z_]+(,[a-z_]+)*$"),
    difficulty: int | None = Query(default=None, ge=1, le=5),
    tag: str | None = Query(default=None, max_length=120),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    published_only: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    b = await _bank_for(request, session, principal, bank_id)
    return await banks.bank_questions(
        session,
        b,
        qtype=type,
        difficulty=difficulty,
        tag=tag,
        text_query=q,
        published_only=published_only,
        limit=limit,
        offset=offset,
    )


@qbank_studio.post("/question-banks/{bank_id}/questions")
async def qbk_07_add_questions(
    request: Request,
    bank_id: uuid.UUID,
    body: BankAddQuestions,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    b = await _bank_for(request, session, principal, bank_id)

    async def fn() -> dict[str, Any]:
        n = await banks.add_questions(session, principal, b, body.question_ids)
        await audit(
            session,
            principal,
            "question_bank.questions_added",
            "question_bank",
            b.id,
            organization_id=b.organization_id,
            after={"added": n, "question_ids": [str(x) for x in body.question_ids]},
        )
        return {"added": n, "bank": await banks.bank_detail(session, b)}

    return await _idem(request, session, principal, fn, required=False)


@qbank_studio.delete("/question-banks/{bank_id}/questions/{question_id}")
async def qbk_08_remove_question(
    request: Request,
    bank_id: uuid.UUID,
    question_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    purge: bool = False,
) -> dict[str, Any]:
    b = await _bank_for(request, session, principal, bank_id)
    if purge:
        q = await qbank.get_question(session, question_id)
        await require_in_org(request, session, principal, "question.edit", q.organization_id)
    purged = await banks.remove_question(session, b, question_id, purge=purge)
    await audit(
        session,
        principal,
        "question_bank.question_removed",
        "question_bank",
        b.id,
        organization_id=b.organization_id,
        after={"question_id": str(question_id), "purged": purged},
    )
    return {"removed": True, "purged": purged}


@qbank_studio.post("/question-banks/resolve")
async def qbk_09_resolve(
    request: Request,
    body: ResolveIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """Picker confirm: full content of the chosen questions (keys only where the caller may read
    them; hidden coding test cases never)."""
    from app.modules.placement.router import _keys_visible

    await _require_app(session)
    keys: dict[uuid.UUID, bool] = {}
    for qid in dict.fromkeys(body.question_ids):
        q = await qbank.get_question(session, qid)
        await require_in_org(request, session, principal, PERM, q.organization_id)
        keys[qid] = await _keys_visible(request, session, principal, q)
    return {
        "items": await banks.resolve_questions(
            session, body.question_ids, prefer=body.prefer, keys_visible=keys
        )
    }


# --------------------------------------------------------------------------- bulk import


@qbank_studio.post("/question-banks/import/prompt")
async def qbk_10_import_prompt(
    request: Request,
    body: ImportPromptIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    from app.modules.placement.router import _bank_orgs

    await _bank_orgs(request, session, principal, PERM)
    return {
        "prompt": bulk_import.build_prompt(
            body.question_type,
            body.count,
            subject=body.subject,
            topic=body.topic,
            instructions=body.instructions,
        ),
        "schema": bulk_import.ITEM_SCHEMAS[body.question_type],
    }


def _validation_out(
    kind: str, items: list[bulk_import.NormItem], probs: list[bulk_import.Problem]
) -> dict[str, Any]:
    return {
        "ok": not probs,
        "count": len(items),
        "problem_count": len(probs),
        "problems": [p.out() for p in probs[:100]],
        "fix_prompt": bulk_import.fix_prompt(kind, probs),
        "items": [n.preview() for n in items],
    }


@qbank_studio.post("/question-banks/import/validate")
async def qbk_11_import_validate(
    request: Request,
    body: ImportValidateIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    from app.modules.placement.router import _bank_orgs

    await _bank_orgs(request, session, principal, PERM)
    items, probs = bulk_import.check(body.question_type, body.raw, body.items)
    return _validation_out(body.question_type, items, probs)


@qbank_studio.post("/question-banks/import", status_code=201)
async def qbk_12_import(
    request: Request,
    body: ImportIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    if body.bank_id is not None:
        target = await _bank_for(request, session, principal, body.bank_id)
        org = target.organization_id
    else:
        await _require_app(session)
        org = await resolve_owner(request, session, principal, PERM, body.organization_id)
    if body.primary_topic_id is not None:
        await qbank._validate_topic(session, body.primary_topic_id, "primary_topic_id")
    raw_items = (
        [bulk_import.from_ai_item(body.question_type, x) for x in body.items]
        if body.items is not None
        else None
    )
    items, probs = bulk_import.check(body.question_type, body.raw, raw_items)
    if probs:
        raise bulk_import.problems_error(body.question_type, probs, None)
    await _coding_perms(request, principal, org, items)

    async def fn() -> dict[str, Any]:
        if body.bank_id is not None:
            b = await banks.get_bank(session, body.bank_id)
        else:
            name = (body.new_bank_name or "").strip() or _auto_name(body)
            b = await banks.create_bank(
                session,
                principal,
                BankCreate(name=name[:120], subject=body.subject, organization_id=org),
            )
            await audit(
                session,
                principal,
                "question_bank.created",
                "question_bank",
                b.id,
                organization_id=b.organization_id,
                after={"name": b.name, "subject": b.subject},
            )
        ids = await bulk_import.import_items(
            session, principal, items, bank=b, primary_topic_id=body.primary_topic_id, source=body.source
        )
        await audit(
            session,
            principal,
            "question_bank.imported",
            "question_bank",
            b.id,
            organization_id=b.organization_id,
            after={
                "source": body.source,
                "question_type": body.question_type,
                "count": len(ids),
                "question_ids": [str(i) for i in ids],
            },
        )
        return {
            "bank": await banks.bank_detail(session, b),
            "question_ids": [str(i) for i in ids],
            "count": len(ids),
        }

    return await _idem(request, session, principal, fn, required=True, status=201)


def _auto_name(body: ImportIn) -> str:
    label = {
        "mcq": "MCQ",
        "code": "Code",
        "essay": "Essay",
        "poll": "Poll",
        "survey": "Survey",
        "word_cloud": "Words",
    }
    about = (body.topic or body.subject or "").strip()
    stamp = to_rfc3339(utcnow())[:10]
    return f"{about or 'Imported'} · {label[body.question_type]} · {stamp}"


# --------------------------------------------------------------------------- generate with AI


@qbank_studio.post("/question-banks/generate")
async def qbk_13_generate(
    request: Request,
    body: GenerateIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """AI drafts in the import shape — nothing is saved; the author reviews them and saves the
    selected ones through ``POST /studio/question-banks/import`` (``source: "ai"``)."""
    from app.modules.ai import service as ai

    await _require_app(session)
    body.organization_id = await resolve_owner(request, session, principal, PERM, body.organization_id)
    if body.question_type == "code":
        from app.modules.coding.policies import check_permission, scope_for

        # Drafts may carry hidden test cases: only people who may author them see them.
        await check_permission(request, principal, "coding_problem.manage", scope_for(body.organization_id))
        await check_permission(
            request, principal, "coding_test_case.hidden.read", scope_for(body.organization_id)
        )
    spec = ai.QuestionGenSpec(
        question_type=body.question_type,
        count=body.count,
        source_mode=body.source_mode,
        subject=body.subject,
        topic=body.topic,
        company=body.company,
        difficulty=body.difficulty,
        extra_instructions=body.instructions,
    )
    # AIDisabled / AIQuotaExceeded / AIUnavailable are ProblemErrors (403/429/503 ``ai_*``).
    raw = await ai.generate_questions(
        session, org_id=body.organization_id, user_id=principal.user_id, spec=spec
    )
    drafts = [bulk_import.from_ai_item(body.question_type, x) for x in raw][: body.count]
    items, probs = bulk_import.validate_items(body.question_type, drafts)
    valid = {n.index for n in items}
    await audit(
        session,
        principal,
        "question_bank.ai_drafted",
        "question_bank",
        None,
        organization_id=body.organization_id,
        after={"question_type": body.question_type, "requested": body.count, "drafted": len(valid)},
    )
    return {
        "drafts": [d for i, d in enumerate(drafts) if i in valid],
        "previews": [n.preview() for n in items],
        "problems": [p.out() for p in probs],
    }


# --------------------------------------------------------------------------- images


def _media_out(m: QuestionMedia) -> dict[str, Any]:
    return {
        "media_id": str(m.id),
        "status": m.status,
        "scan_status": m.scan_status,
        "content_type": m.content_type,
        "url": qbank.media_url(m.id) if m.scan_status == "clean" else None,
        "clean_not_before": to_rfc3339(media_clean_not_before(m)) if m.scan_status == "pending" else None,
    }


def media_clean_not_before(m: QuestionMedia) -> datetime:
    """SEC-18: the presigned POST stays usable for ``MAX_PRESIGN_SECONDS`` after the upload was
    requested, so the uploader could replace the bytes after a clean scan. A clean result is
    therefore accepted only once that window has closed (plus clock skew); an infected result is
    accepted at once."""
    from app.modules.media.storage import MAX_PRESIGN_SECONDS

    return m.created_at + timedelta(seconds=MAX_PRESIGN_SECONDS + PRESIGN_SKEW_SECONDS)


async def _current_scan(m: QuestionMedia) -> str:
    """The image's scan status, asking the scanner again while it is still ``pending``."""
    if m.scan_status != "pending":
        return m.scan_status
    from app.modules.media.providers import get_scanner
    from app.modules.media.service import scan_result_for
    from app.modules.media.storage import storage_settings

    result = await scan_result_for(get_scanner(), m.s3_key, bucket=storage_settings().S3_BUCKET_CONTENT)
    return result if result in ("clean", "infected") else "pending"


async def refresh_scan(m: QuestionMedia) -> bool:
    """Pull the scan result into the row (writer: the author, or the system sweep). Returns
    whether the row changed."""
    scan = await _current_scan(m)
    if scan == "clean" and m.scan_status == "pending" and utcnow() >= media_clean_not_before(m):
        m.scan_status, m.status = "clean", "ready"
        return True
    if scan == "infected" and m.scan_status != "infected":
        m.scan_status, m.status = "infected", "failed"
        return True
    return False


@qbank_studio.post("/question-media/uploads", status_code=201)
async def qbk_14_media_upload(
    request: Request,
    body: MediaUploadIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    """Presigned POST straight to the content bucket (no binaries through the api); the image
    is served only after the malware scan reports it clean."""
    from app.modules.media.storage import presign_post, safe_filename, storage_settings

    await _require_app(session)
    body.organization_id = await resolve_owner(request, session, principal, PERM, body.organization_id)

    async def fn() -> dict[str, Any]:
        mid = uuid7()
        key = f"{MEDIA_PREFIX}{mid}/{safe_filename(body.filename)}"
        post = presign_post(
            storage_settings().S3_BUCKET_CONTENT,
            key,
            content_type=body.content_type,
            max_bytes=body.size_bytes,
        )
        m = QuestionMedia(
            id=mid,
            organization_id=body.organization_id,
            s3_key=key,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
            status="uploading",
            scan_status="pending",
            created_by=principal.user_id,
        )
        if qbank._fs():
            now = utcnow()
            m.created_at, m.updated_at = now, now
            await (await qbank._repo(session)).create_media(m)
        else:
            session.add(m)
            await session.flush()
        await audit(
            session,
            principal,
            "question_media.upload_requested",
            "question_media",
            m.id,
            organization_id=m.organization_id,
            after={"content_type": m.content_type, "size_bytes": m.size_bytes},
        )
        return {
            "media_id": str(m.id),
            "upload": {"url": post.url, "fields": post.fields},
            "expires_at": to_rfc3339(post.expires_at),
            "max_bytes": body.size_bytes,
        }

    return await _idem(request, session, principal, fn, required=False, status=201)


@qbank_studio.post("/question-media/{media_id}/complete")
async def qbk_15_media_complete(
    request: Request,
    media_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """Pull the scan result (repeatable; the author polls while ``scan_status`` is pending)."""
    m = await _get_media(session, media_id)
    if m is None:
        raise ProblemError("not_found")
    await require_in_org(request, session, principal, PERM, m.organization_id)
    if await refresh_scan(m) and qbank._fs():
        m.updated_at = utcnow()
        await (await qbank._repo(session)).save_media(m)
    await session.flush()
    return _media_out(m)


async def _get_media(session: Any, media_id: uuid.UUID) -> QuestionMedia | None:
    if qbank._fs():
        return await (await qbank._repo(session)).get_media(media_id)
    return await session.get(QuestionMedia, media_id)


@qbank_media.get("/question-media/{media_id}", response_model=None)
async def qbk_16_media_get(
    media_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> RedirectResponse:
    """307 to a short-lived signed URL of a clean-scanned image visible to the caller (RLS:
    the image's organization or platform images)."""
    from app.modules.media.storage import presign_get, storage_settings

    m = await _get_media(session, media_id)
    if m is None:
        raise ProblemError("not_found")
    # SEC-04: strictly read-only. A viewer (e.g. a learner) may not UPDATE the row under RLS
    # and never asks the scanner: only a row already marked clean (by the author's ``complete``
    # call or the ``placement.media_scan_sweep`` job, both after the SEC-18 window) is served.
    if m.scan_status != "clean" or m.status != "ready":
        raise ProblemError("not_found")
    url, _exp = presign_get(storage_settings().S3_BUCKET_CONTENT, m.s3_key, expires_s=300)
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": "private, max-age=240"})
