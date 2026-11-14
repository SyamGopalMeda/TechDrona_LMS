"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { LMS_COURSES_HREF } from "@/lib/site/website";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { practiceApi } from "../lib/api";
import type { MasteryBand, PracticeStartBody } from "../lib/types";

const BAND: Record<string, { label: string; cls: string }> = {
  insufficient_data: { label: "Insufficient data", cls: "border border-dashed border-line-strong bg-surface text-fg-secondary" },
  beginner: { label: "Beginner", cls: "bg-chart-band-1 text-fg" },
  developing: { label: "Developing", cls: "bg-chart-band-2 text-fg" },
  proficient: { label: "Proficient", cls: "bg-chart-band-3 text-fg" },
  mastered: { label: "Mastered", cls: "bg-chart-band-4 text-brand-on" },
};

/** Mastery band chip (design-system §5.14): ordinal indigo bands, always labelled — never traffic lights. */
export function MasteryChip({ band }: { band: MasteryBand }) {
  const b = BAND[band] ?? { label: band, cls: "bg-surface-sunken text-fg-secondary" };
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", b.cls)}>{b.label}</span>;
}

/** "R" entitlement state: paywall card from a 403 entitlement_required problem. */
export function PaywallCard({ error }: { error: unknown }) {
  const detail = isApiError(error) ? error.detail : null;
  return (
    <Card>
      <p className="font-semibold text-fg">This is part of a paid plan</p>
      <p className="mt-1 text-sm text-fg-muted">{detail ?? "Get a plan or path to unlock it."}</p>
      <Link className="mt-3 inline-block text-sm font-medium text-fg-link underline" href={LMS_COURSES_HREF}>
        Explore courses and plans
      </Link>
    </Card>
  );
}

export function isEntitlementError(e: unknown): boolean {
  return isApiError(e) && e.code === "entitlement_required";
}

/** PLC-26 "Next best practice" (≤ 5) with "why recommended"; dismissible (PLC-27). */
export function RecommendationsPanel({
  onStart,
  topicName,
}: {
  onStart?: (start: PracticeStartBody) => void;
  /** Resolves a recommendation's target topic id to a display name (the API returns ids only). */
  topicName?: (topicId: string) => string | undefined;
}) {
  const res = useLoader("recs", () => practiceApi.recommendations());
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const items = (res.data?.items ?? []).filter((r) => !hidden.has(r.id)).slice(0, 5);

  return (
    <Card title="Recommended next">
      {res.error ? (
        <ErrorState error={res.error} onRetry={() => void res.reload()} />
      ) : res.loading && !res.data ? (
        <div aria-busy="true" className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon="chart"
          title="No recommendations yet"
          description={
            res.data && !res.data.personalised
              ? "Personalised suggestions are off. Turn on personalisation in your privacy settings to get them."
              : "Answer a few practice sets and we'll suggest what to work on next."
          }
        />
      ) : (
        <ul className="space-y-3">
          {items.map((r) => (
            <li key={r.id} className="rounded-lg border border-line p-3">
              <p className="font-medium text-fg">{(r.target_type === "topic" && topicName?.(r.target_id)) || "Practise a weak topic"}</p>
              <p className="mt-0.5 text-sm text-fg-muted">Why: {r.why_recommended}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {r.target_type === "topic" && onStart ? (
                  <Button size="sm" onClick={() => onStart({ mode: "topic_set", topic_id: r.target_id })}>
                    Practise
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setHidden((h) => new Set(h).add(r.id));
                    void practiceApi.dismissRecommendation(r.id).catch(() => undefined);
                  }}
                >
                  Dismiss
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
