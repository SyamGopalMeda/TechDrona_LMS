# Audit probes (removed)

The probe code that lived here (37 files: pytest probes from `apps/api/tests/_audit_scratch/`, moved
here by fix wave 3 on 2026-11-04, plus one Vitest BFF probe) was deleted on 2026-11-14 (cleanup D4,
`docs/cleanup/dead-code-plan.md` §3.2). It targeted the retired Postgres API and Next.js BFF.

The audit findings in `docs/audit/*.md` still cite the probe file names as evidence. To read a probe,
check out git commit `24134de` and look under `docs/audit/probes/api/`.
