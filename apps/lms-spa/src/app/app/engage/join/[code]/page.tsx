import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { JoinRun } from "@/features/engage/components/Learner";

export const metadata: Metadata = { title: "Join activity" };

/** STU-031 */
async function Page__server({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return <JoinRun code={code} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/engage/join/[code]/page.tsx#Page");
