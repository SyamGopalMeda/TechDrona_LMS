import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { CompanyPathView } from "@/features/practice/components/CompanyPathView";

export const metadata: Metadata = { title: "Company path" };

/** PRC-005 Company path (PLC-32). */
async function Page__server({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <CompanyPathView slug={slug} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/app/companies/[slug]/page.tsx#Page");
