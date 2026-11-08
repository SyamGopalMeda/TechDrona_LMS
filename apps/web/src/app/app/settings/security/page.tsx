import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { SecuritySettings } from "@/features/account/components/SecuritySettings";
import { SettingsNav } from "@/features/account/components/SettingsNav";

export const metadata: Metadata = { title: "Security" };

/** STU-021 */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />
      <SettingsNav current="/app/settings/security" />
      <SecuritySettings />
    </div>
  );
}
