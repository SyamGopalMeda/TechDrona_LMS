import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { UserLookup } from "@/features/support/components/SupportDesk";

export const metadata: Metadata = { title: "User lookup" };

/** SUP-003 / SUP-004 */
async function Page__server({ params, searchParams }: { params: Promise<{ user_id: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { user_id } = await params;
  const sp = await searchParams;
  const ticket = typeof sp.ticket === "string" ? sp.ticket : undefined;
  return <UserLookup userId={user_id} ticketId={ticket} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/desk/users/[user_id]/page.tsx#Page");
