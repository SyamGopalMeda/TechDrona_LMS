import type { Metadata } from "next";
import { BatchList } from "@/features/batches/components/Batches";

export const metadata: Metadata = { title: "Batches" };

/** ADM-013 batches (cohorts), managed by Admin (single-company plan §3). BatchList renders the header + "Create batch". */
export default function Page() {
  return <BatchList />;
}
