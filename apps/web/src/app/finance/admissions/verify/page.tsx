import type { Metadata } from "next";
import { VerifyQueue } from "@/features/admissions/components/Admissions";

export const metadata: Metadata = { title: "Verify payments" };

/** ADM-020 manual UPI payment verification queue. */
export default function Page() {
  return <VerifyQueue />;
}
