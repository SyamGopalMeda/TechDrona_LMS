"use client";

import Link from "next/link";
import { EmptyState, ErrorState, LoadingBlock, PageHeader, SectionHeader, StatGrid, StatTile, statusLabel } from "@/components/ui";
import { textLink } from "@/features/admin/components/console-ui";
import { useResource } from "@/features/account/lib/use-resource";
import { SECTION_H_REPORTS } from "../lib/catalogue";
import type { SecurityDashboardData } from "../lib/types";
import { EngineControls } from "./EngineControls";
import { levelText, toLevel } from "./RiskLevel";

const n = (v: number | undefined) => (typeof v === "number" ? v.toLocaleString("en-IN") : "0");

/** Case statuses that need a reviewer's attention when the count is above 0. */
const ATTENTION_STATUSES = new Set(["open", "escalated"]);

/** Readable label for a queue status key ("under_review" → "Under review"). */
function queueLabel(status: string): string {
  return statusLabel(status);
}

/**
 * Account-security dashboard. Tiles come from `GET /security/dashboard` (verified:
 * api_engine.py dashboard → queue by status, active restrictions by level, pending unblock
 * requests, engine state). Engine state and the kill switch are in EngineControls.
 */
export function SecurityDashboard() {
  const res = useResource<SecurityDashboardData>("security/dashboard");
  const d = res.data;
  const queue = Object.entries(d?.queue ?? {});
  const restrictions = Object.entries(d?.restrictions ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <div>
      <PageHeader title="Security overview" description="Open cases, active restrictions, unblock requests and the state of the risk engine." />
      {res.error ? (
        <ErrorState error={res.error} title="Could not load the dashboard" onRetry={() => void res.reload()} />
      ) : !d ? (
        <LoadingBlock label="Loading dashboard…" rows={4} size="card" className="mb-6" />
      ) : (
        <div className="mb-8 space-y-8">
          <section aria-labelledby="queue-h">
            <SectionHeader id="queue-h" title="Open cases" description="Cases waiting for a reviewer, by status." />
            {queue.length ? (
              <StatGrid>
                {queue.map(([k, v]) => (
                  <StatTile
                    key={k}
                    label={queueLabel(k)}
                    value={n(v)}
                    href={`/security/cases?status=${encodeURIComponent(k)}`}
                    tone={v > 0 && ATTENTION_STATUSES.has(k) ? (k === "escalated" ? "danger" : "warning") : "neutral"}
                  />
                ))}
                <StatTile
                  label="Pending unblock requests"
                  value={n(d.pending_unblock_requests)}
                  href="/security/unblock-requests"
                  tone={(d.pending_unblock_requests ?? 0) > 0 ? "warning" : "neutral"}
                />
              </StatGrid>
            ) : (
              <EmptyState
                variant="inline"
                icon="check"
                title="No open cases"
                description="Nothing is waiting for review."
                action={
                  <Link className={`${textLink} inline-flex min-h-touch items-center`} href="/security/unblock-requests">
                    Check unblock requests ({n(d.pending_unblock_requests)})
                  </Link>
                }
              />
            )}
          </section>
          <section aria-labelledby="restr-h">
            <SectionHeader id="restr-h" title="Active restrictions" description="Accounts currently limited, by level." />
            {restrictions.length ? (
              <StatGrid>
                {restrictions.map(([k, v]) => {
                  const lv = toLevel(k);
                  return (
                    <StatTile
                      key={k}
                      label={levelText(k)}
                      value={n(v)}
                      href="/security/restrictions"
                      tone={v > 0 && lv !== null && lv >= 4 ? "danger" : v > 0 && lv !== null && lv >= 3 ? "warning" : "neutral"}
                    />
                  );
                })}
              </StatGrid>
            ) : (
              <EmptyState variant="inline" icon="shield" title="No active restrictions" description="No account is limited right now." />
            )}
          </section>
        </div>
      )}
      <section aria-labelledby="engine-h" className="mb-8">
        <SectionHeader id="engine-h" title="Risk engine" description="Whether automatic protections are acting on accounts or only watching." />
        <EngineControls />
      </section>
      <nav aria-label="Security console" className="mb-8 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <Link className={`${textLink} inline-flex min-h-touch items-center`} href="/security/cases">
          Case queue
        </Link>
        <Link className={`${textLink} inline-flex min-h-touch items-center`} href="/security/unblock-requests">
          Unblock requests
        </Link>
        <Link className={`${textLink} inline-flex min-h-touch items-center`} href="/security/restrictions">
          Restrictions and bulk lifts
        </Link>
        <Link className={`${textLink} inline-flex min-h-touch items-center`} href="/security/incidents">
          Incidents
        </Link>
      </nav>
      <section aria-labelledby="reports-h">
        <SectionHeader id="reports-h" title="Reports" />
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {SECTION_H_REPORTS.map((r) => (
            <li key={r.key} className="rounded-lg border border-line bg-surface p-3 text-sm">
              <Link className={`${textLink} inline-flex min-h-6 items-center`} href={`/security/reports/${r.key}`}>
                {r.title}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
