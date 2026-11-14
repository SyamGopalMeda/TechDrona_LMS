import type { Metadata } from "next";
import { RegistrationsList } from "@/features/admissions/components/Admissions";

export const metadata: Metadata = { title: "Registrations" };

/** ADM-021 course registrations from the website. */
export default function Page() {
  return <RegistrationsList />;
}
