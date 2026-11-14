import type { Metadata } from "next";
import { UnblockReviewQueue } from "@/features/security-admin/components/UnblockReviewQueue";

export const metadata: Metadata = { title: "Unblock reviews" };

/** Reviewer queue for unblock requests and appeals. */
export default function Page() {
  return <UnblockReviewQueue />;
}
