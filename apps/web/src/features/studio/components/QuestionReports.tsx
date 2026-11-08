"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Dialog, FormField, Pagination, Select, Table, Tabs, nextCursorStack, previousCursorStack, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { StatusBadge, TextArea, useFailToast } from "@/features/trainer/shared/ui";
import type { QuestionReport, QuestionReportPage, QuestionReportResolution } from "../lib/types";

const PAGE = 25;
const NOTE_MAX = 1000;

const CATEGORY: Record<string, string> = {
  wrong_answer: "Wrong answer key",
  wrong_explanation: "Wrong explanation",
  typo: "Typo / formatting",
  unclear: "Unclear question",
  other: "Other",
};

const RESOLUTIONS: { value: QuestionReportResolution; label: string }[] = [
  { value: "fixed", label: "Fixed (question corrected)" },
  { value: "no_change", label: "No change needed" },
  { value: "duplicate", label: "Duplicate report" },
  { value: "invalid", label: "Not a valid report" },
];

const RESOLUTION_LABEL: Record<string, string> = Object.fromEntries(RESOLUTIONS.map((r) => [r.value, r.label]));

/** CMS-013 reported-error queue (PLC-34) with resolve (PLC-35; the reporter is notified). */
export function QuestionReportQueue() {
  const [status, setStatus] = useState<"open" | "resolved">("open");
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = stack[stack.length - 1];
  const list = useApi<QuestionReportPage>("studio/question-reports", { status, limit: PAGE, cursor });
  const [resolving, setResolving] = useState<QuestionReport | null>(null);

  const switchTo = (s: string) => {
    setStatus(s === "resolved" ? "resolved" : "open");
    setStack([undefined]);
  };

  const table = (
    <div className="space-y-2">
      <Table
        caption={status === "open" ? "Open question reports" : "Resolved question reports"}
        columns={[
          { key: "c", header: "Category", cell: (r: QuestionReport) => CATEGORY[r.category] ?? r.category },
          { key: "m", header: "Report", cell: (r) => <span className="whitespace-pre-wrap break-words">{r.message}</span> },
          {
            key: "q",
            header: "Question",
            cell: (r) => (
              <Link className="text-fg-link underline" href={`/studio/questions/${seg(r.question_id)}`}>
                Open question
              </Link>
            ),
          },
          { key: "d", header: "Reported", cell: (r) => new Date(r.created_at).toLocaleDateString() },
          status === "open"
            ? {
                key: "a",
                header: "Action",
                cell: (r) => (
                  <Button size="sm" variant="secondary" aria-label={`Resolve report ${r.report_id}`} onClick={() => setResolving(r)}>
                    Resolve
                  </Button>
                ),
              }
            : {
                key: "a",
                header: "Resolution",
                cell: (r) => (
                  <span>
                    <StatusBadge status={r.status} /> {r.resolution ? RESOLUTION_LABEL[r.resolution] ?? r.resolution : ""}
                    {r.resolution_note ? <span className="block text-xs text-fg-muted">{r.resolution_note}</span> : null}
                  </span>
                ),
              },
        ]}
        rows={list.data?.data}
        rowKey={(r) => r.report_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: status === "open" ? "No open reports" : "No resolved reports yet" }}
      />
      <Pagination
        hasMore={!!list.data?.meta.has_more}
        hasPrevious={stack.length > 1}
        loading={list.loading}
        onNext={() => setStack((s) => nextCursorStack(s, list.data?.meta.next_cursor ?? null))}
        onPrevious={() => setStack((s) => previousCursorStack(s))}
      />
    </div>
  );

  return (
    <div className="space-y-4">
      {list.data ? <p className="text-sm text-fg-muted">{list.data.open_count} open report{list.data.open_count === 1 ? "" : "s"}</p> : null}
      <Tabs
        label="Report status"
        value={status}
        onValueChange={switchTo}
        items={[
          { id: "open", label: "Open", content: status === "open" ? table : null },
          { id: "resolved", label: "Resolved", content: status === "resolved" ? table : null },
        ]}
      />
      <ResolveDialog
        report={resolving}
        onClose={() => setResolving(null)}
        onResolved={() => {
          setResolving(null);
          void list.reload();
        }}
      />
    </div>
  );
}

function ResolveDialog({ report, onClose, onResolved }: { report: QuestionReport | null; onClose: () => void; onResolved: () => void }) {
  const toast = useToast();
  const fail = useFailToast();
  const [resolution, setResolution] = useState<QuestionReportResolution>("fixed");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastId, setLastId] = useState<string | null>(null);

  if (!report) return null;
  if (lastId !== report.report_id) {
    setLastId(report.report_id);
    setResolution("fixed");
    setNote("");
  }

  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`studio/question-reports/${seg(report.report_id)}/resolve`, { resolution, ...(note.trim() ? { note: note.trim() } : {}) }, { idempotencyKey: true });
      toast.show({ tone: "success", title: "Report resolved", description: "The reporter has been notified." });
      onResolved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.show({ tone: "warning", title: "Already resolved", description: "Someone else resolved this report.", requestId: err.requestId });
        onResolved();
      } else fail(err, "Couldn't resolve the report");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      title="Resolve report"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            Resolve
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 text-sm">{report.message}</p>
        <FormField label="Resolution">
          {(p) => <Select {...p} value={resolution} onChange={(e) => setResolution(e.target.value as QuestionReportResolution)} options={RESOLUTIONS} />}
        </FormField>
        <FormField label="Note to the reporter" hint={`${note.length}/${NOTE_MAX} characters`}>
          {(p) => <TextArea {...p} rows={3} maxLength={NOTE_MAX} value={note} onChange={(e) => setNote(e.target.value)} />}
        </FormField>
      </div>
    </Dialog>
  );
}
