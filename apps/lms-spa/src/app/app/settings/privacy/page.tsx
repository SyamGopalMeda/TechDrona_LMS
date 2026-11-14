import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { PrivacySettings } from "@/features/account/components/PrivacySettings";
import { SettingsNav } from "@/features/account/components/SettingsNav";

export const metadata: Metadata = { title: "Privacy and consent" };

/** STU-023 */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />
      <SettingsNav current="/app/settings/privacy" />
      <PrivacySettings />
    </div>
  );
}
