import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui";
import { VerifyCodeForm } from "@/features/catalog/components/VerifyCodeForm";

export const metadata: Metadata = { title: "Certificate verification" };

const CODE = /^[A-Z0-9]{10,16}$/;

/** FE-13: footer "Certificate verification" entry point; a valid code goes to PUB-017. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const raw = typeof sp.code === "string" ? sp.code.replace(/[\s-]/g, "").toUpperCase().slice(0, 32) : "";
  if (raw && CODE.test(raw)) redirect(`/verify/${raw}`);
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Certificate verification" description="Check that a Tech Drona certificate is genuine." />
      <VerifyCodeForm initial={raw} invalid={raw.length > 0} />
    </div>
  );
}
