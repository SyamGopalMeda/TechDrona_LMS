import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { AdminCertificates } from "@/features/certificates/components/AdminCertificates";

export const metadata: Metadata = { title: "Certificates & documents" };

/** ADM-017 certificates & documents: certificate register, due list, create & send letters and other
 * certificates, documents register, email approval queue, templates, settings (`?course=` pre-filters). */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <AdminCertificates initialCourse={typeof sp.course === "string" ? sp.course : ""} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/admin/certificates/page.tsx#Page");
