import type { Metadata } from "next";
import { RoleGrants } from "@/features/admin/components/Governance";

export const metadata: Metadata = { title: "Role grants" };

/** ADM-005 */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const user_id = typeof sp.user_id === "string" ? sp.user_id : undefined;
  return <RoleGrants initialUserId={user_id ?? ""} />;
}
