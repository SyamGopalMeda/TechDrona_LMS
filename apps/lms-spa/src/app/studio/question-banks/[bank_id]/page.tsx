import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { BankDetail } from "@/features/question-bank/components/BankDetail";

export const metadata: Metadata = { title: "Question bank" };

/** One question bank (CMS-004). */
async function Page__server({ params }: { params: Promise<{ bank_id: string }> }) {
  const { bank_id } = await params;
  return <BankDetail bankId={bank_id} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/studio/question-banks/[bank_id]/page.tsx#Page");
