import type { Metadata } from "next";
import { CompanyPathView } from "@/features/practice/components/CompanyPathView";

export const metadata: Metadata = { title: "Company path" };

/** PRC-005 Company path (PLC-32). */
export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <CompanyPathView slug={slug} />;
}
