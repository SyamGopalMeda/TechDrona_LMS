import type { Metadata } from "next";
import { UnblockReviewQueue } from "@/features/security-admin/components/UnblockReviewQueue";

export const metadata: Metadata = { title: "Unblock requests" };

/** SEC-004 (H6) */
export default function Page() {
  return <UnblockReviewQueue />;
}
