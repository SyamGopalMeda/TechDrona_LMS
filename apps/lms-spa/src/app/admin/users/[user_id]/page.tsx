import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { UserDetail } from "@/features/admin/components/Users";

export const metadata: Metadata = { title: "User" };

/** ADM-004 user account view (ADM-03) */
async function Page__server({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <UserDetail userId={user_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/admin/users/[user_id]/page.tsx#Page");
