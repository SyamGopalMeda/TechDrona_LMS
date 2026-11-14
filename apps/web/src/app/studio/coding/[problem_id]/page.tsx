import type { Metadata } from "next";
import { CodingProblemEditor } from "@/features/studio/components/Coding";

export const metadata: Metadata = { title: "Coding problem" };

/** CMS-010: the problem title is the h1 (rendered by the editor once it loads). */
export default async function Page({ params }: { params: Promise<{ problem_id: string }> }) {
  const { problem_id } = await params;
  return <CodingProblemEditor problemId={problem_id} />;
}
