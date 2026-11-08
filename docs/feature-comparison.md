# Tech Drona LMS: Feature Comparison (v0.1)

| Field | Value |
|---|---|
| Owner | Research & Product Analyst |
| Status | **Planned** (all Tech Drona columns describe planned scope; nothing is Implemented) |
| Source | `research/reference-platform-analysis.md` (RPA). Evidence labels kept from the research: **[Verified]** primary source; **[Reported]** secondary/claims/complaints; **[Rec]** recommendation. A cell with "?" means the research could not verify it, which is not the same as "absent". |
| Related | `docs/product-requirements.md` (FR IDs), `docs/role-permission-matrix.md` |

**Legend.** ● documented/present · ◐ partial or reported only · ○ absent or not found · ? not verifiable. **Stance:** Adopt (copy a proven pattern), Adapt (change it for our context), Build (no reference covers it credibly). **Priority:** P0 launch blocker, P1 v1 (≤ 6 months), P2 later. **TD v1 / later:** what ships in v1 (P0+P1) versus later phases.

Peers grouped with each reference, as in RPA §1: PrepInsta + IndiaBix, GfG, FACE Prep, Talent Battle, Testbook (Indian placement); Moodle + Canvas, Open edX (LMS); Coursera + Udemy, Unacademy, Physics Wallah, Scaler (credential/subscription edtech); HackerRank + HackerEarth, Mettl, LeetCode, Codeforces, Judge0 (coding/assessment).

---

## 1. Content and placement preparation

| Feature | PrepInsta & Indian peers | Moodle & LMS peers | Coursera & edtech peers | HackerRank & judges | TD v1 | TD later | Stance | Pri | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Aptitude (Quant/Logical/Verbal) → programming → DSA → CS core → company → interview taxonomy | ● | ○ | ○ | ○ | Full taxonomy as `topics` tree (FR-PLC-001) | Regional-language content | Adopt | P0 | RPA §1, §2 [Verified] IndiaBix, GfG |
| Company-specific paths/hubs (pattern, syllabus, mocks, experiences) | ● (PrepInsta "150+ company micro-courses" at launch) | ○ | ○ | ◐ (company tests for employers) | Company paths + free public hubs (FR-PLC-007) | Drive-linked readiness, eligibility (FR-ORG-019) | Adopt + Build depth | P0 | RPA §1 [Verified] CXOToday; §4 Discovery |
| Question bank with explanations | ◐ (banks exist; explanation depth not verified) | ● (shared banks since 5.0, random draws) | ◐ | ● | Mandatory explanation per question, versioned (FR-PLC-002..004) | Video explanations at scale | Adopt Moodle model + Build explanation rule | P0 | RPA §2 [Verified] Moodle docs |
| "Pattern-aligned practice" labelling (no "actual questions" claims) | ○ (complaint about ₹99–199 "likely questions" bank) | n/a | n/a | n/a | Labelling rule (FR-PLC-003) | — | Build | P0 | RPA §6 [Reported] ConsumerComplaints |
| Untimed practice with instant feedback | ● | ◐ (quiz feedback modes) | ◐ | ● | Practice sessions (FR-PLC-005) | Adaptive sets | Adopt | P0 | RPA §1 |
| Technical & HR interview prep content | ● | ○ | ◐ | ○ | Curated sets (FR-PLC-008/009) | Recorded-answer feedback | Adopt | P1 | RPA §1 [Verified] GfG TCS course |
| Mock interviews with mentors | ◐ (Talent Battle sells 1:1; PrepInsta call reportedly missed) | ○ | ◐ (cohort programmes) | ○ | Slots, rubric feedback, no-show auto-credit (FR-PLC-010) | Integrated video | Adapt (add SLA) | P1 | RPA §4 Mentoring [Reported] |
| Resume / career prep | ◐ | ○ | ◐ | ○ | Builder + mentor review (FR-PLC-015) | ATS scoring, job board | Adapt | P1 | RPA §4 (career tracks) [Rec] |
| Content-completeness indicator / public roadmap | ○ ("under construction" complaints) | ○ | ○ | ○ | Per-course completeness (FR-CAT-003) | — | Build (D6) | P0 | RPA §4 Learning, §7.6 [Reported] |
| Personalised recommendations (weak-area next practice) | ◐ (not verifiable) | ○ | ◐ | ◐ | Rule-based "next best practice" with "why" (FR-PLC-011) | ML recommendations (adults) | Build (D1) | P1 | RPA §2 row "Topic-level analytics" |
| Skill analytics, topic mastery, percentiles | ◐ (not verifiable) | ◐ (click logs) | ◐ | ◐ | Mastery, percentile, company readiness (FR-PLC-006/012) | Drive-level predictive readiness | Build (D1) | P1 | RPA §2, §7.1 [Rec] |
| Free diagnostic as conversion hook | ◐ | ○ | ◐ (trials) | ◐ | 30-min diagnostic (FR-PLC-013) | — | Adopt | P0 | RPA §4 Discovery [Rec] |

