import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { MfaForm } from "@/features/auth/components/MfaForm";

export const metadata: Metadata = { title: "Two-step verification" };

/** PUB-012 MFA step (AUTH-11). */
export default function Page() {
  return (
    <AuthCard title="Two-step verification" description="Confirm it's you to finish signing in.">
      <MfaForm />
    </AuthCard>
  );
}
