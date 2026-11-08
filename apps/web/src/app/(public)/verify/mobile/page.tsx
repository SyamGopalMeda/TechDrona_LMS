import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { VerifyMobile } from "@/features/auth/components/Verification";

export const metadata: Metadata = { title: "Verify mobile number" };

/** PUB-014 mobile OTP verification (AUTH-04/05; needs a signed-in session). */
export default function Page() {
  return (
    <AuthCard title="Verify your mobile number">
      <VerifyMobile />
    </AuthCard>
  );
}
