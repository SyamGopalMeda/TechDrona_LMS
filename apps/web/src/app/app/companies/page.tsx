import type { Metadata } from "next";
import { CompaniesIndex } from "@/features/practice/components/CompaniesIndex";

export const metadata: Metadata = { title: "Company paths" };

/** Company paths index (readiness per target company, PLC-25). */
export default function Page() {
  return <CompaniesIndex />;
}
