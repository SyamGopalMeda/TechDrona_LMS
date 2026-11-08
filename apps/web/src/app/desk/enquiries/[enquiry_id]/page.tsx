import type { Metadata } from "next";
import { EnquiryDetail } from "@/features/support/components/Enquiries";

export const metadata: Metadata = { title: "Enquiry" };

/** SUP-007 (D8) */
export default async function Page({ params }: { params: Promise<{ enquiry_id: string }> }) {
  const { enquiry_id } = await params;
  return <EnquiryDetail enquiryId={enquiry_id} />;
}
