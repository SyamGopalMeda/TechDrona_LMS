"use client";

import { useState } from "react";
import { StatusBadge, Button, Card, Checkbox, Dialog, EmptyState, ErrorState, LoadingBlock, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { toFormError } from "@/features/auth/lib/errors";
import { OPEN_STATES, type PrivacyCreateBody, type PrivacyListResponse, type PrivacyRequest } from "../lib/types";
import { formatDate } from "@/lib/format";
import { useResource } from "@/lib/api/use-resource";

const TYPE_LABEL: Record<string, string> = {
  access_export: "Download my data",
  erasure: "Delete my account",
  correction: "Correct my data",
  grievance: "Grievance",
  nomination: "Nominate someone",
  consent_withdrawal_help: "Help withdrawing consent",
};

/* Wording for the requester; tones come from the kit status vocabulary. */
const STATUS_LABEL: Record<string, string> = {
  received: "Received",
  identity_verification: "Checking it's you",
  in_progress: "In progress",
  awaiting_requester: "Waiting for you",
  cooling_off: "Cooling-off period",
  completed: "Completed",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

/** Saves the export JSON as a file (the api returns the export payload itself). */
function saveJson(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/**
 * STU-023 "Your data": self-serve DPDP requests (PRV-01..05). Export and erasure are created here;
 * erasure needs a recent step-up (the api client opens the dialog) and starts a 14-day
 * cooling-off that can be withdrawn. Records kept by law are listed from the api response.
 */
export function PrivacyRequests() {
  const toast = useToast();
  const list = useResource<PrivacyListResponse>("me/privacy-requests");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmErase, setConfirmErase] = useState(false);
  const [eraseAck, setEraseAck] = useState(false);

  const rows = list.data?.data ?? [];
  const openOf = (t: string) => rows.find((r) => r.request_type === t && OPEN_STATES.includes(r.status));

  const fail = (err: unknown) => {
    const e = toFormError(err);
    toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
  };

  const create = async (type: PrivacyCreateBody["request_type"], confirm = false) => {
    setBusy(type);
    try {
      const body: PrivacyCreateBody = { request_type: type, details: null, confirm };
      const res = await api.post<PrivacyRequest>("me/privacy-requests", body, { idempotencyKey: true });
      if (res.kind === "ok") {
        toast.show({
          tone: "success",
          title: type === "erasure" ? `Deletion requested (${res.data.request_ref}).` : `Request ${res.data.request_ref} received.`,
          description: type === "erasure" && res.data.cooling_off_until ? `You can cancel until ${formatDate(res.data.cooling_off_until)}.` : `We'll respond by ${formatDate(res.data.due_at)}.`,
        });
      }
      setConfirmErase(false);
      setEraseAck(false);
      await list.reload();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const withdraw = async (r: PrivacyRequest) => {
    setBusy(r.request_id);
    try {
      await api.post<PrivacyRequest>(`me/privacy-requests/${encodeURIComponent(r.request_id)}/withdraw`, {});
      toast.show({ tone: "success", title: r.request_type === "erasure" ? "Deletion cancelled. Your account stays open." : "Request withdrawn." });
      await list.reload();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const download = async (r: PrivacyRequest) => {
    setBusy(r.request_id);
    try {
      const data = await api.get<unknown>(`me/privacy-requests/${encodeURIComponent(r.request_id)}/export`);
      saveJson(`techdrona-data-${r.request_ref}.json`, data);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const pendingExport = openOf("access_export");
  const pendingErase = openOf("erasure");

  return (
    <Card title="Your data">
      <div className="space-y-4 text-sm">
        <p className="max-w-prose text-fg-secondary">
          You can ask for a copy of your data or for your account to be deleted. Deletion starts with a 14-day cooling-off period during which you can cancel. Records we must keep by law (such as invoices and security logs) are kept for the minimum time.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="secondary" loading={busy === "access_export"} disabled={!!pendingExport || list.loading} onClick={() => void create("access_export")}>
            {pendingExport ? "Data copy requested" : "Request a copy of my data"}
          </Button>
          {/* danger-secondary opens the confirm dialog; the filled danger button lives only inside it (DS §3). */}
          <Button variant="danger-secondary" disabled={!!pendingErase || list.loading} onClick={() => setConfirmErase(true)}>
            {pendingErase ? "Deletion requested" : "Delete my account"}
          </Button>
        </div>

        <h3 className="pt-2 font-display text-base font-bold text-fg-heading">Your requests</h3>
        {list.error ? (
          <ErrorState error={list.error} title="We couldn't load your requests" onRetry={list.reload} />
        ) : list.loading && !list.data ? (
          <LoadingBlock label="Loading requests…" rows={1} size="row" />
        ) : rows.length === 0 ? (
          <EmptyState variant="inline" icon="shield" title="No requests yet" description="Requests you make for a copy of your data or to delete your account appear here." />
        ) : (
          <ul className="divide-y divide-line-subtle" aria-label="Privacy requests">
            {rows.map((r) => {
              const open = OPEN_STATES.includes(r.status);
              return (
                <li key={r.request_id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-medium text-fg">
                      {TYPE_LABEL[r.request_type] ?? r.request_type} <StatusBadge status={r.status} label={STATUS_LABEL[r.status] ?? r.status.replace(/_/g, " ")} />
                    </p>
                    <p className="mt-0.5 text-xs text-fg-muted">
                      {r.request_ref} · received {formatDate(r.received_at)}
                      {open ? ` · due ${formatDate(r.due_at)}` : r.completed_at ? ` · completed ${formatDate(r.completed_at)}` : ""}
                    </p>
                    {r.status === "cooling_off" && r.cooling_off_until ? (
                      <p className="mt-0.5 text-xs text-warning-fg">Your account will be deleted after {formatDate(r.cooling_off_until)} unless you cancel.</p>
                    ) : null}
                    {r.retained_by_law?.length ? <p className="mt-0.5 text-xs text-fg-muted">Kept by law: {r.retained_by_law.join(", ")}.</p> : null}
                    {r.response_summary ?<p className="mt-1 text-fg-secondary">{r.response_summary}</p> : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {r.request_type === "access_export" && r.status === "completed" && r.export_available ? (
                      <Button size="sm" loading={busy === r.request_id} onClick={() => void download(r)}>
                        Download
                      </Button>
                    ) : null}
                    {open ? (
                      <Button size="sm" variant="secondary" loading={busy === r.request_id} onClick={() => void withdraw(r)}>
                        {r.request_type === "erasure" ? "Cancel deletion" : "Withdraw"}
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <Dialog
        open={confirmErase}
        onClose={() => {
          setConfirmErase(false);
          setEraseAck(false);
        }}
        dismissible={busy === null}
        title="Delete your account?"
        description="Your account, progress and certificates will be deleted after a 14-day cooling-off period. You can cancel during that time. Invoices (72 months), security logs (at least 1 year) and the audit log (3 years) are kept because the law requires it. You may be asked to confirm it's you."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmErase(false)} disabled={busy !== null}>
              Keep my account
            </Button>
            <Button variant="danger" disabled={!eraseAck} loading={busy === "erasure"} onClick={() => void create("erasure", true)}>
              Request deletion
            </Button>
          </>
        }
      >
        <Checkbox id="erase-ack" label="I understand my account will be deleted after the cooling-off period." checked={eraseAck} onChange={(e) => setEraseAck(e.target.checked)} />
      </Dialog>
    </Card>
  );
}
