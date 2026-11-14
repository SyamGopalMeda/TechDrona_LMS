import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { ResetPasswordForm } from "@/features/auth/components/PasswordRecovery";

export const metadata: Metadata = { title: "Reset password", referrer: "no-referrer" };

/** PUB-013 set a new password with the link token (AUTH-17). */
async function Page__server({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Choose a new password" description="You'll be signed out on all devices.">
      <ResetPasswordForm token={token} />
    </AuthCard>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/reset-password/[token]/page.tsx#Page");
