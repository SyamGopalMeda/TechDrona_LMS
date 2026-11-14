import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { Certificates } from "@/features/learning/components/Certificates";

export const metadata: Metadata = { title: "Certificates" };

/** STU-012 */
export default function Page() {
  return (
    <div>
      <PageHeader title="Certificates" description="Certificates you've earned. Share the verification link with employers." />
      <Certificates />
    </div>
  );
}
