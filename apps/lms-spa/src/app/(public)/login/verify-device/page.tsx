import type { Metadata } from "next";
import { AuthCard } from "@/features/auth/components/shared";
import { DeviceVerificationForm } from "@/features/auth/components/DeviceVerificationForm";

export const metadata: Metadata = { title: "Confirm this new device" };

/** PUB-012 new-device OTP (AUTH-12/13), FR-SES-003/004/005. */
export default function Page() {
  return (
    <AuthCard title="Confirm this new device" description="You can have up to 3 devices on your account.">
      <DeviceVerificationForm />
    </AuthCard>
  );
}
