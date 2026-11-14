import type { Metadata } from "next";
import { CompaniesManager } from "@/features/studio/components/Companies";

export const metadata: Metadata = { title: "Companies" };

/** CMS-009: companies and role paths (PLC-16..18). */
export default function Page() {
  return <CompaniesManager header={{ title: "Companies", description: "Companies students prepare for, and the role paths that group their practice and mocks." }} />;
}
