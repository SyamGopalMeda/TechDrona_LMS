"use client";

import Link from "next/link";
import { Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { formatDateTime, formatMoney } from "@/features/catalog/lib/format";
import { LinkButton } from "@/features/catalog/components/LinkButton";

interface PurchaseOption {
  sku?: string;
  price_id?: string;
  total_paise?: number;
  name?: string;
}

/** L state: skeleton matching a list/card layout; the region is aria-busy. */
export function LoadingBlock({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div aria-busy="true" aria-label={label} role="status" className="space-y-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  );
}

/**
 * Maps a failed content request to the standard states (design-system §5.15):
 * R (entitlement) paywall with the upsell hint, B (restricted) card, R (permission),
 * not found, otherwise X with the request id and retry.
 */
export function ContentErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (isApiError(error)) {
    const p = error.problem;
    if (error.code === "entitlement_required") {
      const options = (Array.isArray(p?.purchase_options) ? p.purchase_options : []) as PurchaseOption[];
      return (
        <Card title="This content needs access">
          <p className="text-sm text-fg-secondary">{p?.detail ?? "Your current plan doesn't include this content."}</p>
          {options.length ? (
            <ul className="mt-3 flex flex-wrap gap-2" aria-label="Ways to get access">
              {options
                .filter((o) => o.price_id)
                .map((o) => (
                  <li key={o.price_id}>
                    <LinkButton href={`/app/checkout/new?price_id=${encodeURIComponent(o.price_id!)}`} size="sm">
                      {o.name ?? o.sku ?? "Get access"}
                      {typeof o.total_paise === "number" ? ` · ${formatMoney(o.total_paise)}` : ""}
                    </LinkButton>
                  </li>
                ))}
            </ul>
          ) : null}
          <p className="mt-3 text-sm">
            <Link href="/pricing" className="font-medium text-fg-link hover:text-fg-link-hover">
              See all plans
            </Link>
          </p>
        </Card>
      );
    }
    if (error.code === "account_restricted") {
      return (
        <Card title="Learning access paused">
          <p className="text-sm text-fg-secondary">
            {p?.until ? `Learning access is paused until ${formatDateTime(p.until)}.` : p?.detail ?? "Learning access is paused on this account."}
            {p?.case_ref ? ` Case reference ${p.case_ref}.` : ""}
          </p>
          <LinkButton href="/app/account-status" variant="secondary" size="sm" className="mt-3">
            See details
          </LinkButton>
        </Card>
      );
    }
    if (error.code === "device_verification_required") {
      return (
        <Card title="Confirm it's you on this device">
          <p className="text-sm text-fg-secondary">{p?.detail ?? "Confirm this device before continuing."}</p>
          <LinkButton href="/app/settings/devices" variant="secondary" size="sm" className="mt-3">
            Review devices
          </LinkButton>
        </Card>
      );
    }
    if (error.status === 403) {
      return (
        <EmptyState
          title="You don't have access to this page"
          description="If you think you should, ask your trainer or contact support."
          action={<LinkButton href="/app/support" variant="secondary" size="sm">Contact support</LinkButton>}
        />
      );
    }
    if (error.status === 404) {
      return <EmptyState title="We couldn't find this" description="It may have been removed or the link is wrong." action={<LinkButton href="/app/learning" variant="secondary" size="sm">My learning</LinkButton>} />;
    }
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
