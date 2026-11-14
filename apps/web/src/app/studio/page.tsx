import type { Metadata } from "next";
import { StudioDashboard } from "@/features/studio/components/StudioDashboard";

export const metadata: Metadata = { title: "Content dashboard" };

/** CMS-001 */
export default function Page() {
  return (
    <StudioDashboard />
  );
}
