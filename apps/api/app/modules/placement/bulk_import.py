"""Bulk question import ("bring your own model") and the shared import shape for AI drafts.

Flow (QBK import endpoints in ``qbank_router``):

1. ``build_prompt`` renders a copyable prompt (question kind, count, subject, topic, extra
   instructions) that asks any chat model for a JSON array in ``QUESTION_IMPORT_SCHEMA``.
2. ``parse_raw`` + ``validate_items`` check the pasted answer and report per-item problems;
   ``fix_prompt`` renders the "copy for the model" text listing them.
3. ``import_items`` creates DRAFT questions (and, for code items, a DRAFT coding problem with
   sealed hidden test cases via ``app.modules.coding.service``) in a bank — all-or-nothing in
   the request transaction. Nothing is published: the normal review/publish workflow applies.

``app.modules.ai.service.generate_questions`` returns items in this same shape.
"""

from __future__ import annotations

import html
import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.placement import bank as qbank
from app.modules.placement import grading
from app.modules.placement.models import QuestionBank, QuestionBankItem
from app.modules.placement.schemas import OptionIn, QuestionCreate, TagIn

KINDS = ("mcq", "code", "essay", "poll", "survey", "word_cloud")
KIND_LABEL = {
    "mcq": "multiple-choice (MCQ)",
    "code": "programming",
    "essay": "essay",
    "poll": "poll",
    "survey": "survey",
    "word_cloud": "word cloud",
}
DIFFICULTY = {"easy": 2, "medium": 3, "hard": 4}
MAX_ITEMS = 50
MAX_TEXT = 5000
MAX_CASE = 96 * 1024
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 +#.\-]{0,39}$")

_TAGS = {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 8}
_DIFF = {"type": "string", "enum": ["easy", "medium", "hard"]}

ITEM_SCHEMAS: dict[str, dict[str, Any]] = {
    "mcq": {
        "type": "object",
        "required": ["question", "options"],
        "properties": {
            "type": {"const": "mcq"},
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "required": ["text", "correct"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "correct": {"type": "boolean"},
                    },
                },
            },
            "explanation": {"type": "string", "maxLength": MAX_TEXT},
            "difficulty": _DIFF,
            "tags": _TAGS,
        },
    },
    "code": {
        "type": "object",
        "required": ["description", "testCases"],
        "properties": {
            "type": {"const": "code"},
            "title": {"type": "string", "maxLength": 200},
            "description": {"type": "string", "minLength": 1, "maxLength": 20000},
            "sampleInput": {"type": "string"},
            "sampleOutput": {"type": "string"},
            "acceptanceCriteria": {"type": "string", "maxLength": MAX_TEXT},
            "testCases": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "required": ["input", "expectedOutput"],
                    "properties": {
                        "input": {"type": "string"},
                        "expectedOutput": {"type": "string"},
                        "hidden": {"type": "boolean"},
                    },
                },
            },
            "difficulty": _DIFF,
            "tags": _TAGS,
        },
    },
    "essay": {
        "type": "object",
        "required": ["question"],
        "properties": {
            "type": {"const": "essay"},
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "referenceAnswer": {"type": "string", "maxLength": 20000},
            "rubric": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "required": ["criterion", "marks"],
                    "properties": {
                        "criterion": {"type": "string", "maxLength": 300},
                        "marks": {"type": "number", "minimum": 0, "maximum": 100},
                    },
                },
            },
            "maxWords": {"type": "integer", "minimum": 1, "maximum": 5000},
            "difficulty": _DIFF,
            "tags": _TAGS,
        },
    },
    "poll": {
        "type": "object",
        "required": ["question", "options"],
        "properties": {
            "type": {"const": "poll"},
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 10,
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "allowMultiple": {"type": "boolean"},
            "tags": _TAGS,
        },
    },
    "survey": {
        "type": "object",
        "required": ["question", "scale"],
        "properties": {
            "type": {"const": "survey"},
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "scale": {"type": "string", "enum": ["likert", "open"]},
            "points": {"type": "integer", "minimum": 3, "maximum": 7},
            "labels": {"type": "array", "items": {"type": "string", "maxLength": 100}},
            "tags": _TAGS,
        },
    },
    "word_cloud": {
        "type": "object",
        "required": ["question"],
        "properties": {
            "type": {"const": "word_cloud"},
            "question": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT},
            "maxWords": {"type": "integer", "minimum": 1, "maximum": 5},
            "tags": _TAGS,
        },
    },
}

