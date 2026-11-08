import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { AccessList } from "@/features/commerce/components/AccessList";

export const metadata: Metadata = { title: "What I have access to" };

/** STU-019 */
export default function Page() {
  return (
    <div>
      <PageHeader title="What I have access to" />
      <AccessList />
    </div>
  );
}
