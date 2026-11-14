import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { CodingProblemEditor } from "@/features/studio/components/Coding";

export const metadata: Metadata = { title: "Coding problem" };

/** CMS-010: the problem title is the h1 (rendered by the editor once it loads). */
async function Page__server({ params }: { params: Promise<{ problem_id: string }> }) {
  const { problem_id } = await params;
  return <CodingProblemEditor problemId={problem_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/studio/coding/[problem_id]/page.tsx#Page");
