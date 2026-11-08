import type { Metadata } from "next";
import { UserTimelinePage } from "@/features/security-admin/components/UserTimelinePage";

export const metadata: Metadata = { title: "User security timeline" };

/** SEC-007 (H12) */
export default async function Page({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <UserTimelinePage userId={user_id} />;
}
