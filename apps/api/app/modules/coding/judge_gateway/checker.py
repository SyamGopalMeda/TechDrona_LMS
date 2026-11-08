"""Output checking and verdict/score aggregation (pure functions, unit-tested)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.modules.coding.judge_gateway.base import JudgeRunResult

CASE_VERDICTS = ("AC", "WA", "TLE", "MLE", "RE", "CE", "IE", "SKIPPED")
# Order used to pick the overall verdict when nothing passed.
_FAIL_PRIORITY = ("CE", "IE", "RE", "MLE", "TLE", "WA")


def _lines(s: str) -> list[str]:
    out = [ln.rstrip() for ln in s.replace("\r\n", "\n").split("\n")]
    while out and out[-1] == "":
        out.pop()
    return out


def outputs_match(
    actual: str, expected: str, checker_type: str, config: dict[str, Any] | None
) -> bool | None:
    """``True``/``False``; ``None`` when the checker is not supported (custom → IE)."""
    if checker_type == "exact":
        return _lines(actual) == _lines(expected)
    if checker_type == "token":
        return actual.split() == expected.split()
    if checker_type == "float_tolerance":
        cfg = config or {}
        abs_eps = float(cfg.get("abs", 1e-6))
        rel_eps = float(cfg.get("rel", 1e-6))
        a, e = actual.split(), expected.split()
        if len(a) != len(e):
            return False
        for x, y in zip(a, e, strict=True):
            try:
                fx, fy = float(x), float(y)
            except ValueError:
                if x != y:
                    return False
                continue
            if not (math.isfinite(fx) and math.isfinite(fy)):
                if x != y:
                    return False
                continue
            if abs(fx - fy) > max(abs_eps, rel_eps * abs(fy)):
                return False
        return True
    return None


def case_verdict(
    result: JudgeRunResult,
    expected: str | None,
    checker_type: str,
    config: dict[str, Any] | None,
) -> str:
    """Map an execution result (+ expected output) to a case verdict.

    ``expected=None`` is a custom-input run: a clean run is reported as ``AC`` (no checker).
    """
    if result.status in ("CE", "TLE", "MLE", "RE", "IE"):
        return result.status
    if result.status != "ok":
        return "IE"
    if expected is None:
        return "AC"
    ok = outputs_match(result.stdout or "", expected, checker_type, config)
    if ok is None:
        return "IE"
    return "AC" if ok else "WA"


@dataclass(frozen=True, slots=True)
class ScoredCase:
    ordinal: int
    weight: Decimal
    verdict: str


@dataclass(frozen=True, slots=True)
class Aggregate:
    verdict: str
    score: Decimal
    max_score: Decimal
    passed: int
    total: int
    awarded: dict[int, Decimal]


def aggregate(cases: Sequence[ScoredCase], scoring_mode: str) -> Aggregate:
    """Overall verdict + score. ``weighted_cases``: score = Σ weights of passed cases
    (partial credit, verdict ``PARTIAL`` when some but not all pass). ``all_or_nothing``:
    full weight only if every case passes, else 0 and the first failing verdict."""
    total = len(cases)
    max_score = sum((c.weight for c in cases), Decimal(0))
    passed_cases = [c for c in cases if c.verdict == "AC"]
    passed = len(passed_cases)
    awarded = {c.ordinal: (c.weight if c.verdict == "AC" else Decimal(0)) for c in cases}
    if total == 0:
        return Aggregate("IE", Decimal(0), Decimal(0), 0, 0, {})
    if passed == total:
        return Aggregate("AC", max_score, max_score, passed, total, awarded)
    failing = {c.verdict for c in cases if c.verdict != "AC"}
    first_fail = next((v for v in _FAIL_PRIORITY if v in failing), "WA")
    if "CE" in failing:
        zero = {c.ordinal: Decimal(0) for c in cases}
        return Aggregate("CE", Decimal(0), max_score, 0, total, zero)
    if scoring_mode == "all_or_nothing":
        zero = {c.ordinal: Decimal(0) for c in cases}
        return Aggregate(first_fail, Decimal(0), max_score, passed, total, zero)
    score = sum(awarded.values(), Decimal(0))
    verdict = "PARTIAL" if passed > 0 else first_fail
    return Aggregate(verdict, score, max_score, passed, total, awarded)
