import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { AccessList } from "@/features/commerce/components/AccessList";

export const metadata: Metadata = { title: "My access" };

/** STU-019 */
export default function Page() {
  return (
    <div>
      <PageHeader title="My access" description="The courses, practice and features your plans and batches unlock." />
      <AccessList />
    </div>
  );
}
