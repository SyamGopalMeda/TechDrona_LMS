import type { Metadata } from "next";
import { AttemptRunner } from "@/features/assessment/components/AttemptRunner";

export const metadata: Metadata = { title: "Resume test" };

/** TST-004 Resume after crash/disconnect. */
export default async function Page({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <AttemptRunner attemptId={attempt_id} forceResume />;
}
