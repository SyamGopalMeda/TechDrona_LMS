import type { Metadata } from "next";
import { AttemptRunner } from "@/features/assessment/components/AttemptRunner";

export const metadata: Metadata = { title: "Test attempt" };

/** TST-002 Attempt runner (focus shell). */
export default async function Page({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <AttemptRunner attemptId={attempt_id} />;
}
