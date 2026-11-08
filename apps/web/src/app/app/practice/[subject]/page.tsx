import type { Metadata } from "next";
import { SubjectTopics } from "@/features/practice/components/SubjectTopics";

export const metadata: Metadata = { title: "Topics & mastery" };

/** PRC-002 Topics & mastery. */
export default async function Page({ params }: { params: Promise<{ subject: string }> }) {
  const { subject } = await params;
  return <SubjectTopics subject={subject} />;
}
