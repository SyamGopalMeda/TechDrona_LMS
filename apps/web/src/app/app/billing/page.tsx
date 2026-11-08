import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { Billing } from "@/features/commerce/components/Billing";

export const metadata: Metadata = { title: "Billing" };

/** STU-018 subscriptions, orders, invoices, refunds */
export default function Page() {
  return (
    <div>
      <PageHeader title="Billing" description="Orders, subscriptions, GST invoices and refund requests." />
      <Billing />
    </div>
  );
}
