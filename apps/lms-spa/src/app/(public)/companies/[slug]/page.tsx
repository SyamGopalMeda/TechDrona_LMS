import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasSessionCookie } from "@/lib/api/server";
import { CompanyHub } from "@/features/public/components/CompanyHubs";

export const metadata: Metadata = { title: "Company hub", robots: { index: false } };

const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;

/** PUB-007: honest state until CAT-04 exists; signed-in learners are pointed at their company path. */
async function Page__server({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!SLUG.test(slug)) notFound();
  return <CompanyHub slug={slug} signedIn={await hasSessionCookie()} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/companies/[slug]/page.tsx#Page");