## 2. LMS core (courses, batches, institutions)

| Feature | PrepInsta & peers | Moodle & LMS peers | Coursera & edtech peers | HackerRank & judges | TD v1 | TD later | Stance | Pri | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Course → module → lesson structure, polymorphic activities | ◐ | ● (category → course → section → activity) | ● | ○ | `courses`/`course_versions`/`course_modules`/`lessons` (FR-CAT-001) | SCORM import | Adopt Moodle shape | P0 | RPA §1, §6 [Verified] |
| Course versioning (immutable published versions) | ? | ◐ | ? | ○ | Draft/published versions (FR-CAT-002) | — | Build | P1 | [Rec] |
| DRM video + dynamic watermark | ? (buffering complaints) | ○ (plugins) | ◐ | ○ | VdoCipher DRM + user watermark (FR-MED-001) | Android FLAG_SECURE | Adopt | P0 | RPA §3 watermark row [Reported, vendor] |
| Assignments with rubric grading | ○ | ● | ● (peer review) | ○ | Rubrics, late policy (FR-LRN-004/005) | Peer review | Adopt | P1 | RPA §1 |
| Cohorts / batches / seat pools | ◐ (college-wide Prime) | ● (cohort sync, groups) | ● (seat licences; Coursera Campus up to 20,000) | ◐ | Org → batch, contract seat pool, reassignment rules (FR-ORG, BR-ENT-15..18) | White-label domains | Adapt | P0 | RPA §1, §2 [Verified] edX Business, Coursera flyer |
| Bulk roster import + invites | ◐ | ● (CSV upload, cohort sync [Reported]) | ● (license assignment) | ◐ | CSV/XLSX with preview + idempotent commit (FR-ORG-010/011) | SIS/LMS sync | Adopt | P0 | RPA §5 [Reported] Cohort sync |
| TPO / coordinator console (readiness, shortlists, exports) | ○ (no public dashboard docs) | ◐ (generic reports) | ◐ (consumption metrics, daily refresh) | ◐ (employer reports) | Coordinator dashboard, shortlists (COL-001, FR-ORG-015/016) | Drive management | Build (D2) | P0 | RPA §1 Dashboards row, §7.2 |
| Context-scoped roles | ○ | ● (Allow/Prevent/Prohibit, contexts) | ◐ | ◐ | Allow-only grants at platform/org/batch/course (role-permission-matrix) | — | Adapt (simplify) | P0 | RPA §5 [Verified] role.php |
| Verifiable certificates | ? | ◐ (plugin customcert) | ● (share link, identity statement; activation reportedly 24–48 h) | ○ | Instant `/verify/{id}`, LinkedIn add (FR-LRN-006/008) | Open Badges | Adopt + improve | P1 | RPA §2, §4 Certificates |
| LTI 1.3 / xAPI / Caliper interoperability | ○ | ● (`mod_lti`, `enrol_lti`) | ◐ | ◐ | xAPI-shaped internal events (FR-ANL-001) | LTI tool/platform, LRS export | Adapt later | P2 | RPA §2 [Verified] Open edX ADR, Canvas Caliper |
| Discussion forums | ◐ | ● | ● | ◐ (LeetCode discuss) | — | After Intermediary Rules review | Defer | P2 | RPA §8 Q7 |

## 3. Assessments and coding

