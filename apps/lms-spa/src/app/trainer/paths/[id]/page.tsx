import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { PathEditor } from "@/features/paths/components/PathEditor";

export const metadata: Metadata = { title: "Edit learning path" };

async function Page__server({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PathEditor pathId={id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/trainer/paths/[id]/page.tsx#Page");
