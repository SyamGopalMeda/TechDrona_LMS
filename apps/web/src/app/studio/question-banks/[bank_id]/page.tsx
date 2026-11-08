import type { Metadata } from "next";
import { BankDetail } from "@/features/question-bank/components/BankDetail";

export const metadata: Metadata = { title: "Question bank" };

/** One question bank (CMS-004). */
export default async function Page({ params }: { params: Promise<{ bank_id: string }> }) {
  const { bank_id } = await params;
  return <BankDetail bankId={bank_id} />;
}
