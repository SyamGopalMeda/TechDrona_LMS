# Tech Drona LMS: Analytics Event Schema and Time-on-Task Measurement Model

> **Single-company note (2026-11-06).** Tech Drona now runs as a single company ([ADR-0015](architecture-decisions/ADR-0015-single-company.md)); the college/B2B features described in this document (college portal and coordinators, institution contracts and seats, invitations and roster import, per-organization settings, trusted networks and lab devices, the "For colleges" page) are removed. Roles are Admin (`super_admin`), Trainer, Evaluator, Content manager and Student; finance, support, security and mentor duties belong to Admin. Batches are Tech Drona cohorts managed by Admin at `/admin/batches`; businesses use the corporate enquiry form at `/enquiries`. Org/college dimensions collapse to the company org; college dashboards and org reports are removed; batch reports stay. Where this document conflicts, ADR-0015 and [`single-company/REMOVAL-PLAN.md`](single-company/REMOVAL-PLAN.md) §8 win.

| | |
|---|---|
| Owner | Analytics Engineer |
| Status | **Planned** (blueprint stage, nothing is built yet) |
| Contract base | `docs/blueprint-brief.md` v0.4 (Shared Contracts; originally written against v0.1) |
| Revision | v0.5 (2026-11-03, Stage 10): server event `assessment.attempt_scored` added to §2.4; domain event name fixed as `attempt.scored` (not `attempt.graded`). v0.4 (2026-11-03): Integration Lead applied CPR-ANL-01..03 and IPR-AN-01/02 (`contract-reconciliation.md` §9): `touch_engaged` after credited batches; IN-01/IN-02 are not sharing-score inputs; §5.2 is the single source of ingest limits; `analytics.event.ingest` retired (ownership); synthetic accounts excluded from aggregates, k-counts and the security feed |
| Research base | `research/reference-platform-analysis.md`; `research_notes/Tech Drona LMS reference platforms/moodle_lms_architecture.md` §9 |
| Measurement model version | `tm-1.0` (stored on every derived row; see §3.12) |

Evidence tags follow the research convention. **[Verified]** means read in a primary source. **[Reported]** means a secondary or community source. **[Rec]** is our recommendation. Every item in this document is **Planned** unless marked otherwise.

---

## 0. Why this design: the research constraints

