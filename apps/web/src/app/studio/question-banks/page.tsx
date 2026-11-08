import type { Metadata } from "next";
import { BankList } from "@/features/question-bank/components/BankList";

export const metadata: Metadata = { title: "Question banks" };

/** Question banks (CMS-004): list, bulk import, generate with AI. */
export default function Page() {
  return <BankList />;
}
