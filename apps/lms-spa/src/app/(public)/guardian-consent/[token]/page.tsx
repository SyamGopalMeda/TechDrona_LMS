import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { GuardianConsent } from "@/features/auth/components/GuardianConsent";

export const metadata: Metadata = { title: "Guardian consent", referrer: "no-referrer" };

/** PUB-015 guardian consent landing (AUTH-25/26/27). */
async function Page__server({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Parent or guardian consent">
      <GuardianConsent token={token} />
    </AuthCard>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/(public)/guardian-consent/[token]/page.tsx#Page");