1. **Every LMS "time spent" figure is an estimate.** LMS logs record discrete actions, so time-on-task has to be estimated. Kovanović et al. (LAK 2015; J. Learning Analytics 2015) showed that the choice of estimation strategy significantly changed learning-analytics models of performance, and that the method is rarely reported [Verified, abstract level; we did not read the full text] ([Monash](https://research.monash.edu/en/publications/penetrating-the-black-box-of-time-on-task-estimation/)). Our response is to **version and publish the estimation method** (`tm-1.0`), **keep raw signals** long enough to recompute it, and **never present an estimate as a fact**.
2. **Canvas's "Total Activity" keeps growing while a tab sits idle.** It reportedly includes gaps of under 10 minutes between activities, and video watched without page requests is not captured [Reported, community/institutional sources; no official algorithm found] ([Canvas Community](https://community.canvaslms.com/t5/Admin-Group/What-does-Total-Activity-mean/m-p/71879)). Our response is that **only visible tabs with recent input, or a playing video, earn active credit**, measured by client heartbeats rather than click gaps (moodle notes §9, Inferences).
3. **Open edX uses xAPI as its default analytics standard, and Canvas emits Caliper 1.1** [Verified] ([Aspects ADR 0002](https://docs.openedx.org/projects/openedx-aspects/en/latest/technical_documentation/decisions/0002_xapi.html); [Instructure Caliper](https://developerdocs.instructure.com/services/canvas/data-services/live-events/event-format/caliper-ims-1.1)). Our response is that every event type has a defined **xAPI verb/object mapping**, so we can export to an LRS later. Internal storage stays a compact relational form.
4. **DPDP s.9(3) prohibits tracking and behavioural monitoring of children.** Time-on-task used to deliver progress is *plausibly* an educational activity, but the same data used for targeting is not (research §DPDP; Open legal Q1/Q2) [Verified for the statute; the interpretation is Rec]. Our response is a **minor data tier** that limits processing to learning-progress metrics (§4.6).

---

## 1. Event envelope

### 1.1 Principles [Rec]

- **The client cannot assert identity.** `user_id`, `organization_id`, `auth_session_id`, `device_id` and `privacy_tier` are **set by the server** from the authenticated session. The wire schema forbids them (`additionalProperties: false`).
- **Idempotency is per event.** The client generates `event_id` as a **UUIDv7** when the event happens and reuses it on every retry. The server inserts with `ON CONFLICT DO NOTHING` (§5.4).
- **The server owns all authoritative facts.** Assessment, coding-submission, practice-answer and completion events are **emitted by the server** from the owning domain module, through a transactional outbox (CP-8). The ingest API rejects these types if a client sends them (`server_only_event`).
- **Events carry no free text and no secrets.** `route` is a **route template** (`/courses/[courseSlug]/lessons/[lessonId]`), never a raw URL with query string. Events never contain answer text, code, tokens, cookies, IP addresses or user-agent strings. IP and UA belong to the `security`/`sessions` modules.
- The structure maps to xAPI: actor = `user_id`, verb = `event_type`, object = `entity`, context = `tab_id`/`page_instance_id`/`auth_session_id`/`organization_id`, result = `payload`, timestamp = `effective_at`.

### 1.2 Identifiers used in the envelope

| Field | Generated by | Lifetime / meaning |
|---|---|---|
| `event_id` | Client (UUIDv7; ms timestamp = event time) or server for server events | One logical event. Unchanged across retries. |
| `tab_id` | Client, random UUIDv4 stored in `sessionStorage` | One browser tab. **Survives a refresh** in the same tab and is new for a duplicated tab. |
| `page_instance_id` | Client, UUIDv4 per page view | One rendered route view. A full refresh or an SPA route change creates a new one. |
| `seq` | Client, monotonic integer per `page_instance_id`, starting at 0 | Detects loss and orders events without relying on clocks. |
| `auth_session_id` | Server = `auth_sessions.id` | **The row ID, not the cookie token and not the token hash.** |
| `device_id` | Server = `devices.id` bound to the auth session | Analytics never collects its own fingerprint. |

### 1.3 Clock-skew handling [Rec]

Client clocks are untrusted and are often wrong on Indian Android and low-cost laptops. The model uses four fields:

- `occurred_at`: client wall-clock time (RFC 3339 with offset, ms precision).
- `mono_ms`: `performance.now()` at the event, relative to the page's time origin.
- Batch-level `sent_at`: client wall clock at the moment of sending.
- `received_at`: server time when the batch arrived (from the NTP-synced app server).

**Per-batch skew:** `skew_ms = received_at − sent_at`. This includes network latency, typically under 1 s, which is acceptable at heartbeat granularity.

**Effective time:** `effective_at = min(occurred_at + skew_ms, received_at)`. If `effective_at < received_at − L_late` (72 h), the event is rejected (`event_too_old`). **All interval construction and aggregation uses `effective_at`.** `occurred_at` is kept for audit.

**Clock-jump detection:** within one `page_instance_id`, compare `Δoccurred_at` with `Δmono_ms` between consecutive events. If they differ by more than 2 s, the user's clock was changed or the device slept. In that case `effective_at` for that page instance is re-anchored to `mono_ms`, using the anchor from the first batch, and the flag `clock_jump` is set. Because `performance.now()` may not advance during system sleep (implementation-dependent), mono time is used only as a consistency check plus a fallback, never as the only basis.

**Flags:** if `|skew_ms| > 10 min`, set `ingest_flags.large_skew` and still accept. If the corrected time falls outside the late window, the event is rejected with `event_too_old` (§5.3).

### 1.4 Wire envelope: JSON Schema (client → server)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.techdrona.in/analytics/v1/batch.json",
  "title": "AnalyticsEventBatch (client wire format, schema family v1)",
  "type": "object",
  "additionalProperties": false,
  "required": ["sent_at", "client", "events"],
  "properties": {
    "sent_at": { "type": "string", "format": "date-time" },
    "csrf": { "type": "string", "maxLength": 256, "description": "Only on the sendBeacon fallback path, which cannot set headers (CP-5)." },
    "client": {
      "type": "object",
      "additionalProperties": false,
      "required": ["app_version", "platform"],
      "properties": {
        "app_version": { "type": "string", "maxLength": 32 },
        "platform": { "enum": ["web", "android_webview", "ios_webview"] },
        "tz_offset_min": { "type": "integer", "minimum": -840, "maximum": 840 },
        "measurement_version": { "const": "tm-1.0" }
      }
    },
    "events": {
      "type": "array",
      "minItems": 1,
      "maxItems": 100,
      "items": { "$ref": "#/$defs/event" }
    }
  },
  "$defs": {
    "uuid": { "type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "uuid7": { "type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$" },
    "entity": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "course_id": { "$ref": "#/$defs/uuid" },
        "course_version_id": { "$ref": "#/$defs/uuid" },
        "lesson_id": { "$ref": "#/$defs/uuid" },
        "lesson_asset_id": { "$ref": "#/$defs/uuid" },
        "topic_id": { "$ref": "#/$defs/uuid" },
        "company_path_id": { "$ref": "#/$defs/uuid" },
        "question_id": { "$ref": "#/$defs/uuid" },
        "question_version_id": { "$ref": "#/$defs/uuid" },
        "test_id": { "$ref": "#/$defs/uuid" },
        "test_attempt_id": { "$ref": "#/$defs/uuid" },
        "test_section_id": { "$ref": "#/$defs/uuid" },
        "coding_problem_id": { "$ref": "#/$defs/uuid" },
        "assignment_id": { "$ref": "#/$defs/uuid" },
        "batch_id": { "$ref": "#/$defs/uuid" }
      }
    },
    "event": {
      "type": "object",
      "additionalProperties": false,
      "required": ["event_id", "event_type", "schema_version", "occurred_at", "mono_ms", "tab_id", "page_instance_id", "seq", "route", "payload"],
      "properties": {
        "event_id": { "$ref": "#/$defs/uuid7" },
        "event_type": { "type": "string", "pattern": "^[a-z]+\\.[a-z_]+$", "maxLength": 48 },
        "schema_version": { "type": "integer", "minimum": 1, "maximum": 99 },
        "occurred_at": { "type": "string", "format": "date-time" },
        "mono_ms": { "type": "integer", "minimum": 0 },
        "tab_id": { "$ref": "#/$defs/uuid" },
        "page_instance_id": { "$ref": "#/$defs/uuid" },
        "seq": { "type": "integer", "minimum": 0 },
        "route": { "type": "string", "maxLength": 200, "pattern": "^/[A-Za-z0-9_\\-/\\[\\]]*$" },
        "surface": { "enum": ["lesson_text", "lesson_video", "practice", "test", "coding", "dashboard", "catalog", "account", "other"] },
        "entity": { "$ref": "#/$defs/entity" },
        "payload": { "type": "object", "maxProperties": 24 }
      }
    }
  }
}
```

Validation also enforces these rules: the UUIDv7 timestamp embedded in `event_id` must be within ±5 min of `occurred_at`, and serialized event size must be ≤ 4 KiB. The payload is validated by a per-`event_type` + `schema_version` schema (Pydantic v2 discriminated union, §2).

### 1.5 Stored envelope: JSON Schema (server-enriched, as persisted)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.techdrona.in/analytics/v1/stored-event.json",
  "title": "StoredAnalyticsEvent",
  "allOf": [{ "$ref": "batch.json#/$defs/event" }],
  "type": "object",
  "required": ["event_ts", "received_at", "effective_at", "skew_ms", "source", "user_id", "privacy_tier"],
  "properties": {
    "event_ts": { "type": "string", "format": "date-time", "description": "Derived from the UUIDv7 ms timestamp of event_id; partition key (CP-1)." },
    "received_at": { "type": "string", "format": "date-time" },
    "effective_at": { "type": "string", "format": "date-time" },
    "skew_ms": { "type": "integer" },
    "source": { "enum": ["client", "server"] },
    "user_id": { "type": "string", "format": "uuid" },
    "organization_id": { "type": ["string", "null"], "format": "uuid", "description": "Org context of the enrolment/entitlement the activity belongs to; null for D2C." },
    "auth_session_id": { "type": ["string", "null"], "format": "uuid" },
    "device_id": { "type": ["string", "null"], "format": "uuid" },
    "privacy_tier": { "enum": ["adult", "minor"], "description": "Snapshot at ingest time from users/guardian_consents." },
    "ingest_flags": {
      "type": "array",
      "items": { "enum": ["large_skew", "clock_jump", "late", "seq_gap", "rate_capped", "implausible_clamped"] }
    },
    "measurement_version": { "const": "tm-1.0" }
  }
}
```

---

## 2. Event catalogue (schema family v1)

Column key. **Src**: C = client, S = server-emitted by the owning module via outbox. **Purpose**: L = learning delivery (core; processed for all users, including minors, as learning-progress data), P = product analytics (optional consent; **never collected for minors**), I = integrity/security (adults with the security-monitoring consent, §6.5). **Store**: E = `analytics_events`, H = `activity_heartbeats`.

All payload fields are optional unless shown in **bold**. Positions are in seconds with 0.1 s precision.

### 2.1 Page lifecycle

| event_type | Src | Purpose | Store | Payload | xAPI verb | Notes |
|---|---|---|---|---|---|---|
| `page.view` | C | L | E | **`nav_type`** (`navigate`/`reload`/`back_forward`/`spa`), `referrer_route`, **`visible`**, **`focused`** | `viewed` | Opens a `page_instance_id`. `seq` = 0. |
| `page.visibility_change` | C | L | E | **`visible`** (bool) | — | From the Page Visibility API (`visibilitychange`). Forces an immediate heartbeat flush. |
| `page.focus` / `page.blur` | C | L | E | — | — | Window focus. Forces a flush. |
| `page.idle_change` | C | L | E | **`idle`** (bool), **`idle_threshold_s`** | — | Fired when the client's idle detector crosses the threshold (§3.2). |
| `page.heartbeat` | C | L | H | See §2.1.1 | — | Sampled every 15 s while *engaged*, and every 5 min (`keepalive`) while visible but idle. |
| `page.hide` | C | L | E | **`reason`** (`pagehide`/`freeze`/`route_change`), `persisted` (bfcache) | `exited` | Sent with `fetch(…, {keepalive:true})`, falling back to `navigator.sendBeacon` (§5.1). Closes the page instance. |

#### 2.1.1 `page.heartbeat` payload (schema_version 1)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["kind", "sample_interval_ms", "active_ms", "state"],
  "properties": {
    "kind": { "enum": ["engaged", "keepalive"] },
    "sample_interval_ms": { "type": "integer", "minimum": 1000, "maximum": 330000 },
    "active_ms": { "type": "integer", "minimum": 0, "maximum": 20000, "description": "Client-measured active ms since previous sample of this page instance (0 for keepalive)." },
    "state": {
      "type": "object", "additionalProperties": false,
      "required": ["visible", "focused", "input_recent", "media_playing"],
      "properties": {
        "visible": { "type": "boolean" },
        "focused": { "type": "boolean" },
        "input_recent": { "type": "boolean" },
        "media_playing": { "type": "boolean" }
      }
    },
    "input_events": { "type": "integer", "minimum": 0, "maximum": 1000, "description": "Count only (key+pointer+touch+scroll). Never key codes or content." },
    "media": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "lesson_asset_id": { "type": "string", "format": "uuid" },
        "position_s": { "type": "number", "minimum": 0 },
        "rate": { "type": "number", "minimum": 0.25, "maximum": 2.0 },
        "played_ranges": { "type": "array", "maxItems": 8, "items": { "type": "array", "items": { "type": "number" }, "minItems": 2, "maxItems": 2 } }
      }
    },
    "editor": {
      "type": "object", "additionalProperties": false,
      "properties": { "focused": { "type": "boolean" }, "edit_ops": { "type": "integer", "minimum": 0, "maximum": 5000 } }
    },
    "reading": {
      "type": "object", "additionalProperties": false,
      "properties": { "max_scroll_depth_pct": { "type": "integer", "minimum": 0, "maximum": 100 } }
    }
  }
}
```

### 2.2 Video (VdoCipher player events)

The client maps VdoCipher player API events to these types. The player event names still need checking against the VdoCipher API docs; that check is not done [Rec].

| event_type | Src | Purpose | Store | Payload | xAPI verb |
|---|---|---|---|---|---|
| `video.play` | C | L | E | **`position_s`**, **`rate`**, `lesson_asset_id` (in entity) | `played` |
| `video.pause` | C | L | E | **`position_s`** | `paused` |
| `video.seek` | C | L | E | **`from_s`**, **`to_s`** | `seeked` |
| `video.rate_change` | C | L | E | **`from_rate`**, **`to_rate`**, **`position_s`** | `interacted` |
| `video.ended` | C | L | E | **`position_s`**, **`duration_s`** | `completed` |
| `video.buffering` | C | P | E | **`position_s`**, **`buffer_ms`** (on buffer end), `bitrate_kbps` | — |
| `video.error` | C | P | E | **`code`** (player code only), **`position_s`** | — |

During playback, `page.heartbeat.media.played_ranges` carries the media ranges actually played since the last sample. These ranges are the **input for unique coverage** (§3.9). Discrete video events are used to validate and close the ranges.

### 2.3 Practice (placement module)

| event_type | Src | Purpose | Store | Payload | xAPI verb |
|---|---|---|---|---|---|
| `practice.question_viewed` | C | L | E | **`position_in_set`**, `set_id` | `viewed` |
| `practice.hint_viewed` | S | L | E | **`hint_index`** | `requested-hint` |
| `practice.solution_viewed` | S | L | E | **`before_answer`** (bool) | `viewed` |
| `practice.answer_submitted` | S | L | E | **`practice_response_id`**, **`is_correct`**, **`attempt_no`** (per user × question), `server_time_on_question_ms` (server receipt minus `question_served_at`), `difficulty` | `answered` |

### 2.4 Assessment (assessments module; server-authoritative)

| event_type | Src | Purpose | Store | Payload | xAPI verb |
|---|---|---|---|---|---|
| `assessment.attempt_started` | S | L | E | **`started_at`**, **`deadline_at`**, `time_limit_s`, `attempt_no` | `attempted` |
| `assessment.attempt_resumed` | S | L | E | **`resumed_at`**, `prev_auth_session_id` | `resumed` |
| `assessment.section_entered` | S | L | E | **`entered_at`**, `section_deadline_at` | `progressed` |
| `assessment.question_viewed` | C | L | E | **`question_index`** | `viewed` (advisory only) |
| `assessment.answer_saved` | S | L | E | **`attempt_response_id`**, `is_final_for_question`, `changed` (bool) | `answered` (no correctness until submitted) |
| `assessment.attempt_submitted` | S | L | E | **`submitted_at`**, **`score`**, **`max_score`**, `section_scores` | `completed` |
| `assessment.auto_submitted` | S | L | E | **`submitted_at`**, **`reason`** (`deadline`/`section_deadline`/`admin`/`session_revoked`), **`score`** | `completed` |
| `assessment.attempt_scored` | S | L | E | **`attempt_id`**, `topic_scores` `[{topic_id, correct, total}]` or per-question `responses` `[{topic_ids, is_correct, difficulty?, question_version_id?}]` | `scored` |

**Domain event name (decided 2026-11-03, Stage 10):** the assessments module emits **`attempt.scored`** on the transactional outbox when an attempt's result is computed (it is **not** called `attempt.graded`). Analytics consumes it (`app/modules/analytics/consumer.py`, `ATTEMPT_DONE_TYPES`) and stores it as `assessment.attempt_scored`; it drives mastery updates (test weight 1.0) and, together with `attempt.started` / `attempt.submitted` (stored as `assessment.attempt_started` / `assessment.attempt_submitted`, `auto: true` → `assessment.auto_submitted`), metric M4. Analytics currently reads `outbox_events` with its own cursor; moving to `app.core.outbox.register_handler` is backlog A3.

The source of truth is `test_attempts`, `attempt_responses` and `attempt_events` (assessments module). Analytics consumes copies of these records and never decides them.

### 2.5 Coding (coding module)

| event_type | Src | Purpose | Store | Payload | xAPI verb |
|---|---|---|---|---|---|
| `coding.editor_focus` / `coding.editor_blur` | C | L | E | `language` | — |
| `coding.run` | S | L | E | **`language`**, **`samples_passed`**, **`samples_total`**, `status` | `attempted` |
| `coding.submit` | S | L | E | **`code_submission_id`**, **`language`** | `attempted` |
| `coding.submission_judged` | S | L | E | **`code_submission_id`**, **`verdict`** (AC/WA/TLE/MLE/RE/CE), **`tests_passed`**, **`tests_total`**, `score` | `scored` |

Code content and hidden-test details are never sent to analytics.

### 2.6 Learning (learning module)

| event_type | Src | Purpose | Store | Payload | xAPI verb |
|---|---|---|---|---|---|
| `learning.lesson_started` | S | L | E | **`first_open`** (bool) | `launched` |
| `learning.lesson_completed` | S | L | E | **`completion_rule`** (`manual`/`video_coverage`/`quiz_pass`/`assignment`), `coverage_pct` | `completed` |
| `learning.course_completed` | S | L | E | **`completed_lessons`**, **`total_lessons`** | `completed` |
| `learning.certificate_issued` | S | L | E | **`certificate_id`** | `earned` |
| `learning.resource_downloaded` | S | L | E | **`resource_id`** | `accessed` |
| `learning.assignment_submitted` | S | L | E | **`assignment_submission_id`** | `submitted` |

### 2.7 Auth and security events: owned by `security`/`sessions`, not analytics

These events are **not stored in `analytics_events`**. They live in the `security`, `sessions` and `audit` modules (`login_attempts`, `auth_sessions`, `security_signals`, `audit_log`), with the 1-year log floor that those modules own.

| Event (security-owned) | Crosses over to analytics? | Direction and use |
|---|---|---|
| `auth.login_succeeded`, `auth.login_failed`, `auth.mfa_*`, `auth.password_changed/reset`, `device.registered/verified/replaced` | **No** | Not needed for learning metrics. |
| `session.ended` (logout / idle-expired / absolute-expired / revoked) | **Yes, consumed** | Analytics closes every open interval of that `auth_session_id` at `ended_at` with `close_reason = session_end`. |
| `session.concurrency_limit_enforced`, `playback.stream_limit_enforced` | **No** | Deterministic caps stay in sessions/media. |
| `account.restricted` / `account.restriction_lifted` | **Yes, consumed** | While a restriction blocks learning, ingest returns 403 through `require_active_principal`. Analytics shows a restricted period on timelines. |
| `consent.changed` (purposes `analytics_product`, `security_monitoring`), `guardian_consent.changed`, age-tier change | **Yes, consumed** | Toggles optional purposes. Re-evaluates `privacy_tier`. |
| `analytics.plausibility_violation` | **Yes, produced by analytics → `security_signals`** | Emitted for ingest abuse (heartbeat flood, forged `seq` replays, repeated `server_only_event`) and implausible days. Security records it as integrity signal **IN-01** (implausible day) or **IN-02** (ingest forgery bursts); these are **not** inputs to any sharing score for any user (adult or minor) (v0.4, CPR-ANL-02; RE §4.5). These are security-necessary logs for all users. |
| Daily activity summary feed | **Yes, produced** | §6.5, adults with consent only. |

---

## 3. Time measurement model `tm-1.0`

### 3.1 Parameters (configurable in `policy_settings`, key prefix `analytics.tm.`)

| Parameter | Default | Allowed range | Meaning |
|---|---|---|---|
| `H` heartbeat sample interval | 15 s | 10–30 s | Sampling cadence while engaged. |
| `F` flush interval | 30 s | 15–60 s | Samples are batched. The client also flushes immediately on any state change and on `page.hide`. |
| `K` idle keepalive interval | 300 s | 120–600 s | Low-rate signal while the tab is visible but idle. It feeds only **session elapsed time**. |
| `T_idle` (generic) | 90 s | 30–600 s | No input for `T_idle` makes the tab idle. |
| `T_idle` per surface | lesson_text 180 s, practice 240 s, coding 180 s, test 300 s, video (not playing) 90 s | 30–600 s | Thinking without input is normal on aptitude items and while reading. |
| `C_max` per-sample credit cap | 20 s | H … 2H | Server cap on any single heartbeat's credit. |
| `G` crash grace | 7.5 s (= H/2) | 0 … H | Bounded credit after the last sample when no terminal event arrived. |
| `D_close` interval-close timeout | 2F + 5 s = 65 s | — | No sample for this long means the interval is closed by the builder. |
| `ε_merge` | 5 s | 0–10 s | Adjacent credited segments merge into one interval if the gap is ≤ ε. |
| `S_gap` learning-session gap | 30 min | 10–60 min | Sessionization gap for session elapsed time. |
| `L_late` late-acceptance window | 72 h | 24–168 h | Older events are rejected. |
| Per-item MLAT caps | practice question 10 min / view; lesson text max(3 × est. reading time, 10 min) per lesson-day; video 1.25 × duration per asset-day; coding 120 min per problem-day | — | Applied to meaningful learning time (§3.10). |

Changing any parameter bumps the minor version (`tm-1.1`). Aggregates computed under different versions are never mixed in one comparison (§3.12).

### 3.2 Client state machine: active vs idle

For each page instance the client keeps `last_input_at`, updated by keydown, pointerdown, pointermove (throttled to 1/s), wheel, scroll and touchstart. Only the timestamp and counts are kept, never content.

```
visible       = document.visibilityState === "visible"
focused       = document.hasFocus()
input_recent  = (now − last_input_at) ≤ T_idle(surface)
media_playing = player.state === "playing" && !player.muted_and_hidden

