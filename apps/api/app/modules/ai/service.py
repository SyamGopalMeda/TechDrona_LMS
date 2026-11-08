"""Public contract of the ai module (WISEMAN-FEATURES build, coordinator-defined 2026-11-06).

Callers (placement question banks, learning assignments, assessments evaluation, paths) import
ONLY these names. The ai agent implements them; signatures may gain optional keyword args but
must not otherwise change without the coordinator.

Rules for every function:
* Raises ``AIDisabled`` when AI (or the app) is turned off on the platform,
  ``AIQuotaExceeded`` when a platform cap or a learner's tutor limit is hit, ``AIUnavailable`` when the
  provider is unreachable / not configured. Each maps to problem+json (403 ``ai_disabled``,
  429 ``ai_quota_exceeded``, 503 ``ai_unavailable``) via ``ProblemError``-compatible codes.
* AI output is a SUGGESTION: callers must store it as draft / pending and require a human or
  deterministic step to finalize (no AI result is ever auto-published).
* Never send hidden test cases, answer keys of other questions, or personal data beyond the
  learner's own response text to the provider.
* Every call is metered (``ai_usage``) and runs through the provider adapter; tests and dev use
  the clearly-named fake adapter, which production startup refuses.

Implementation notes (ai agent):
* ``AIError`` subclasses ``ProblemError``: letting one propagate out of a route renders the
  right problem+json automatically; ``e.code`` and ``str(e)`` (the detail) keep working for
  callers that catch and re-raise.
* Output is parsed and validated against a per-feature schema; one repair round-trip is made
  on invalid output, then ``AIUnavailable``. Every provider call is metered, valid or not
  (only valid tutor replies count against a learner's interaction limit).
* App gating: ``generate_questions``/``generate_path`` need ``ai_generation``,
  ``grade_response`` needs ``ai_grading``, ``tutor_reply`` needs ``ai_tutor``.
* Single company (WS3): settings and app toggles are platform-wide. Every ``org_id`` argument
  is accepted for compatibility and IGNORED; callers should stop passing it.
* SEC-05 per-user rate limits (``enforce_tutor_rate``, ``enforce_generate_rate``), SEC-14/15
  reserve → call → finalise ledger (``store``), SEC-17 server-side tutor history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.db import as_system
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.core.ratelimit import DAY, HOUR, MIN, Rule
from app.core.time import to_rfc3339
from app.modules.ai import prompts as P
from app.modules.ai import store
from app.modules.ai.adapters import (
    AIAdapter,
    AICompletion,
    AIConfigurationError,
    AIProviderError,
    AIRequest,
    get_ai_adapter,
    load_config,
)


class AIError(ProblemError):
    code = "ai_unavailable"
    status = 503
    title = "AI is temporarily unavailable"

    def __init__(self, detail: str | None = None, **ext: Any) -> None:
        cls = type(self)
        super().__init__(cls.code, cls.status, cls.title, detail or cls.title, **ext)

    def __str__(self) -> str:
        return self.detail


class AIDisabled(AIError):
    code = "ai_disabled"
    status = 403
    title = "AI is turned off"


class AIQuotaExceeded(AIError):
    code = "ai_quota_exceeded"
    status = 429
    title = "AI usage limit reached"


class AIUnavailable(AIError):
    code = "ai_unavailable"
    status = 503
    title = "AI is temporarily unavailable"


QuestionKind = Literal["mcq", "code", "essay", "poll", "survey", "word_cloud"]
SourceMode = Literal["topic", "company", "subject", "test"]


@dataclass(frozen=True, slots=True)
class QuestionGenSpec:
    question_type: QuestionKind
    count: int  # 1..50
    source_mode: SourceMode
    subject: str | None = None
    topic: str | None = None
    company: str | None = None
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    extra_instructions: str | None = None


@dataclass(frozen=True, slots=True)
class GradeSuggestion:
    marks: Decimal
    max_marks: Decimal
    feedback_md: str
    confidence: float  # 0..1
    criteria: list[dict[str, Any]] = field(default_factory=list)  # per-rubric-row breakdown


@dataclass(frozen=True, slots=True)
class PathGenSpec:
    title: str
    level: Literal["beginner", "intermediate", "advanced"]
    style: Literal["mixed", "textbook"]
    target_hours: int
    approx_steps: int
    guidelines: str | None = None


# --------------------------------------------------------------------------- internals


@dataclass(frozen=True, slots=True)
class _Ctx:
    adapter: AIAdapter
    model: str
    settings: store.PlatformAI


def _adapter() -> AIAdapter:
    try:
        return get_ai_adapter()
    except (AIProviderError, AIConfigurationError) as e:
        raise AIUnavailable("AI is not configured on this server.") from e


async def _gate(session: AsyncSession, app_key: str) -> _Ctx:
    """Provider configured → platform AI enabled → app enabled. Caps are checked per call when
    the usage row is reserved (``store.reserve``)."""
    cfg = load_config()
    adapter = _adapter()
    st = await store.system_settings(session)
    if not st.enabled:
        raise AIDisabled("AI features are turned off.")
    if not (await store.system_apps(session)).get(app_key, True):
        raise AIDisabled("This AI feature is turned off.", app_key=app_key)
    model = st.model if st.model in cfg.allowed_models else cfg.default_model
    return _Ctx(adapter=adapter, model=model, settings=st)


def _uid(principal_or_user: Principal | uuid.UUID) -> uuid.UUID:
    return principal_or_user if isinstance(principal_or_user, uuid.UUID) else principal_or_user.user_id


async def _settings_for_rate(session: AsyncSession | None) -> store.PlatformAI:
    if session is not None:
        return await store.system_settings(session)
    async with store.ledger_tx("ai.settings") as s:
        return await store.read_settings(s)


async def enforce_tutor_rate(
    principal: Principal | uuid.UUID, *, session: AsyncSession | None = None
) -> None:
    """SEC-05: per-user AI tutor rate limit (platform ``tutor_per_minute`` / ``tutor_per_day``,
    default 10/min and 200/day). Raises ``429 rate_limited`` (``Retry-After``). Counts one
    request. ``tutor_reply`` already calls this, so callers need not; call it yourself only to
    refuse a request before doing other work (it then counts once more)."""
    st = await _settings_for_rate(session)
    rules = (Rule(st.tutor_per_minute, MIN), Rule(st.tutor_per_day, DAY))
    await ratelimit.hit(f"ai:tutor:{_uid(principal)}", rules, scope="ai.tutor")


async def enforce_generate_rate(
    principal: Principal | uuid.UUID, *, session: AsyncSession | None = None
) -> None:
    """SEC-05: per-user limit on "Generate with AI" (questions, paths): platform
    ``generate_per_hour`` / ``generate_per_day`` (default 30/h, 100/day)."""
    st = await _settings_for_rate(session)
    rules = (Rule(st.generate_per_hour, HOUR), Rule(st.generate_per_day, DAY))
    await ratelimit.hit(f"ai:generate:{_uid(principal)}", rules, scope="ai.generate")


def _est_tokens(system: str, messages: list[dict[str, str]]) -> int:
    return (len(system) + sum(len(m.get("content", "")) for m in messages)) // 4 + 1


async def _call(ctx: _Ctx, req: AIRequest, rid: uuid.UUID) -> AICompletion:
    """Provider call with no AI lock or AI transaction held (SEC-15); provider errors are
    finalised on the ledger before ``AIUnavailable`` is raised."""
    try:
        return await ctx.adapter.complete(req)
    except AIProviderError as e:
        await store.finalize(
            rid,
            provider=ctx.adapter.provider,
            model=ctx.model,
            tokens_in=0,
            tokens_out=0,
            outcome="provider_error",
        )
        raise AIUnavailable("The AI service could not be reached. Please try again later.") from e


def _quota(e: store.CapExceeded) -> AIQuotaExceeded:
    if e.kind == "tutor":
        return AIQuotaExceeded(
            "You've used all your tutor interactions for this activity.", used=e.used, limit=e.limit
        )
    if e.kind == "calls":
        return AIQuotaExceeded("The platform has used its AI requests for this month.")
    return AIQuotaExceeded("The platform has used its AI allowance for this month.")


async def _run[M: BaseModel](
    ctx: _Ctx,
    *,
    user_id: uuid.UUID,
    feature: str,
    system: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    out_model: type[M],
    max_tokens: int,
    effort: str = "medium",
    meta: dict[str, Any] | None = None,
    check: Any = None,
    context_type: str | None = None,
    context_id: uuid.UUID | None = None,
    tutor_limit: int | None = None,
) -> tuple[M, int]:
    """Reserve (caps + tutor limit) → call the provider → validate → finalise; one repair round.
    Returns the parsed output and the learner's valid tutor replies before this one."""
    msgs = list(messages)
    problem = ""
    used = 0
    for attempt in range(2):
        try:
            res = await store.reserve(
                settings=ctx.settings,
                user_id=user_id,
                feature=feature,
                provider=ctx.adapter.provider,
                model=ctx.model,
                est_tokens_in=_est_tokens(system, msgs),
                max_tokens=max_tokens,
                context_type=context_type,
                context_id=context_id,
                tutor_limit=tutor_limit,
            )
        except store.CapExceeded as e:
            raise _quota(e) from None
        if attempt == 0:
            used = res.tutor_used
        req = AIRequest(
            feature=feature,
            model=ctx.model,
            system=system,
            messages=msgs,
            max_tokens=max_tokens,
            json_schema=schema,
            effort=effort,
            meta=meta or {},
        )
        out = await _call(ctx, req, res.id)
        parsed: M | None = None
        try:
            parsed = out_model.model_validate(P.parse_json(out.text))
            problem = check(parsed) if check else ""
        except (ValueError, ValidationError) as e:
            problem = _short_error(e)
        ok = parsed is not None and not problem
        await store.finalize(
            res.id,
            provider=ctx.adapter.provider,
            model=out.model,
            tokens_in=out.tokens_in,
            tokens_out=out.tokens_out,
            outcome="ok" if ok else "invalid_output",
        )
        if ok and parsed is not None:
            return parsed, used
        if attempt == 0:
            msgs = [
                *messages,
                {"role": "assistant", "content": P.clip(out.text, 8000) or "{}"},
                {
                    "role": "user",
                    "content": f"That reply was not valid: {problem}. Return the corrected JSON object only.",
                },
            ]
    raise AIUnavailable("The AI returned an unusable answer. Please try again.")


