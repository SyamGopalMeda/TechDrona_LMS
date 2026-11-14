import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { EnquiryDetail } from "@/features/support/components/Enquiries";

export const metadata: Metadata = { title: "Enquiry" };

/** SUP-007 (D8) */
async function Page__server({ params }: { params: Promise<{ enquiry_id: string }> }) {
  const { enquiry_id } = await params;
  return <EnquiryDetail enquiryId={enquiry_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/desk/enquiries/[enquiry_id]/page.tsx#Page");
