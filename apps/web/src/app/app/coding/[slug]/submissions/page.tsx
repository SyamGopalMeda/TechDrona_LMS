import type { Metadata } from "next";
import { SubmissionHistory } from "@/features/coding/components/SubmissionHistory";

export const metadata: Metadata = { title: "Submissions" };

/** COD-003 Submission history (COD-10). */
export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <SubmissionHistory slug={slug} />;
}
