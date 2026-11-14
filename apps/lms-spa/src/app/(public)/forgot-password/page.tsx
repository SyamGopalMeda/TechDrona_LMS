import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { ForgotPasswordForm } from "@/features/auth/components/PasswordRecovery";

export const metadata: Metadata = { title: "Forgot password" };

/** PUB-013 recovery request (AUTH-16). */
export default function Page() {
  return (
    <AuthCard title="Reset your password" description="We'll help you get back into your account.">
      <ForgotPasswordForm />
    </AuthCard>
  );
}
