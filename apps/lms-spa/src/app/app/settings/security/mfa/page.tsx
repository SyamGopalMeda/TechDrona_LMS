import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MfaEnrolment } from "@/features/account/components/SecuritySettings";
import { SettingsNav } from "@/features/account/components/SettingsNav";

export const metadata: Metadata = { title: "2-step verification" };

/**
 * Target of the api's `mfa_enrolment_required` problem (`enrol_url`, sessions/resolver.py):
 * the same enrolment card as STU-021, with the reason stated first (or, in simple
 * authentication, a note that 2-step verification isn't used).
 */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />
      <SettingsNav current="/app/settings/security" />
      <MfaEnrolment />
    </div>
  );
}
