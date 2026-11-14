import type { Metadata } from "next";
import { CompaniesIndex } from "@/features/public/components/CompanyHubs";

export const metadata: Metadata = { title: "Companies" };

/** PUB-006: honest state until the public company-hub API (CAT-03) exists. */
export default function Page() {
  return <CompaniesIndex />;
}
