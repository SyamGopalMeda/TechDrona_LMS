import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { UserTimelinePage } from "@/features/security-admin/components/UserTimelinePage";

export const metadata: Metadata = { title: "User security timeline" };

/** One user's audited security timeline. */
async function Page__server({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <UserTimelinePage userId={user_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/security/users/[user_id]/timeline/page.tsx#Page");
