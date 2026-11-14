# Archive

Material that is no longer current but is kept as a record. Nothing here is built, deployed or run by CI.
Archived on 2026-11-14 by cleanup batch D4 (`docs/cleanup/dead-code-plan.md` §3).

| Folder | What it is | Why it is here |
|---|---|---|
| `aws-terraform/terraform/` | AWS ECS/ECR/RDS/ElastiCache Terraform skeleton (was `infra/terraform/`) | Never applied; the LMS runs on Firebase. **Owner decision pending:** delete it if AWS is abandoned. `make tf-fmt` / `make lint-infra` now point here; the CI IaC job skips because `infra/terraform/` no longer exists. |
| `aws-terraform/deploy.yml` | Disabled AWS deploy workflow (was `.github/workflows/deploy.yml`) | Never enabled. Same owner decision as above. |
| `redesign-next-app/perf/` | Performance measurement scripts for the retired Next.js app | Findings are in `docs/redesign/perf-baseline.md`. The raw JSON outputs were deleted (recover from git commit `24134de`). |
| `redesign-next-app/a11y/` | Accessibility audit scripts for the retired Next.js app | Findings are in `docs/redesign/a11y-responsive.md`. The raw results and screenshots were deleted (recover from git commit `24134de`). |

The scripts reference the retired localhost Next.js/BFF stack and are not expected to run as-is.

Deleted outright in the same batch (recoverable from `24134de`): `docs/redesign/shots/` (436 PNGs),
`docs/redesign/security/` (local BFF probe scripts and outputs), `docs/redesign/audit-scripts/`,
the probe code under `docs/audit/probes/` (a README pointer remains), and the duplicate
`reports/Tech Drona LMS reference platforms.md` (canonical copy: `research/reference-platform-analysis.md`).
