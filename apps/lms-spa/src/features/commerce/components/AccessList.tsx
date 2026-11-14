"use client";

import Link from "next/link";
import { Card, EmptyState, LoadingBlock, StatusBadge, buttonClasses } from "@/components/ui";
import { LMS_COURSES_HREF } from "@/lib/site/website";
import { humanize } from "@/features/catalog/lib/format";
import { ContentErrorState } from "@/features/learning/components/States";
import type { EntitlementDto, EntitlementsResponse } from "../lib/types";
import { formatDate } from "@/lib/format";
import { useResource } from "@/lib/api/use-resource";

const SOURCE: Record<string, string> = {
  placement_package: "Placement package",
  subscription: "Subscription",
  purchase: "Purchase",
  coupon: "Coupon",
  admin_grant: "Granted by Tech Drona",
  trial: "Trial",
  free_enrolment: "Free enrolment",
};

/** Known access keys the api may send as a title; anything else that looks like a key is humanised. */
const KEY_TITLES: Record<string, string> = {
  all_practice: "All practice questions",
};

/** A readable title: API titles pass through, raw keys ("all_practice") never reach students. */
export function accessTitle(title: string | null | undefined, sourceType: string): string {
  if (!title) return humanize(sourceType);
  if (/^[a-z0-9]+(_[a-z0-9]+)+$/.test(title)) return KEY_TITLES[title] ?? humanize(title);
  return title;
}

function Quotas({ quotas }: { quotas: EntitlementDto["quotas"] }) {
  const entries = Object.entries(quotas ?? {}).filter(([, v]) => typeof v === "number");
  if (!entries.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-2 text-xs text-fg-secondary">
      {entries.map(([k, v]) => (
        <li key={k} className="rounded-full bg-surface-sunken px-2 py-0.5">
          {humanize(k.replace(/_remaining$/, ""))}: {v} left
        </li>
      ))}
    </ul>
  );
}

/** STU-019 "What I have access to" (ENT-03). */
export function AccessList() {
  const { data, error, loading, reload } = useResource<EntitlementsResponse>("me/entitlements");
  if (error) return <ContentErrorState error={error} onRetry={reload} />;
  if (loading && !data) return <LoadingBlock label="Loading your access" size="card" />;
  const rows = data?.data ?? [];
  return (
    <div className="space-y-4">
      {data?.restriction_gate?.active ? (
        <p role="alert" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          Learning access is paused on this account. Your access dates below are unchanged.{" "}
          <Link href="/app/account-status" className="font-medium underline">
            See details
          </Link>
        </p>
      ) : null}
      {rows.length === 0 ? (
        <EmptyState icon="lock" title="Nothing here yet" description="Free courses and anything you buy or are granted appear here." action={<Link href={LMS_COURSES_HREF} className={buttonClasses({ variant: "secondary", size: "sm" })}>Explore courses</Link>} />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2" aria-label="Your access">
          {rows.map((e) => {
            const status = e.effective_status ?? e.status;
            return (
            <li key={e.entitlement_id}>
              <Card>
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-display text-base font-semibold text-fg">{accessTitle(e.title, e.source_type)}</h2>
                  <StatusBadge status={status} label={status === "grace" ? "Payment due" : humanize(status)} />
                </div>
                <p className="mt-1 text-sm text-fg-secondary">
                  {SOURCE[e.source_type] ?? humanize(e.source_type)}
                  {e.source_ref ? <span className="font-mono text-xs text-fg-muted"> · {e.source_ref}</span> : null}
                </p>
                <p className="mt-1 text-sm text-fg-secondary">{e.ends_at ? `Until ${formatDate(e.ends_at)}` : "No end date"}</p>
                {status === "grace" && e.grace_ends_at ? (
                  <p className="mt-1 text-sm text-warning-fg">
                    Renewal payment failed. Update your payment method by {formatDate(e.grace_ends_at)} to keep access.{" "}
                    <Link href="/app/billing" className="font-medium underline">
                      Billing
                    </Link>
                  </p>
                ) : null}
                <Quotas quotas={e.quotas} />
              </Card>
            </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
