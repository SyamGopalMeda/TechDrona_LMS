import type { Metadata } from "next";
import { AccountStatus } from "@/features/unblock/components/AccountStatus";

export const metadata: Metadata = { title: "Account status" };

/** STU-026 account status (SEC-01 / SEC-02), with the review request flow (UNB-01). */
export default function Page() {
  return (
    <div className="max-w-3xl">
      <AccountStatus />
    </div>
  );
}
