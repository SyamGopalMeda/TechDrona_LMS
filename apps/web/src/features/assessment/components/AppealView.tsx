"use client";

import Link from "next/link";
import { Card, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { LinkButton } from "@/features/catalog/components/LinkButton";
import { assessmentApi } from "../lib/api";
import { formatIstDateTime } from "../lib/format";
import { useLoader } from "../lib/use-resource";

/** Support ticket prefilled for an assessment appeal (same target as the invalidation notice). */
export function appealTicketHref(attemptId: string): string {
  const qs = new URLSearchParams({ topic: "assessment", attempt_id: attemptId, from: `/app/attempts/${attemptId}/appeal` });
  return `/app/support/new?${qs.toString()}`;
}

/**
 * Appeal an invalidated attempt (FR-ASM-012). There is no dedicated appeal API: appeals are
 * handled as an "assessment" support ticket that carries the attempt reference, the same route
 * the invalidation notification links to (assessments/integrity.py).
 */
export function AppealView({ attemptId }: { attemptId: string }) {
  const res = useLoader(attemptId, () => assessmentApi.result(attemptId));
  const back = (
    <Link className="text-sm text-fg-link underline" href="/app/tests">
      Back to tests
    </Link>
  );

  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data)
    return (
      <div aria-busy="true" className="space-y-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-32 w-full" />
      </div>
    );

  const r = res.data;
  if (r.status !== "invalidated") {
    return (
      <div>
        <PageHeader title="Appeal a test decision" actions={back} />
        <EmptyState
          title="There is nothing to appeal for this attempt"
          description="Only attempts that were invalidated after review can be appealed."
        />
      </div>
    );
  }

  return (
    <div className="max-w-prose">
      <PageHeader title="Appeal a test decision" description="Your attempt was invalidated after an integrity review." actions={back} />
      <Card title="How appeals work">
        <ol className="list-decimal space-y-2 pl-5 text-sm text-fg-secondary">
          <li>Open a support ticket with the topic “Assessment”. This attempt’s reference is attached for you.</li>
          <li>Explain what happened during the test and add anything that helps the reviewer.</li>
          <li>The team reviews your appeal and replies on the ticket. You can follow it under Support.</li>
        </ol>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-fg-muted">Attempt</dt>
          <dd className="break-all font-mono text-xs">{r.attempt_id}</dd>
          {r.submitted_at ? (
            <>
              <dt className="text-fg-muted">Submitted</dt>
              <dd>{formatIstDateTime(r.submitted_at)}</dd>
            </>
          ) : null}
        </dl>
        <div className="mt-5">
          <LinkButton href={appealTicketHref(r.attempt_id)}>Start an appeal</LinkButton>
        </div>
      </Card>
    </div>
  );
}
