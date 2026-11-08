import type { Metadata } from "next";
import { CodingWorkspace } from "@/features/coding/components/CodingWorkspace";

export const metadata: Metadata = { title: "Coding workspace" };

/** COD-002 Coding workspace (COD-03..08). */
export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <CodingWorkspace slug={slug} />;
}
