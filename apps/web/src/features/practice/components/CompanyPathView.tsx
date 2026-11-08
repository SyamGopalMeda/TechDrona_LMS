"use client";

import Link from "next/link";
import { Button, Card, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { formatPercent } from "@/features/assessment/lib/format";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { practiceApi } from "../lib/api";
import type { CompanyPathStep } from "../lib/types";
import { useStartPractice } from "./PracticeHub";
import { isEntitlementError, PaywallCard } from "./shared";

const KIND: Record<string, string> = { practice_set: "Practice set", test: "Mock test", coding_set: "Coding set", lesson: "Lesson" };

function stepHref(s: CompanyPathStep): string | null {
  if (s.step_type === "test" && s.test_id) return `/app/tests/${encodeURIComponent(s.test_id)}`;
  return null;
}

/** PRC-005 company path (PLC-32): one card per published role path with its steps, pattern and readiness. */
export function CompanyPathView({ slug }: { slug: string }) {
  const res = useLoader(slug, () => practiceApi.companyPath(slug));
  const { start, starting, error } = useStartPractice();
  if (res.error) return isEntitlementError(res.error) ? <PaywallCard error={res.error} /> : <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data)
    return (
      <div aria-busy="true" className="space-y-3">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  const { company, paths } = res.data;

  return (
    <div>
      <PageHeader eyebrow="Company path" title={company.name} description={company.industry ?? undefined} />
      {error ? <div className="mb-4">{isEntitlementError(error) ? <PaywallCard error={error} /> : <ErrorState error={error} />}</div> : null}
      <div className="space-y-8">
        {paths.map((p) => (
          <div key={p.id} className="grid gap-6 lg:grid-cols-[2fr_1fr]">
            <Card title={`${p.role_name} path`}>
              <ol className="space-y-2">
                {p.steps.map((s, i) => {
                  const href = stepHref(s);
                  return (
                    <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line p-3">
                      <div>
                        <p className="text-xs text-fg-muted">
                          Step {i + 1} · {KIND[s.step_type] ?? s.step_type}
                          {s.is_required ? "" : " · Optional"}
                        </p>
                        {href ? (
                          <Link className="font-medium text-fg-link underline" href={href}>
                            {s.title}
                          </Link>
                        ) : (
                          <p className="font-medium text-fg">{s.title}</p>
                        )}
                      </div>
                      {s.step_type === "practice_set" ? (
                        <Button size="sm" variant="secondary" loading={starting} onClick={() => void start({ mode: "company_step", company_path_step_id: s.id })}>
                          Practise
                        </Button>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            </Card>
            <div className="space-y-6">
              <Card title={`Readiness for ${company.name}`}>
                {p.readiness.score_pct === null ? (
                  <p className="text-sm text-fg-secondary">Practise this company&apos;s topics to see your readiness.</p>
                ) : (
                  <p className="font-display text-3xl font-bold tabular-nums">{formatPercent(p.readiness.score_pct)}</p>
                )}
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer text-fg-link">Method</summary>
                  <p className="mt-1 text-fg-secondary">
                    {p.readiness.formula} ({p.readiness.method}).
                  </p>
                </details>
              </Card>
              {p.pattern.length ? (
                <Card title="Exam pattern">
                  <ul className="space-y-1 text-sm">
                    {p.pattern.map((sec, i) => (
                      <li key={i} className="flex justify-between gap-2">
                        <span>{sec.section}</span>
                        <span className="tabular-nums text-fg-muted">
                          {[sec.question_count ? `${sec.question_count} Qs` : null, sec.minutes ? `${sec.minutes} min` : null].filter(Boolean).join(" · ") || "—"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
