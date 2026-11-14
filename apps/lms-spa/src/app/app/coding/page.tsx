import type { Metadata } from "next";
import { ProblemList } from "@/features/coding/components/ProblemList";

export const metadata: Metadata = { title: "Coding" };

/** COD-001 Problem list (COD-02). */
export default function Page() {
  return <ProblemList />;
}
