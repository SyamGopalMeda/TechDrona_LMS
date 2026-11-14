import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { UnblockRequestForm } from "@/features/unblock/components/UnblockRequestForm";
import { UnblockLookup } from "@/features/unblock/components/UnblockStatus";
import { APL_REF, SEC_REF } from "@/features/unblock/lib/copy";

export const metadata: Metadata = { title: "Request a review" };

/**
 * Unblock request (account-unblock-workflow §3; UNB-01) and status lookup by APL reference
 * (UNB-05/06). Requires the signed-in account holder (restricted / status-only scope); the
 * reference is never an authenticator.
 */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const caseRef = typeof sp.case_ref === "string" && SEC_REF.test(sp.case_ref) ? sp.case_ref : null;
  const reference = typeof sp.reference === "string" && APL_REF.test(sp.reference.toUpperCase()) ? sp.reference.toUpperCase() : null;
  return (
    <div className="mx-auto max-w-2xl space-y-10">
      <section aria-labelledby="form-h">
        <PageHeader title="Request a review" description="Tell us what happened. A person, not a computer, will look at it." />
        <h2 id="form-h" className="sr-only">
          Review request form
        </h2>
        <UnblockRequestForm caseRef={caseRef} />
      </section>
      <section id="status" aria-labelledby="status-h" className="space-y-3">
        <h2 id="status-h" className="font-display text-lg font-semibold text-fg">
          Check the status of a request
        </h2>
        <UnblockLookup initialReference={reference} />
      </section>
    </div>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/unblock-request/page.tsx#Page");
