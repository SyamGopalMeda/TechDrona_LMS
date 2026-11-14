import type { Metadata } from "next";
import { AdminCertificates } from "@/features/certificates/components/AdminCertificates";

export const metadata: Metadata = { title: "Certificates & documents" };

/** ADM-017 certificates & documents: certificate register, due list, create & send letters and other
 * certificates, documents register, email approval queue, templates, settings (`?course=` pre-filters). */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <AdminCertificates initialCourse={typeof sp.course === "string" ? sp.course : ""} />;
}
