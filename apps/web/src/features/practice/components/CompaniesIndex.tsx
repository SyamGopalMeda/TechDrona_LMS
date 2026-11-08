"use client";

import Link from "next/link";
import { EmptyState, PageHeader } from "@/components/ui";

/**
 * Company paths index. Not available yet: the backend has no student-facing list of companies or
 * target-company readiness (only GET me/company-paths/{slug} and the staff-only studio/companies),
 * so we show an honest empty state and point to the public company hubs.
 */
export function CompaniesIndex() {
  return (
    <div>
      <PageHeader title="Company paths" description="Readiness for the companies you're preparing for." />
      <EmptyState
        title="Not available yet"
        description="A list of your target companies isn't available yet. Open a company hub to see its path and your readiness."
        action={<Link className="text-sm text-fg-link underline" href="/companies">Browse companies</Link>}
      />
    </div>
  );
}
