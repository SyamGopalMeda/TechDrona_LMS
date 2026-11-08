import type { Metadata } from "next";
import { ResultsView } from "@/features/assessment/components/ResultsView";

export const metadata: Metadata = { title: "Results" };

/** STU-010 Results & review (ATT-11, ATT-12). */
export default async function Page({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <ResultsView attemptId={attempt_id} />;
}
