import type { Metadata } from "next";
import { ContentDocView } from "@/features/public/components/ContentDoc";
import { PRIVACY } from "@/features/public/content/legal";

export const metadata: Metadata = { title: PRIVACY.title, description: PRIVACY.summary };

/** PUB-018 privacy notice (privacy-and-data-retention §3.1; draft pending legal review). */
export default function Page() {
  return <ContentDocView doc={PRIVACY} kind="policy" />;
}
