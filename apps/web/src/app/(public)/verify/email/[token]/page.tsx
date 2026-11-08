import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { VerifyEmail } from "@/features/auth/components/Verification";

export const metadata: Metadata = { title: "Verify email", referrer: "no-referrer" };

/** PUB-014 email verification (AUTH-02). */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Verify your email">
      <VerifyEmail token={token} />
    </AuthCard>
  );
}
