import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { SubjectTopics } from "@/features/practice/components/SubjectTopics";

export const metadata: Metadata = { title: "Topics & mastery" };

/** PRC-002 Topics & mastery. */
async function Page__server({ params }: { params: Promise<{ subject: string }> }) {
  const { subject } = await params;
  return <SubjectTopics subject={subject} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/practice/[subject]/page.tsx#Page");
