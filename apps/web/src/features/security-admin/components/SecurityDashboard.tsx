"use client";

import Link from "next/link";
import { ErrorState, PageHeader, Skeleton, StatTile } from "@/components/ui";
import { textLink } from "@/features/admin/components/console-ui";
import { humanize } from "@/features/admin/lib/console";
import { useResource } from "@/features/account/lib/use-resource";
import { SECTION_H_REPORTS } from "../lib/catalogue";
import type { SecurityDashboardData } from "../lib/types";
import { EngineControls } from "./EngineControls";

const n = (v: number | undefined) => (typeof v === "number" ? v.toLocaleString("en-IN") : "0");

function Tiles({ title, id, entries, empty }: { title: string; id: string; entries: [string, number][]; empty: string }) {
  return (
    <section aria-labelledby={id} className="mb-6">
      <h2 id={id} className="mb-2 font-display text-base font-semibold text-fg">
        {title}
      </h2>
      {entries.length ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {entries.map(([k, v]) => (
            <StatTile key={k} label={humanize(k)} value={n(v)} />
          ))}
        </div>
      ) : (
        <p className="text-sm text-fg-muted">{empty}</p>
      )}
    </section>
  );
}

/**
 * SEC-001 account-security dashboard. Tiles come from SEC-40 `GET /security/dashboard`
 * (verified: api_engine.py dashboard → queue by status, active restrictions by level,
 * pending unblock requests, engine state). Engine state + kill switch is EngineControls.
 */
export function SecurityDashboard() {
  const res = useResource<SecurityDashboardData>("security/dashboard");
  const d = res.data;
  return (
    <div>
      <PageHeader eyebrow="SEC-001" title="Account security" description="Queue health, restrictions, appeals, engine state and Section H reports." />
      <EngineControls />
      {res.error ? (
        <ErrorState error={res.error} title="Could not load the dashboard" onRetry={() => void res.reload()} />
      ) : !d ? (
        <div aria-busy="true" className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <span className="sr-only">Loading dashboard</span>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : (
        <>
          <Tiles id="queue-h" title="H1 queue (open cases by status)" entries={Object.entries(d.queue ?? {})} empty="No open cases." />
          <Tiles
            id="restr-h"
            title="Active restrictions by level"
            entries={Object.entries(d.restrictions ?? {}).sort(([a], [b]) => a.localeCompare(b))}
            empty="No active restrictions."
          />
          <section aria-labelledby="appeals-h" className="mb-6">
            <h2 id="appeals-h" className="mb-2 font-display text-base font-semibold text-fg">
              Appeals
            </h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Pending unblock requests" value={n(d.pending_unblock_requests)} />
            </div>
          </section>
        </>
      )}
      <nav aria-label="Security console" className="mb-6 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <Link className={textLink} href="/security/cases">
          Open the queue
        </Link>
        <Link className={textLink} href="/security/unblock-requests">
          Unblock requests
        </Link>
        <Link className={textLink} href="/security/restrictions">
          Restrictions and bulk lifts
        </Link>
        <Link className={textLink} href="/security/incidents">
          Incidents
        </Link>
      </nav>
      <section aria-labelledby="reports-h">
        <h2 id="reports-h" className="mb-2 font-display text-base font-semibold text-fg">
          Reports
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {SECTION_H_REPORTS.map((r) => (
            <li key={r.key} className="rounded-lg border border-line bg-surface p-3 text-sm">
              <span className="mr-2 font-mono text-xs text-fg-muted">{r.code}</span>
              <Link className={textLink} href={`/security/reports/${r.key}`}>
                {r.title}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
