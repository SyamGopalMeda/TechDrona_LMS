import { Badge, Card } from "@/components/ui";
import { formatDate } from "../lib/format";
import type { CertificateVerificationDto } from "../lib/types";

/**
 * PUB-017 result. Shows only what LRN-13 returns: name, course, issue date, identity flag,
 * status. A revoked certificate shows the date only (no reason). Unknown codes get one
 * neutral message (no enumeration hints).
 */
export function CertificateVerification({ code, data }: { code: string; data: CertificateVerificationDto | null }) {
  if (!data) {
    return (
      <Card>
        <p role="status" className="font-semibold text-fg">
          We couldn’t verify this certificate
        </p>
        <p className="mt-1 text-sm text-fg-secondary">
          No certificate matches <span className="font-mono">{code || "this code"}</span>. Check the code on the certificate (10–16 letters and digits) and try again.
        </p>
      </Card>
    );
  }
  const valid = data.status === "valid";
  return (
    <Card>
      <div role="status" className="flex flex-wrap items-center gap-2">
        {valid ? <Badge tone="success">Valid certificate</Badge> : <Badge tone="danger">Revoked{data.revoked_on ? ` on ${formatDate(data.revoked_on)}` : ""}</Badge>}
        <span className="font-mono text-sm text-fg-muted">{data.public_code ?? code}</span>
      </div>
      {valid ? (
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-fg-muted">Awarded to</dt>
          <dd className="font-medium text-fg">{data.name_on_certificate ?? "—"}</dd>
          <dt className="text-fg-muted">Course</dt>
          <dd className="text-fg">{data.course_title ?? "—"}</dd>
          <dt className="text-fg-muted">Issued on</dt>
          <dd className="text-fg">{formatDate(data.issued_at)}</dd>
          <dt className="text-fg-muted">Identity</dt>
          <dd className="text-fg">{data.identity_verified ? "Identity verified" : "Identity not verified"}</dd>
          <dt className="text-fg-muted">Issuer</dt>
          <dd className="text-fg">{data.issuer ?? "Tech Drona"}</dd>
        </dl>
      ) : (
        <p className="mt-3 text-sm text-fg-secondary">This certificate is no longer valid.</p>
      )}
    </Card>
  );
}
