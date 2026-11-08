"""Judge provider interface (ADR-0005 §2): ``submit_batch`` / ``poll`` / ``languages``.

Only the ``worker-judge`` service calls an adapter. The API process never talks to a judge
and never executes student code.

``JudgeJob.expected_output`` is given to adapters ONLY so the clearly-named
``FakeJudgeAdapter`` can simulate AC/WA. Real adapters must not send it to the provider:
output checking happens in our worker (``checker.py``), so hidden expected outputs never
leave our infrastructure.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# Execution outcome as reported by the sandbox (before output checking).
RunStatus = Literal["ok", "CE", "TLE", "MLE", "RE", "IE", "pending"]

# Hard caps (task brief / ADR-0005 §5): never exceeded whatever the problem says.
HARD_CPU_S = 5.0
HARD_WALL_S = 10.0
HARD_MEMORY_KB = 262_144
MAX_STDOUT_BYTES = 64 * 1024


class JudgeUnavailable(RuntimeError):
    """Provider unreachable / 5xx / quota: the submission stays queued (judge_degraded)."""


class JudgeTimeout(RuntimeError):
    """Polling budget exhausted (``judge_timeout``; one automatic retry)."""


@dataclass(frozen=True, slots=True)
class JudgeLimits:
    cpu_time_s: float
    wall_time_s: float
    memory_kb: int
    max_processes: int

    @classmethod
    def for_problem(
        cls,
        *,
        time_limit_ms: int,
        wall_limit_ms: int,
        memory_limit_kb: int,
        time_multiplier: float,
        memory_extra_kb: int,
        max_processes: int,
    ) -> JudgeLimits:
        cpu = min(time_limit_ms * time_multiplier / 1000.0, HARD_CPU_S)
        wall = min(max(wall_limit_ms / 1000.0, 2 * cpu + 1.0), HARD_WALL_S)
        mem = min(memory_limit_kb + memory_extra_kb, HARD_MEMORY_KB)
        return cls(round(cpu, 3), round(wall, 3), int(mem), max(1, min(max_processes, 128)))


@dataclass(frozen=True, slots=True)
class JudgeJob:
    ordinal: int
    source_code: str
    language_key: str
    provider_language_id: int
    stdin: str
    limits: JudgeLimits
    expected_output: str | None = None  # fake adapter only; never sent to a provider


@dataclass(frozen=True, slots=True)
class JudgeRunResult:
    token: str
    status: RunStatus
    stdout: str | None = None
    compile_output: str | None = None
    time_ms: int | None = None
    memory_kb: int | None = None
    exit_code: int | None = None


@runtime_checkable
class JudgeAdapter(Protocol):
    #: value stored in ``code_submissions.judge_provider``
    provider: str
    is_fake: bool

    async def submit_batch(self, jobs: Sequence[JudgeJob]) -> list[str]:
        """Submit jobs; return provider tokens in job order."""
        ...

    async def poll(self, tokens: Sequence[str]) -> list[JudgeRunResult]:
        """Current state of each token (``status='pending'`` while queued/running)."""
        ...

    async def languages(self) -> list[dict[str, object]]: ...


async def run_jobs(
    adapter: JudgeAdapter,
    jobs: Sequence[JudgeJob],
    *,
    budget_s: float = 30.0,
    first_delay_s: float = 0.5,
    max_delay_s: float = 4.0,
) -> list[JudgeRunResult]:
    """Submit a batch and poll with exponential backoff until done or the budget is spent."""
    if not jobs:
        return []
    tokens = await adapter.submit_batch(jobs)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    delay = first_delay_s
    while True:
        results = await adapter.poll(tokens)
        if all(r.status != "pending" for r in results):
            return results
        if loop.time() + delay > deadline:
            raise JudgeTimeout(f"judge did not finish {len(tokens)} jobs within {budget_s}s")
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay_s)
