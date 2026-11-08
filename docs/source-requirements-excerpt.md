# Source Requirements Excerpt (from product owner's master prompt, 2026-11-03)

Verbatim lists that downstream agents must cover exactly.

## Section H — Account security reports (admin)

- Top suspicious accounts.
- Multiple-account/device associations.
- Concurrent login events.
- Repeated IP/device associations.
- Blocked accounts.
- Pending unblock requests.
- Average review time.
- False-positive rate.
- Repeat incidents.
- Active-session counts.
- Daily/weekly/monthly learning activity.
- Device and login history.

All reports must be permission-controlled, auditable and exportable only by authorised users.

> Note (non-verbatim): Report ids H1–H12 follow the order of this list (brief v0.3 §7).

## Phase 8 — Account-sharing control test scenarios (minimum)

1. One student logs in on a laptop and continues using the same account on a phone.
2. One student has several browser tabs open on the same laptop.
3. Two students access the site from the same college Wi-Fi.
4. One student changes from Wi-Fi to mobile data.
5. One account is active concurrently from two unrelated devices.
6. Several different accounts repeatedly use the same browser/device.
7. One account is accessed from geographically inconsistent locations within an implausibly short time.
8. A legitimate student uses a VPN.
9. A suspicious account is automatically restricted by a configured high-confidence rule.
10. A student submits an unblock request with a legitimate explanation.
11. An administrator approves the request and revokes suspicious sessions.
12. An administrator rejects a request and provides a reason.
13. A blocked user tries to access private content through a direct API request.
14. The same payment webhook is delivered repeatedly.
15. An inactive tab remains open for several hours.
16. A browser crashes during a timed assessment.
17. A student opens multiple tabs and attempts to manipulate time tracking.
18. An administrator accesses another institution's records without permission.
19. A user attempts to change a session identifier or reuse a revoked session.
20. A student disputes a false-positive account-sharing decision.

For every test define: expected result; security rule being tested; event recorded; risk score or severity; user-facing response; admin notification, if applicable; whether automatic restriction is appropriate; recovery or appeal behaviour.

## Session/login fields required (Section A)

Student/user ID; session reference (safely stored); login time; last active; logout time; session duration; source IP; browser + version; OS + device category; privacy-conscious device/session identifier; approximate IP region (if justified); auth method + verification status; session status (active/expired/revoked/blocked); termination reason.

## Unblock request statuses (Section E)

Draft, Submitted, Under review, Additional information requested, Approved, Rejected, Closed.

## Phase 9 deliverables

research/reference-platform-analysis.md; docs/product-requirements.md; docs/feature-comparison.md; docs/system-architecture.md; docs/database-schema.md; docs/database-erd.md; docs/api-specification.md; docs/role-permission-matrix.md; docs/account-security-and-risk-engine.md; docs/account-unblock-workflow.md; docs/analytics-event-schema.md; docs/security-threat-model.md; docs/privacy-and-data-retention.md; docs/implementation-roadmap.md; docs/testing-and-acceptance-criteria.md; docs/deployment-and-operations.md; docs/architecture-decisions/; README.md; .env.example; automated test suites; database migrations; working application source; deployment configuration; seed scripts (clearly labelled dev/demo data only).

> Note (non-verbatim): Implementation stage order (12 stages) is defined in `docs/implementation-roadmap.md` §2 — 1 Discovery, 2 Product design, 3 Technical foundation, 4 Identity & permissions, 5 Core LMS, 6 Placement prep, 7 Account security & monitoring, 8 Commerce & college management, 9 Coding assessments, 10 Integration & hardening, 11 Pilot, 12 Production.
