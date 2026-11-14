import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthCard } from "@/features/auth/components/shared";
import { AcceptTerms } from "@/features/account/components/AcceptTerms";
import { safeNextPath } from "@/features/auth/lib/validation";
import { STAFF_LANDING } from "@/features/auth/lib/login-flow";
import { ACCEPT_TERMS_PATH } from "@/lib/api/client";
import { hasSessionCookie } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Accept the terms", robots: { index: false, follow: false } };

/** Target of `403 consent_required` for the required purposes (new admin-created accounts). */
export default async function AcceptTermsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  let next = safeNextPath(typeof sp.next === "string" ? sp.next : undefined, STAFF_LANDING);
  if (next.split("?")[0] === ACCEPT_TERMS_PATH) next = STAFF_LANDING;
  if (!(await hasSessionCookie())) redirect(`/login?next=${encodeURIComponent(ACCEPT_TERMS_PATH)}`);
  return (
    <AuthCard title="One last step" description="Please agree to the Terms of Use and Privacy Notice to start using Tech Drona.">
      <AcceptTerms next={next} />
    </AuthCard>
  );
}