def _short_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        errs = e.errors()[:3]
        return "; ".join(f"{'.'.join(str(p) for p in x.get('loc', ()))}: {x.get('msg')}" for x in errs)
    return str(e)[:200] or type(e).__name__


# --------------------------------------------------------------------------- contract


async def ai_enabled(
    session: AsyncSession, *, org_id: uuid.UUID | None = None, app_key: str | None = None
) -> bool:
    """True when AI is configured and enabled on the platform (and, if given, the app
    ``app_key`` is enabled). ``org_id`` is accepted for old callers and ignored."""
    del org_id
    if not load_config().configured:
        return False
    if not (await store.system_settings(session)).enabled:
        return False
    if app_key is not None:
        return (await store.system_apps(session)).get(app_key, True)
    return True


async def generate_questions(
    session: AsyncSession, *, org_id: uuid.UUID | None = None, user_id: uuid.UUID, spec: QuestionGenSpec
) -> list[dict[str, Any]]:
    """Draft questions in the BULK-IMPORT JSON shape owned by placement (see
    ``app.modules.placement.bulk_import.QUESTION_IMPORT_SCHEMA``). Drafts are unsaved.

    Each item: ``{"question_type", "stem_md", "difficulty": easy|medium|hard, "tags": [str],
    "explanation_md", "options": [{"text", "is_correct"}], "starter_code"?, "test_cases":
    [{"input", "expected_output", "hidden"}]}`` (validated per type), plus ``"source": "ai"``.
    Per-user rate limited (SEC-05). ``org_id`` is ignored."""
    del org_id
    if not 1 <= spec.count <= 50:
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "count", "code": "out_of_range", "message": "Ask for 1 to 50 questions."}],
        )
    if not (spec.topic or spec.subject or spec.company):
        raise ProblemError(
            "validation_failed",
            422,
            errors=[{"field": "topic", "code": "required", "message": "Give a topic, subject or company."}],
        )
    ctx = await _gate(session, "ai_generation")
    await enforce_generate_rate(user_id, session=session)
    system, user = P.questions_prompt(spec)

    def _check(o: P.QuestionsOut) -> str:
        if len(o.questions) < spec.count:
            return f"expected {spec.count} questions, got {len(o.questions)}"
        if any(q.question_type != spec.question_type for q in o.questions):
            return f"every question must have question_type {spec.question_type!r}"
        return ""

    out, _ = await _run(
        ctx,
        user_id=user_id,
        feature="question_generation",
        system=system,
        messages=[{"role": "user", "content": user}],
        schema=P.QUESTIONS_SCHEMA,
        out_model=P.QuestionsOut,
        max_tokens=min(16000, 1200 * spec.count + 1000),
        effort="medium",
        meta={
            "question_type": spec.question_type,
            "count": spec.count,
            "topic": spec.topic or spec.subject or spec.company,
            "difficulty": spec.difficulty,
        },
        check=_check,
    )
    return [{**q.model_dump(mode="json"), "source": "ai"} for q in out.questions[: spec.count]]


