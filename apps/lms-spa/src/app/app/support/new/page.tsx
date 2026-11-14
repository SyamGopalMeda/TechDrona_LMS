import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { NewTicketForm } from "@/features/support/components/StudentSupport";

export const metadata: Metadata = { title: "New support ticket" };

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

/** STU-025. `?topic=` prefills the category and `?attempt_id=` links an appeal (SUP-01 `related_attempt_id`). */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  return <NewTicketForm from={one(sp.from)} topic={one(sp.topic)} attemptId={one(sp.attempt_id)} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/support/new/page.tsx#Page");
