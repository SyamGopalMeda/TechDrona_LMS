import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { CertificateVerification } from "@/features/catalog/components/CertificateVerification";
import { serverLoad } from "@/features/catalog/lib/server";
import { DOC_REF, normaliseDocRef, type CertificateVerificationDto } from "@/features/catalog/lib/types";

export const metadata: Metadata = { title: "Certificate verification", robots: { index: false } };

const CODE = /^[A-Z0-9]{10,16}$/;

/** PUB-017 public verification (LRN-13): course certificates and issued documents (letters,
 * other certificates; references such as TD-AL-2026-7K3QX9). No enumeration hints. */
async function Page__server({ params }: { params: Promise<{ certificate_id: string }> }) {
  const { certificate_id } = await params;
  const raw = decodeURIComponent(certificate_id).trim().toUpperCase();
  const ref = normaliseDocRef(raw);
  const code = DOC_REF.test(ref) ? ref : raw;
  const known = CODE.test(code) || DOC_REF.test(code);
  const result = known ? await serverLoad<CertificateVerificationDto>(`certificates/verify/${code}`) : null;
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Certificate verification" description="Check that a Tech Drona certificate or letter is genuine." />
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

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/(public)/verify/[certificate_id]/page.tsx#Page");
