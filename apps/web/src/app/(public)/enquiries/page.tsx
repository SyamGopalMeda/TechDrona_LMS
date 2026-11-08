import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { EnquiryForm } from "@/features/public/components/EnquiryForm";

export const metadata: Metadata = {
  title: "Corporate enquiries",
  description: "Training for your team: tell Tech Drona what you need and we will get back to you.",
};

/** PUB-010 corporate enquiries (owner decision D8; replaces the former "For colleges" page). */
export default function Page() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader
        title="Corporate enquiries"
        description="Want Tech Drona courses, practice and assessments for your team or new hires? Tell us what you need and our team will reply within two working days."
      />
      <section aria-label="Enquiry form" className="rounded-xl border border-line bg-surface p-5 sm:p-6">
        <EnquiryForm />
      </section>
    </div>
  );
}
