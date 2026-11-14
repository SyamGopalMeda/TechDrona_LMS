"""Engage service, Firestore path (``TD_STORE_ENGAGE=firestore``).

``service.py`` dispatches every public function here when the switch is on. Authorization,
validation, rate limits, app gating, audit, outbox events, notifications, batch membership and
profile nicknames are the same calls as on Postgres (those tables stay on Postgres); only the
engage rows move. Serializers (``activity_out``, ``run_summary``, ``_question_result`` ...) are
shared with ``service.py``, so responses keep their exact shape.

Aggregation SQL is replaced by Python folds over the run's responses with the same grouping and
ordering (``_aggregate``, ``_leaderboard``, ``_texts``).
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.firestore.collation import sort_key
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.ai.public import require_app_enabled
from app.modules.engage import service as pg
from app.modules.engage.models import (
    EngageActivity,
    EngageParticipant,
    EngageQuestion,
    EngageResponse,
    EngageRun,
)
from app.modules.engage.repo_firestore import LIVE_STATUSES, EngageRepo, JoinRefused
from app.modules.engage.repo_firestore import repo as _repo
from app.modules.engage.schemas import ActivityIn, AnswerIn, ControlIn, LaunchIn


def repo() -> EngageRepo:
    return _repo("engage.service")


# =========================================================================== activities


async def get_activity(activity_id: uuid.UUID) -> EngageActivity:
    a = await repo().get_activity(activity_id)
    if a is None or a.deleted_at is not None:
        raise ProblemError("not_found")
    return a


async def create_activity(
    request: Request, session: AsyncSession, principal: Principal, body: ActivityIn
) -> dict[str, Any]:
    pg.validate_activity(body)
    org = await pg._create_scope(request, session, principal, body)
    await require_app_enabled(session, app_key="engage")
    a = EngageActivity(id=uuid7(), owner_id=principal.user_id, deleted_at=None)
    pg._apply_settings(a, body, org)
    qs = pg._question_rows(a, body)
    a = await repo().create_activity(a, qs)
    await audit(
        session,
        principal,
        "engage.activity_created",
        "engage_activity",
        a.id,
        organization_id=org,
        after={"type": a.activity_type, "questions": len(qs)},
    )
    return pg.activity_out(a, qs)


async def update_activity(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID, body: ActivityIn
) -> dict[str, Any]:
    a = await get_activity(activity_id)
    await pg.require_manage(request, session, principal, a)
    pg.validate_activity(body)
    if body.activity_type != a.activity_type:
        raise pg._invalid([{"field": "activity_type", "code": "immutable", "message": "type cannot change"}])
    if body.batch_id != a.batch_id or (a.batch_id is None and a.organization_id is not None):
        org = await pg._create_scope(request, session, principal, body)
    else:
        org = a.organization_id
    pg._apply_settings(a, body, org)
    qs = pg._question_rows(a, body)
    a = await repo().replace_activity(a, qs)
    await audit(
        session,
        principal,
        "engage.activity_updated",
        "engage_activity",
        a.id,
        organization_id=a.organization_id,
        after={"questions": len(qs)},
    )
    return pg.activity_out(a, qs)


async def activity_detail(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID
) -> dict[str, Any]:
    a = await get_activity(activity_id)
    await pg.require_manage(request, session, principal, a)
    rp = repo()
    out = pg.activity_out(a, await rp.questions_of(a.id))
    runs = [await rp.refresh_run(r) for r in await rp.runs_of(a.id)]
    out["runs"] = [pg.run_summary(r) for r in runs]
    return out


async def list_activities(
    request: Request,
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    activity_type: str | None,
    limit: int = 200,
) -> dict[str, Any]:
    rp = repo()
    rows = await rp.list_activities(activity_type=activity_type, title_like=q or None, limit=limit)
    cache: dict[tuple[Any, ...], bool] = {}
    visible: list[EngageActivity] = []
    for a in rows:
        key = (a.organization_id, a.batch_id, a.owner_id == principal.user_id)
        if key not in cache:
            cache[key] = await pg.can_manage(request, session, principal, a)
        if cache[key]:
            visible.append(a)
    ids = [a.id for a in visible]
    counts = await rp.question_counts(ids) if ids else {}
    latest = await rp.latest_runs(ids) if ids else {}
    return {
        "data": [
            pg.activity_out(a, question_count=counts.get(a.id, 0), latest_run=latest.get(a.id))
            for a in visible
        ],
        "counts": {"total": len(visible)},
    }


async def duplicate_activity(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID
) -> dict[str, Any]:
    src = await get_activity(activity_id)
    await pg.require_manage(request, session, principal, src)
    rp = repo()
    a = EngageActivity(
        id=uuid7(),
        organization_id=src.organization_id,
        batch_id=src.batch_id,
        owner_id=principal.user_id,
        activity_type=src.activity_type,
        title=(src.title[: 200 - len(" (copy)")] + " (copy)"),
        description=src.description,
        run_mode=src.run_mode,
        audience=src.audience,
        identity_mode=src.identity_mode,
        results_mode=src.results_mode,
        pacing=src.pacing,
        winner_rule=src.winner_rule,
        participant_limit=src.participant_limit,
        opens_at=src.opens_at,
        closes_at=src.closes_at,
        deleted_at=None,
    )
    qs = [
        EngageQuestion(
            id=uuid7(),
            activity_id=a.id,
            organization_id=a.organization_id,
            position=q.position,
            kind=q.kind,
            prompt=q.prompt,
            options=[{**o, "id": str(uuid7())} for o in q.options],
            max_words=q.max_words,
            source_question_id=q.source_question_id,
            source_version_id=q.source_version_id,
        )
        for q in await rp.questions_of(src.id)
    ]
    a = await rp.create_activity(a, qs)
    await audit(
        session,
        principal,
        "engage.activity_duplicated",
        "engage_activity",
        a.id,
        organization_id=a.organization_id,
        after={"source": str(src.id)},
    )
    return pg.activity_out(a, qs)


async def delete_activity(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID
) -> None:
    a = await get_activity(activity_id)
    await pg.require_manage(request, session, principal, a)
    await repo().delete_activity(a.id, utcnow())
    await audit(
        session,
        principal,
        "engage.activity_deleted",
        "engage_activity",
        a.id,
        organization_id=a.organization_id,
    )


# =========================================================================== runs


async def launch_run(
    request: Request, session: AsyncSession, principal: Principal, activity_id: uuid.UUID, body: LaunchIn
) -> dict[str, Any]:
    a = await get_activity(activity_id)
    await pg.require_manage(request, session, principal, a)
    await ratelimit.hit(f"engage:launch:{a.id}:{principal.user_id}", pg.LAUNCH_RULES, scope="engage.launch")
    await require_app_enabled(session, app_key="engage")
    rp = repo()
    qs = await rp.questions_of(a.id)
    if not qs:
        raise pg._invalid(
            [{"field": "questions", "code": "required", "message": "add at least one question"}]
        )
    opens_at = body.opens_at or a.opens_at
    closes_at = body.closes_at or a.closes_at
    if a.run_mode == "scheduled":
        if opens_at is None or closes_at is None:
            raise pg._invalid([{"field": "opens_at", "code": "required", "message": "needs a window"}])
        if closes_at <= opens_at or closes_at <= utcnow():
            raise pg._invalid(
                [{"field": "closes_at", "code": "invalid", "message": "future, after opens_at"}]
            )
    else:
        opens_at = None
        closes_at = body.closes_at
    now = utcnow()
    run_id = uuid7()
    settings = pg.settings_of(a)
    snapshot = [pg._snapshot(q) for q in qs]

    def build(run_no: int) -> EngageRun:
        return EngageRun(
            id=run_id,
            activity_id=a.id,
            organization_id=a.organization_id,
            run_no=run_no,
            join_code="",
            status="scheduled",
            settings=dict(settings),
            questions=list(snapshot),
            current_position=0,
            revealed_positions=[],
            closed_positions=[],
            results_published=False,
            state_version=1,
            opens_at=opens_at,
            closes_at=closes_at,
            opened_at=None,
            closed_at=None,
            finalised_at=None,
            created_by=principal.user_id,
            created_at=now,
        )

    r = await rp.launch(a, build, pg._join_code, now)
    r = await rp.refresh_run(r)
    await audit(
        session,
        principal,
        "engage.run_launched",
        "engage_run",
        r.id,
        organization_id=a.organization_id,
        after={"activity_id": str(a.id), "run_no": r.run_no},
    )
    return pg.run_summary(r)


async def manager_run(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID
) -> tuple[EngageRun, EngageActivity]:
    rp = repo()
    r = await rp.get_run(run_id)
    if r is None:
        raise ProblemError("not_found")
    a = await rp.get_activity(r.activity_id)
    if a is None:
        raise ProblemError("not_found")
    await pg.require_manage(request, session, principal, a)
    return await rp.refresh_run(r), a


async def control_run(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, body: ControlIn
) -> dict[str, Any]:
    r, a = await manager_run(request, session, principal, run_id)
    now = utcnow()
    act = body.action

    def apply(r: EngageRun) -> None:
        n = len(r.questions)

        def bad(allowed: list[str]) -> ProblemError:
            return ProblemError("invalid_state_transition", current_state=r.status, allowed=allowed)

        if act == "start":
            if r.status != "scheduled":
                raise bad(["scheduled"])
            r.status, r.opened_at = "open", now
        elif act == "close":
            if r.status not in LIVE_STATUSES:
                raise bad(list(LIVE_STATUSES))
            r.status, r.closed_at = "closed", now
        elif act == "finalise":
            if r.status == "finalised":
                raise bad(["scheduled", "open", "closed"])
            r.status = "finalised"
            r.closed_at = r.closed_at or now
            r.finalised_at = now
            r.results_published = True
        elif act == "goto":
            if r.status == "finalised":
                raise bad(["scheduled", "open", "closed"])
            if body.position is None or body.position >= n:
                raise pg._invalid([{"field": "position", "code": "invalid", "message": f"0..{n - 1}"}])
            r.current_position = body.position
        elif act in ("reveal", "hide"):
            targets = (
                set(range(n))
                if r.settings.get("pacing") == "all_at_once" and body.position is None
                else {r.current_position if body.position is None else body.position}
            )
            if any(p >= n for p in targets):
                raise pg._invalid([{"field": "position", "code": "invalid", "message": f"0..{n - 1}"}])
            cur = set(r.revealed_positions or [])
            r.revealed_positions = sorted(cur | targets if act == "reveal" else cur - targets)
            if act == "reveal":
                r.closed_positions = sorted(set(r.closed_positions or []) | targets)
        elif act in ("publish", "unpublish"):
            if act == "publish" and r.status in LIVE_STATUSES:
                raise bad(["closed", "finalised"])
            r.results_published = act == "publish"
        r.state_version += 1

    r = await repo().mutate_run(r.id, apply)
    await audit(
        session,
        principal,
        f"engage.run_{act}",
        "engage_run",
        r.id,
        organization_id=a.organization_id,
        after={"position": body.position, "status": r.status},
    )
    if act == "finalise":
        await emit_event(
            session,
            "engage.run_finalised",
            {"run_id": str(r.id), "activity_id": str(a.id), "activity_type": a.activity_type},
            aggregate_type="engage_run",
            aggregate_id=r.id,
            organization_id=a.organization_id,
        )
    return pg.run_summary(r)


# =========================================================================== participants


async def run_by_code(code: str) -> tuple[EngageRun, EngageActivity]:
    code = (code or "").strip().upper()
    if len(code) != pg.JOIN_CODE_LEN or any(c not in pg.JOIN_ALPHABET for c in code):
        raise ProblemError("not_found")
    rp = repo()
    run_id = await rp.run_id_by_code(code)
    r = await rp.get_run(run_id) if run_id else None
    if r is None:
        raise ProblemError("not_found")
    a = await rp.get_activity(r.activity_id)
    if a is None or a.deleted_at is not None:
        raise ProblemError("not_found")
    return r, a


async def join_preview(
    request: Request, session: AsyncSession, principal: Principal, code: str
) -> dict[str, Any]:
    await ratelimit.hit(f"engage:join:{principal.user_id}", pg.JOIN_RULES, scope="engage.join")
    r, a = await run_by_code(code)
    rp = repo()
    r = await rp.refresh_run(r)
    joined = (await rp.participant(r.id, principal.user_id)) is not None
    may = await pg._may_join(request, session, principal, a, r)
    return {
        "run_id": str(r.id),
        "title": a.title,
        "description": a.description,
        "activity_type": a.activity_type,
        "status": r.status,
        "audience": r.settings.get("audience"),
        "identity_mode": r.settings.get("identity_mode"),
        "eligible": may,
        "joined": joined,
    }


def _closed(status: str) -> ProblemError:
    return ProblemError(
        "invalid_state_transition",
        detail="This activity is no longer accepting participants.",
        current_state=status,
        allowed=list(LIVE_STATUSES),
    )


async def join(request: Request, session: AsyncSession, principal: Principal, code: str) -> dict[str, Any]:
    await ratelimit.hit(f"engage:join:{principal.user_id}", pg.JOIN_RULES, scope="engage.join")
    r, a = await run_by_code(code)
    rp = repo()
    r = await rp.refresh_run(r)
    if not await pg._may_join(request, session, principal, a, r):
        raise ProblemError("permission_denied", detail="This activity is open to members of its batch only.")
    await require_app_enabled(session, app_key="engage")
    existing = await rp.participant(r.id, principal.user_id)
    if existing is None:
        if r.status not in LIVE_STATUSES:
            raise _closed(r.status)
        name: Any = None
        if r.settings.get("identity_mode") != "anonymous":
            from app.modules.identity import public as identity_public

            async with pg._sys(session, "engage.join"):
                # §2.4: the nickname only, never a learner's full name or e-mail.
                prof = await identity_public.get_profile(session, principal.user_id)
                name = prof.display_name if prof else None
        try:
            await rp.join(r.id, principal.user_id, (name or None) and str(name)[:200], r.organization_id)
        except JoinRefused as e:
            if e.reason == "full":
                raise pg._problem(
                    "participant_limit_reached", 409, "This activity is full", limit=e.limit
                ) from None
            raise _closed(e.status) from None
    return {"run_id": str(r.id), "status": r.status, "joined": True}


async def answer(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, body: AnswerIn
) -> dict[str, Any]:
    await ratelimit.hit(f"engage:answer:{principal.user_id}", pg.ANSWER_RULES, scope="engage.answer")
    rp = repo()
    r = await rp.get_run(run_id)
    if r is None:
        raise ProblemError("not_found")
    r = await rp.refresh_run(r)
    p = await rp.participant(r.id, principal.user_id)
    if p is None:
        raise pg._problem("not_joined", 403, "Join the activity first")
    q = next((x for x in r.questions if x["id"] == str(body.question_id)), None)
    if q is None:
        raise ProblemError("not_found")
    if not pg._answerable(r, int(q["position"])):
        raise pg._problem("question_not_open", 409, "This question isn't accepting answers right now")
    ans, terms, filtered, correct = pg._build_answer(r, q, body)
    resp = EngageResponse(
        id=uuid7(),
        run_id=r.id,
        participant_id=p.id,
        organization_id=r.organization_id,
        user_id=principal.user_id,
        question_id=body.question_id,
        answer=ans,
        terms=terms,
        filtered=filtered,
        is_correct=correct,
    )
    at = await rp.answer(principal.user_id, resp)
    if at is None:
        raise pg._problem("already_answered", 409, "You already answered this question")
    return {"question_id": str(body.question_id), "accepted": True, "answered_at": to_rfc3339(at)}


# =========================================================================== aggregation


def counts_of(participants: int, responses: list[EngageResponse]) -> tuple[int, int, int]:
    return participants, len({x.participant_id for x in responses}), len(responses)


def aggregate(responses: list[EngageResponse]) -> dict[str, Any]:
    """``service._aggregate`` over the run's responses (same keys, counts and word order)."""
    answered = Counter(str(x.question_id) for x in responses)
    choice: dict[str, dict[str, int]] = defaultdict(dict)
    term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    ratings: dict[str, dict[str, int]] = defaultdict(dict)
    for x in responses:
        q = str(x.question_id)
        ans = x.answer or {}
        for o in ans.get("option_ids") or []:
            choice[q][str(o)] = choice[q].get(str(o), 0) + 1
        if not x.filtered:
            term_counts[q].update(x.terms or [])
        if "rating" in ans:
            k = str(int(ans["rating"]))
            ratings[q][k] = ratings[q].get(k, 0) + 1
    words: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in sorted(term_counts):
        # ORDER BY n DESC, t: the term under the database collation (en_US.utf8), not code points
        for t, n in sorted(term_counts[q].items(), key=lambda kv: (-kv[1], sort_key(kv[0])))[: pg.WORD_TOP]:
            words[q].append({"term": t, "count": int(n)})
    return {"answered": dict(answered), "choice": choice, "words": words, "ratings": ratings}


