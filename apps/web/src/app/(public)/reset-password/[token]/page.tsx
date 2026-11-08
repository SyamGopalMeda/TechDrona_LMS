import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { ResetPasswordForm } from "@/features/auth/components/PasswordRecovery";

export const metadata: Metadata = { title: "Reset password", referrer: "no-referrer" };

/** PUB-013 set a new password with the link token (AUTH-17). */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Choose a new password" description="You'll be signed out on all devices.">
      <ResetPasswordForm token={token} />
    </AuthCard>
  );
}