ACTIVE  ⇔ visible ∧ ( (focused ∧ input_recent) ∨ media_playing )
IDLE    ⇔ visible ∧ ¬ACTIVE
HIDDEN  ⇔ ¬visible
```

- **An ACTIVE tab** samples every `H`. `active_ms` is the ms the tab spent in ACTIVE since the previous sample, measured with `performance.now()`.
- **When ACTIVE turns IDLE** the tab emits `page.idle_change{idle:true}` and flushes. Engaged sampling then stops and the tab emits only keepalives every `K`.
- **The idle crediting rule.** Because `input_recent` stays true for `T_idle` after the last input, the time *after* the last input is credited up to `T_idle`. This equals the "timeout" estimation heuristic from the literature, `credit = min(gap, T_idle)`, applied continuously. It is **disclosed** to users.
- **A HIDDEN tab** never earns active credit. Browsers also throttle background timers, so the client does not rely on them.
- **A video playing in a visible but unfocused window counts as active.** An example is a video on a second monitor while the user types notes elsewhere. **Video playing in a hidden tab** (audio only) earns **video playback time** but **not** active engagement. It is flagged `hidden_playback` in the interval.

### 3.3 Server-side crediting of heartbeats

For page instance `p`, let `t_k` be the `effective_at` of sample `k`, and `t_{k−1}` the previous sample (or the `page.view`, `page.focus`, `page.visibility_change{visible}` or `page.idle_change{idle:false}` event that started ACTIVE).

```
credit_k  = min( active_ms_k / 1000 , t_k − t_{k−1} , C_max )      (seconds, ≥ 0)
segment_k = [ t_k − credit_k , t_k ]
```

- Segments of `p` with gap ≤ `ε_merge` merge into one **engagement interval**.
- A **terminal event** (`page.hide`, `page.blur` with no media playing, `page.visibility_change{visible:false}`, `page.idle_change{idle:true}`, or `session.ended`) at time `t_x` after the last sample `t_n` adds `[t_n, min(t_x, t_n + H)]` when the state at `t_n` was ACTIVE. It then closes the interval with `close_reason` = the event type.
- **Crash or disconnect** happens when no terminal event arrives and no sample comes for `D_close` in server time. The builder closes the interval at `ended_at = t_n + G` with `close_reason = timeout_grace`. Because of flush batching, up to `F` seconds of unflushed samples may be lost. They are **not** reconstructed, so the error is biased toward under-counting by design.
- Keepalive samples (`kind = keepalive`) earn **zero** active credit. They only extend the page instance's *presence* span, which session elapsed time uses.

### 3.4 Engagement interval construction (`engagement_intervals`)

The **interval builder** is a Celery beat job that runs every 60 s. It keeps a per-partition watermark on `activity_heartbeats.received_at`. For each page instance with new samples it upserts its open interval: it extends `ended_at`, increments `heartbeat_count` and ORs the state flags. It closes intervals according to §3.3.

**Each interval belongs to exactly one page instance and one mode.** The mode is `interactive` (focused ∧ input_recent), `media` (media_playing only) or `mixed`. Intervals from different tabs **may overlap**. Overlaps are resolved only in aggregation (§3.5), so the raw intervals stay explainable to a reviewer.

### 3.5 Multi-tab and multi-device overlap: union per user, never a sum

Let `A_u` be the set of active intervals of user `u` across all tabs and devices within a day (IST). The rules are:

1. **User-level active time** = `|⋃ A_u|`, the measure of the union. With this rule, **one wall-clock second can earn at most one active second per user**, whatever the number of tabs or devices.
2. **Attribution to entities** is needed for lesson, course and topic totals. The union is cut into elementary sub-intervals at every interval boundary. Each sub-interval is assigned to exactly **one** interval by priority:
   1. an interval inside an in-progress assessment attempt (`test_attempt_id` set)
   2. `interactive` (focused with recent input)
   3. `mixed`
   4. `media`
   5. Ties go to the interval whose most recent sample is latest, then to the lowest `page_instance_id` (deterministic).

   Therefore **Σ (attributed seconds over all entities) = |⋃ A_u|** exactly.
3. **Background tabs** produce no intervals, apart from hidden playback, which is playback-only, so they never inflate totals.
4. **Simultaneous intervals on different `device_id`s** are kept in the union for learning metrics (the person is credited once). They are also measured as `multi_device_overlap_s` for the security feed (§6.5, adults with consent only).

### 3.6 Refresh, navigation, back-forward cache

- **Refresh.** The old page instance sends `page.hide{reason:pagehide}` through keepalive/beacon, and its interval closes at that time. The new page instance (same `tab_id`, `nav_type = reload`) opens a new interval. The 1–3 s load gap is **not** credited. If the `page.hide` is lost, the old interval closes by `timeout_grace`. Its grace may overlap the new interval, and the union removes the double count.
- **SPA route change.** The client emits `page.hide{reason:route_change}` and then `page.view{nav_type:spa}` with a new `page_instance_id`, so attribution follows the entity on screen.
- **bfcache restore** (`pageshow.persisted`). The client creates a new `page_instance_id` with `nav_type = back_forward`.

### 3.7 Duplicate, out-of-order and late events

- **Duplicates:** inserts use `INSERT … ON CONFLICT (event_id, event_ts) DO NOTHING`. `event_ts` is derived deterministically from the UUIDv7 inside `event_id` (CP-1), so a retry always targets the same partition and the same unique key. The response reports `duplicate`, which the client treats as success.
- **Out of order:** the builder orders by (`page_instance_id`, `seq`), not by arrival order. A `seq` gap is flagged (`seq_gap`) but not filled.
- **Late events.** Events whose `effective_at` is ≤ `L_late` (72 h) old are accepted. Older events are rejected (`event_too_old`). A late sample for an already-closed interval of the same page instance is inserted with the `late` flag. The builder **reopens and rebuilds** that page instance's intervals from raw samples, which is deterministic and idempotent. Every affected user-date is marked dirty in `analytics_dirty_days` (CP-2).
- **Re-aggregation:** the dirty-day worker recomputes daily aggregates for dirty `(user_id, date)` pairs. A day is **frozen at D + 4** (late window plus 1 day of slack). After that, only an explicit backfill job (super_admin, audited) can recompute it, for example after a `tm-x.y` change.

### 3.8 Assessment time: server-authoritative

The attempt timestamps (`started_at`, `deadline_at`, `submitted_at`) are set by the assessments module on the server. Client clocks never change assessment time.

```
assessment_time(attempt) = min(submitted_at, deadline_at) − started_at
section_time(attempt, s) = min(next_section_entered_at, section_deadline_at, submitted_at) − section_entered_at(s)
```

- **`assessment_active_s`** (advisory) = the active seconds attributed to the attempt (§3.5, priority 1). It is shown to trainers only as "time actively on test page", never as a score input.
- **Time away during an attempt** = `assessment_time − assessment_active_s`. It is reported only in the optional integrity report for tests configured with `integrity_report = on` and disclosed to the candidate. For minors it is shown only on college-sponsored tests, pending legal Q1. **Disconnects are logged as events, not penalties** (research §4, Practice and mocks).
- **Per-question time** = active seconds attributed to sub-intervals with that `question_id` on screen. Server receipt gaps are the fallback when heartbeats are missing.

### 3.9 Video: playback time vs unique coverage

For user `u` and asset `a` on day `d`:

```
video_playback_time(u,a,d) = |⋃ { wall-clock spans where media_playing = true for asset a }|        (seconds, across tabs; stream limit = 1 anyway)
media_seconds_consumed      = Σ over played_ranges (to − from)                                     (re-watching counts again)
unique_coverage(u,a)        = |⋃ played_ranges over all time| / duration_s(a)                     (0–1, lifetime, seeks excluded)
```

**Plausibility clamp:** for every sample, `Σ(to − from) ≤ credit_wall_s × rate × 1.1 + 1`. Any excess is dropped and flagged `implausible_clamped`. A seek produces no coverage, because ranges come only from actual playback. A rate above the platform maximum (2.0) is rejected by the schema.

The lesson-completion rule `video_coverage` is owned by the learning module. The proposed default is **coverage ≥ 0.9**. Analytics provides coverage to `lesson_progress` through a service call; analytics does not mark completion itself.

### 3.10 Coding editor time

`coding_time(u, problem, d)` = active seconds attributed to page instances whose `entity.coding_problem_id = problem`. A sub-interval counts only if `editor.focused` was true, `edit_ops > 0` in the sample, or a run/submit happened within ±5 min. The result is capped at 120 min per problem per day. The derived metric `time_to_first_accept` = active coding seconds from the first `page.view` of the problem to the first `AC` verdict. The wall-clock equivalent is also kept.

### 3.11 The five metrics (precise definitions)

Notation: `|X|` is the Lebesgue measure (seconds) of a union of intervals. `day(d)` is the IST calendar day `[d 00:00, d+1 00:00) Asia/Kolkata`; intervals that cross midnight are split.

| # | Metric | Definition / formula | What it is not |
|---|---|---|---|
| M1 | **Session elapsed time** | First, *learning sessions* are built per user by sorting all of the user's events and samples (engaged **and** keepalive) by `effective_at`. A new session starts after any gap > `S_gap` (30 min). `M1(u,d) = Σ_sessions (last_ts − first_ts)`, clipped to `day(d)`. | **Not study time.** It includes idle reading pauses and idle open tabs, until the auth session expires (CP-6 keeps idle keepalives from extending the auth session). Labelled "Time signed in (approx.)". |
| M2 | **Estimated active engagement time** | `M2(u,d) = |⋃ A_u ∩ day(d)|` over all surfaces (§3.5). | Not proof of attention (§9). |
| M3 | **Video playback time** | `M3(u,d) = Σ_assets video_playback_time(u,a,d)` (§3.9). Lifetime **unique coverage** is a separate companion metric. | Includes hidden-tab playback, which is flagged. Not a learning measure on its own. |
| M4 | **Assessment time** | `M4(u,d) = Σ_attempts |[started_at, min(submitted_at, deadline_at)] ∩ day(d)|` using **server timestamps**. Includes time away. | Not active time. The advisory `assessment_active_s` is separate. |
| M5 | **Meaningful learning activity time** | `M5(u,d) = Σ_items min( cap(item), |{s ∈ attributed sub-intervals of item in day(d) : surface(s) ∈ LearningSurfaces ∧ E(s)}| )`. LearningSurfaces = {lesson_text, lesson_video, practice, test, coding}. The evidence rule **E(s)** holds if, within ±5 min of `s` on the same page instance, there was ≥1 learning signal: media playing, `reading.max_scroll_depth_pct` increased, `practice.answer_submitted`/`hint_viewed`, `assessment.answer_saved`, `coding.run`/`submit`/`edit_ops > 0`, or an in-progress attempt. | Excludes dashboard, catalog, account and billing pages, and "active but no learning evidence" time. **This is the headline "learning time"** shown to students, trainers and coordinators. |

Invariants, tested in QA: `M5 ≤ M2 ≤ M1`; `|⋃ A_u|` per second ≤ 1; `M3` can exceed `M2` only through hidden-tab playback; `M4` is independent of client clocks.

### 3.12 Disclosure and versioning

Every derived row stores `measurement_version`. The student "How we measure time" page shows the active parameters (the §3.1 table). Reports that compare periods computed under different versions show a banner, and cohort comparisons refuse to mix versions. This answers the "undisclosed heuristic" criticism (Kovanović et al.; moodle notes §9 Inferences).

### 3.13 Worked examples

**Example 1: overlapping tabs (two windows side by side, one laptop).** All times are IST and the student is adult.

| Time | Window A (page_instance A1, lesson L1 video, 30 min) | Window B (page_instance B1, practice set on topic "Percentages") |
|---|---|---|
| 10:00–10:20 | Video playing, window focused | — |
| 10:20 | Video keeps playing; the user clicks into window B (A1 is visible but not focused) | Opens; focused with input |
| 10:20–10:30 | `media` interval continues | `interactive` interval; answers Q1 at 10:24 and Q2 at 10:31 |
| 10:30 | Video ends (`video.ended`) | — |
| 10:30–10:40 | Visible, no input, video ended → IDLE after 90 s, but A1 is unfocused anyway, so no credit | Answers Q3 at 10:37 and closes the tab at 10:40 (`page.hide`) |

- Raw intervals: A1 = [10:00, 10:30] (30 min; `mixed` until 10:20, then `media`) and B1 = [10:20, 10:40] (20 min, `interactive`).
- **A naive per-tab sum gives 50 min. M2 = |[10:00, 10:40]| = 40 min.**
- Attribution of the overlap [10:20, 10:30]: `interactive` beats `media`, so it goes to B1. Result: lesson L1 = 20 min and practice/"Percentages" = 20 min. The sum is 40 min = M2 ✔.
- M3 (video playback) = 30 min, because playback is measured on its own and is not exclusive. Unique coverage of L1 = 30/30 = 100 %.
- M5: A1 has evidence (media playing) and B1 has evidence (answers). Caps: Q1 viewed 10:20–10:24 = 4 min, Q2 10:24–10:31 = 7 min, Q3 10:31–10:40 = 9 min, all under the 10 min/view cap. **M5 = 40 min.**
- M1: one learning session from 10:00 to 10:40 = 40 min. M4 = 0.
- *Variant: the same two tabs in **one** window.* Only one tab can be visible, so the hidden video tab gets no M2 credit. Its playback counts toward M3 with the `hidden_playback` flag, and coverage still grows. M2 = |[10:00, 10:20] ∪ [10:20, 10:40]| = 40 min, with L1 = 20 and practice = 20.

**Example 2: a tab left open for hours.** The student opens lesson L2 (text) at 14:00, reads and scrolls with inputs less than 180 s apart until 14:12:00, then walks away. The laptop stays awake with the tab visible and focused until 18:00.

- Active credit continues for `T_idle(lesson_text)` = 180 s after the last input, so `idle_change{idle:true}` fires at 14:15:00. **M2 = M5 = 15 min.** The scroll-depth rise is the evidence. The lesson's estimated reading time is 8 min, so its cap is max(3 × 8, 10) = 24 min, and 15 min stays under it.
- Keepalives go out every 5 min. They do **not** refresh the auth session (CP-6). The student idle timeout is 60 min from the last *real* request, which was the last engaged flush at about 14:15, so the session expires around 15:15. The next keepalive gets 401 and the client stops.
- **M1 = 14:00 → ~15:15 ≈ 75 min**, labelled "signed in", not study time. A Canvas-style gap heuristic would report a much larger and growing figure [Reported behaviour, §0].
- M3 = M4 = 0.

**Example 3: crash.** Engaged samples are flushed at 11:07:15 and 11:07:45. The samples taken at 11:07:30 and 11:07:45 arrive, and the device dies at 11:07:52. No `page.hide` arrives. At 11:08:50 (`D_close` = 65 s after the last sample) the builder closes the interval at **11:07:45 + 7.5 s = 11:07:52.5** (`timeout_grace`). If the 11:07:45 flush had also been lost, the interval would end at 11:07:30 + 7.5 s, an under-count of about 22 s. That is acceptable by design.

**Example 4: assessment with a disconnect.** The server records `started_at` 10:00:00 and `deadline_at` 11:00:00. The browser closes at 10:20, the student resumes on the same device at 10:35 (`attempt_resumed`) and submits at 10:50:00.

- **M4 = 50 min.** Heartbeat-active on the test page: 10:00–10:20 and 10:35–10:50 = 35 min, so `assessment_active_s` = 35 min. Time away = 15 min, which is logged and not penalised.
- If the student had not returned, `auto_submitted` would fire at 11:00 and M4 = 60 min.

**Example 5: video seeking and rate.** A 20-min video. The student watches 0:00–5:00 at 1×, seeks to 15:00, watches 15:00–20:00 at 2×, then seeks back and re-watches 3:00–5:00 at 1×.

- M3 (wall-clock playing) = 5 + 2.5 + 2 = **9.5 min**.
- Media seconds consumed = 5 + 5 + 2 = 12 min.
- **Unique coverage** = |[0, 5] ∪ [15, 20] ∪ [3, 5]| / 20 = 10/20 = **50 %**. The lesson is not complete under the 90 % rule.

**Example 6: two devices at once (account-sharing shape).** A laptop is active on lesson L3 from 20:00–21:00 and a phone is active on practice from 20:30–21:30, both on the same user.

- M2 = |[20:00, 21:30]| = 90 min (not 120). Attribution: the overlap goes by priority; both are interactive, so ties go to the latest sample, alternating at sample granularity.
- `multi_device_overlap_s` = 30 min goes to the security feed **only if** the user is an adult with the `security_monitoring` consent (§6.5). For a minor it is never computed.

---

## 4. Aggregations, storage, retention and privacy

### 4.1 Pipeline

```
Browser ──fetch keepalive / sendBeacon──▶ Next.js BFF ──▶ FastAPI analytics.ingest
                                                            │ validate, enrich, clamp, dedupe
                                                            ├─▶ activity_heartbeats  (partitioned, monthly)
                                                            └─▶ analytics_events     (partitioned, monthly)
