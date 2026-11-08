import type { Metadata } from "next";
import { AssignmentEditor } from "@/features/learning/assignment-manager/AssignmentEditor";

export const metadata: Metadata = { title: "Edit assignment" };

/** Structured assignment editor (sections, questions, marks, allocations). */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AssignmentEditor assignmentId={decodeURIComponent(id)} />;
}
