import type { Metadata } from "next";
import { UserSearch } from "@/features/admin/components/Users";

export const metadata: Metadata = { title: "Users" };

/** ADM-004 (`?status=` pre-filters the list, e.g. from the dashboard tiles). */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <UserSearch initialStatus={typeof sp.status === "string" ? sp.status : ""} openAdd={sp.add === "1"} />;
}
