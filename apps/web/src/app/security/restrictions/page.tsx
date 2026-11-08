import type { Metadata } from "next";
import { Restrictions } from "@/features/security-admin/components/Restrictions";

export const metadata: Metadata = { title: "Restrictions" };

/** SEC-005 (H5) */
export default function Page() {
  return <Restrictions />;
}
