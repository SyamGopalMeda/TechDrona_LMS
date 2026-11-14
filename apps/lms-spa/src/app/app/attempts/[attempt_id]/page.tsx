import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AttemptRunner } from "@/features/assessment/components/AttemptRunner";

export const metadata: Metadata = { title: "Test attempt" };

/** TST-002 Attempt runner (focus shell). */
async function Page__server({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <AttemptRunner attemptId={attempt_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/attempts/[attempt_id]/page.tsx#Page");