def leaderboard(
    r: EngageRun, participants: dict[uuid.UUID, EngageParticipant], responses: list[EngageResponse]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[uuid.UUID, dict[str, Any]]]:
    """``service._leaderboard``: correct responses ordered by (question_id, answered_at, id)."""
    anon = r.settings.get("identity_mode") == "anonymous"
    rule = r.settings.get("winner_rule")
    started = r.opened_at or r.created_at
    rows = sorted(
        (x for x in responses if x.is_correct is True),
        key=lambda x: (str(x.question_id), x.answered_at, str(x.id)),
    )
    score: dict[uuid.UUID, dict[str, Any]] = {}
    winners: dict[str, dict[str, Any]] = {}
    by_q: dict[str, list[uuid.UUID]] = defaultdict(list)
    for x in rows:
        s = score.setdefault(x.participant_id, {"wins": 0, "correct": 0, "time_ms": 0})
        s["correct"] += 1
        s["time_ms"] += max(0, int((x.answered_at - started).total_seconds() * 1000)) if started else 0
        by_q[str(x.question_id)].append(x.participant_id)
    for q_key, pids in by_q.items():
        first = pids[0]
        if rule == "fastest_first":
            score[first]["wins"] += 1
        winners[q_key] = {
            "fastest": pg._label(participants.get(first), anon),
            "also_correct": [pg._label(participants.get(p), anon) for p in pids[1:6]],
            "also_correct_count": max(0, len(pids) - 1),
        }
    if rule == "fastest_first":
        order = sorted(score.items(), key=lambda kv: (-kv[1]["wins"], -kv[1]["correct"], kv[1]["time_ms"]))
    else:
        order = sorted(score.items(), key=lambda kv: (-kv[1]["correct"], kv[1]["time_ms"]))
    ranked: list[dict[str, Any]] = []
    mine: dict[uuid.UUID, dict[str, Any]] = {}
    for i, (pid, s) in enumerate(order, start=1):
        row = {"rank": i, "label": pg._label(participants.get(pid), anon), **s}
        mine[pid] = row
        if i <= pg.LEADERBOARD_TOP:
            ranked.append(row)
    return ranked, winners, mine


