# ADR-0013: Assessment engine — server-authoritative timer, frozen layouts, ≤10 s autosave

* **Status:** Accepted (task brief requirements) — implementation **Planned**
* **Related:** `system-architecture.md §8`, `database-schema.md §9`
* **Revision:** v0.4 (2026-11-03, Integration Lead): autosave ceiling 10 s (Brief v0.3 §1, API I-17); attempt binding, same-device re-attach and idle hold (CPR-BRF-04, CPR-ARC-04, CPR-SCH-03/06) — `contract-reconciliation.md` §9

## Context

Placement mocks and drives must survive Indian campus Wi-Fi drops and power cuts, resist client-side timer and answer-key tampering, and support disputes and regrading. Moodle autosaves every 60 s and keeps attempt state server-side; it calls the interval a trade-off between server load and lost work (research §2, §6 [Verified]). A competitor's resume bug lost answers (research §6 [Reported]).

## Decision

* **Frozen layout:** question selection happens once at start with a stored seed; the ordered `question_version_id`s and option orders are stored on the attempt. Questions are immutable versions.
* **Server timer:** `deadline_at` computed server-side (duration + overrides, bounded by window); every response carries `server_now` and deadlines; writes after `deadline + grace` are rejected; Redis ZSET sweeper (5 s) + DB sweeper (60 s) auto-submit.
* **Autosave:** IndexedDB write on every change; network flush after 5 s debounce, at most 10 s after the first unsynced change, and on `pagehide`; server upsert guarded by monotonically increasing `client_seq` (idempotent, order-safe); history in partitioned `attempt_events`.
* **Resume:** state endpoint returns layout (keys stripped), saved responses and deadlines; client merges newer IndexedDB entries. Disconnects are logged events, not penalties.
* **Scoring:** server-side only, asynchronous, idempotent per `scoring_version`; rank/percentile provisional until window close.
* **Keys:** never in delivery DTOs or caches; review endpoints apply the 4-phase review policy server-side.
* **One active session per attempt** (`test_attempts.bound_session_id`/`bound_device_id`): another session gets `409 attempt_bound_elsewhere` and may rebind after explicit confirmation (OTP at ≥ L2, max 2 rebinds; events `rebind_requested`/`rebind`/`rebind_refused`). Re-login on the same device re-attaches without consuming a rebind (`reattach_same_device`). No Redis takeover lock. The bound session holds `idle_hold_until = deadline_at + grace + 5 min`; a start whose session would expire earlier returns `409 session_too_short_for_attempt` (v0.4).

## Alternatives considered

| Option | Why not |
|---|---|
| Moodle-style 60 s autosave | Up to a minute of lost work per crash; research recommends 5–10 s. |
| Client timer with server check at submit | Tamperable; disputes unresolvable. |
| Write-behind autosave to Redis only | Lower DB load but risk of loss on Redis failover; DB writes at ≤ ~400/s are well within capacity. |
| WebSocket-based sync | More infra (sticky connections) for marginal gain; HTTP + IndexedDB is simpler and works through captive portals. |

## Consequences

* (+) At most ~10 s of unsynced work at risk, usually zero thanks to IndexedDB; full dispute/regrade traceability.
* (−) Higher write volume than Moodle; partitioning and single-row upserts keep it cheap.
* (−) Offline-tolerant clients must handle "attempt closed" conflicts gracefully in UX.
