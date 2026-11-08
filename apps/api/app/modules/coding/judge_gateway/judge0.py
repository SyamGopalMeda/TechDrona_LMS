"""Judge0 adapter (phase 1: Judge0 Cloud; phase 2: self-hosted isolated Judge0).

HTTP to ``JUDGE0_BASE_URL`` (alias ``JUDGE0_URL``) with ``JUDGE0_API_KEY`` sent in the
``JUDGE0_AUTH_HEADER`` header (default ``X-Auth-Token``; RapidAPI uses ``X-RapidAPI-Key``).
Batch submissions, base64 everywhere, per-job CPU/wall/memory/process limits (hard caps
5 s / 10 s / 256 MB), ``enable_network: false``. ``expected_output`` is never sent:
checking is done in our worker. Only the ``worker-judge`` service constructs this adapter.

NOT verified against the real provider (no credentials in this environment).
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app.modules.coding.judge_gateway.base import (
    MAX_STDOUT_BYTES,
    JudgeJob,
    JudgeRunResult,
    JudgeUnavailable,
    RunStatus,
)

FIELDS = "token,status,stdout,compile_output,time,memory,exit_code"


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _unb64(s: str | None, limit: int = MAX_STDOUT_BYTES) -> str | None:
    if s is None:
        return None
    raw = base64.b64decode(s)[:limit]
    return raw.decode("utf-8", errors="replace")


def map_status(status_id: int, memory_kb: int | None = None, memory_limit_kb: int | None = None) -> RunStatus:
    """Judge0 status id → execution outcome (docs: /statuses)."""
    if status_id in (1, 2):
        return "pending"
    if status_id in (3, 4):  # without expected_output, 3 = ran cleanly; 4 never expected
        return "ok"
    if status_id == 5:
        return "TLE"
    if status_id == 6:
        return "CE"
    if 7 <= status_id <= 12 or status_id == 14:
        if memory_kb is not None and memory_limit_kb and memory_kb >= int(memory_limit_kb * 0.97):
            return "MLE"
        return "RE"
    return "IE"  # 13 Internal Error and anything unknown


class Judge0Adapter:
    is_fake = False

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        auth_header: str = "X-Auth-Token",
        provider: str = "judge0_cloud",
        extra_headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        if provider not in ("judge0_cloud", "judge0_selfhosted"):
            raise ValueError("provider must be judge0_cloud or judge0_selfhosted")
        if not base_url.startswith("https://") and provider == "judge0_cloud":
            raise ValueError("Judge0 Cloud must be reached over https")
        self.provider = provider
        self._base = base_url.rstrip("/")
        self._headers = {auth_header: api_key, "Content-Type": "application/json", **(extra_headers or {})}
        self._transport = transport
        self._timeout = timeout_s
        self._limits: dict[str, int] = {}  # token -> memory limit (MLE heuristic)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base, headers=self._headers, transport=self._transport, timeout=self._timeout
        )

    @staticmethod
    def payload(job: JudgeJob) -> dict[str, Any]:
        lim = job.limits
        return {
            "source_code": _b64(job.source_code),
            "language_id": job.provider_language_id,
            "stdin": _b64(job.stdin),
            "cpu_time_limit": lim.cpu_time_s,
            "cpu_extra_time": 0.5,
            "wall_time_limit": lim.wall_time_s,
            "memory_limit": lim.memory_kb,
            "stack_limit": min(64_000, lim.memory_kb),
            "max_processes_and_or_threads": lim.max_processes,
            "max_file_size": 1024,
            "enable_network": False,
            "redirect_stderr_to_stdout": False,
            "number_of_runs": 1,
        }

    async def submit_batch(self, jobs: Sequence[JudgeJob]) -> list[str]:
        body = {"submissions": [self.payload(j) for j in jobs]}
        try:
            async with self._client() as c:
                r = await c.post("/submissions/batch", params={"base64_encoded": "true"}, json=body)
        except httpx.HTTPError as e:
            raise JudgeUnavailable(f"judge0 unreachable: {type(e).__name__}") from e
        if r.status_code in (429,) or r.status_code >= 500:
            raise JudgeUnavailable(f"judge0 submit returned {r.status_code}")
        r.raise_for_status()
        items = r.json()
        tokens = []
        for item, job in zip(items, jobs, strict=True):
            if "token" not in item:
                raise JudgeUnavailable(f"judge0 rejected a job: {sorted(item)}")
            tokens.append(str(item["token"]))
            self._limits[str(item["token"])] = job.limits.memory_kb
        return tokens

    async def poll(self, tokens: Sequence[str]) -> list[JudgeRunResult]:
        params = {"tokens": ",".join(tokens), "base64_encoded": "true", "fields": FIELDS}
        try:
            async with self._client() as c:
                r = await c.get("/submissions/batch", params=params)
        except httpx.HTTPError as e:
            raise JudgeUnavailable(f"judge0 unreachable: {type(e).__name__}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise JudgeUnavailable(f"judge0 poll returned {r.status_code}")
        r.raise_for_status()
        out: list[JudgeRunResult] = []
        for tok, item in zip(tokens, r.json()["submissions"], strict=True):
            status_id = int((item.get("status") or {}).get("id", 13))
            mem = item.get("memory")
            t = item.get("time")
            out.append(
                JudgeRunResult(
                    token=tok,
                    status=map_status(status_id, mem, self._limits.get(tok)),
                    stdout=_unb64(item.get("stdout")),
                    compile_output=_unb64(item.get("compile_output"), 16 * 1024),
                    time_ms=round(float(t) * 1000) if t is not None else None,
                    memory_kb=int(mem) if mem is not None else None,
                    exit_code=item.get("exit_code"),
                )
            )
        return out

    async def languages(self) -> list[dict[str, object]]:
        try:
            async with self._client() as c:
                r = await c.get("/languages")
        except httpx.HTTPError as e:
            raise JudgeUnavailable(f"judge0 unreachable: {type(e).__name__}") from e
        r.raise_for_status()
        return list(r.json())