def texts_of(
    r: EngageRun, participants: dict[uuid.UUID, EngageParticipant], responses: list[EngageResponse]
) -> dict[str, list[dict[str, Any]]]:
    anon = r.settings.get("identity_mode") == "anonymous"
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    text_q = {q["id"] for q in r.questions if q["kind"] == "text"}
    if not text_q:
        return out
    for x in sorted(responses, key=lambda x: (x.answered_at, str(x.id)), reverse=True):
        k = str(x.question_id)
        if k in text_q and len(out[k]) < pg.TEXT_SAMPLE:
            out[k].append(
                {
                    "label": pg._label(participants.get(x.participant_id), anon),
                    "text": None if x.filtered else (x.answer or {}).get("text"),
                    "filtered": x.filtered,
                }
            )
    return out


async def presenter_state(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, since: str | None
) -> tuple[dict[str, Any], str]:
    r, a = await manager_run(request, session, principal, run_id)
    rp = repo()
    participants = await rp.participants_map(r.id)
    responses = await rp.responses(r.id)
    counts = counts_of(len(participants), responses)
    version = pg.version_of(r, counts)
    if since and since == version:
        return {"unchanged": True, "version": version}, version
    agg = aggregate(responses)
    is_quiz = r.settings.get("winner_rule") is not None
    ranked, winners, _ = leaderboard(r, participants, responses) if is_quiz else ([], {}, {})
    texts = texts_of(r, participants, responses)
    anon = r.settings.get("identity_mode") == "anonymous"
    questions = []
    for q in r.questions:
        qr = pg._question_result(q, agg, with_dist=True, with_correct=True)
        qr["revealed"] = q["position"] in (r.revealed_positions or [])
        if is_quiz:
            qr["winner"] = winners.get(q["id"])
        if q["kind"] == "text":
            qr["texts"] = texts.get(q["id"], [])
        questions.append(qr)
    recent = sorted(participants.values(), key=lambda p: p.seq)
    return (
        {
            "version": version,
            "run": pg.run_summary(r),
            "activity": {
                "id": str(a.id),
                "title": a.title,
                "description": a.description,
                "activity_type": a.activity_type,
            },
            "joined": counts[0],
            "voted": counts[1],
            "total_votes": counts[2],
            "participants": [{"label": pg._label(p, anon), "seq": p.seq} for p in recent[-50:]],
            "questions": questions,
            "leaderboard": ranked,
        },
        version,
    )