QUESTION_IMPORT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Tech Drona question import",
    "description": "A JSON array of questions of ONE kind (mcq, code, essay, poll, survey, word_cloud).",
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_ITEMS,
    "items": {"oneOf": list(ITEM_SCHEMAS.values())},
}

_SHAPES: dict[str, str] = {
    "mcq": """{
  "question": "the full question text",
  "options": [ { "text": "option text", "correct": true }, { "text": "option text", "correct": false } ],
  "explanation": "why the correct option(s) are correct",
  "difficulty": "easy | medium | hard",
  "tags": ["2-5 short lowercase tags"]
}""",
    "code": """{
  "title": "short problem title",
  "description": "the full problem statement",
  "sampleInput": "example input",
  "sampleOutput": "expected output for that input",
  "acceptanceCriteria": "how a correct solution is judged (optional, use \\"\\" if none)",
  "testCases": [
    { "input": "stdin for one case", "expectedOutput": "exact stdout for that input", "hidden": false }
  ],
  "difficulty": "easy | medium | hard",
  "tags": ["2-5 short lowercase tags"]
}""",
    "essay": """{
  "question": "the essay prompt",
  "referenceAnswer": "a model answer for the grader",
  "rubric": [ { "criterion": "what is assessed", "marks": 2 } ],
  "maxWords": 300,
  "difficulty": "easy | medium | hard",
  "tags": ["2-5 short lowercase tags"]
}""",
    "poll": """{
  "question": "the poll question",
  "options": ["choice 1", "choice 2", "choice 3"],
  "allowMultiple": false,
  "tags": ["2-5 short lowercase tags"]
}""",
    "survey": """{
  "question": "the survey statement or question",
  "scale": "likert | open",
  "points": 5,
  "tags": ["2-5 short lowercase tags"]
}""",
    "word_cloud": """{
  "question": "a prompt answered with one to three words",
  "maxWords": 1,
  "tags": ["2-5 short lowercase tags"]
}""",
}

_RULES: dict[str, list[str]] = {
    "mcq": [
        'Each question has 2-10 "options"; at least one has "correct": true (more than one is allowed)',
        'Give every question an "explanation"',
    ],
    "code": [
        "Include realistic, consistent sampleInput and sampleOutput",
        'Provide 4-6 "testCases" for automatic grading. Each has the exact stdin in "input" and the exact '
        'expected stdout in "expectedOutput"; mark grading-only cases with "hidden": true',
    ],
    "essay": ['Give a "referenceAnswer" and a "rubric" whose marks add up to the question total'],
    "poll": ['Polls have no correct answer: give 2-10 "options" as plain strings'],
    "survey": [
        'Use "scale": "likert" for agreement statements (with "points" between 3 and 7) '
        'or "open" for free text',
        "Surveys have no correct answer",
    ],
    "word_cloud": ['Word-cloud prompts are answered with 1-5 words; set "maxWords" accordingly'],
}


def _shape_for(kind: str) -> str:
    return _SHAPES[kind]


