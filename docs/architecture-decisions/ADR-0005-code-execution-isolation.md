# ADR-0005: Code execution isolation — judge-gateway, Judge0 Cloud (phase 1), self-hosted isolated judge (phase 2)

* **Status:** Accepted (Brief §1) — implementation **Planned**
* **Related:** `system-architecture.md §9`, `database-schema.md §10`

## Context

Coding practice and assessments execute untrusted code. Judge0 had CVSS 10.0 sandbox escapes in 2024 caused by privileged containers, `--share-net`, host symlink following and default credentials (research §8, Tanto Security [Verified]). Judge0 needs cgroup v1 while isolate's cgroup mode needs v2 (research §8 [Verified]). Hidden test cases are valuable IP and must never reach the browser (research §5 HackerRank [Verified]). Drive peaks may reach ~60k submissions/day (research §8 [Rec]).

## Decision

1. **Never run student code on application servers or in the app VPC.**
2. `coding.judge_gateway` (inside the monolith codebase) is the only component that talks to a judge. It runs only in the `worker-judge` ECS service, which alone holds judge credentials and `kms:Decrypt` on the hidden-test KMS key. Provider interface: `submit_batch`, `poll`, `languages`.
3. **Phase 1:** Judge0 Cloud (paid tier) via `Judge0CloudProvider`. Hidden test inputs are decrypted in worker memory and sent server-to-server only.
4. **Phase 2:** self-hosted hardened Judge0/isolate on dedicated EC2 VMs in a separate AWS account/VPC (`services/judge-runner`, `infra/terraform/envs/judge`): no internet egress, no route to RDS/Redis, ingress only via PrivateLink + mTLS; non-privileged, network-disabled sandboxes; no host mounts; patched images; per-run CPU, wall, memory, process and output limits. Later: gVisor/Firecracker microVMs.
5. Limits default to 2 s CPU (cap 5 s), wall 2×CPU+1 s (cap 10 s), 256 MB (cap 512 MB), 64 processes, 64 KiB output, no network.
6. Queues by priority (`judge_assessment` > `judge_submit` > `judge_run`), per-user rate limits, global token bucket sized to provider quota; runs shed first under load.
7. Hidden cases envelope-encrypted in S3; results for hidden cases expose verdict/time/memory only.

## Alternatives considered

| Option | Why not |
|---|---|
| Run Judge0 in ECS Fargate | Fargate cannot provide the cgroup/privilege configuration isolate needs without unsafe settings. |
| Self-host from day 1 | Ops + security hardening effort before product-market fit; Cloud costs €27–107/month (research §8 [Verified]). |
| Commercial assessment vendor (HackerRank/Mettl APIs) | Cost per candidate, loss of UX control, data residency questions. |
| AWS Lambda per submission | 15-min max fine, but language runtimes, cold starts and per-invocation limits make strict CPU/wall measurement unreliable. |

## Consequences

* (+) Compromise of a sandbox cannot reach student data or credentials.
* (+) Provider swap is a config change behind the gateway interface.
* (−) Phase 1 sends hidden tests to a third party — contractual control only; accelerate phase 2 before large paid drives.
* (−) Phase 2 adds a separate account to operate (patching, capacity planning).
* (−) Judge0 GPL-3.0 obligations if a modified judge is ever shipped on-prem to colleges — legal review (research §8 [Rec]).
