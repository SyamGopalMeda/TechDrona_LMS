import type { Metadata } from "next";
import { EnquiryQueue } from "@/features/support/components/Enquiries";

export const metadata: Metadata = { title: "Corporate enquiries" };

/** SUP-006 (D8) */
export default function Page() {
  return <EnquiryQueue />;
}
