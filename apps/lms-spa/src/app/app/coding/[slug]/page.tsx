import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { CodingWorkspace } from "@/features/coding/components/CodingWorkspace";

export const metadata: Metadata = { title: "Coding workspace" };

/** COD-002 Coding workspace (COD-03..08). */
async function Page__server({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <CodingWorkspace slug={slug} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/coding/[slug]/page.tsx#Page");
