"""Coding module (api-specification §16, database-schema §10, ADR-0005).

Layout:

* ``router.py``   — COD endpoints (student + studio). Never executes code, never decrypts.
* ``service.py``  — authoring, submission intake, rate limits, ``judge_for_attempt`` (the
  interface for the assessments module), plagiarism hash.
* ``worker.py``   — judge worker (``python -m app.modules.coding.worker``): claims queued
  submissions, decrypts hidden cases, calls the judge adapter, checks output, scores.
* ``judge_gateway/`` — adapter interface, ``Judge0Adapter``, ``FakeJudgeAdapter``.
* ``crypto.py``   — AES-256-GCM envelope encryption of hidden cases (``TD_K_TESTCASE_KEY_V{n}``).

Production safety: the FakeJudgeAdapter check is registered with the startup gate here
(``create_app`` imports every module's models; the worker imports this package before it
serves). The factory additionally refuses to build the fake adapter in production, and the
test-case keyring refuses a missing/non-hex key in production (``crypto.get_testcase_keyring``).
"""

from __future__ import annotations

from app.core.startup_checks import register_fake_adapter

register_fake_adapter(
    "coding judge (FakeJudgeAdapter, JUDGE_PROVIDER=fake)", lambda s: s.JUDGE_PROVIDER.lower() == "fake"
)
