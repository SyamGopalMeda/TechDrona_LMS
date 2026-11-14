import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import Link from "next/link";
import { RestrictedStatus } from "@/features/unblock/components/RestrictedStatus";
import { SEC_REF } from "@/features/unblock/lib/copy";

export const metadata: Metadata = { title: "Account status" };

/**
 * PUB-021 status-only page (L4) and target of the API client's `403 account_restricted`
 * redirect. The state is read from SEC-01; query values (from the problem body) are validated
 * and only used as a fallback reference while the status cannot be loaded.
 */
async function AccountRestrictedPage__server({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const raw = typeof sp.case_ref === "string" ? sp.case_ref : undefined;
  const caseRef = raw && SEC_REF.test(raw) ? raw : null;
  const levelNum = typeof sp.level === "string" ? Number.parseInt(sp.level, 10) : NaN;
  const level = Number.isInteger(levelNum) && levelNum >= 1 && levelNum <= 4 ? levelNum : null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Account status</p>
      <RestrictedStatus fallbackCaseRef={caseRef} fallbackLevel={level} />
      <nav aria-label="Account status links" className="flex flex-wrap gap-4 text-sm">
        <Link href="/unblock-request#status" className="text-fg-link underline">
          Check a review request
        </Link>
        <Link href="/help" className="text-fg-link underline">
          Help
        </Link>
        <Link href="/legal/privacy" className="text-fg-link underline">
          Privacy requests
        </Link>
      </nav>
    </div>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(AccountRestrictedPage__server, "app/(public)/account/restricted/page.tsx#AccountRestrictedPage");
