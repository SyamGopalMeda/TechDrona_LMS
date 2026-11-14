import type { Metadata } from "next";
import { TestBuilder } from "@/features/studio/components/Tests";

export const metadata: Metadata = { title: "Test builder" };

/** TRN-006: the test title is the h1 (rendered by the builder once it loads). */
export default async function Page({
  params,
}: {
  params: Promise<{ test_id: string }>;
}) {
  const { test_id } = await params;
  return <TestBuilder testId={test_id} crumbs={[{ label: "Tests", href: "/trainer/tests" }]} />;
}