| Feature | PrepInsta & peers | Moodle & LMS peers | Coursera & edtech peers | HackerRank & judges | TD v1 | TD later | Stance | Pri | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Sectional timers / company-pattern mocks | ● (Prime Mock) | ○ (no core sectional timer) | ○ | ◐ | Sections with own timers, draw rules (FR-ASM-001) | — | Build | P0 | RPA §2 [Verified] Prime Mock, quiz settings |
| Server-authoritative timer | ? | ● | ? | ◐ (Xobin, Bubble document server timers) | `started_at`/`deadline_at`, server auto-submit (FR-ASM-004) | — | Adopt | P0 | RPA §2, §6 |
| Autosave + resume | ? | ● (60 s autosave) | ? | ◐ | 5–10 s debounce + IndexedDB mirror (FR-ASM-005/006) | — | Adopt + improve | P0 | RPA §6 [Verified] Moodle settings; [Reported] resume bug elsewhere |
| Review-visibility matrix (4 phases) | ? | ● | ◐ | ◐ | Adopted (FR-ASM-008) | — | Adopt | P0 | RPA §5 [Verified] quiz.php |
| Per-user / per-group overrides (extra time) | ? | ● | ? | ? | Overrides with reason + audit (FR-ASM-007) | Accommodation profiles auto-applied (FR-ASM-013, P1) | Adopt | P0 | RPA §5 [Verified] |
| Immutable attempt steps / regrade | ? | ● | ? | ◐ | Append-only responses, regrade (FR-ASM-011) | — | Adopt | P0 | RPA §2 conclusion [Rec] |
| Settings lock once attempts start | ? | ◐ | ? | ● (Proctor Mode locks) | Lock (FR-ASM-010) | — | Adopt | P0 | RPA §5 [Verified] HackerRank |
| Integrity signals as advisory with human review | ○ | ◐ (subnet, popup, SEB) | ◐ (honor code) | ● (MOSS + ML, 85% stated precision; session replay) | Event log + "review recommended", provisional leaderboard (FR-ASM-010/015) | Keystroke replay (adults) | Adapt (D5) | P0 | RPA §5 [Verified] HackerRank KB, [Reported] Codeforces |
| Webcam / screenshot proctoring | ○ | ◐ (plugins) | ◐ | ● (webcam every 5 s, screenshots 15 s) | — (excluded) | Phase 3 with consent + retention | Defer | P2 | RPA §1 [Verified] Proctor Mode; §7.5 bias evidence |
| Coding questions with hidden tests | ◐ (GfG 75+ problems in TCS course) | ○ (needs CodeRunner) | ○ | ● | Run on samples / Submit on hidden, weighted cases (FR-COD-004) | — | Build UX, buy engine | P0 | RPA §2 [Verified/Reported] HackerRank KB |
| Multi-language judge | ◐ | ○ | ○ | ● | C, C++, Java, Python (+JS, Go in P1) via Judge0 Cloud | Self-hosted hardened judge (Phase 2) | Buy then build | P0 | Brief §1; RPA §4 Coding, §8 judge security [Verified] Tanto |
| Code similarity check | ○ | ○ | ○ | ● (MOSS, ML) | Cohort similarity after close (FR-COD-008) | Cross-cohort | Adapt | P1 | RPA §6 Integrity basics |
| Leaderboards | ◐ | ○ | ○ | ● | Provisional, anonymised by default (FR-ASM-015) | — | Adapt | P1 | RPA §5 [Reported] Codeforces rollback |
| Published penalty ladder with appeal | ○ | ○ | ○ | ◐ (LeetCode ladder, no appeal) | Appeal included (FR-SEC-004) | — | Adapt | P0 | RPA §5 [Verified] LeetCode |

## 4. Commerce and access

