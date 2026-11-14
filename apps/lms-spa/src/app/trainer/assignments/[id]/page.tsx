import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AssignmentEditor } from "@/features/learning/assignment-manager/AssignmentEditor";

export const metadata: Metadata = { title: "Edit assignment" };

/** Structured assignment editor (sections, questions, marks, allocations). */
async function Page__server({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AssignmentEditor assignmentId={decodeURIComponent(id)} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/trainer/assignments/[id]/page.tsx#Page");
