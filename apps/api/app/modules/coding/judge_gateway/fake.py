"""FakeJudgeAdapter — for local development and tests ONLY. It NEVER executes code.

Verdicts are driven by a marker in the submitted source, e.g. ``# FAKE_VERDICT: AC`` or
``// FAKE_VERDICT: AC,WA,TLE`` (comma list = per job in order; the last entry repeats).
Supported: ``AC`` (stdout = expected output), ``WA`` (wrong stdout), ``TLE``, ``MLE``,
``RE``, ``CE``, ``IE``. Without a marker every job is ``WA``.

Refused when ``APP_ENV`` is production: the factory raises and the startup gate fails
(``register_fake_adapter``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from app.modules.coding.judge_gateway.base import JudgeJob, JudgeRunResult, RunStatus

MARKER_RE = re.compile(r"FAKE_VERDICT:\s*([A-Z]{2,3}(?:\s*,\s*[A-Z]{2,3})*)")
_KNOWN = {"AC", "WA", "TLE", "MLE", "RE", "CE", "IE"}
_FAIL_STATUS: dict[str, RunStatus] = {"TLE": "TLE", "MLE": "MLE", "RE": "RE"}


def fake_verdicts(source: str) -> list[str]:
    m = MARKER_RE.search(source)
    if not m:
        return ["WA"]
    vs = [v.strip() for v in m.group(1).split(",")]
    return [v if v in _KNOWN else "IE" for v in vs]


class FakeJudgeAdapter:
    provider = "fake"
    is_fake = True

    def __init__(self) -> None:
        self._results: dict[str, JudgeRunResult] = {}
        self.submitted: list[JudgeJob] = []  # tests inspect what would be sent

    async def submit_batch(self, jobs: Sequence[JudgeJob]) -> list[str]:
        tokens: list[str] = []
        for idx, job in enumerate(jobs):
            self.submitted.append(job)
            verdicts = fake_verdicts(job.source_code)
            v = verdicts[idx] if idx < len(verdicts) else verdicts[-1]
            token = "fake-" + hashlib.sha256(f"{len(self.submitted)}:{job.ordinal}".encode()).hexdigest()[:16]
            self._results[token] = self._result(token, v, job)
            tokens.append(token)
        return tokens

    @staticmethod
    def _result(token: str, v: str, job: JudgeJob) -> JudgeRunResult:
        cpu_ms = int(job.limits.cpu_time_s * 1000)
        if v == "AC":
            out = job.expected_output if job.expected_output is not None else ""
            return JudgeRunResult(token, "ok", stdout=out, time_ms=7, memory_kb=3_200, exit_code=0)
        if v == "WA":
            return JudgeRunResult(
                token, "ok", stdout="fake-wrong-answer\n", time_ms=7, memory_kb=3_200, exit_code=0
            )
        if v == "CE":
            return JudgeRunResult(token, "CE", compile_output="fake: compilation error (simulated)\n")
        status: RunStatus = _FAIL_STATUS.get(v, "IE")
        mem = job.limits.memory_kb if v == "MLE" else 3_200
        return JudgeRunResult(
            token, status, time_ms=cpu_ms if v == "TLE" else 5, memory_kb=mem, exit_code=137
        )

    async def poll(self, tokens: Sequence[str]) -> list[JudgeRunResult]:
        return [self._results[t] for t in tokens]

    async def languages(self) -> list[dict[str, object]]:
        return [{"id": 0, "name": "fake (no execution)"}]
