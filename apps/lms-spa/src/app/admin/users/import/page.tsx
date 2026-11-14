import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ImportStudents } from "@/features/admin/components/StudentImport";

export const metadata: Metadata = { title: "Import students" };

/** ADM-024 Import students (`?batch=<id>` pre-selects the batch, e.g. from a batch page). */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <ImportStudents initialBatchId={typeof sp.batch === "string" ? sp.batch : ""} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/admin/users/import/page.tsx#Page");
