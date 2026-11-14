import type { Metadata } from "next";
import { PracticeReview } from "@/features/practice/components/PracticeReview";

export const metadata: Metadata = { title: "Review" };

/** PRC-004 Review incorrect & bookmarked (PLC-24). */
export default function Page() {
  return <PracticeReview />;
}
