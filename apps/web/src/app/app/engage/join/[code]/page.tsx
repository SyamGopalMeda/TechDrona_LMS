import type { Metadata } from "next";
import { JoinRun } from "@/features/engage/components/Learner";

export const metadata: Metadata = { title: "Join activity" };

/** STU-031 */
export default async function Page({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return <JoinRun code={code} />;
}
