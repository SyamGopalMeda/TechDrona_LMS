import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { DevicesAndSessions } from "@/features/account/components/DevicesAndSessions";
import { DevicePolicyCard } from "@/features/account/components/SecurityActivity";
import { SettingsNav } from "@/features/account/components/SettingsNav";

export const metadata: Metadata = { title: "Devices and sessions" };

/** STU-022 account-integrity centre */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" />
      <SettingsNav current="/app/settings/devices" />
      <div className="space-y-6">
        <DevicesAndSessions />
        <DevicePolicyCard />
      </div>
    </div>
  );
}
