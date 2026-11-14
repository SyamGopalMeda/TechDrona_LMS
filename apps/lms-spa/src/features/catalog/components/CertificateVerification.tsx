import Link from "next/link";
import { Badge, Card } from "@/components/ui";
import type { CertificateVerificationDto } from "../lib/types";
import { PdfCheck } from "./PdfCheck";
import { formatDate } from "@/lib/format";

const DETAIL_LABELS: [string, string][] = [
  ["hours", "Hours"],
  ["duration", "Duration"],
  ["mode", "Mode"],
  ["grade", "Grade / result"],
  ["project", "Project"],
  ["event_date", "Held on"],
];

/**
 * PUB-017 result. Course certificates show only what LRN-13 returns: name, course, issue date,
 * identity flag, status (a revoked certificate shows the date only). Issued documents (letters,
 * internship / appreciation / participation certificates) show the type, holder, program, dates,
 * summary and signatory, never a letter's text, contact details or fees; a recommendation letter
 * shows holder, signer and date only. Unknown codes get one neutral message (no enumeration hints).
 */
export function CertificateVerification({ code, data }: { code: string; data: CertificateVerificationDto | null }) {
  if (!data) {
    return (
      <Card>
        <p role="status" className="font-semibold text-fg">
          We couldn’t verify this certificate or document
        </p>
        <p className="mt-1 text-sm text-fg-secondary">
          Nothing matches <span className="font-mono">{code || "this code"}</span>. Check the number printed on it (a certificate code of 10–16 letters and digits, or a reference such as TD-AL-2026-7K3QX9) and try again.
        </p>
      </Card>
    );
  }
  if (data.kind === "document") return <DocumentVerification code={code} data={data} />;
  const valid = data.status === "valid";
  return (
    <div className="space-y-4">
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
      {valid ? <PdfCheck code={data.public_code ?? code} /> : null}
    </div>
  );
}

function DocumentVerification({ code, data }: { code: string; data: CertificateVerificationDto }) {
  const number = data.ref_no ?? code;
  const what = data.layout === "letter" ? "document" : "certificate";
  const lor = data.doc_type === "lor";
  const issuer = data.issuer ?? "Tech Drona";
  const d = data.details ?? {};
  const skills = (d.skills ?? "").split("\n").map((s) => s.trim()).filter(Boolean);
  return (
    <div className="space-y-4">
      <Card>
        <div role="status" className="flex flex-wrap items-center gap-2">
          {data.status === "valid" ? (
            <Badge tone="success">{`Valid ${what}`}</Badge>
          ) : data.status === "superseded" ? (
            <Badge tone="neutral">Superseded by a corrected copy</Badge>
          ) : (
            <Badge tone="danger">{`Revoked${data.revoked_on ? ` on ${formatDate(data.revoked_on)}` : ""}`}</Badge>
          )}
          <span className="font-mono text-sm text-fg-muted">{number}</span>
        </div>
        <h2 className="mt-3 font-display text-lg font-bold text-fg-heading">
          {data.status === "valid" ? `Genuine ${issuer} ${String(data.label ?? what).toLowerCase()}` : data.status === "superseded" ? `This ${what} was replaced by a corrected one` : `This ${what} has been revoked`}
        </h2>
        {data.status === "superseded" ? (
          <p className="mt-1 text-sm text-fg-secondary">
            {`It was issued to ${data.recipient ?? "the holder"} on ${formatDate(data.issued_at)} and corrected${data.superseded_on ? ` on ${formatDate(data.superseded_on)}` : ""}. Only the corrected ${what} is valid: `}
            {data.superseded_by ? (
              <Link href={`/verify/${encodeURIComponent(data.superseded_by)}`} className="font-mono text-fg-link">
                {data.superseded_by}
              </Link>
            ) : (
              "ask the holder for the new one"
            )}
            .
          </p>
        ) : null}
        {data.status === "revoked" ? (
          <p className="mt-1 text-sm text-fg-secondary">
            {`It was issued by ${issuer} to ${data.recipient ?? "the holder"} on ${formatDate(data.issued_at)}, but has been withdrawn and is no longer valid.`}
            {data.revoked_reason ? ` Reason: ${data.revoked_reason}` : ""}
          </p>
        ) : null}
        {data.status === "valid" ? (
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-fg-muted">Reference no.</dt>
            <dd className="font-mono text-fg">{number}</dd>
            <dt className="text-fg-muted">{data.layout === "letter" ? "Issued to" : "Awarded to"}</dt>
            <dd className="font-medium text-fg">{data.recipient ?? "—"}</dd>
            <dt className="text-fg-muted">Document</dt>
            <dd className="text-fg">{data.label ?? "—"}</dd>
            {!lor && data.program ? (
              <>
                <dt className="text-fg-muted">Program / role</dt>
                <dd className="text-fg">{data.program}</dd>
              </>
            ) : null}
            {!lor && (data.start_date || data.end_date) ? (
              <>
                <dt className="text-fg-muted">Period</dt>
                <dd className="text-fg">{[data.start_date, data.end_date].filter(Boolean).map((x) => formatDate(x as string)).join(" – ")}</dd>
              </>
            ) : null}
            <dt className="text-fg-muted">Issued on</dt>
            <dd className="text-fg">{formatDate(data.issued_at)}</dd>
            {data.signatory ? (
              <>
                <dt className="text-fg-muted">{lor ? "Signed by" : "Signatory"}</dt>
                <dd className="text-fg">{data.signatory}</dd>
              </>
            ) : null}
            {!lor
              ? DETAIL_LABELS.filter(([k]) => d[k]).map(([k, l]) => (
                  <div key={k} className="contents">
                    <dt className="text-fg-muted">{l}</dt>
                    <dd className="text-fg">{d[k]}</dd>
                  </div>
                ))
              : null}
            <dt className="text-fg-muted">Issuer</dt>
            <dd className="text-fg">{issuer}</dd>
          </dl>
        ) : null}
        {data.status === "valid" && !lor && skills.length ? (
          <div className="mt-4 text-sm">
            <h3 className="font-semibold text-fg">Skills covered</h3>
            <ul className="mt-1 list-disc pl-5 text-fg-secondary">
              {skills.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {data.status === "valid" && lor ? (
          <p className="mt-3 text-sm text-fg-secondary">{`This confirms that the letter of recommendation exists, who signed it and when. Its text is private: ask ${data.recipient ?? "the holder"} for a copy, then compare it with the PDF check below.`}</p>
        ) : null}
        {data.status === "valid" && data.replaces ? <p className="mt-3 text-sm text-fg-secondary">{`This corrects an earlier ${what} (${data.replaces}), which is no longer valid.`}</p> : null}
        {data.status === "valid" && data.related?.length ? (
          <div className="mt-4 text-sm">
            <h3 className="font-semibold text-fg">{`Other documents issued to ${data.recipient ?? "this person"}`}</h3>
            <ul className="mt-1 space-y-1">
              {data.related.map((r) => (
                <li key={r.ref_no}>
                  <Link href={`/verify/${encodeURIComponent(r.ref_no)}`} className="font-mono text-fg-link">
                    {r.ref_no}
                  </Link>{" "}
                  <span className="text-fg-muted">{r.label}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>
      {data.status === "valid" && data.pdf_check ? <PdfCheck code={number} /> : null}
    </div>
  );
}
