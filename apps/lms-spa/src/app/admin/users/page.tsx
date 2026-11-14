import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { UserSearch } from "@/features/admin/components/Users";

export const metadata: Metadata = { title: "Users" };

/** ADM-004 (`?status=` pre-filters the list, e.g. from the dashboard tiles). */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <UserSearch initialStatus={typeof sp.status === "string" ? sp.status : ""} openAdd={sp.add === "1"} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/admin/users/page.tsx#Page");