| Feature | PrepInsta & peers | Moodle & LMS peers | Coursera & edtech peers | HackerRank & judges | TD v1 | TD later | Stance | Pri | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Free resources and free courses | ● (SEO content) | ● (guest access) | ● (audit) | ● | Free resources/courses (FR-COM-001, BR-ENT-20) | — | Adopt | P0 | RPA §1 Purpose |
| Individual course purchase | ● | ◐ (`enrol_fee`) | ● | n/a | One-time purchase with validity (FR-COM-001) | — | Adopt | P0 | RPA §2 [Verified] enrol plugins |
| Subscriptions (all-access) | ● (Prime 6–48 months) | ○ | ● (Coursera Plus ₹2,099/mo, ₹13,999/yr) | n/a | Monthly/annual, UPI AutoPay, ≤ ₹15,000 per debit (FR-COM-005) | Buddy seats | Adapt | P0 | RPA §1 [Verified] Coursera Plus; [Reported] Prime pricing |
| Premium placement packages | ◐ (Prime Mock, crash courses) | ○ | ◐ (cohort tracks, e.g. Scaler) | n/a | Package with mentor quota (FR-COM-001) | — | Adapt | P1 | RPA §1, §8 cost table |
| College-sponsored seats / institution contracts | ● (college-wide Prime; FACE Prep 2,000+ colleges claimed) | ● (cohort sync) | ● (Campus, Udemy Business per user/year) | ● (per-seat B2B) | Contracts, seat pool, reassignment allowance, grace (FR-COM-010, BR-ENT-15..19) | PO workflows, auto-invoicing | Adapt | P0 | RPA §1 [Verified] edX Business, Udemy Business; [Reported] FACE Prep |
| Coupons | ● ("80% off" on anchor) | ○ | ● | n/a | Coupons with caps, dual approval for deep discounts (FR-COM-007) | — | Adapt (no fake anchors) | P0 | RPA §1 [Reported] purchase page |
| Real list prices, no inflated anchors | ○ (₹21,999–33,999 anchors) | n/a | ◐ | n/a | Rule FR-COM-002 | — | Build (D3) | P0 | RPA §4, §7.3; CCPA guidance [Reported] |
| Refund rule incl. discounted purchases, same text everywhere | ○ (no refund on discounted purchases) | n/a | ○ (Coursera Terms vs marketing contradiction) | n/a | 7 days, < 20% consumed, no certificate (FR-COM-008; OPD-01) | — | Build (D3) | P0 | RPA §4 [Verified] PrepInsta & Coursera Terms |
| One-click cancel + pre-renewal reminder | ○ (Unacademy auto-renew, "no refund") | n/a | ◐ | n/a | FR-COM-005 | — | Build (D3) | P0 | RPA §4 [Verified] Unacademy Terms; dark-pattern rules 1 Jan 2027 [Reported] |
| GST invoices, B2B GSTIN | ◐ | ○ | ◐ | ◐ | FR-COM-009 | — | Build | P0 | RPA §4 Payment [Rec]; RPA §8 Q8 |
| Central entitlement system (one access check for all sources) | ? | ◐ (several enrolment methods per course) | ? | n/a | `entitlements` with precedence/grace/revocation rules (§4.12 PRD) | — | Adapt Moodle multi-enrolment idea | P0 | RPA §1 [Verified] enrol plugins |

## 5. Account security and trust

| Feature | PrepInsta & peers | Moodle & LMS peers | Coursera & edtech peers | HackerRank & judges | TD v1 | TD later | Stance | Pri | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Published device / session limits | ○ (Terms ban sharing; no numbers) | ◐ (`limitconcurrentlogins`, opt-in, kills oldest, breaks SSO) | ○ (Coursera ToS: one account, no numeric limit) | ◐ (assessment-only proctoring) | 3 devices, 2 sessions, 1 stream, 2 replacements/30 d, 1 session per attempt (FR-SES-004..011) | Buddy seat | Build (D4) | P0 | RPA §1, §3 [Verified] PrepInsta/Coursera Terms, Moodle auth.php |
| Concurrent stream cap at token issuance | ◐ (PW app: new login logs out old [Reported]) | ○ | ◐ (Unacademy 2 web sessions, old report [Reported]) | n/a | Enforced at VdoCipher token (FR-SES-007) | — | Adapt | P0 | RPA §3 |
| Devices & sessions page (self-service) | ○ | ○ | ○ | ○ | STU-022 (ASVS 7.5.2) | — | Build (D4) | P0 | RPA §6 [Verified] ASVS V7 |
| New-device OTP step-up | ◐ (phone OTP login) | ◐ (MFA factors) | ○ | ○ | FR-SES-003 | — | Adopt (Disney+ pattern) | P0 | RPA §3 [Reported] OTTVerse |
| Explainable restrictions + appeal | ○ (permanent suspension threat) | ○ | ○ | ◐ (reviewers use replay) | Reasons, levels, appeal SLA (FR-SEC-003/004) | — | Build (D4) | P0 | RPA §3, §5 |
| Behavioural sharing detection | ? (Device ID collected, enforcement undocumented) | ○ | ? | ◐ (LeetCode multi-account bans) | Rule-based overlap scoring for adults (FR-SEC-001) | ML; fingerprinting if evasion data justifies | Build (rule-based) | P1 | RPA §3 [Verified] PrepInsta privacy policy; Cloudflare CGNAT data |
| MFA (passkey/TOTP) | ? | ● (tool_mfa since 4.3) | ? | ? | Mandatory for staff, optional students (FR-IDN-006) | — | Adopt | P0 | RPA §1 [Verified] Moodle source |
| Password policy (NIST 800-63B-4) and Argon2id | ? | ◐ (8 chars + classes; lockout off by default) | ? | ? | 15/8 chars, blocklist, Argon2id (FR-IDN-004) | — | Adopt standards | P0 | RPA §8 baseline [Verified] |
| Minor-aware monitoring | ○ (18+ Terms, inconsistent) | ○ | ○ | ○ | No behavioural scoring for minors (BR-MIN-01) | — | Build | P0 | RPA §8 [Verified] DPDP s.9(3) |
| Privacy request workflow + retention registry | ○ | ● (`tool_dataprivacy`) | ? | ○ | Export/deletion (FR-PRV-002) | Automated retention registry | Adopt Moodle pattern | P0/P1 | RPA §2 [Verified] Moodle classes |
| Append-only audit log of privileged actions | ? | ◐ (logs) | ? | ? | Hash-chained `audit_log` (FR-ADM-001) | — | Build | P0 | RPA §5 [Verified] OWASP Logging CS, DPDP Rule 6 |

