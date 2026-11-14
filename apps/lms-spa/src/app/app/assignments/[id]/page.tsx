import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AssignmentDetail } from "@/features/learning/components/Assignments";

export const metadata: Metadata = { title: "Assignment" };

/** STU-008 */
async function Page__server({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AssignmentDetail assignmentId={decodeURIComponent(id)} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/assignments/[id]/page.tsx#Page");
