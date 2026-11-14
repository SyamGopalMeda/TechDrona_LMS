import type { Metadata } from "next";
import { CodingProblemList } from "@/features/studio/components/Coding";

export const metadata: Metadata = { title: "Coding problems" };

/** CMS-010 */
export default function Page() {
  return <CodingProblemList header={{ title: "Coding problems", description: "Write problems, add sample and hidden test cases, and validate a reference solution before publishing." }} />;
}