## 6. Analytics and support

| Feature | PrepInsta & peers | Moodle & LMS peers | Coursera & edtech peers | HackerRank & judges | TD v1 | TD later | Stance | Pri | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Time-on-task with disclosed method | ○ | ◐ (click logs) | ◐ (Canvas "Total Activity" grows on idle tabs [Reported]) | ○ | Visible-tab heartbeats (FR-ANL-002) | — | Build | P0 | RPA §4 Analytics [Verified] Kovanović et al. |
| Student progress dashboard | ◐ | ● | ● | ◐ | STU-001 | — | Adopt | P0 | RPA §1 |
| Admin metrics freshness | ? | ◐ (live logs) | ● (daily refresh) | ◐ | ≤ 15 min dashboards, daily snapshots for B2B (FR-ANL-004) | Near-real-time OLAP | Adapt | P0 | RPA §1 [Verified] Mass.gov guide |
| Support SLAs visible to users | ○ (unresponsive-support complaints) | n/a | ◐ | ◐ | SLA by priority, grievance timers (FR-SUP-003) | — | Build (D6) | P0 | RPA §4 [Reported] ConsumerComplaints |
| Verified placement-outcome claims | ○ (self-reported "7.4 LPA") | n/a | ◐ | n/a | — (OPD-13) | Cohort stats with sample size | Build later | P2 | RPA §7.6 [Verified, company claim] CXOToday |

---

## 7. Priority summary

| Priority | Count of rows | Themes |
|---|---|---|
| P0 (incl. 1 row P0/P1) | 48 | Taxonomy, company paths, question bank, timed/sectional engine with autosave and server timer, coding Run/Submit, DRM video, batches and seat pools, TPO console v1, honest commerce, entitlement system, published device/session policy, explainable restrictions, minor safeguards, audit, time-on-task |
| P1 | 12 | Readiness/mastery analytics, recommendations, mentor interviews, resume prep, interview content, assignments with rubrics, certificates, similarity checks, leaderboards, behavioural sharing detection (adults), placement packages |
| P2 | 4 | LTI/xAPI export, forums, webcam proctoring, verified outcomes, drive management |

## 8. Key takeaways

1. **Adopt** the market taxonomy and Moodle's attempt engine, review matrix, overrides and privacy-provider pattern: these are proven and documented (RPA §2 conclusion [Rec]).
2. **Buy** execution (Judge0 Cloud, VdoCipher, Razorpay) and **build** the UX and rules around them (brief §1).
3. **Build** the six gaps no reference fills credibly: readiness engine, TPO console, honest commerce, transparent account-integrity centre, dispute-ready integrity, verified credentials/outcomes (RPA §7). These are the P0/P1 differentiators.
4. **Defer** webcam AI, fingerprinting and forums until legal and evidence thresholds are met (RPA §8 Phase 3).
