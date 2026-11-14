import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { SubmissionHistory } from "@/features/coding/components/SubmissionHistory";

export const metadata: Metadata = { title: "Submissions" };

/** COD-003 Submission history (COD-10). */
async function Page__server({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <SubmissionHistory slug={slug} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/coding/[slug]/submissions/page.tsx#Page");
