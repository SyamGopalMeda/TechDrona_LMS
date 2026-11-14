import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { RegistrationView } from "@/features/admissions/components/Admissions";

export const metadata: Metadata = { title: "Registration" };

/** ADM-021 registration detail: payments, instalments, history, contact, enrolment. */
async function Page__server({ params }: { params: Promise<{ registration_id: string }> }) {
  const { registration_id } = await params;
  return <RegistrationView registrationId={registration_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/finance/admissions/registrations/[registration_id]/page.tsx#Page");