async def grade_response(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID,
    purpose: Literal["assignment", "assessment"],
    question_md: str,
    response_text: str,
    max_marks: Decimal,
    rubric: list[dict[str, Any]] | None = None,
    reference_answer_md: str | None = None,
) -> GradeSuggestion:
    """Suggested marks + feedback for an essay / code / short answer (pending human review).
    ``org_id`` is ignored."""
    del org_id
    ctx = await _gate(session, "ai_grading")
    if not (response_text or "").strip():
        # Nothing to grade: deterministic, no provider call.
        return GradeSuggestion(Decimal("0"), max_marks, "No response was submitted.", 1.0, [])
    system, user = P.grading_prompt(
        purpose=purpose,
        question_md=question_md,
        response_text=response_text,
        max_marks=max_marks,
        rubric=rubric,
        reference_answer_md=reference_answer_md,
    )

    def _check(o: P.GradeOut) -> str:
        return f"marks must be between 0 and {max_marks}" if o.marks > max_marks else ""

    out, _ = await _run(
        ctx,
        user_id=user_id,
        feature="grading",
        system=system,
        messages=[{"role": "user", "content": user}],
        schema=P.GRADE_SCHEMA,
        out_model=P.GradeOut,
        max_tokens=4000,
        effort="medium",
        meta={"max_marks": str(max_marks), "rubric": rubric or []},
        check=_check,
    )
    return GradeSuggestion(
        marks=out.marks.quantize(Decimal("0.01")),
        max_marks=max_marks,
        feedback_md=out.feedback_md,
        confidence=float(out.confidence),
        criteria=[c.model_dump(mode="json") for c in out.criteria],
    )