async def participant_state(
    request: Request, session: AsyncSession, principal: Principal, run_id: uuid.UUID, since: str | None
) -> tuple[dict[str, Any], str]:
    rp = repo()
    r = await rp.get_run(run_id)
    if r is None:
        raise ProblemError("not_found")
    a = await rp.get_activity(r.activity_id)
    if a is None:
        raise ProblemError("not_found")
    r = await rp.refresh_run(r)
    p = await rp.participant(r.id, principal.user_id)
    if p is None:
        raise pg._problem("not_joined", 403, "Join the activity first")
    responses = await rp.responses(r.id)
    mine_rows = [x for x in responses if x.participant_id == p.id]
    counts = counts_of(await rp.participant_count(r.id), responses)
    version = pg.version_of(r, counts, f"{p.id}:{len(mine_rows)}")
    if since and since == version:
        return {"unchanged": True, "version": version}, version
    live = r.settings.get("results_mode") == "live"
    visible = pg._visible_positions(r)
    revealed = set(r.revealed_positions or [])
    needs_agg = live or r.results_published or bool(revealed)
    empty: dict[str, Any] = {"answered": {}, "choice": {}, "words": {}, "ratings": {}}
    agg = aggregate(responses) if needs_agg else empty
    is_quiz = r.settings.get("winner_rule") is not None
    show_board = is_quiz and r.results_published
    if show_board:
        participants = await rp.participants_map(r.id)
        ranked, _w, by_p = leaderboard(r, participants, responses)
    else:
        ranked, by_p = [], {}
    mine = {str(x.question_id): (x.answer, x.is_correct, x.answered_at) for x in mine_rows}
    anon = r.settings.get("identity_mode") == "anonymous"
    questions = []
    for q in r.questions:
        pos = int(q["position"])
        if pos not in visible:
            continue
        shown = pos in revealed or r.results_published
        live_kind = live and q["kind"] in ("single_choice", "multi_choice", "rating")
        qr = pg._question_result(q, agg, with_dist=shown or live_kind, with_correct=shown and is_quiz)
        qr["revealed"] = pos in revealed
        qr["answerable"] = pg._answerable(r, pos) and q["id"] not in mine
        m = mine.get(q["id"])
        qr["my_answer"] = m[0] if m else None
        if m and shown and is_quiz:
            qr["my_correct"] = m[1]
        questions.append(qr)
    return (
        {
            "version": version,
            "run": {
                "id": str(r.id),
                "status": r.status,
                "pacing": r.settings.get("pacing"),
                "results_mode": r.settings.get("results_mode"),
                "identity_mode": r.settings.get("identity_mode"),
                "current_position": r.current_position,
                "question_count": len(r.questions),
                "results_published": r.results_published,
                "closes_at": to_rfc3339(r.closes_at) if r.closes_at else None,
            },
            "activity": {"title": a.title, "description": a.description, "activity_type": a.activity_type},
            "me": {"label": pg._label(p, anon), "answered": len(mine_rows)},
            "joined": counts[0],
            "questions": questions,
            "leaderboard": ranked if show_board else [],
            "my_rank": by_p.get(p.id) if show_board else None,
        },
        version,
    )


async def my_runs(principal: Principal) -> dict[str, Any]:
    rp = repo()
    out = []
    for part in await rp.my_participations(principal.user_id, 50):
        r = await rp.get_run(part.run_id)
        a = await rp.get_activity(r.activity_id) if r else None
        if r is None or a is None or a.deleted_at is not None:
            continue
        out.append(
            {
                "run_id": str(r.id),
                "title": a.title,
                "activity_type": a.activity_type,
                "status": r.status,
                "results_published": r.results_published,
                "joined_at": to_rfc3339(part.joined_at),
            }
        )
    return {"data": out}


async def erase_user(user_id: uuid.UUID) -> dict[str, Any]:
    return await _repo("engage.erasure").erase_user(user_id)
