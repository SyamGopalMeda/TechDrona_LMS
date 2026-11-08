import type { Metadata } from "next";
import { PracticeHub } from "@/features/practice/components/PracticeHub";

export const metadata: Metadata = { title: "Practice" };

/** PRC-001 Practice hub (PLC-01, PLC-19, PLC-26). */
export default function Page() {
  return <PracticeHub />;
}