TutorContext = Literal["assignment", "path_step", "practice"]


async def tutor_reply(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID,
    context_type: TutorContext,
    context_id: uuid.UUID,
    mode: Literal["guide", "explain"],
    question_md: str,
    learner_input: str,
    history: list[dict[str, str]] | None = None,
    per_learner_limit: int | None = None,
    item_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Hint-style tutor answer that never gives the full solution in ``guide`` mode.
    Returns ``{"reply_md": str, "used": int, "limit": int}``.

    * Rate limited per user (SEC-05, ``enforce_tutor_rate``) → ``429 rate_limited``.
    * Limit per (learner, activity): the stricter of ``per_learner_limit`` and the platform
      ``per_activity_default_cap`` (default 20, D10); beyond it ``AIQuotaExceeded`` (429). The
      check and the usage reservation are atomic (SEC-14), so concurrent calls cannot overshoot.
    * History is kept on the server (SEC-17): the last turns of this learner for
      (``context_type``, ``context_id``, ``item_id``) are sent to the model, and this exchange
      is appended after a valid reply. ``history`` (client-supplied) is IGNORED and kept only
      for signature compatibility; read the history with ``tutor_history``.
    * ``org_id`` is ignored.
    """
    del org_id, history
    await enforce_tutor_rate(user_id, session=session)
    ctx = await _gate(session, "ai_tutor")
    caps = [c for c in (per_learner_limit, ctx.settings.per_activity_default_cap) if c is not None]
    limit = min(caps)
    async with as_system(session, "ai.tutor_history"):
        past = await store.history(
            session, user_id, context_type, context_id, item_id, store.TUTOR_HISTORY_TURNS
        )
        turns = [{"role": t.role, "content": t.content} for t in past]
    system, messages = P.tutor_prompt(
        mode=mode, question_md=question_md, learner_input=learner_input, history=turns
    )

    def _check(o: P.TutorOut) -> str:
        if mode == "guide" and (o.contains_full_solution or P.leaks_solution(o.reply_md)):
            return "guide mode must not contain the full solution or long code; give a hint instead"
        return ""

    out, used = await _run(
        ctx,
        user_id=user_id,
        feature="tutor",
        system=system,
        messages=messages,
        schema=P.TUTOR_SCHEMA,
        out_model=P.TutorOut,
        max_tokens=1500,
        effort="low",
        meta={"mode": mode},
        check=_check,
        context_type=context_type,
        context_id=context_id,
        tutor_limit=limit,
    )
    reply = out.reply_md
    if mode == "guide":
        reply = P.strip_long_code(reply)
    await store.append_turns(
        session, user_id, context_type, context_id, item_id, [("learner", learner_input), ("tutor", reply)]
    )
    return {"reply_md": reply, "used": used + 1, "limit": limit}


async def tutor_history(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    context_type: TutorContext,
    context_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Server-side tutor history (SEC-17) for one learner and activity, oldest first:
    ``[{"role": "learner" | "tutor", "content": str, "created_at": RFC 3339}]``. Runs in the
    caller's RLS context, so a learner only ever sees their own turns."""
    rows = await store.history(session, user_id, context_type, context_id, item_id, max(1, min(limit, 200)))
    return [{"role": t.role, "content": t.content, "created_at": to_rfc3339(t.created_at)} for t in rows]


async def generate_path(
    session: AsyncSession, *, org_id: uuid.UUID | None = None, user_id: uuid.UUID, spec: PathGenSpec
) -> dict[str, Any]:
    """Draft learning path: ``{"title", "description", "steps": [{"title", "step_type",
    "est_hours", "credits", "description_md", "url"?}]}`` — unsaved, editable by the author.
    Per-user rate limited (SEC-05). ``org_id`` is ignored."""
    del org_id
    if not 1 <= spec.approx_steps <= 60 or not 1 <= spec.target_hours <= 2000 or not spec.title.strip():
        raise ProblemError(
            "validation_failed",
            422,
            errors=[
                {
                    "field": "approx_steps",
                    "code": "out_of_range",
                    "message": "Use 1-60 steps and 1-2000 hours.",
                }
            ],
        )
    ctx = await _gate(session, "ai_generation")
    await enforce_generate_rate(user_id, session=session)
    system, user = P.path_prompt(spec)
    out, _ = await _run(
        ctx,
        user_id=user_id,
        feature="path_generation",
        system=system,
        messages=[{"role": "user", "content": user}],
        schema=P.PATH_SCHEMA,
        out_model=P.PathOut,
        max_tokens=min(16000, 600 * spec.approx_steps + 1000),
        effort="medium",
        meta={
            "title": spec.title,
            "approx_steps": spec.approx_steps,
            "target_hours": spec.target_hours,
            "style": spec.style,
        },
    )
    data = out.model_dump(mode="json")
    for s in data["steps"]:
        if not s.get("url"):
            s.pop("url", None)  # never invent links; authors attach real content
    return data


APP_KEYS = tuple(store.APPS)


async def is_app_enabled(session: AsyncSession, app_key: str) -> bool:
    """Platform toggle for ``app_key`` (no row = enabled)."""
    if app_key not in store.APPS:
        raise ValueError(f"unknown app key {app_key!r}")
    return (await store.system_apps(session)).get(app_key, True)


async def require_app_enabled(
    session: AsyncSession, org_id: uuid.UUID | None = None, *, app_key: str
) -> None:
    """Raise 403 ``app_disabled`` when Admin has turned ``app_key`` off for the platform
    ("Apps" settings). No row = enabled. Server-side enforcement for engage, paths, assignments,
    assessments and question banks (SEC-19: call it in every question-bank route, including
    ``_bank_for`` and ``resolve``); the web nav only hides entries. ``org_id`` is accepted for
    old callers and ignored: the toggle applies to everyone."""
    del org_id
    if not await is_app_enabled(session, app_key):
        raise ProblemError(
            "app_disabled",
            403,
            "App not enabled",
            f"{store.APPS[app_key][0]} is turned off.",
            app_key=app_key,
        )
