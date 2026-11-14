"""Server-side answer validation and scoring for objective question types (pure functions).

Response bodies (practice answers and attempt autosave):

* ``mcq_single`` / ``mcq_multi``: ``{"option_ids": ["<uuid>", ...]}`` (``[]`` = cleared)
* ``numeric``: ``{"value": "12.5"}``  — key ``{"value": "12.5", "tolerance": "0.01"}``
* ``fill_blank``: ``{"value": "photosynthesis"}`` — key ``{"accepted": [..], "case_sensitive": false}``
* ``essay`` (also used for short answers with settings ``max_words``): ``{"text": "..."}`` — key
  ``{"reference_answer_md", "reference_answer_html"?, "rubric": [{criterion, max_marks, description?}]}``;
  never auto-scored (``is_correct`` is None: human / AI-suggested grading in the consumer)
* ``poll``: ``{"option_ids": [..]}`` (one unless settings ``allow_multiple``) — ungraded
* ``survey``: Likert ``{"option_ids": ["<one>"]}`` / open ``{"text": "..."}`` — ungraded
* ``word_cloud``: ``{"words": ["..", ..]}`` (settings ``max_words`` / ``max_chars``) — ungraded

Multi-select is exact-set match (system-architecture §8.6); negative marks apply only to
answered-and-wrong items; unanswered items score 0.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.errors import ProblemError

OBJECTIVE_TYPES = frozenset({"mcq_single", "mcq_multi", "numeric", "fill_blank"})
CODING_TYPE = "coding"  # tests only (judged by the coding module); never served in practice
MCQ_TYPES = frozenset({"mcq_single", "mcq_multi"})
MAX_VALUE_CHARS = 200
ESSAY_TYPE = "essay"
UNGRADED_TYPES = frozenset({"poll", "survey", "word_cloud"})
NEW_TYPES = frozenset({ESSAY_TYPE}) | UNGRADED_TYPES
ALL_TYPES = OBJECTIVE_TYPES | {CODING_TYPE} | NEW_TYPES
OPTION_TYPES = MCQ_TYPES | {"poll", "survey"}
MAX_ESSAY_CHARS = 20000
MAX_OPEN_CHARS = 2000
LIKERT_LABELS: dict[int, list[str]] = {
    3: ["Disagree", "Neutral", "Agree"],
    4: ["Strongly disagree", "Disagree", "Agree", "Strongly agree"],
    5: ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"],
    6: ["Strongly disagree", "Disagree", "Slightly disagree", "Slightly agree", "Agree", "Strongly agree"],
    7: [
        "Strongly disagree",
        "Disagree",
        "Slightly disagree",
        "Neutral",
        "Slightly agree",
        "Agree",
        "Strongly agree",
    ],
}


def _bad(field: str, message: str, code: str = "invalid") -> ProblemError:
    return ProblemError("validation_failed", errors=[{"field": field, "code": code, "message": message}])


def _decimal(raw: Any, field: str) -> Decimal:
    try:
        d = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError) as e:
        raise _bad(field, "must be a number") from e
    if not d.is_finite():
        raise _bad(field, "must be a finite number")
    return d


def validate_key(
    qtype: str, options: list[dict[str, Any]], answer_key: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Validate an authored key; returns the normalised ``answer_key`` to store."""
    if qtype == CODING_TYPE:
        if options:
            raise _bad("options", "coding questions have no options")
        return None  # judged against the coding problem's hidden cases
    if qtype in NEW_TYPES:
        return _validate_new_key(qtype, options, answer_key)
    if qtype not in OBJECTIVE_TYPES:
        raise _bad("question_type", "unsupported question type")
    if qtype in MCQ_TYPES:
        if not 2 <= len(options) <= 10:
            raise _bad("options", "2 to 10 options are required")
        n_correct = sum(1 for o in options if o.get("is_correct"))
        if qtype == "mcq_single" and n_correct != 1:
            raise _bad("options", "exactly one option must be correct")
        if qtype == "mcq_multi" and n_correct < 1:
            raise _bad("options", "at least one option must be correct")
        return None
    if options:
        raise _bad("options", f"{qtype} questions have no options")
    if not isinstance(answer_key, dict):
        raise _bad("answer_key", "answer_key is required", "required")
    if qtype == "numeric":
        value = _decimal(answer_key.get("value"), "answer_key.value")
        tol = _decimal(answer_key.get("tolerance", "0"), "answer_key.tolerance")
        if tol < 0:
            raise _bad("answer_key.tolerance", "must be >= 0")
        return {"value": str(value), "tolerance": str(tol)}
    accepted = answer_key.get("accepted")
    if (
        not isinstance(accepted, list)
        or not accepted
        or not all(isinstance(a, str) and a.strip() for a in accepted)
    ):
        raise _bad("answer_key.accepted", "a non-empty list of accepted answers is required")
    return {
        "accepted": [a.strip() for a in accepted][:20],
        "case_sensitive": bool(answer_key.get("case_sensitive", False)),
    }


