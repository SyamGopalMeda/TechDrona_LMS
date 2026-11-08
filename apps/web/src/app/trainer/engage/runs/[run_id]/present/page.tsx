import type { Metadata } from "next";
import { Presenter } from "@/features/engage/components/Presenter";

export const metadata: Metadata = { title: "Present" };

/** TRN-022 big screen */
export default async function Page({ params }: { params: Promise<{ run_id: string }> }) {
  const { run_id } = await params;
  return <Presenter runId={run_id} />;
}
