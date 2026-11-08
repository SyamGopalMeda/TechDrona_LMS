import type { Metadata } from "next";
import { UserDetail } from "@/features/admin/components/Users";

export const metadata: Metadata = { title: "User" };

/** ADM-004 user account view (ADM-03) */
export default async function Page({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <UserDetail userId={user_id} />;
}