def build_prompt(
    kind: str,
    count: int,
    *,
    subject: str | None = None,
    topic: str | None = None,
    instructions: str | None = None,
) -> str:
    """Step 1 prompt for any chat model (deterministic; user text is quoted, not interpreted)."""
    about = ""
    if subject and subject.strip():
        about += f' for the subject "{subject.strip()}"'
    if topic and topic.strip():
        about += f' on the topic "{topic.strip()}"'
    lines = [
        "You are an expert assessment author. "
        f"Generate exactly {count} {KIND_LABEL[kind]} question(s){about}.",
    ]
    if instructions and instructions.strip():
        lines.append(f"Additional instructions: {instructions.strip()}")
    lines += [
        "",
        f"Return ONLY a JSON array — no prose, no explanations, no markdown, no code fences. "
        f"The array must contain exactly {count} objects, each with this exact shape:",
        _shape_for(kind),
        "",
        "Rules:",
        f"- Output must be valid JSON that JSON.parse can read — a single array of {count} objects",
        "- Do NOT wrap the JSON in ``` fences or add any text before or after it",
        '- Any double quote that appears INSIDE a string value MUST be escaped as \\" '
        "(and newlines inside strings as \\n)",
        '- "tags" must be an array of 2-5 short lowercase strings',
        *[f"- {r}" for r in _RULES[kind]],
        '- Begin the response with "[" and end with "]"',
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- validation


@dataclass
class Problem:
    index: int | None
    field: str
    message: str

    def out(self) -> dict[str, Any]:
        return {"index": self.index, "field": self.field, "message": self.message}


@dataclass
class NormItem:
    kind: str
    index: int
    data: dict[str, Any]
    tags: list[str] = field(default_factory=list)

    def preview(self) -> dict[str, Any]:
        d = self.data
        cases = d.get("testCases") or []
        if self.kind == "mcq":
            opts = [{"text": o["text"], "correct": o["correct"]} for o in d["options"]]
        elif self.kind == "poll":
            opts = [{"text": o, "correct": False} for o in d["options"]]
        elif self.kind == "survey" and d["scale"] == "likert":
            opts = [{"text": o, "correct": False} for o in d["labels"]]
        else:
            opts = []
        return {
            "index": self.index,
            "type": self.kind,
            "text": d.get("question") or d.get("title") or d.get("description", ""),
            "options": opts,
            "tags": self.tags,
            "difficulty": d.get("difficulty"),
            "sample_cases": sum(1 for c in cases if not c["hidden"]) + (1 if d.get("sampleInput") else 0),
            "hidden_cases": sum(1 for c in cases if c["hidden"]),
        }


def parse_raw(raw: str) -> tuple[list[Any] | None, list[Problem]]:
    """Parse pasted model output; tolerates surrounding ``` fences and a ``{"questions": [...]}``
    wrapper, nothing else."""
    text = raw.strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text:
        return None, [Problem(None, "json", "Nothing was pasted.")]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [Problem(None, "json", f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}.")]
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        data = data["questions"]
    if not isinstance(data, list):
        return None, [Problem(None, "json", "The response must be a JSON array of question objects.")]
    return data, []


def _str(
    item: dict[str, Any], key: str, i: int, probs: list[Problem], *, required: bool, max_len: int = MAX_TEXT
) -> str | None:
    v = item.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            probs.append(Problem(i, key, f'"{key}" is required.'))
        return None
    if not isinstance(v, str):
        probs.append(Problem(i, key, f'"{key}" must be a string.'))
        return None
    if len(v) > max_len:
        probs.append(Problem(i, key, f'"{key}" is longer than {max_len} characters.'))
        return None
    return v.strip()


def _int(item: dict[str, Any], key: str, i: int, probs: list[Problem], lo: int, hi: int) -> int | None:
    v = item.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        probs.append(Problem(i, key, f'"{key}" must be a whole number from {lo} to {hi}.'))
        return None
    return v


def _tags(item: dict[str, Any], i: int, probs: list[Problem]) -> list[str]:
    raw = item.get("tags", [])
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        probs.append(Problem(i, "tags", '"tags" must be an array of strings.'))
        return []
    out: list[str] = []
    for t in raw:
        t = re.sub(r"\s+", " ", t.strip().lower())
        if not t:
            continue
        if not TAG_RE.match(t):
            probs.append(Problem(i, "tags", f'Tag "{t[:40]}" is too long or has unsupported characters.'))
            continue
        if t not in out:
            out.append(t)
    if len(out) > 8:
        probs.append(Problem(i, "tags", "At most 8 tags are allowed."))
    return out[:8]


def _validate_one(kind: str, item: Any, i: int, probs: list[Problem]) -> NormItem | None:
    if not isinstance(item, dict):
        probs.append(Problem(i, "item", "Each item must be a JSON object."))
        return None
    n0 = len(probs)
    declared = item.get("type")
    if declared is not None and declared != kind:
        probs.append(Problem(i, "type", f'Expected "{kind}" questions, got "{declared}".'))
    known = set(ITEM_SCHEMAS[kind]["properties"])
    for extra in sorted(set(item) - known):
        probs.append(Problem(i, extra, f'Unknown field "{extra}" for {kind} questions.'))
    d: dict[str, Any] = {}
    diff = item.get("difficulty")
    if diff is not None:
        if diff not in DIFFICULTY:
            probs.append(Problem(i, "difficulty", '"difficulty" must be "easy", "medium" or "hard".'))
        else:
            d["difficulty"] = diff
    tags = _tags(item, i, probs)
    if kind == "code":
        d["title"] = _str(item, "title", i, probs, required=False, max_len=200)
        d["description"] = _str(item, "description", i, probs, required=True, max_len=20000)
        for k in ("sampleInput", "sampleOutput"):
            v = item.get(k, "")
            if v is not None and not isinstance(v, str):
                probs.append(Problem(i, k, f'"{k}" must be a string.'))
            elif v is not None and len(v.encode()) > MAX_CASE:
                probs.append(Problem(i, k, f'"{k}" is too large.'))
            d[k] = v if isinstance(v, str) else ""
        if bool(d["sampleInput"].strip()) != bool(d["sampleOutput"].strip()):
            probs.append(Problem(i, "sampleOutput", "Give both sampleInput and sampleOutput, or neither."))
        d["acceptanceCriteria"] = _str(item, "acceptanceCriteria", i, probs, required=False)
        cases = item.get("testCases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
            probs.append(Problem(i, "testCases", '"testCases" must be an array of 1 to 20 cases.'))
            cases = []
        norm_cases = []
        for j, c in enumerate(cases):
            f = f"testCases[{j}]"
            if not isinstance(c, dict):
                probs.append(Problem(i, f, "Each test case must be an object."))
                continue
            inp, exp, hid = c.get("input"), c.get("expectedOutput"), c.get("hidden", False)
            if not isinstance(inp, str) or not isinstance(exp, str):
                probs.append(Problem(i, f, '"input" and "expectedOutput" must be strings.'))
                continue
            if not exp.strip():
                probs.append(Problem(i, f"{f}.expectedOutput", '"expectedOutput" must not be empty.'))
            if len(inp.encode()) > MAX_CASE or len(exp.encode()) > MAX_CASE:
                probs.append(Problem(i, f, "Test case is too large (96 KB max each)."))
            if not isinstance(hid, bool):
                probs.append(Problem(i, f"{f}.hidden", '"hidden" must be true or false.'))
                hid = False
            extra_keys = set(c) - {"input", "expectedOutput", "hidden"}
            if extra_keys:
                probs.append(Problem(i, f, f"Unknown test-case field(s): {', '.join(sorted(extra_keys))}."))
            norm_cases.append({"input": inp, "expectedOutput": exp, "hidden": hid})
        d["testCases"] = norm_cases
    else:
        d["question"] = _str(item, "question", i, probs, required=True)
    if kind == "mcq":
        opts = item.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 10:
            probs.append(Problem(i, "options", '"options" must be an array of 2 to 10 options.'))
            opts = []
        norm = []
        for j, o in enumerate(opts):
            if not isinstance(o, dict) or not isinstance(o.get("text"), str) or not o["text"].strip():
                probs.append(Problem(i, f"options[{j}]", 'Each option needs a non-empty "text".'))
                continue
            if not isinstance(o.get("correct"), bool):
                probs.append(Problem(i, f"options[{j}].correct", '"correct" must be true or false.'))
                continue
            if len(o["text"]) > 2000:
                probs.append(Problem(i, f"options[{j}].text", "Option text is too long."))
            norm.append({"text": o["text"].strip(), "correct": o["correct"]})
        if opts and norm and not any(o["correct"] for o in norm):
            probs.append(Problem(i, "options", 'At least one option must have "correct": true.'))
        if len({o["text"].casefold() for o in norm}) != len(norm):
            probs.append(Problem(i, "options", "Options must be different from each other."))
        d["options"] = norm
        d["explanation"] = _str(item, "explanation", i, probs, required=False)
    elif kind == "poll":
        opts = item.get("options")
        if (
            not isinstance(opts, list)
            or not 2 <= len(opts) <= 10
            or not all(isinstance(o, str) and o.strip() and len(o) <= 500 for o in opts)
        ):
            probs.append(Problem(i, "options", '"options" must be 2 to 10 non-empty strings.'))
            opts = []
        d["options"] = [o.strip() for o in opts]
        am = item.get("allowMultiple", False)
        if not isinstance(am, bool):
            probs.append(Problem(i, "allowMultiple", '"allowMultiple" must be true or false.'))
            am = False
        d["allowMultiple"] = am
    elif kind == "survey":
        scale = item.get("scale")
        if scale not in ("likert", "open"):
            probs.append(Problem(i, "scale", '"scale" must be "likert" or "open".'))
            scale = "open"
        d["scale"] = scale
        if scale == "likert":
            points = _int(item, "points", i, probs, 3, 7) or 5
            labels = item.get("labels")
            if labels is None:
                labels = grading.LIKERT_LABELS[points]
            elif (
                not isinstance(labels, list)
                or len(labels) != points
                or not all(isinstance(x, str) and x.strip() and len(x) <= 100 for x in labels)
            ):
                probs.append(Problem(i, "labels", f'"labels" must be {points} non-empty strings.'))
                labels = grading.LIKERT_LABELS[points]
            d["points"], d["labels"] = points, [x.strip() for x in labels]
    elif kind == "word_cloud":
        d["maxWords"] = _int(item, "maxWords", i, probs, 1, 5) or 1
    elif kind == "essay":
        d["referenceAnswer"] = _str(item, "referenceAnswer", i, probs, required=False, max_len=20000)
        d["maxWords"] = _int(item, "maxWords", i, probs, 1, 5000)
        rubric = item.get("rubric")
        rows = []
        if rubric is not None:
            if not isinstance(rubric, list) or len(rubric) > 20:
                probs.append(Problem(i, "rubric", '"rubric" must be an array of at most 20 rows.'))
                rubric = []
            for j, r in enumerate(rubric):
                ok = (
                    isinstance(r, dict)
                    and isinstance(r.get("criterion"), str)
                    and r["criterion"].strip()
                    and len(r["criterion"]) <= 300
                    and isinstance(r.get("marks"), int | float)
                    and not isinstance(r.get("marks"), bool)
                    and 0 <= r["marks"] <= 100
                )
                if not ok:
                    probs.append(
                        Problem(
                            i, f"rubric[{j}]", 'Each rubric row needs "criterion" text and "marks" 0-100.'
                        )
                    )
                    continue
                rows.append({"criterion": r["criterion"].strip(), "marks": r["marks"]})
        d["rubric"] = rows
    if len(probs) > n0:
        return None
    return NormItem(kind, i, d, tags)


def validate_items(
    kind: str, items: list[Any], *, expected_count: int | None = None
) -> tuple[list[NormItem], list[Problem]]:
    probs: list[Problem] = []
    if kind not in KINDS:
        return [], [Problem(None, "question_type", "Unknown question type.")]
    if not items:
        return [], [Problem(None, "json", "The array is empty.")]
    if len(items) > MAX_ITEMS:
        return [], [Problem(None, "json", f"At most {MAX_ITEMS} questions can be imported at once.")]
    if expected_count is not None and len(items) != expected_count:
        probs.append(Problem(None, "json", f"Expected {expected_count} questions, got {len(items)}."))
    out = [n for i, it in enumerate(items) if (n := _validate_one(kind, it, i, probs)) is not None]
    return out, probs


def fix_prompt(kind: str, problems: list[Problem], count: int | None = None) -> str | None:
    """The "copy for the model" text: the problems, and the instruction to resend fixed JSON."""
    if not problems:
        return None
    lines = ["Your previous JSON response could not be imported. Problems found:"]
    for p in problems[:50]:
        where = "Whole response" if p.index is None else f"Item {p.index + 1}"
        lines.append(f"- {where} · {p.field}: {p.message}")
    if len(problems) > 50:
        lines.append(f"- … and {len(problems) - 50} more")
    n = f"{count} " if count else ""
    lines += [
        "",
        f"Fix every problem and return ONLY the corrected JSON array of {n}{KIND_LABEL[kind]} "
        "questions — no prose, no markdown, no code fences. Each object must have this exact shape:",
        _shape_for(kind),
    ]
    return "\n".join(lines)


def check(kind: str, raw: str | None, items: list[Any] | None) -> tuple[list[NormItem], list[Problem]]:
    if (raw is None) == (items is None):
        return [], [Problem(None, "json", "Give either the pasted text or the items.")]
    if raw is not None:
        parsed, probs = parse_raw(raw)
        if parsed is None:
            return [], probs
        items = parsed
    assert items is not None
    return validate_items(kind, items)


def problems_error(kind: str, problems: list[Problem], count: int | None) -> ProblemError:
    return ProblemError(
        "validation_failed",
        detail=f"{len(problems)} problem{'s' if len(problems) != 1 else ''} found; nothing was imported.",
        errors=[
            {
                "field": p.field if p.index is None else f"items[{p.index}].{p.field}",
                "code": "invalid",
                "message": p.message,
            }
            for p in problems[:100]
        ],
        problems=[p.out() for p in problems[:100]],
        problem_count=len(problems),
        fix_prompt=fix_prompt(kind, problems, count),
    )


# --------------------------------------------------------------------------- import


def _p(text: str) -> str:
    """Plain model text -> safe paragraph HTML (escaped; newlines kept)."""
    paras = [x for x in re.split(r"\n\s*\n", text.strip()) if x.strip()]
    return "".join(f"<p>{html.escape(x.strip()).replace(chr(10), '<br>')}</p>" for x in paras) or "<p></p>"


def _code(text: str) -> str:
    return f"<pre><code>{html.escape(text)}</code></pre>"


def needs_hidden_permission(items: list[NormItem]) -> bool:
    return any(c["hidden"] for n in items if n.kind == "code" for c in n.data["testCases"])


async def _coding_problem(
    session: AsyncSession,
    principal: Principal,
    n: NormItem,
    organization_id: uuid.UUID | None,
    difficulty: int,
) -> uuid.UUID:
    from app.modules.coding import service as coding
    from app.modules.coding.schemas import ProblemCreateIn, TestCaseIn

    d = n.data
    first_line = d["description"].strip().splitlines()[0][:80].strip()
    title = (d.get("title") or first_line or "Imported problem").strip()
    if len(title) < 3:
        title = f"{title} problem"
    statement = d["description"]
    if d.get("acceptanceCriteria"):
        statement += f"\n\n**Acceptance criteria**\n\n{d['acceptanceCriteria']}"
    try:
        p = await coding.create_problem(
            session,
            principal,
            ProblemCreateIn(
                slug=f"imp-{uuid7().hex[-16:]}",
                title=title[:200],
                statement_md=statement,
                difficulty=difficulty,
                organization_id=organization_id,
            ),
        )
        cases: list[TestCaseIn] = []
        if d.get("sampleInput", "").strip():
            cases.append(TestCaseIn(kind="sample", input=d["sampleInput"], expected_output=d["sampleOutput"]))
        cases += [
            TestCaseIn(
                kind="hidden" if c["hidden"] else "sample",
                input=c["input"],
                expected_output=c["expectedOutput"],
                weight=Decimal(1),
            )
            for c in d["testCases"]
        ]
        for c in cases:
            await coding.add_test_case(session, p, c)
    except ValidationError as e:
        raise problems_error("code", [Problem(n.index, "testCases", str(e.errors()[0]["msg"]))], None) from e
    return p.id


def question_create(
    n: NormItem,
    *,
    organization_id: uuid.UUID | None,
    primary_topic_id: uuid.UUID | None,
    source: str,
    coding_problem_id: uuid.UUID | None = None,
) -> QuestionCreate:
    d = n.data
    difficulty = DIFFICULTY.get(d.get("difficulty") or "medium", 3)
    tags = [TagIn(tag_type="custom", value=t) for t in n.tags]
    tags.append(TagIn(tag_type="source", value="ai-generated" if source == "ai" else "bulk-import"))
    common: dict[str, Any] = {
        "organization_id": organization_id,
        "primary_topic_id": primary_topic_id,
        "difficulty": difficulty,
        "tags": tags,
    }
    if n.kind == "mcq":
        n_correct = sum(1 for o in d["options"] if o["correct"])
        return QuestionCreate(
            question_type="mcq_single" if n_correct == 1 else "mcq_multi",
            stem_html=_p(d["question"]),
            options=[OptionIn(html=_p(o["text"]), is_correct=o["correct"]) for o in d["options"]],
            explanation_html=_p(d["explanation"]) if d.get("explanation") else None,
            **common,
        )
    if n.kind == "code":
        stem = _p(d["description"])
        if d.get("sampleInput", "").strip():
            stem += "<p><strong>Sample input</strong></p>" + _code(d["sampleInput"])
            stem += "<p><strong>Sample output</strong></p>" + _code(d["sampleOutput"])
        return QuestionCreate(
            question_type="coding", stem_html=stem, coding_problem_id=coding_problem_id, **common
        )
    if n.kind == "essay":
        key: dict[str, Any] = {}
        if d.get("referenceAnswer"):
            key["reference_answer_html"] = _p(d["referenceAnswer"])
            key["reference_answer_md"] = d["referenceAnswer"]
        if d.get("rubric"):
            key["rubric"] = d["rubric"]
        total = sum(Decimal(str(r["marks"])) for r in d.get("rubric") or [])
        return QuestionCreate(
            question_type="essay",
            stem_html=_p(d["question"]),
            answer_key=key or None,
            settings={"max_words": d["maxWords"]} if d.get("maxWords") else None,
            default_marks=total if 0 < total <= 100 else Decimal(1),
            **common,
        )
    if n.kind == "poll":
        return QuestionCreate(
            question_type="poll",
            stem_html=_p(d["question"]),
            options=[OptionIn(html=_p(o)) for o in d["options"]],
            settings={"allow_multiple": d["allowMultiple"]},
            **common,
        )
    if n.kind == "survey":
        return QuestionCreate(
            question_type="survey",
            stem_html=_p(d["question"]),
            options=[OptionIn(html=_p(x)) for x in d.get("labels") or []],
            settings={"scale": d["scale"]},
            **common,
        )
    return QuestionCreate(
        question_type="word_cloud",
        stem_html=_p(d["question"]),
        settings={"max_words": d["maxWords"]},
        **common,
    )


async def import_items(
    session: AsyncSession,
    principal: Principal,
    items: list[NormItem],
    *,
    bank: QuestionBank,
    primary_topic_id: uuid.UUID | None,
    source: str,
) -> list[uuid.UUID]:
    """Create one draft question per item in ``bank`` (caller holds the transaction: any error
    rolls back everything)."""
    ids: list[uuid.UUID] = []
    default_topic = primary_topic_id or bank.default_topic_id or await qbank.uncategorised_topic(session)
    fs = qbank._fs()
    built: list[Any] = []
    for n in items:
        problem_id = None
        if n.kind == "code":
            difficulty = DIFFICULTY.get(n.data.get("difficulty") or "medium", 3)
            problem_id = await _coding_problem(session, principal, n, bank.organization_id, difficulty)
        body = question_create(
            n,
            organization_id=bank.organization_id,
            primary_topic_id=default_topic,
            source=source,
            coding_problem_id=problem_id,
        )
        try:
            if fs:  # validate + build every item first, then write them together (all or nothing)
                await qbank._validate_topic(session, default_topic, "primary_topic_id")
                entry = await qbank.fs_build_question(session, principal, body, default_topic)
                built.append(entry)
                ids.append(entry[0].id)
                continue
            q, _qv = await qbank.create_question(session, principal, body)
        except ProblemError as e:
            errs = e.ext.get("errors") or [{"field": "item", "message": e.detail}]
            raise problems_error(
                n.kind, [Problem(n.index, str(x.get("field")), str(x.get("message"))) for x in errs], None
            ) from e
        session.add(
            QuestionBankItem(
                id=uuid7(),
                bank_id=bank.id,
                question_id=q.id,
                organization_id=bank.organization_id,
                added_by=principal.user_id,
            )
        )
        ids.append(q.id)
    from app.core.time import utcnow

    if fs:
        await (await qbank._repo(session)).create_questions_in_bank(built, bank, principal.user_id)
        bank.last_added_at = utcnow()
        return ids
    bank.last_added_at = utcnow()
    await session.flush()
    return ids


def from_ai_item(kind: str, item: Any) -> Any:
    """Map an ``ai.generate_questions`` draft to the import shape. Items already in the import
    shape pass through unchanged; the ai module's draft form (``stem_md``/``explanation_md``/
    ``options[].is_correct``/``test_cases``) is converted. ``tags`` > 8 are cut to 8."""
    if not isinstance(item, dict) or "stem_md" not in item:
        return item
    stem = str(item.get("stem_md") or "")
    tags = [t for t in item.get("tags") or [] if isinstance(t, str)][:8]
    out: dict[str, Any] = {"tags": tags}
    diff = item.get("difficulty")
    opts = [o for o in item.get("options") or [] if isinstance(o, dict)]
    expl = item.get("explanation_md")
    if kind == "mcq":
        out.update(
            question=stem,
            options=[{"text": str(o.get("text", "")), "correct": bool(o.get("is_correct"))} for o in opts],
            difficulty=diff,
        )
        if expl:
            out["explanation"] = expl
    elif kind == "code":
        out.update(
            description=stem,
            testCases=[
                {
                    "input": str(c.get("input", "")),
                    "expectedOutput": str(c.get("expected_output", "")),
                    "hidden": bool(c.get("hidden")),
                }
                for c in item.get("test_cases") or []
                if isinstance(c, dict)
            ],
            difficulty=diff,
        )
    elif kind == "essay":
        out.update(question=stem, difficulty=diff)
        if expl:
            out["referenceAnswer"] = expl
    elif kind == "poll":
        out.update(question=stem, options=[str(o.get("text", "")) for o in opts])
    elif kind == "survey":
        labels = [str(o.get("text", "")) for o in opts]
        if 3 <= len(labels) <= 7:
            out.update(question=stem, scale="likert", points=len(labels), labels=labels)
        else:
            out.update(question=stem, scale="open")
    else:
        out.update(question=stem)
    return {k: v for k, v in out.items() if v is not None}
