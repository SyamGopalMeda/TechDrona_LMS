import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { TestInstructions } from "@/features/assessment/components/TestInstructions";

export const metadata: Metadata = { title: "Test instructions" };

/** TST-001 Instructions & system check (ASM-02, ATT-01). */
async function Page__server({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return <TestInstructions testId={test_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/tests/[test_id]/page.tsx#Page");
