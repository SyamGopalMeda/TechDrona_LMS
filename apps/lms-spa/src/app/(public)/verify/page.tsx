import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui";
import { VerifyCodeForm } from "@/features/catalog/components/VerifyCodeForm";
import { DOC_REF, normaliseDocRef } from "@/features/catalog/lib/types";

export const metadata: Metadata = { title: "Certificate verification" };

const CODE = /^[A-Z0-9]{10,16}$/;

/** FE-13: footer "Certificate verification" entry point; a valid certificate code or document
 * reference (TD-AL-2026-7K3QX9, also typed as TD/AL/2026/7K3QX9) goes to PUB-017. */
async function Page__server({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const typed = typeof sp.code === "string" ? sp.code.slice(0, 40) : "";
  const ref = normaliseDocRef(typed);
  if (typed && DOC_REF.test(ref)) redirect(`/verify/${ref}`);
  const raw = typed.replace(/[\s-]/g, "").toUpperCase().slice(0, 32);
  if (raw && CODE.test(raw)) redirect(`/verify/${raw}`);
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Certificate verification" description="Check that a Tech Drona certificate or letter is genuine." />
      <VerifyCodeForm initial={typed.trim().toUpperCase()} invalid={typed.trim().length > 0} />
    </div>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/verify/page.tsx#Page");
