import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { GuardianPending } from "@/features/account/components/GuardianPending";

export const metadata: Metadata = { title: "Guardian consent" };

/** Target of `minor_consent_pending` (`guardian_flow_url`): status of the guardian's decision. */
export default function Page() {
  return (
    <div className="max-w-3xl">
      <PageHeader title="Guardian consent" />
      <GuardianPending />
    </div>
  );
}
