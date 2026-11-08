import type { Metadata } from "next";
import { PathEditor } from "@/features/paths/components/PathEditor";

export const metadata: Metadata = { title: "Edit learning path" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PathEditor pathId={id} />;
}
