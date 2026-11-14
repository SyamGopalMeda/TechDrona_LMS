import type { Metadata } from "next";
import { Restrictions } from "@/features/security-admin/components/Restrictions";

export const metadata: Metadata = { title: "Restrictions" };

/** Restrictions and bulk lifts. */
export default function Page() {
  return <Restrictions />;
}
