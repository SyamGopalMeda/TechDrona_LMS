"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, PageHeader, Pagination, Select, Skeleton, StatTile, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Schema } from "@/lib/api-types";
import { useResource } from "@/features/account/lib/use-resource";
import { FilterBar, InlineProblem, KeyValueList, TextArea, textLink } from "@/features/admin/components/console-ui";
import { cleanQuery, formatDateTime, humanize, useCursorList } from "@/features/admin/lib/console";

/**
 * Corporate enquiry queue (owner decision D8, WS5): enquiries from the public `/enquiries` form,
 * for Admin. Backend: `GET/PATCH support/enquiries` (apps/api/app/modules/support/enquiries.py).
 * Every detail view is audited server-side; the list only carries a 160-character preview.
 */

export const ENQUIRY_STATUSES = ["new", "in_progress", "closed", "spam"] as const;
export type EnquiryStatus = (typeof ENQUIRY_STATUSES)[number];

/** verified: support/enquiries.py `_out(full=False)` */
export interface EnquirySummary {
  enquiry_id: string;
  reference: string;
  name: string;
  company: string;
  email: string;
  phone: string | null;
  status: EnquiryStatus;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  message_preview: string;
}

/** verified: support/enquiries.py `_out(full=True)` (GET and PATCH). */
export interface EnquiryDetailOut extends Omit<EnquirySummary, "message_preview"> {
  message: string;
  staff_note: string | null;
  consent_at: string;
  notice_version: string;
}

const STATUS_TONE = { new: "info", in_progress: "warning", closed: "success", spam: "neutral" } as const;
const STATUS_LABEL: Record<EnquiryStatus, string> = { new: "New", in_progress: "In progress", closed: "Closed", spam: "Spam" };

export function EnquiryStatusBadge({ status }: { status: EnquiryStatus }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{STATUS_LABEL[status] ?? humanize(status)}</Badge>;
}

const enquiryHref = (id: string) => `/desk/enquiries/${id}`;

/** SUP-006 corporate enquiry queue. */
export function EnquiryQueue() {
  const [status, setStatus] = useState<EnquiryStatus | "">("new");
  const list = useCursorList<EnquirySummary>("support/enquiries", cleanQuery({ status }));
  const counts = list.envelope?.counts as { new?: number } | undefined;
  const cols: Column<EnquirySummary>[] = [
    {
      key: "ref",
      header: "Reference",
      cell: (e) => (
        <Link className={textLink} href={enquiryHref(e.enquiry_id)}>
          {e.reference}
        </Link>
      ),
    },
    { key: "company", header: "Company", cell: (e) => e.company },
    { key: "name", header: "Contact", cell: (e) => e.name },
    { key: "preview", header: "Message", cell: (e) => <span className="line-clamp-2 text-fg-secondary">{e.message_preview}</span> },
    { key: "status", header: "Status", cell: (e) => <EnquiryStatusBadge status={e.status} /> },
    { key: "who", header: "Assignee", cell: (e) => (e.assigned_to ? <span className="font-mono text-xs">{e.assigned_to.slice(0, 8)}</span> : <span className="text-fg-muted">Unassigned</span>) },
    { key: "at", header: "Received", cell: (e) => formatDateTime(e.created_at) },
  ];
  return (
    <div>
      <PageHeader eyebrow="SUP-006" title="Corporate enquiries" description="Enquiries sent through the public enquiry form. Opening an enquiry is recorded in the audit log." />
      {counts ? (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="New enquiries" value={String(counts.new ?? 0)} />
        </div>
      ) : null}
      <FilterBar label="Enquiry filters">
        <FormField label="Status">
          {(f) => (
            <Select
              {...f}
              value={status}
              onChange={(e) => setStatus(e.target.value as EnquiryStatus | "")}
              options={[{ value: "", label: "Any" }, ...ENQUIRY_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))]}
            />
          )}
        </FormField>
      </FilterBar>
      <Table
        caption="Corporate enquiries"
        columns={cols}
        rows={list.rows}
        rowKey={(e) => e.enquiry_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: status ? `No ${STATUS_LABEL[status].toLowerCase()} enquiries` : "No enquiries yet" }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />}
      />
    </div>
  );
}

