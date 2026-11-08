import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { Notice } from "@/features/auth/components/shared";
import { MfaCard } from "@/features/account/components/SecuritySettings";
import { SettingsNav } from "@/features/account/components/SettingsNav";

export const metadata: Metadata = { title: "Set up 2-step verification" };

/**
 * Target of the api's `mfa_enrolment_required` problem (`enrol_url`, sessions/resolver.py):
 * the same enrolment card as STU-021, with the reason stated first.
 */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />
      <SettingsNav current="/app/settings/security" />
      <div className="space-y-6">
        <Notice tone="warning" title="2-step verification is required for your account">
          Your role requires 2-step verification. Add an authenticator app below, then go back to what you were doing.
        </Notice>
        <MfaCard />
      </div>
    </div>
  );
}
