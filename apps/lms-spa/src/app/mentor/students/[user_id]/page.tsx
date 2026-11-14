import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { MentorStudent } from "@/features/mentor/components/Mentor";

export const metadata: Metadata = { title: "Student" };

/** MEN-004 */
async function Page__server({ params }: { params: Promise<{ user_id: string }> }) {
  const { user_id } = await params;
  return <MentorStudent userId={user_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/mentor/students/[user_id]/page.tsx#Page");
