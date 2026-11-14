import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { VerifyEmail } from "@/features/auth/components/Verification";

export const metadata: Metadata = { title: "Verify email", referrer: "no-referrer" };

/** PUB-014 email verification (AUTH-02). */
async function Page__server({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Verify your email">
      <VerifyEmail token={token} />
    </AuthCard>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/verify/email/[token]/page.tsx#Page");
