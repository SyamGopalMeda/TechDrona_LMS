# ADR-0007: Video delivery — VdoCipher DRM + dynamic watermark, stream cap at OTP issuance

* **Status:** Accepted (Brief §1) — implementation **Planned**
* **Related:** `system-architecture.md §12`, `database-schema.md §4` (`playback_sessions`)

## Context

Paid video is the main content asset; competitors face complaints about buffering (research §4). The device policy caps concurrent video streams at 1 (Brief §1). "DRM blocks downloading, and the watermark deters and traces" [Reported, vendor]; an iframe embed cannot show the user ID (research §3 [Verified]). Videos must not be stored in Postgres; logs stay in India.

## Decision

* Host and stream videos on VdoCipher (Widevine/FairPlay). Store only `lesson_assets.provider_asset_id` and metadata.
* Playback requires a server-minted OTP (`ttl=300`) issued by `POST /api/v1/media/playback` after `require_active_principal`, feature-restriction check and entitlement check.
* **Stream cap enforced at OTP issuance:** advisory lock per user, count `playback_sessions` with a heartbeat in the last 90 s, refuse or offer takeover at cap. Heartbeats every 30 s keep sessions alive and report progress; revoked sessions instruct the player to stop.
* Dynamic watermark: masked name + masked phone/email + short user id + timestamp, moving, low opacity, rendered via the VdoCipher JS API (not a bare iframe).
* Non-video files: private S3 + CloudFront OAC + 5-minute signed URLs; malware scan on upload.

## Alternatives considered

| Option | Why not |
|---|---|
| AWS MediaConvert + MediaPackage + SPEKE DRM | Full control but significant build/ops effort and DRM licensing for a small team. |
| Mux / Gumlet / Cloudflare Stream | Comparable; VdoCipher chosen by product owner for India focus, watermark and pricing ("from $149/year" [Reported]). |
| Unprotected HLS with signed URLs | Trivially downloadable; no deterrence for sharing. |

## Consequences

* (+) Strong download protection with low engineering cost; CDN handles 5k concurrent streams.
* (+) Stream cap is deterministic and minor-safe.
* (−) An already-licensed stream cannot be killed server-side; cap relies on OTP issuance + cooperative player stop + short TTL. Verify VdoCipher licence-duration/concurrency options.
* (−) Vendor lock-in for video library; export rights and residency of VdoCipher logs need contractual confirmation.
