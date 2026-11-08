import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { GuardianConsent } from "@/features/auth/components/GuardianConsent";

export const metadata: Metadata = { title: "Guardian consent", referrer: "no-referrer" };

/** PUB-015 guardian consent landing (AUTH-25/26/27). */
export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <AuthCard title="Parent or guardian consent">
      <GuardianConsent token={token} />
    </AuthCard>
  );
}
