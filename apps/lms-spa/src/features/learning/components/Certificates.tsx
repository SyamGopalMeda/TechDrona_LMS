"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, ErrorState, Table } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { CertificateDto, SignedUrlDto } from "../lib/types";
import { formatDate } from "@/lib/format";
import { useAllPages } from "@/lib/api/use-resource";

/** STU-012 certificates (LRN-11, every cursor page followed), PDF via short-lived signed URL (LRN-12). */
export function Certificates() {
  const { data, error, loading, reload } = useAllPages<CertificateDto>("me/certificates");
  const [busy, setBusy] = useState<string | null>(null);
  const [dlError, setDlError] = useState<unknown>(null);

  async function download(c: CertificateDto) {
    setBusy(c.id);
    setDlError(null);
    try {
      const res = await api.get<SignedUrlDto>(`me/certificates/${encodeURIComponent(c.id)}/pdf`);
      if (res.url) window.open(res.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setDlError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {dlError ? <ErrorState error={dlError} /> : null}
      <Table<CertificateDto>
        caption="Your certificates"
        rows={data?.data}
        rowKey={(r) => r.id}
        loading={loading}
        error={error}
        onRetry={reload}
        empty={{ title: "No certificates yet", description: "Complete a course's requirements to earn its certificate. It appears here automatically." }}
        columns={[
          { key: "course", header: "Course", cell: (r) => <span className="font-medium text-fg">{r.course_title ?? "—"}</span> },
          { key: "issued", header: "Issued", cell: (r) => formatDate(r.issued_at) },
          {
            key: "status",
            header: "Status",
            cell: (r) => (r.status === "revoked" ? <Badge tone="danger">Revoked{r.revoked_at ? ` ${formatDate(r.revoked_at)}` : ""}</Badge> : <Badge tone="success">Valid</Badge>),
          },
          {
            key: "verify",
            header: "Verification link",
            cell: (r) => (
              <Link href={`/verify/${encodeURIComponent(r.public_code)}`} className="font-mono text-sm text-fg-link hover:text-fg-link-hover">
                {r.public_code}
              </Link>
            ),
          },
          {
            key: "pdf",
            header: <span className="sr-only">Download</span>,
            align: "right",
            cell: (r) =>
              r.status === "revoked" ? null : r.pdf_available ? (
                <Button variant="secondary" size="sm" loading={busy === r.id} onClick={() => void download(r)} aria-label={`Download certificate for ${r.course_title ?? "this course"}`}>
                  Download PDF
                </Button>
              ) : (
                <span className="text-xs text-fg-muted">PDF being generated</span>
              ),
          },
        ]}
      />
    </div>
  );
}