/** SUP-007 corporate enquiry detail: full message, status, assignment and a staff note. */
export function EnquiryDetail({ enquiryId }: { enquiryId: string }) {
  const toast = useToast();
  const res = useResource<EnquiryDetailOut>(`support/enquiries/${enquiryId}`);
  const [current, setCurrent] = useState<EnquiryDetailOut>();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (res.data) {
      setCurrent(res.data);
      setNote(res.data.staff_note ?? "");
    }
  }, [res.data]);

  if (res.error && !current) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!current) return <Skeleton className="h-60 w-full" />;
  const e = current;

  const patch = async (key: string, body: Schema<"EnquiryPatch">, done: string) => {
    setBusy(key);
    setError(null);
    try {
      const out = await api.patch<EnquiryDetailOut>(`support/enquiries/${enquiryId}`, body);
      if (out.kind === "approval_pending") toast.show({ title: "Sent for approval.", tone: "success" });
      else {
        setCurrent(out.data);
        setNote(out.data.staff_note ?? "");
        toast.show({ title: done, tone: "success" });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const open = e.status === "new" || e.status === "in_progress";

  return (
    <div>
      <PageHeader
        eyebrow="SUP-007"
        title={`${e.company} · ${e.reference}`}
        description={`Received ${formatDateTime(e.created_at)}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" loading={busy === "assign"} onClick={() => void patch("assign", { assign_to_me: true, ...(e.status === "new" ? { status: "in_progress" } : {}) }, "Assigned to you.")}>
              Assign to me
            </Button>
            {open ? (
              <>
                <Button loading={busy === "closed"} onClick={() => void patch("closed", { status: "closed" }, "Enquiry closed.")}>
                  Close
                </Button>
                <Button variant="secondary" loading={busy === "spam"} onClick={() => void patch("spam", { status: "spam" }, "Marked as spam.")}>
                  Mark as spam
                </Button>
              </>
            ) : (
              <Button variant="secondary" loading={busy === "reopen"} onClick={() => void patch("reopen", { status: "in_progress" }, "Enquiry reopened.")}>
                Reopen
              </Button>
            )}
          </div>
        }
      />
      <div className="mb-4">
        <Link className={textLink} href="/desk/enquiries">
          ← All enquiries
        </Link>
      </div>
      <InlineProblem error={error} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Message">
            <p className="whitespace-pre-wrap break-words text-sm text-fg">{e.message}</p>
          </Card>
          <Card title="Staff note">
            <form
              className="space-y-3"
              onSubmit={(ev) => {
                ev.preventDefault();
                void patch("note", { staff_note: note.trim() || null }, "Note saved.");
              }}
            >
              <FormField label="Internal note" hint="Only Admin can see this. Up to 4000 characters.">
                {(f) => <TextArea {...f} value={note} maxLength={4000} onChange={(ev) => setNote(ev.target.value)} />}
              </FormField>
              <Button type="submit" variant="secondary" loading={busy === "note"} disabled={(e.staff_note ?? "") === note.trim()}>
                Save note
              </Button>
            </form>
          </Card>
        </div>
        <Card title="Details">
          <KeyValueList
            className="sm:grid-cols-1"
            items={[
              { label: "Status", value: <EnquiryStatusBadge status={e.status} /> },
              { label: "Name", value: e.name },
              { label: "Company", value: e.company },
              {
                label: "Email",
                value: (
                  <a className={textLink} href={`mailto:${e.email}`}>
                    {e.email}
                  </a>
                ),
              },
              { label: "Phone", value: e.phone ?? <span className="text-fg-muted">Not given</span> },
              { label: "Assignee", value: e.assigned_to ? <span className="font-mono text-xs">{e.assigned_to.slice(0, 8)}</span> : <span className="text-fg-muted">Unassigned</span> },
              { label: "Consent", value: `${formatDateTime(e.consent_at)} (notice ${e.notice_version})` },
              { label: "Closed", value: e.closed_at ? formatDateTime(e.closed_at) : "—" },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
