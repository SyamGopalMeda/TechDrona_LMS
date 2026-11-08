import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { MentorStudent } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Student" };

/** MEN-004 */
export default async function Page({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return (
    <div>
      <PageHeader title="Student" eyebrow="MEN-004" />
      <MentorStudent userId={user_id} />
    </div>
  );
}
