import type { Metadata } from "next";
import { TestInstructions } from "@/features/assessment/components/TestInstructions";

export const metadata: Metadata = { title: "Test instructions" };

/** TST-001 Instructions & system check (ASM-02, ATT-01). */
export default async function Page({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return <TestInstructions testId={test_id} />;
}
