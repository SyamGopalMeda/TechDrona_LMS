import type { Metadata } from "next";
import { UserTimelinePage } from "@/features/security-admin/components/UserTimelinePage";

export const metadata: Metadata = { title: "User security timeline" };

/** One user's audited security timeline. */
export default async function Page({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <UserTimelinePage userId={user_id} />;
}
