import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { PathPlayer } from "@/features/paths/components/Learner";

export const metadata: Metadata = { title: "Learning path" };

async function Page__server({ params }: { params: Promise<{ allocationId: string }> }) {
  const { allocationId } = await params;
  return <PathPlayer allocationId={allocationId} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/path/my/[allocationId]/page.tsx#Page");
