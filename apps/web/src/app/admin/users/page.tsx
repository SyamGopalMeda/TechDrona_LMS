import type { Metadata } from "next";
import { UserSearch } from "@/features/admin/components/Users";

export const metadata: Metadata = { title: "Users" };

/** ADM-004 */
export default function Page() {
  return <UserSearch />;
}
