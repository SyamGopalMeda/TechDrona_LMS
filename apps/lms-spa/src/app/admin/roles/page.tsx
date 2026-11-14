import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { RoleGrants } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Role grants" };

/** ADM-005 */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const user_id = typeof sp.user_id === "string" ? sp.user_id : undefined;
  return <RoleGrants initialUserId={user_id ?? ""} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/admin/roles/page.tsx#Page");