def _validate_new_key(
    qtype: str, options: list[dict[str, Any]], answer_key: dict[str, Any] | None
) -> dict[str, Any] | None:
    if any(o.get("is_correct") for o in options):
        raise _bad("options", f"{qtype} questions have no correct answer")
    if qtype == "poll" and not 2 <= len(options) <= 10:
        raise _bad("options", "2 to 10 options are required")
    if qtype == "survey" and options and not 3 <= len(options) <= 7:
        raise _bad("options", "a Likert scale has 3 to 7 points")
    if qtype in (ESSAY_TYPE, "word_cloud") and options:
        raise _bad("options", f"{qtype} questions have no options")
    if qtype != ESSAY_TYPE:
        if answer_key:
            raise _bad("answer_key", f"{qtype} questions are ungraded and have no answer key")
        return None
    if not answer_key:
        return None
    if not isinstance(answer_key, dict):
        raise _bad("answer_key", "must be an object")
    out: dict[str, Any] = {}
    # Reference answer: ``reference_answer_md`` (plain/markdown, what ``ai.grade_response`` takes)
    # and/or ``reference_answer_html`` (rich text from the studio editor; sanitised by the bank).
    for name in ("reference_answer_md", "reference_answer_html"):
        ref = answer_key.get(name)
        if ref is None:
            continue
        if not isinstance(ref, str) or len(ref) > MAX_ESSAY_CHARS:
            raise _bad(f"answer_key.{name}", "must be text up to 20000 characters")
        if ref.strip():
            out[name] = ref.strip()
    if "reference_answer_md" not in out and "reference_answer_html" in out:
        plain = re.sub(r"<[^>]+>", " ", out["reference_answer_html"])
        out["reference_answer_md"] = re.sub(r"\s+", " ", plain).strip()
    rubric = answer_key.get("rubric")
    if rubric is not None:
        if not isinstance(rubric, list) or len(rubric) > 20:
            raise _bad("answer_key.rubric", "must be a list of at most 20 rows")
        rows = []
        for i, row in enumerate(rubric):
            crit = row.get("criterion") if isinstance(row, dict) else None
            if not isinstance(crit, str) or not crit.strip() or len(crit) > 300:
                raise _bad(f"answer_key.rubric.{i}.criterion", "1 to 300 characters required")
            assert isinstance(row, dict)
            raw = row.get("max_marks", row.get("marks", 0))
            marks = _decimal(raw, f"answer_key.rubric.{i}.max_marks")
            if not Decimal(0) <= marks <= Decimal(100):
                raise _bad(f"answer_key.rubric.{i}.max_marks", "must be between 0 and 100")
            r: dict[str, Any] = {"criterion": crit.strip(), "max_marks": str(marks), "marks": str(marks)}
            desc = row.get("description")
            if desc is not None:
                if not isinstance(desc, str) or len(desc) > 1000:
                    raise _bad(f"answer_key.rubric.{i}.description", "must be text up to 1000 characters")
                if desc.strip():
                    r["description"] = desc.strip()
            rows.append(r)
        if rows:
            out["rubric"] = rows
    return out or None


def _int_setting(settings: dict[str, Any], name: str, lo: int, hi: int, default: int | None) -> int | None:
    raw = settings.get(name, default)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or not lo <= raw <= hi:
        raise _bad(f"settings.{name}", f"must be a whole number from {lo} to {hi}")
    return raw


def validate_settings(qtype: str, settings: dict[str, Any] | None, n_options: int) -> dict[str, Any]:
    """Normalised non-key per-type settings (delivered to learners)."""
    st = dict(settings or {})
    if qtype == "poll":
        allow = st.get("allow_multiple", False)
        if not isinstance(allow, bool):
            raise _bad("settings.allow_multiple", "must be true or false")
        return {"allow_multiple": allow}
    if qtype == "survey":
        scale = st.get("scale", "likert" if n_options else "open")
        if scale not in ("likert", "open"):
            raise _bad("settings.scale", "must be likert or open")
        if scale == "open":
            if n_options:
                raise _bad("options", "open survey questions have no options")
            return {"scale": "open"}
        if not n_options:
            raise _bad("options", "a Likert question needs its scale labels")
        return {"scale": "likert", "points": n_options}
    if qtype == "word_cloud":
        return {
            "max_words": _int_setting(st, "max_words", 1, 5, 1),
            "max_chars": _int_setting(st, "max_chars", 1, 40, 30),
        }
    if qtype == ESSAY_TYPE:
        mw = _int_setting(st, "max_words", 1, 5000, None)
        return {"max_words": mw} if mw else {}
    if st:
        raise _bad("settings", f"{qtype} questions have no settings")
    return {}


