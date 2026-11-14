import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AppealView } from "@/features/assessment/components/AppealView";

export const metadata: Metadata = { title: "Appeal a test decision" };

/** INV-09: target of ATT-11 `appeal_url` for an invalidated attempt (FR-ASM-012). */
async function Page__server({ params }: { params: Promise<{ attempt_id: string }> }) {
  const { attempt_id } = await params;
  return <AppealView attemptId={attempt_id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/attempts/[attempt_id]/appeal/page.tsx#Page");
