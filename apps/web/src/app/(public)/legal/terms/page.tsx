import type { Metadata } from "next";
import { ContentDocView } from "@/features/public/components/ContentDoc";
import { TERMS } from "@/features/public/content/legal";

export const metadata: Metadata = { title: TERMS.title, description: TERMS.summary };

/** PUB-018 Terms (draft pending legal review). */
export default function Page() {
  return <ContentDocView doc={TERMS} kind="policy" />;
}
