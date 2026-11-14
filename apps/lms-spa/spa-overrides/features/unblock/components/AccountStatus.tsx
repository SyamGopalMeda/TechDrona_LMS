"use client";

import Link from "next/link";
import { Badge, Card, ErrorState, Skeleton } from "@/components/ui";
import { formatDate, formatDateTime } from "@/features/auth/lib/format";
import { useAccountScope, type AccountScope } from "@/features/account/lib/account-scope";
import { useResource } from "@/features/account/lib/use-resource";
import type { MyCase, SecurityStatus } from "../lib/types";
import { RestrictedStatus, STUDENT_HOME } from "./RestrictedStatus";

/** verified: security/restrictions.py end_restriction callers (+ unblock.py reverify reasons). */
const END_REASON: Record<string, string> = {
  case_decision: "Ended after review",
  deescalated: "Lowered automatically",
  superseded: "Replaced by a newer restriction",
  takeover_recovered: "Ended after you secured your account",
  ended: "Ended",
};

/** verified: security/cases.py case.status values. */
const CASE_STATUS: Record<string, string> = {
  open: "Open",
  escalated: "Being reviewed by the security team",
  decided: "Decided",
  closed: "Closed",
};

/** SEC-02 case details for the student (decision summary and student-visible notes only). */
function CaseDetails({ caseRef }: { caseRef: string }) {
  const c = useResource<MyCase>(`me/security/cases/${encodeURIComponent(caseRef)}`, { handle: { restriction: false } });
  return (
    <Card title="Case details">
      {c.error ? (
        <ErrorState error={c.error} title="We couldn't load the case" onRetry={c.reload} />
      ) : !c.data ? (
        <div aria-busy="true">
          <span className="sr-only">Loading case…</span>
          <Skeleton className="h-16 w-full" />
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-fg-secondary">
            Status: <Badge tone={c.data.status === "closed" ? "neutral" : "info"}>{CASE_STATUS[c.data.status] ?? c.data.status.replace(/_/g, " ")}</Badge>
            {c.data.restriction?.state === "lift_pending" ? <span className="ml-2">Your access is being restored.</span> : null}
          </p>
          {c.data.decision ? (
            <div>
              <p className="font-medium text-fg">Decision · {formatDate(c.data.decision.decided_at)}</p>
              {c.data.decision.summary ? <p className="mt-0.5 text-fg-secondary">{c.data.decision.summary}</p> : null}
            </div>
          ) : null}
          {c.data.notes.length ? (
            <div>
              <p className="font-medium text-fg">Messages from the review team</p>
              <ul className="mt-1 space-y-2">
                {c.data.notes.map((n) => (
                  <li key={`${n.at}-${n.body.slice(0, 16)}`} className="rounded-md border border-line-subtle p-2">
                    <p className="text-xs text-fg-muted">{formatDateTime(n.at)}</p>
                    <p className="whitespace-pre-line text-fg-secondary">{n.body}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}

function Details(s: SecurityStatus, scope: AccountScope) {
  const history = s.history ?? [];
  const p = s.policy ?? {};
  const limits: [string, number | undefined][] = [
    ["Trusted devices", p.max_trusted_devices],
    ["Signed-in devices at once", p.max_concurrent_sessions],
    // Video playback is a student limit.
    ...(scope.student ? [["Videos playing at once", p.max_concurrent_streams] as [string, number | undefined]] : []),
    ["Device replacements per 30 days", p.max_replacements_per_30d],
  ];
  return (
    <>
      {s.case_ref ? <CaseDetails caseRef={s.case_ref} /> : null}
      <Card title="Account limits">
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {limits.map(([label, v]) => (
            <div key={String(label)}>
              <dt className="text-fg-muted">{label}</dt>
              <dd className="font-medium text-fg">{typeof v === "number" ? v : "—"}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-sm">
          <Link href="/legal/device-policy" className="text-fg-link underline">
            Device policy
          </Link>{" "}
          ·{" "}
          <Link href="/app/settings/devices" className="text-fg-link underline">
            Manage devices
          </Link>
        </p>
      </Card>
      <Card title="Past restrictions">
        {history.length === 0 ? (
          <p className="text-sm text-fg-muted">No past restrictions.</p>
        ) : (
          <ul className="divide-y divide-line-subtle text-sm" aria-label="Past restrictions">
            {history.map((h) => (
              <li key={`${h.starts_at}-${h.level}`} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:justify-between">
                <span className="text-fg">
                  Level {h.level} · {formatDate(h.starts_at)}
                  {h.ended_at ? ` – ${formatDate(h.ended_at)}` : ""}
                </span>
                <span className="text-fg-muted">{(h.end_reason && END_REASON[h.end_reason]) ?? h.end_reason?.replace(/_/g, " ") ?? ""}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <nav aria-label="Account status links" className="flex flex-wrap gap-4 text-sm">
        {/* Review requests and support tickets are student flows; for staff those routes bounce
            to their home portal (live audit staff-portals.md F4), so staff get their home instead. */}
        {scope.student ? (
          <>
            <Link href="/unblock-request#status" className="text-fg-link underline">
              Check a review request
            </Link>
            <Link href="/app/support/new" className="text-fg-link underline">
              Contact support
            </Link>
          </>
        ) : (
          <Link href={scope.home} className="text-fg-link underline">
            Back to {scope.homeTitle}
          </Link>
        )}
        <Link href="/app/settings/privacy" className="text-fg-link underline">
          Privacy requests
        </Link>
      </nav>
    </>
  );
}

/**
 * STU-026 account status inside the learner portal (target of the L3 login redirect and the
 * api's `status_url`). SEC-01 status panel (reasons, case reference, review request / reverify)
 * plus SEC-02 case details, the published limits and restriction history.
 */
export function AccountStatus() {
  const scope = useAccountScope();
  if (!scope) {
    return (
      <div aria-busy="true" className="space-y-3">
        <span className="sr-only">Loading your account status…</span>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  const home = scope.student ? STUDENT_HOME : { href: scope.home, label: `Go to ${scope.homeTitle}` };
  return <RestrictedStatus details={(s) => Details(s, scope)} home={home} />;
}
