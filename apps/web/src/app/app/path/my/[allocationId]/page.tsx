import type { Metadata } from "next";
import { PathPlayer } from "@/features/paths/components/Learner";

export const metadata: Metadata = { title: "Learning path" };

export default async function Page({ params }: { params: Promise<{ allocationId: string }> }) {
  const { allocationId } = await params;
  return <PathPlayer allocationId={allocationId} />;
}