Domain modules ──transactional outbox (CP-8)──▶ outbox relay ─▶ analytics_events (source=server)
Celery beat:
  interval_builder (60 s) ─▶ engagement_intervals
  daily_aggregator (15 min for "today"; 02:30 IST full D-1; dirty days up to D-3) ─▶ daily_learning_aggregates (+ companion tables)
  rollups (03:30 IST) ─▶ weekly / course / topic / cohort rollups
  mastery (near-real-time on answer events + 04:00 IST item recalibration)
  security_feed (04:30 IST) ─▶ security_activity_feed_daily
  partition_maintenance (daily) ─▶ create 3 months ahead; detach + drop expired
```

v1 inserts **synchronously** with multi-row inserts. A 200 response means the events are durable. The scale step is a Redis Streams buffer with bulk `COPY`. The ADR must evaluate ClickHouse or BigQuery when ingest goes above about 2,000 events/s sustained, or when the 02:30 job takes more than 20 min (brief §1).

**Volume sizing assumption [Rec, to validate]:** 10k DAU × 45 min active ≈ 1.8 M heartbeat rows/day (about 54 M/month, roughly 10–12 GB/month with indexes), plus about 1 M other events/day. Short raw retention keeps the hot set below about 60 GB.

### 4.2 Tables and grain

| Table | Grain | Key columns (abridged) | Refresh |
|---|---|---|---|
| `analytics_events` *(brief)* | 1 row / event | `event_id`, `event_ts` (partition key), `event_type`, `schema_version`, `source`, `user_id`, `organization_id`, `auth_session_id`, `device_id`, `tab_id`, `page_instance_id`, `seq`, `route`, `surface`, entity FK columns (nullable, typed UUIDs, no FK constraints across partitions), `occurred_at`, `received_at`, `effective_at`, `skew_ms`, `privacy_tier`, `ingest_flags`, `payload` JSONB (≤ 4 KiB) | Real-time |
| `activity_heartbeats` *(brief)* | 1 row / sample | `event_id`, `event_ts`, `user_id`, `organization_id`, `auth_session_id`, `device_id`, `tab_id`, `page_instance_id`, `seq`, `effective_at`, `received_at`, `kind`, `active_ms`, `state_bits` smallint, `surface`, `course_id`, `lesson_id`, `lesson_asset_id`, `question_id`, `test_attempt_id`, `coding_problem_id`, `media_position_s`, `media_rate`, `played_ranges` (int4range[] in deciseconds), `edit_ops`, `scroll_depth_pct`, `input_events`, `ingest_flags`. **Narrow columns, no JSONB.** | Real-time |
| `engagement_intervals` *(brief)* | 1 row / contiguous active interval per page instance | `id`, `user_id`, `organization_id`, `auth_session_id`, `device_id`, `tab_id`, `page_instance_id`, `surface`, `mode`, entity columns, `started_at`, `ended_at`, `active_s`, `heartbeat_count`, `close_reason`, `flags` (`hidden_playback`, `clock_jump`, `seq_gap`, `late`), `is_open`, `measurement_version` | 60 s |
| `daily_learning_aggregates` *(brief)* | 1 row / user × IST date × entity (`entity_kind` ∈ course, lesson, topic, test_attempt, coding_problem, `_total`) | `user_id`, `organization_id`, `activity_date`, `entity_kind`, `entity_id`, `course_id`, `topic_id`, `category_topic_id`, `m1_session_elapsed_s` (only on `_total`), `m2_active_s`, `m3_video_playback_s`, `m4_assessment_s`, `m5_learning_s`, `questions_attempted`, `questions_correct`, `first_attempt_correct`, `code_runs`, `code_submissions`, `code_accepted`, `lessons_completed`, `video_coverage_gain_s`, `privacy_tier`, `measurement_version`, `computed_at`, `is_frozen` | 15 min (today), nightly, dirty-day |
| `video_watch_coverage` *(CP-2)* | 1 row / user × lesson_asset | `covered_ranges` int4range[] (merged), `coverage_pct`, `duration_s`, `last_position_s`, `updated_at` | Interval builder |
| `weekly_learning_aggregates` *(CP-2; a table, not a materialized view, because RLS does not apply to MVs)* | user × ISO week (Mon, IST) × entity | sums of daily M2–M5 + `active_days` (days with M5 ≥ 10 min) | Nightly |
| `cohort_learning_aggregates` *(CP-2)* | (organization or batch) × date/week × course/topic/category | `learners_enrolled`, `learners_active` (M5 > 0), `m5_sum_s`, `m5_p50_s`, `m5_p90_s`, completion counts, accuracy, test score distribution (deciles), `suppressed` (k-rule) | Nightly 03:30 |
| `route_daily_aggregates` *(CP-2, Purpose P, adults with consent only)* | route template × date | `views`, `unique_users` (HLL), `m2_p50_s`, `bounce_count`, buffering stats | Nightly |
| `topic_mastery` *(CP-11)* | user × topic | `theta`, `n_eff`, `weighted_accuracy`, `band`, `last_practiced_at`, `model_version` | Near-real-time |
| `question_item_stats` *(CP-2)* | question_version | `n_first`, `p_value`, `median_time_s`, `skip_rate`, `option_dist` JSONB, `point_biserial`, `difficulty_b`, `review_flag` | Nightly 04:00 |
| `security_activity_feed_daily` *(CP-2, §6.5)* | user × date (adults with consent) | see §6.5 | 04:30 IST |
| `analytics_dirty_days`, `analytics_ingest_rejections` *(CP-2)* | ops | `user_id`, `date`, `reason`; rejection counters by code/hour (no payloads) | Real-time |

**Aggregation levels requested in the brief:**

- **Per page:** `route_daily_aggregates` (product view). Per page instance is available from `engagement_intervals`.
- **Lesson, course, topic and placement category:** `entity_kind` rows in `daily_learning_aggregates`. Topics resolve through the lesson→topic and question→topic mappings (DM-4). Category = the root of the `topics` tree.
- **Daily and weekly per user:** `_total` rows plus `weekly_learning_aggregates`.
- **Batch and college rollups:** `cohort_learning_aggregates`. A user's activity rolls up to the org or batch of the **enrolment or entitlement** under which the content was accessed (`organization_id` resolved at ingest from `entity.course_id` → enrolment). A D2C purchase does **not** roll up to the college, even when the student is also a college member.

### 4.3 Partitioning and indexes

- `analytics_events` and `activity_heartbeats` use `PARTITION BY RANGE (event_ts)` with monthly partitions (brief §1). Partitions are created three months ahead. The PK is `(event_id, event_ts)`. Per-partition indexes are `(user_id, event_ts)`, `(page_instance_id, seq)` and BRIN on `received_at` for the builder watermark.
- `engagement_intervals` is range-partitioned by `started_at` (monthly), with index `(user_id, started_at)` and a partial index `WHERE is_open`.
- RLS with FORCE applies on every analytics table that has `organization_id` (brief §1). D2C rows (`organization_id IS NULL`) are visible only to the user, to platform-scoped roles, and to the system role.

### 4.4 Retention [Rec, aligned with research §DPDP: 12–24 months identifiable, then aggregate]

| Data | Retention | Mechanism |
|---|---|---|
| `activity_heartbeats` | **35 days** | Monthly partitions detached and dropped once wholly older than 35 days (≤ about 65 days physically). That covers the 72 h late window plus a 30-day dispute or recompute window. |
| `analytics_events` (client + server) | **90 days** (brief v0.2 §1; reduced from the proposed 120 days to the privacy doc's raw-analytics cap, reconciliation §3.1, PO-13) | Partition drop. Authoritative records (attempts, submissions, progress) remain in their owning modules under those modules' retention. |
| `engagement_intervals` | **13 months** | Supports year-on-year comparison and recompute of aggregates. |
| `daily_learning_aggregates`, `weekly_…`, `video_watch_coverage`, `topic_mastery` | **24 months identifiable** after the activity date, or account deletion + 30 days, whichever is first | After that, user rows are deleted. Only cohort aggregates remain. |
| `cohort_learning_aggregates`, `question_item_stats`, `route_daily_aggregates` | Life of the platform or contract | Non-identifying (k-rule). B2B cohort data is returned or deleted at contract end under the DPA (research §Retention). |
| `security_activity_feed_daily` | **180 days** | Aligned with "account-sharing score inputs ≤ 180 days" (research §Retention). |
| `analytics_ingest_rejections` | 90 days, counters only | — |

These analytics tables are **not** the "logs" that carry the DPDP 1-year floor. Access and security logs live in `sessions`, `security` and `audit`. Whether any analytics data counts as "traffic data" under Rules 6(e) and 8(3) is legal Q4. It is flagged to the Security Specialist (privacy-and-data-retention.md), and the retention table above may need to change.

**Account deletion and erasure (s.8(7)).** The analytics `privacy_provider` deletes the user's rows from every identifiable analytics table within 30 days, including rows inside not-yet-dropped raw partitions (`DELETE … WHERE user_id = $1`, indexed). Cohort aggregates are not recomputed. They are already non-identifying under the k-rule.

### 4.5 Pseudonymisation and minimisation

- Analytics tables store **no names, emails, phone numbers, IP addresses, user agents, answer text or code**. `user_id` is an opaque UUID, and joins to `users` happen only in permission-checked report queries.
- **Exports and warehouse:** a future ClickHouse/BigQuery sink, BI extracts and research exports receive `subject_key = HMAC-SHA256(k_analytics_vN, user_id)` (brief v0.2 §1; privacy doc §8 owns the key and its yearly rotation). Dates are coarsened to a day and rare entities are suppressed.
- **The small-cell rule (k-anonymity floor):** a cohort cell is shown only if it has ≥ `analytics.k_min.cohort` (10) learners; item analytics need ≥ `analytics.k_min.item` (10) responses. Cross-organisation benchmarks shown to coordinators or students need ≥ `analytics.k_min.cross_org_display` (50) per bucket; a percentile reference cohort needs ≥ `analytics.k_min.percentile_reference` (20). Suppressed cells show "<10". Synthetic accounts (`users.is_synthetic`, `organizations.is_synthetic`) never count toward k and are excluded from every aggregate and from the security feed (v0.4, IPR-AN-02; §6.5).
- Coordinators and trainers see **identifiable** per-student learning metrics for students within their granted scope (`organization:{id}` / `batch:{id}`), under the college DPA. They never see the security feed.

### 4.6 Minors (`privacy_tier = minor`)

The brief's minors rule (§1) and DPDP s.9(3) apply. Open legal questions Q1 and Q2 are unresolved, so the design applies the **conservative** reading.

| Allowed for minors (learning-progress) | Not allowed for minors |
|---|---|
| L-purpose events and heartbeats, used **only** to compute M1–M5, completion, coverage, accuracy, mastery and test results | P-purpose events: product analytics, `route_daily_aggregates`, buffering/quality telemetry tied to the user. **The client does not send them and the server drops them.** |
| Display to the student, the guardian (if a guardian view exists) and the sponsoring college's scoped staff | Security activity feed, `multi_device_overlap_s`, any behavioural risk scoring or account-sharing profiling input |
| Recommendations based on mastery and syllabus gaps (learning delivery) | Engagement-optimisation nudges based on behaviour patterns (time-of-day, streak-loss pressure), marketing audiences, ad pixels, and cross-org benchmarking that profiles the individual |
| Test integrity "time away" on **college-sponsored** tests only, disclosed beforehand, pending Q1 | Integrity reports on D2C tests for minors |

Rules for minors:

- `privacy_tier` is snapshotted per event. When a user turns 18, nothing is re-processed retroactively. Only new data falls under the adult purposes, and only after the adult consents.
- The "no behavioural profiling" rule also covers **aggregate** analysis that singles out an individual minor: there is no minor-level "engagement score" or "at-risk" label derived from time patterns. A trainer "needs attention" list uses only progress and mastery (§7.2).

---

## 5. Ingest API contract (proposal for `docs/api-specification.md`)

### 5.1 Endpoints

| Method / path | Purpose | Auth | Permission / scope |
|---|---|---|---|
| `POST /api/v1/analytics/events` | Batch ingest (primary; `fetch` with `keepalive: true` on unload) | Session cookie through the BFF, CSRF header, `require_active_principal` | No permission key: an authenticated session is required and only the principal's own events are written (ownership **S**; role matrix §2.7 note). `analytics.event.ingest` is retired (IPR-AN-01) |
| `POST /api/v1/analytics/events/beacon` | `navigator.sendBeacon` fallback (no custom headers possible) | Session cookie + `csrf` field in the body + `Sec-Fetch-Site: same-origin` required (CP-5) | same |
| `GET /api/v1/analytics/config` | Returns the active `tm-*` parameters, enabled purposes for this user (consent and tier) and the sampling flags | Session | self |

**Idle effect (v0.4, CPR-ANL-01).** Both ingest routes are `x-td-idle: engaged_only`. After crediting a batch, if the credited active seconds for the requesting session are > 0, the handler calls `sessions.touch_engaged(session_id)`; keepalive-only batches (and batches crediting 0 s) never call it, so they never extend the idle timeout (brief v0.4 §1).

`fetch(keepalive)` has a 64 KiB in-flight body budget per document [Rec; Fetch spec limit to re-verify], so the batch limit below fits it.

### 5.2 Limits and rate limiting (Redis token buckets)

**This section is the single authoritative source** of ingest rate, cadence and page-instance limits (v0.4, CPR-ANL-03; AMB-11). `security-threat-model.md` and `api-specification.md` reference it and do not state their own values.

| Limit | Value | On breach |
|---|---|---|
| Body size | ≤ 64 KiB (compressed upload not supported in v1) | 413 problem+json |
| Events per batch | ≤ 100 | 422 |
| Single event serialized | ≤ 4 KiB; payload ≤ 24 props, depth ≤ 3, strings ≤ 256 chars | Event rejected `payload_too_large` |
| Requests per auth session | 30/min sustained, burst 10 | 429 + `Retry-After`; the client keeps its queue |
| Requests per user (all sessions) | 60/min | 429 |
| Per IP (BFF-forwarded) | 600/min | 429 |
| Engaged heartbeats per page instance | ≥ 10 s apart in `effective_at` (excess dropped as `rate_capped`, still 200) | Counter → `analytics.plausibility_violation` if > 3× for 10 min |
| Concurrently ACTIVE page instances per user | Credit is unaffected by the union. More than 6 at once is flagged. | Signal (adults with consent) |

### 5.3 Validation and response

The server applies these checks in order. It returns per-event results and does not fail the whole batch for per-event problems.

1. Authentication and `require_active_principal`; CSRF / Fetch Metadata.
2. Batch schema (§1.4); `sent_at` present.
3. Per event: `event_type` is known and the `schema_version` is supported; the type is **not server-only**; the purpose is allowed for this user (consent and tier); the UUIDv7 time is within ±5 min of `occurred_at`; `effective_at` is within `L_late`; the entity IDs exist and the user is **entitled** to them (cached entitlement check). This prevents crediting time to content the user cannot access.
4. Payload schema; plausibility clamps (§5.5).

```json
HTTP/1.1 200 OK
{
  "accepted": 41, "duplicate": 2, "rejected": 1,
  "results": [
    { "event_id": "0193…", "status": "accepted" },
    { "event_id": "0193…", "status": "duplicate" },
    { "event_id": "0193…", "status": "rejected", "code": "event_too_old" }
  ],
  "server_time": "2026-11-03T10:15:02.123Z",
  "config_version": "tm-1.0"
}
```

Rejection codes: `unknown_event_type`, `unsupported_schema_version`, `server_only_event`, `purpose_not_permitted`, `event_too_old`, `event_in_future`, `invalid_payload`, `payload_too_large`, `entity_not_entitled`, `rate_capped`, `uuid_time_mismatch`. The client deletes accepted, duplicate and rejected events from its IndexedDB queue. It retries only on network errors, 429 and 5xx, using exponential backoff with jitter, up to the 72 h window.

**Idempotency:** this is per event via `event_id`, so the `Idempotency-Key` header (brief §5) is not required here (CP-4).

### 5.4 Client SDK obligations (`@techdrona/analytics`)

- Keep an IndexedDB-backed queue, with an in-memory fallback in private mode. Maximum 2,000 queued events. When full, drop the oldest *P-purpose* events first.
- Flush every `F`, immediately on state change, and on `pagehide`/`visibilitychange→hidden` (not `unload`, which is unreliable and blocks bfcache).
- Generate UUIDv7 with a monotonic counter within the same ms.
- Read `GET /analytics/config` at boot and never hard-code thresholds.

### 5.5 Anti-manipulation (server-side)

Browser time can be forged by a script, so the server limits how much forged time can matter:

1. **Identity comes from the session only.** Events cannot be attributed to another user.
2. **Per-sample cap** `C_max`, and **credit ≤ Δ server-corrected time since the previous sample**, so a burst of replayed samples earns nothing extra.
3. **Union per user.** At most **1 active second per wall-clock second per user**, however many tabs, devices or forged page instances there are (§3.5).
4. **Daily plausibility:** if M2 > 16 h/day for a user, the day is flagged `implausible`. It is excluded from cohort percentiles and leaderboards, and an `analytics.plausibility_violation` signal is raised (security integrity signal IN-01; never an input to any sharing score, for any user; v0.4).
5. **Entitlement check** on entity refs. No credit for content the user cannot access.
6. **Video coverage clamp** (§3.9) and the schema-enforced maximum rate.
7. **Evidence rule for M5.** Time without learning signals does not count as learning time.
8. **Time never gates value on its own.** Completion, certificates and grades depend on server-verifiable evidence: coverage + quiz, accepted submissions, attempt scores. **Time-based thresholds are never sufficient on their own** (recommended business rule for the Product Analyst).

---

## 6. Performance and learning analytics

### 6.1 Question accuracy and item statistics

| Metric | Definition |
|---|---|
| `accuracy(u, scope)` | Correct ÷ answered, over **first attempts** per question in scope. Retries are reported separately. Skipped questions are excluded and reported as `skip_rate`. |
| `test_accuracy` | From `attempt_results` (server-scored). Negative marking is reflected in score, not accuracy. |
| `time_per_question` | Active attributed seconds on the question (§3.8), capped at 10 min. Reported as the median per user, topic or item. |
| Item `p_value` | Share of correct first attempts (n ≥ 30 to display). |
| Item `point_biserial` | Correlation of item correctness with the total test score (test items, n ≥ 50). |
| Item `review_flag` | p < 0.15, p > 0.95, point-biserial < 0, or one distractor chosen more often than the key. Goes to content_manager. |

### 6.2 Topic mastery v1 (Elo-style, explainable) [Rec]

Inputs: `practice.answer_submitted` and scored test responses. **Time is not an input to mastery.**

```
P(correct) = 1 / (1 + exp(−(θ_{u,t} − b_q)))
θ_{u,t} ← θ_{u,t} + K_u · w · (r − P)          K_u = 0.4 / (1 + 0.05 · n_{u,t})
b_q     ← b_q     − K_q · w · (r − P)          K_q = 0.4 / (1 + 0.05 · n_q)   (item side, nightly batch)
b_q seed: authored difficulty easy −1.0, medium 0.0, hard +1.0
w (response weight): test 1.0; practice first attempt 1.0; practice retry 0.5; answered after solution_viewed 0.0;
                     after hint_viewed 0.5; secondary topic tags 0.5 × w
