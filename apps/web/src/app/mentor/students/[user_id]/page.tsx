import type { Metadata } from "next";
import { MentorStudent } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Student" };

/** MEN-004 */
export default async function Page({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <MentorStudent userId={user_id} />;
}
