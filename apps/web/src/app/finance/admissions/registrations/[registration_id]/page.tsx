import type { Metadata } from "next";
import { RegistrationView } from "@/features/admissions/components/Admissions";

export const metadata: Metadata = { title: "Registration" };

/** ADM-021 registration detail: payments, instalments, history, contact, enrolment. */
export default async function Page({ params }: { params: Promise<{ registration_id: string }> }) {
  const { registration_id } = await params;
  return <RegistrationView registrationId={registration_id} />;
}
