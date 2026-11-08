import type { Metadata } from "next";
import { AssignmentDetail } from "@/features/learning/components/Assignments";

export const metadata: Metadata = { title: "Assignment" };

/** STU-008 */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AssignmentDetail assignmentId={decodeURIComponent(id)} />;
}
