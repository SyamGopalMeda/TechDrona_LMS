import type { Metadata } from "next";
import { AppealView } from "@/features/assessment/components/AppealView";

export const metadata: Metadata = { title: "Appeal a test decision" };

/** INV-09: target of ATT-11 `appeal_url` for an invalidated attempt (FR-ASM-012). */
export default async function Page({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <AppealView attemptId={attempt_id} />;
}
