import type { Metadata } from "next";
import { PracticeSession } from "@/features/practice/components/PracticeSession";

export const metadata: Metadata = { title: "Practice session" };

/** PRC-003 Practice session (PLC-20..23). */
export default async function Page({ params }: { params: Promise<{ session_id: string }> }) {
  const { session_id } = await params;
  return <PracticeSession sessionId={session_id} />;
}
