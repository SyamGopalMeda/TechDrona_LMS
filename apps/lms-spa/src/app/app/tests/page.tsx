import type { Metadata } from "next";
import { TestsList } from "@/features/assessment/components/TestsList";

export const metadata: Metadata = { title: "Tests" };

/** STU-009 Tests list (ASM-01). */
export default function Page() {
  return <TestsList />;
}
