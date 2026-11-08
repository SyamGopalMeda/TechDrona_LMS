# ADR-0012: Identifiers (UUIDv7), time (UTC timestamptz) and money (integer paise)

* **Status:** Accepted (Brief §4 "id UUID (v7 preferred)") — implementation **Planned**
* **Related:** `database-schema.md §1.1`

## Context

Tables need globally unique ids that are safe to expose in URLs, generated without DB round trips, and index-friendly. PostgreSQL 16 has no native UUIDv7 generator. Money calculations must be exact for GST invoices.

## Decision

* **IDs:** UUIDv7 generated in the application (`uuid_utils.uuid7()` in Python; `uuidv7` npm in the BFF where needed). Time-ordered → good B-tree locality. Analytics events use client-generated UUIDv7 as dedupe keys. Human-facing numbers (order, invoice, case, ticket, certificate codes) are separate unique columns.
* **Time:** `timestamptz` in UTC everywhere; IST conversion only at presentation and for "calendar day" aggregates (`activity_date` in IST). Servers use Amazon Time Sync (CERT-In NTP requirement).
* **Money:** `bigint` paise, `char(3)` currency fixed to `INR` in v1; GST rounding per line item (half-up to paise) in a single `core.money` module with property-based tests.

## Alternatives considered

| Option | Why not |
|---|---|
| bigint identity ids | Enumerable/guessable in URLs; cross-system merges harder. |
| UUIDv4 | Random → index bloat and poor locality on hot tables. |
| `numeric` rupees | Works, but integer paise avoids accidental float conversions in Python/TS. |

## Consequences

* (+) Ids sortable by creation time; no DB sequence contention.
* (−) UUIDv7 leaks approximate creation time — acceptable; never use ids as secrets.
* (−) Upgrade to PostgreSQL 18 `uuidv7()` defaults can be adopted later without data change.