r: 1 correct, 0 incorrect; skipped = no update
```

- **Displayed mastery** `m = σ(θ)`, the probability of answering a medium item correctly. Bands: `insufficient data` (n_eff < 5), `weak` (< 0.40), `developing` (0.40–0.70) and `strong` (≥ 0.70).
- **Companion "weighted accuracy"** = `Σ w·decay·r / Σ w·decay` with `decay = 0.5^(age_days/30)`. It is shown next to the band so the number is explainable to students.
- **Roll-up:** subtopic → topic → category uses an `n_eff`-weighted mean of `m`.
- Every row stores `model_version` (`mastery-1.0`). A later IRT/BKT model gets a new version and is never mixed with the old one.

### 6.3 Percentiles

The test percentile is computed within a **cohort definition**: the same test version, first attempt, and a cohort that is platform-wide (`analytics.k_min.percentile_reference` ≥ 20) or the batch (`analytics.k_min.cohort` ≥ 10). It is recomputed nightly and on result publication. Days flagged `implausible` and attempts flagged by the integrity review are excluded from the reference distribution, not from the student's own result.

### 6.4 Recommendation inputs (deterministic ranking v1)

| Input | Source | Used as |
|---|---|---|
| Weak topics (`band = weak`, n_eff ≥ 5) | `topic_mastery` | Primary "next practice" |
| Stale topics (developing, `last_practiced_at` > 21 days) | `topic_mastery` | Spaced review |
| Company-path gaps (required topics with band < developing) | `company_paths` × `topic_mastery` | Path ordering |
| Incomplete prerequisite lessons (coverage < 0.9 or not completed) | `video_watch_coverage`, `lesson_progress` | "Watch before practising" |
| Assigned work due | `assignments` | Pinned |
| Items with high `p_value` already mastered | `question_item_stats` | Down-rank |

Time metrics are **not** recommendation inputs in v1. For minors the same inputs apply, because all of them are learning-delivery inputs.

### 6.5 Account-risk feed to the security module (contract)

- **Direction and form.** Analytics computes the feed and security reads it. Security calls the read-only service interface `analytics.feeds.get_activity_summary(user_id, from_date, to_date) → list[ActivityFeedDay]`, backed by `security_activity_feed_daily`. **Security never queries raw analytics tables.**
- **Second interface (5-min buckets).** `analytics.feeds.get_engaged_buckets(user_id, from, to) → list[(device_id, auth_session_id, bucket_5min, activity_kind)]`, read from `activity_heartbeats` (engaged samples only). Used by risk signals SH-01/SH-02 and security dashboard H3. Same eligibility as below; the window is limited by heartbeat retention (35 days). No content identities are returned (brief v0.2 §2; reconciliation §3.10).
- **Eligibility.** `privacy_tier = adult` **and** an active `security_monitoring` consent (brief §1 Privacy: itemised consent). If the consent is withdrawn, the rows are deleted within 24 h and no new rows are built. Minors: **no rows, ever**.
- **Fields, per user per IST day:**

| Field | Meaning |
|---|---|
| `active_devices` | Distinct `device_id` with M2 > 0 |
| `multi_device_overlap_s` | Measure of seconds where active intervals exist on ≥ 2 distinct devices |
| `max_concurrent_active_page_instances` | Peak count |
| `active_hours_bitmap` | 24-bit IST hour presence. **Coarse only, never minute-level timelines.** |
| `implausible_day` | bool (§5.5 rule 4) |
| `plausibility_violations` | count by code |
| `clock_jump_count`, `large_skew_count` | counts |
| `feed_version` | e.g. `feed-1.0` |

- **Synthetic accounts (v0.4, IPR-AN-02).** Rows of users with `users.is_synthetic = true` (and of organizations with `organizations.is_synthetic = true`) are excluded from all aggregates (`daily_learning_aggregates` onward, cohort, route and item statistics), from k-counts and from this security feed.
- **What is not shared:** content identities (which lessons or questions), scores, mastery, raw events, intervals and timestamps finer than an hour.
- Security rule versions must record the `feed_version` they consume. Retention is 180 days.

---

## 7. Reports and dashboards: metric definitions

All time metrics display their `tm-*` version and a "How we measure" link. "Learning time" always means **M5**.

### 7.1 Student (self)

| Metric | Definition |
|---|---|
| Learning time today / this week | M5 (`_total` daily / weekly) |
| Active days streak | Consecutive IST days with M5 ≥ 10 min. **Not shown to minors as a pressure mechanic; shown as a neutral count only.** |
| Course progress | Completed lessons ÷ total lessons in the enrolled `course_version` |
| Video coverage per lesson | `unique_coverage` (%), with a "resume at" position |
| Topic mastery | Band + weighted accuracy + n per topic and category |
| Accuracy and median time per question by topic | §6.1 |
| Tests | Score, section scores, percentile (k-rule), attempt time (M4) |
| Coding | Problems attempted / accepted, acceptance rate, `time_to_first_accept` (median) |
| Recommendations | §6.4 |

### 7.2 Trainer (scope: `batch:{id}` / `course:{id}`)

| Metric | Definition |
|---|---|
| Batch progress distribution | Histogram of course progress % across batch members |
| Lesson funnel | Started → completed per lesson; median M5 per lesson |
| Video drop-off curve | For each 5 % bucket of a video, the share of learners whose coverage includes the bucket (k ≥ `analytics.k_min.cohort`, 10) |
| Item analysis | §6.1 per question in the trainer's tests and practice sets |
| Test results | Score distribution (deciles), section averages, submission vs auto-submit counts |
| Learners needing attention | Progress < 50 % of batch median **or** ≥ 2 weak required topics **or** a missed assignment. **Progress and mastery only, with no time-pattern profiling** (same rule for adults and minors in v1). |
| Weekly learning time | Per learner M5 (weekly), with the median and p90 for the batch |

### 7.3 College coordinator (scope: `organization:{id}`)

| Metric | Definition |
|---|---|
| Seat utilisation | Learners with ≥ 1 active day in the period ÷ seats assigned |
| Weekly active learners | Learners with M5 > 0 in the ISO week |
| Learning time per active learner | Median and p90 of weekly M5, per batch |
| Course completion rate | Completed enrolments ÷ enrolments, per course and batch |
| Placement readiness by category | Share of learners with band ≥ developing per placement category (Quant, Logical, Verbal, Programming, DSA, CS core) |
| Test participation and outcomes | Attempted ÷ assigned; score distribution; batch percentile bands |
| Per-student drill-down | §7.1 metrics for students in scope (DPA-governed); CSV export (audit-logged) |

Coordinators never see the security feed, risk levels (security module UI only), device data or M1.

### 7.4 Admin (platform: `super_admin`, `content_manager` for content metrics)

| Metric | Definition |
|---|---|
| DAU / WAU / MAU (learning) | Users with M5 > 0 (daily, 7-day, 30-day). Minors are counted, never profiled. |
| Learning time totals | Σ M5; median per active user |
| Content performance | Per course/lesson: completion rate, median M5, drop-off, item review flags |
| Ingest health | Events/s, rejection rate by code, duplicate %, late % (> 5 min), skew distribution, `seq_gap` %, builder lag (target < 2 min), daily job duration, partition headroom |
| Data-quality guards | % of user-days flagged `implausible`; M2/M1 ratio distribution (alert if the median moves > 20 % week on week, which suggests SDK regression) |
| Cohort benchmarks | Cross-org comparisons with k ≥ 20 |
| Product (P-purpose, adults with consent) | Route views, buffering ratio, error rates |

---

## 8. Data-quality tests (handed to QA Lead)

1. The union invariant: random multi-tab fixtures give `Σ attributed = |⋃|` and `≤ wall-clock`.
2. Retrying an identical batch 10× gives the same row counts (`duplicate` statuses).
3. A clock 3 h fast or slow on the client gives `effective_at` within 1 s of server time.
4. A late event (48 h) changes the D-2 aggregate after the dirty-day run; a 73 h event is rejected.
5. Examples 1–6 above are executable fixtures, and their expected values are golden values.
6. A minor fixture produces no P events, no feed rows and no route aggregates.

---

## 9. Limitations: what browser-based time cannot prove

State these to users, coordinators and in contracts. Do not over-claim.

1. **Attention.** A visible, focused tab with recent input does not prove the person was looking or learning. Mouse jigglers, auto-scrollers and a video playing to an empty room all earn M2 credit.
2. **Identity of the person.** Events prove that the *session* was active. They do not prove that the *account holder* was at the keyboard. Account sharing can only be inferred, never proven (security module).
3. **Integrity against a determined client.** Heartbeats are generated by code the user controls. Server caps (§5.5) bound the damage, roughly 1 s per wall-clock second per user per surface, but cannot stop a script that simulates input on a visible tab. **No grade, certificate or payment outcome may rest on time alone.**
4. **Offline and crash under-count.** Up to `F` seconds per crash and all time while the network is blocked beyond 72 h are lost. Strict corporate or college networks and ad blockers that block `/analytics/*` (same-origin reduces this) cause silent gaps.
5. **Reading without input.** Long thinking or reading pauses beyond `T_idle` are under-credited. The threshold is a disclosed trade-off, not a truth (Kovanović et al.).
6. **Background and multi-window viewing.** Visibility APIs report what the browser thinks. A window covered by another window can still be "visible", and multi-monitor setups vary.
7. **Mobile webviews and OS behaviour.** Page lifecycle events (`pagehide`, `freeze`) are unreliable on some Android webviews and iOS. Tab discarding and OS sleep can end sessions without a terminal event, which leads to grace-based closes.
8. **Video truth.** Coverage reflects player-reported playback ranges. It does not prove comprehension, and DRM players may report positions coarsely.
9. **Cross-platform comparability.** Our numbers are **not comparable** with Canvas "Total Activity", Moodle log-gap estimates or competitor claims. They are comparable only within the same `tm-*` version.
10. **Assessment time ≠ effort.** M4 is authoritative elapsed time from the server. It includes time away and says nothing about effort per question.

---

## 10. Data model requirements for Architect

- **DM-1.** `analytics_events` and `activity_heartbeats`: `PARTITION BY RANGE (event_ts)` monthly, PK `(event_id, event_ts)`, where `event_ts` is **derived from the event_id UUIDv7 timestamp** (CP-1). Columns as §4.2. No cross-partition FKs; entity columns are typed UUIDs without FK constraints. Heartbeats use narrow typed columns (no JSONB).
- **DM-2.** `engagement_intervals` is monthly-partitioned by `started_at`, has a partial index on open intervals, and carries the `measurement_version` column.
- **DM-3.** `daily_learning_aggregates` grain = user × IST date × (`entity_kind`, `entity_id`), unique on those 4 columns, plus `measurement_version`, `is_frozen` and `privacy_tier`.
- **DM-4.** Topic mapping is needed for attribution. Add `lesson_topics` (lesson_id, topic_id, is_primary) and ensure `question_tags` / `questions.primary_topic_id` exist. Placement category = the root node of `topics` (or an explicit `topics.category` enum). `lessons` needs `est_reading_minutes`, and `lesson_assets` needs `duration_s`.
- **DM-5.** A practice-answer store in `placement` (`practice_responses`: user, question_version, is_correct, attempt_no, served_at, answered_at, hint/solution flags). It is **not in the canonical list** (CP-3).
- **DM-6.** `test_attempts` must hold server `started_at`, `deadline_at`, `submitted_at`, `submit_reason`; `attempt_events` must record section entry with a server timestamp.
- **DM-7.** A transactional outbox table (`outbox_events`) shared by the domain modules, with a relay worker (CP-8).
- **DM-8.** `policy_settings` keys `analytics.tm.*`, `analytics.retention.*` and `analytics.k_min.*`.
- **DM-9.** `consents` purpose codes: `core_service` (item A, includes basic learning-progress analytics; replaces the notice-only `analytics_learning`), `analytics_personalisation` (item C, opt-in, default off), `analytics_product` (item H, opt-in, adults), `security_monitoring` (opt-in, adults) (CP-10). `users` needs the derived `privacy_tier`, available to ingest cheaply (cached).
- **DM-10.** RLS on all analytics tables with `organization_id`. Rows are org-scoped through the enrolment/entitlement context. D2C rows have `organization_id NULL`.
- **DM-11.** New tables (CP-2): `video_watch_coverage`, `weekly_learning_aggregates` (table, for RLS), `cohort_learning_aggregates`, `route_daily_aggregates`, `topic_mastery`, `question_item_stats`, `security_activity_feed_daily`, `analytics_dirty_days`, `analytics_ingest_rejections`.
- **DM-12.** A `privacy_provider` for the analytics module (export and delete per user), registered in the retention registry (research §Privacy plumbing).

## 11. Contract change proposals

Reconciled in `contract-reconciliation.md` §2.4; outcomes in the last column.

| ID | Proposal | Reason | Reconciliation outcome |
|---|---|---|---|
| **CP-1** | Partition key for the raw analytics tables = `event_ts`, derived from the UUIDv7 `event_id`, with PK `(event_id, event_ts)`. | Postgres unique indexes on partitioned tables must include the partition key. Deriving it from the ID makes retries land on the same key, so global idempotency works without a separate dedupe store. | → Accepted in brief v0.2 §1 |
| **CP-2** | Add the analytics tables in DM-11 to the canonical entity list (brief §4). | The 4 brief tables cannot hold coverage, cohort rollups, mastery, item stats or the security feed. | → Accepted-modified: all tables added; `weekly_learning_aggregates` is a table, not an MV |
| **CP-3** | Add `practice_responses` (placement) to the canonical list. | Practice answers have no home; `attempt_responses` is for tests only. | → Accepted (columns per DM-5) |
| **CP-4** | Exempt `POST /analytics/events` from the `Idempotency-Key` header rule. | Idempotency is per event via the client UUIDv7. | → Accepted in brief v0.2 §5 (also `/beacon`) |
| **CP-5** | CSRF variant for `/analytics/events/beacon`: accept a body-borne signed CSRF token + `Sec-Fetch-Site: same-origin`. The primary path stays `fetch(keepalive)` with headers. | `sendBeacon` cannot set custom headers. | → Accepted in brief v0.2 §5 |
| **CP-6** | Sessions module: analytics ingest requests touch the session idle timer **only** if the batch contains an engaged sample with `input_recent` or `media_playing`. Keepalives never extend the idle timeout. | Otherwise an idle open tab keeps a session alive indefinitely, which defeats the 60 min / 30 min idle timeouts (brief §1). | → Accepted in brief v0.2 §1 Timeouts |
| **CP-7** | `session.ended`, `account.restricted`, `consent.changed` and age-tier changes are published as internal domain events that analytics consumes. | Needed to close intervals and toggle purposes promptly. | → Accepted in brief v0.2 §2 (via `outbox_events`; `age_tier.changed`) |
| **CP-8** | Standardise a transactional outbox (`outbox_events`) for server-emitted domain events. | Server-authoritative analytics events must not be lost or double-emitted. | → Accepted (same as ARCH CCP-1) |
| **CP-9** | Analytics day boundary = **Asia/Kolkata** calendar day for all daily rollups. Storage remains UTC. | Indian users; matches coordinator reporting expectations. | → Accepted in brief v0.2 §4 |
| **CP-10** | Consent purpose codes `analytics_learning` (now `core_service` for basic progress and `analytics_personalisation` for item C), `analytics_product` and `security_monitoring`, with `security_monitoring` as a prerequisite for the §6.5 feed. | Itemised consent (brief §1 Privacy; DPDP Rule 3). | → Accepted-modified: canonical purposes in brief v0.2 §1 (`core_service`, `analytics_personalisation`, `analytics_product` = item H, `security_monitoring` = item B) |
| **CP-11** | `topic_mastery` is owned by `analytics` (computed); `placement` reads it through a service interface. | One writer per table; mastery is derived data. | → Accepted (one writer: `analytics`) |
| **CP-12** | Business rule for the Product Analyst: no completion, certificate or grade may depend on time thresholds alone. | Browser time is forgeable (§9). | → Accepted in brief v0.2 §1 (learning-evidence rule) |