def _text_response(response: dict[str, Any], limit: int) -> dict[str, Any] | None:
    raw = response.get("text")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        raise _bad("response.text", "must be text")
    if len(raw) > limit:
        raise _bad("response.text", "too long")
    return {"text": raw.strip()}


def _words_response(response: dict[str, Any], settings: dict[str, Any] | None) -> dict[str, Any] | None:
    st = settings or {}
    words = response.get("words")
    if words is None:
        return None
    if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
        raise _bad("response.words", "must be a list of words")
    clean = [re.sub(r"\s+", " ", w.strip()) for w in words if w.strip()]
    if len(clean) > int(st.get("max_words") or 5):
        raise _bad("response.words", "too many words")
    if any(len(w) > int(st.get("max_chars") or 40) for w in clean):
        raise _bad("response.words", "a word is too long")
    return {"words": clean} if clean else None


def normalise_response(
    qtype: str,
    response: Any,
    option_ids: set[uuid.UUID],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Validate a learner's response against the version; ``None`` = cleared/unanswered."""
    if response is None:
        return None
    if not isinstance(response, dict):
        raise _bad("response", "must be an object")
    if qtype == ESSAY_TYPE:
        return _text_response(response, MAX_ESSAY_CHARS)
    if qtype == "survey" and not option_ids:
        return _text_response(response, MAX_OPEN_CHARS)
    if qtype == "word_cloud":
        return _words_response(response, settings)
    if qtype == CODING_TYPE:
        raw_sub = response.get("submission_id")
        if raw_sub is None:
            return None
        try:
            return {"submission_id": str(uuid.UUID(str(raw_sub)))}
        except ValueError as e:
            raise _bad("response.submission_id", "not a valid submission id") from e
    if qtype in OPTION_TYPES:
        raw = response.get("option_ids")
        if not isinstance(raw, list):
            if raw is None and "value" in response:
                raise _bad("response", "this question takes option_ids, not a value", "wrong_response_type")
            raise _bad("response.option_ids", "must be a list of option ids")
        try:
            ids = sorted({str(uuid.UUID(str(x))) for x in raw})
        except ValueError as e:
            raise _bad("response.option_ids", "not a valid option id") from e
        if any(uuid.UUID(i) not in option_ids for i in ids):
            raise _bad("response.option_ids", "option does not belong to this question")
        single = qtype in ("mcq_single", "survey") or (
            qtype == "poll" and not (settings or {}).get("allow_multiple")
        )
        if single and len(ids) > 1:
            raise _bad("response.option_ids", "only one option may be selected")
        return {"option_ids": ids} if ids else None
    if "value" not in response and response.keys() & {"option_ids", "text", "words", "submission_id"}:
        # e.g. {"option_ids": [...]} sent for a numeric question: a wrong shape, not "cleared".
        raise _bad("response", f"a {qtype} answer is a value", "wrong_response_type")
    raw_value = response.get("value")
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        return None
    if not isinstance(raw_value, str | int | float) or isinstance(raw_value, bool):
        raise _bad("response.value", "must be a string or number")
    value = str(raw_value).strip()
    if len(value) > MAX_VALUE_CHARS:
        raise _bad("response.value", "too long")
    if qtype == "numeric":
        _decimal(value, "response.value")
    return {"value": value}


def _norm_text(s: str, case_sensitive: bool) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    return s if case_sensitive else s.casefold()


def is_correct(
    qtype: str,
    response: dict[str, Any] | None,
    correct_option_ids: set[uuid.UUID],
    answer_key: dict[str, Any] | None,
) -> bool | None:
    """``None`` when unanswered or not auto-scorable (coding, essay, ungraded types)."""
    if response is None:
        return None
    if qtype in NEW_TYPES:
        return None  # essay: human-graded; poll/survey/word_cloud: ungraded
    if qtype == CODING_TYPE:
        return None  # needs the judge verdict: scored by assessments (``assessments.coding``)
    if qtype in MCQ_TYPES:
        chosen = {uuid.UUID(x) for x in response.get("option_ids", [])}
        return chosen == correct_option_ids
    if not answer_key:
        return False
    value = str(response.get("value", ""))
    if qtype == "numeric":
        try:
            v = Decimal(value)
        except InvalidOperation:
            return False
        return abs(v - Decimal(answer_key["value"])) <= Decimal(answer_key.get("tolerance", "0"))
    cs = bool(answer_key.get("case_sensitive"))
    target = _norm_text(value, cs)
    return any(_norm_text(a, cs) == target for a in answer_key.get("accepted", []))


def marks_for(correct: bool | None, marks: Decimal, negative: Decimal) -> Decimal:
    if correct is None:
        return Decimal("0")
    return marks if correct else -negative
