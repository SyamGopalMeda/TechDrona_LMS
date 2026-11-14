import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { TestBuilder } from "@/features/studio/components/Tests";

export const metadata: Metadata = { title: "Test builder" };

/** CMS-011: the test title is the h1 (rendered by the builder once it loads). */
async function Page__server({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return <TestBuilder testId={test_id} crumbs={[{ label: "Template mocks", href: "/studio/tests" }]} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/studio/tests/[test_id]/page.tsx#Page");
