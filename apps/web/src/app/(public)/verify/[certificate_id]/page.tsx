import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { CertificateVerification } from "@/features/catalog/components/CertificateVerification";
import { serverLoad } from "@/features/catalog/lib/server";
import type { CertificateVerificationDto } from "@/features/catalog/lib/types";

export const metadata: Metadata = { title: "Certificate verification", robots: { index: false } };

const CODE = /^[A-Z0-9]{10,16}$/;

/** PUB-017 public certificate verification (LRN-13). No enumeration hints. */
export default async function Page({ params }: { params: Promise<{ certificate_id: string }> }) {
  const { certificate_id } = await params;
  const code = decodeURIComponent(certificate_id).trim().toUpperCase();
  const result = CODE.test(code) ? await serverLoad<CertificateVerificationDto>(`certificates/verify/${code}`) : null;
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Certificate verification" description="Check that a Tech Drona certificate is genuine." />
      {result === null || (!result.ok && result.status === 404) ? (
        <CertificateVerification code={code} data={null} />
      ) : !result.ok ? (
        <ServerErrorState result={result} retryHref={`/verify/${encodeURIComponent(code)}`} />
      ) : (
        <CertificateVerification code={code} data={result.data} />
      )}
    </div>
  );
}
