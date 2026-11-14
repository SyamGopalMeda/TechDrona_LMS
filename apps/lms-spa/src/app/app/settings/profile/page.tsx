import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ProfileSettings } from "@/features/account/components/ProfileSettings";
import { SettingsNav } from "@/features/account/components/SettingsNav";

export const metadata: Metadata = { title: "Profile" };

/** STU-020 */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />
      <SettingsNav current="/app/settings/profile" />
      <ProfileSettings />
    </div>
  );
}
