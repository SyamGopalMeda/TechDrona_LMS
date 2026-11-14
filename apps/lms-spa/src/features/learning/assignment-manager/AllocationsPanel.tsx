"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, Dialog, FormField, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { BatchMember } from "@/features/batches/lib/types";
import { fieldErrorsOf, useFailToast, TextArea } from "@/features/trainer/shared/ui";
import { allocationErrorText } from "./AllocateDialog";
import { engineLabel, staffApi } from "./api";
import type { AllocationOut } from "./types";
import { formatDateTime } from "@/lib/format";
import { localInputToIso } from "@/lib/time";

function ExtensionDialog({ allocation, onClose, onDone }: { allocation: AllocationOut | null; onClose: () => void; onDone: () => Promise<void> }) {
  const toast = useToast();
  const fail = useFailToast();
  const [members, setMembers] = useState<{ user_id: string; label: string }[]>([]);
  const [userId, setUserId] = useState("");
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUserId("");
    setUntil("");
    setReason("");
    setErrors({});
    if (!allocation) return;
    let live = true;
    if (allocation.batch_id) {
      api
        .get<{ data: BatchMember[] }>(`batches/${encodeURIComponent(allocation.batch_id)}/members`)
        .then((r) => {
          if (!live) return;
          setMembers(r.data.filter((m) => m.member_role === "student" || !m.member_role).map((m) => ({ user_id: m.user_id, label: m.full_name ?? "Unnamed learner" })));
        })
        .catch(() => live && setMembers([]));
    } else {
      setMembers(allocation.user_ids.map((u, i) => ({ user_id: u, label: `Learner ${i + 1}` })));
    }
    return () => {
      live = false;
    };
  }, [allocation]);

  const submit = async () => {
    if (!allocation) return;
    const errs: Record<string, string> = {};
    const iso = localInputToIso(until);
    if (!userId) errs.user_id = "Choose a learner.";
    if (!iso) errs.until = "Choose the new deadline.";
    else if (Date.parse(iso) <= Date.parse(allocation.due_at)) errs.until = "Must be after the current deadline.";
    if (reason.trim().length < 3) errs.reason = "Add a short reason.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await staffApi.extend(allocation.id, { user_id: userId, until: iso!, reason: reason.trim() });
      toast.show({ tone: "success", title: "Extension granted" });
      onClose();
      await onDone();
    } catch (err) {
      // WS4 SEC-12: 403 conflict_of_interest (own extension), 422 not_allocated (not targeted).
      const known = allocationErrorText(err);
      const fe = fieldErrorsOf(err);
      if (known) setErrors({ user_id: known });
      else if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't grant the extension");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={allocation !== null}
      onClose={onClose}
      dismissible={!busy}
      title="Grant extra time"
      description={allocation ? `Current deadline: ${formatDateTime(allocation.due_at, { year: true })}` : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            Grant extension
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Learner" required error={errors.user_id}>
          {(p) => <Select {...p} value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="Choose a learner…" options={members.map((m) => ({ value: m.user_id, label: m.label }))} />}
        </FormField>
        <FormField label="New deadline" required error={errors.until}>
          {(p) => <Input {...p} type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />}
        </FormField>
        <FormField label="Reason" required error={errors.reason}>
          {(p) => <TextArea {...p} rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </FormField>
      </div>
    </Dialog>
  );
}

/** Allocations of one assignment: schedule, engines, revoke and per-learner extensions. */
export function AllocationsPanel({
  allocations,
  sections,
  onChanged,
  onAllocate,
}: {
  allocations: AllocationOut[];
  sections: { id: string; title: string }[];
  onChanged: () => Promise<void>;
  onAllocate?: () => void;
}) {
  const toast = useToast();
  const fail = useFailToast();
  const [revoke, setRevoke] = useState<AllocationOut | null>(null);
  const [extend, setExtend] = useState<AllocationOut | null>(null);
  const [busy, setBusy] = useState(false);
  const title = (id: string) => sections.find((s) => s.id === id)?.title ?? "Section";

  const doRevoke = async () => {
    if (!revoke) return;
    setBusy(true);
    try {
      await staffApi.patchAllocation(revoke.id, { status: "revoked" });
      toast.show({ tone: "success", title: "Allocation revoked" });
      setRevoke(null);
      await onChanged();
    } catch (err) {
      fail(err, "Couldn't revoke the allocation");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Allocations to batches">
      {allocations.length === 0 ? (
        <p className="text-sm text-fg-muted">
          Not allocated yet. Use <strong>Allocate</strong> to give it to a batch with a schedule and evaluators.
          {onAllocate ? (
            <Button size="sm" variant="ghost" className="ml-2" onClick={onAllocate}>
              Allocate now
            </Button>
          ) : null}
        </p>
      ) : (
        <ul className="space-y-3" aria-label="Allocations">
          {allocations.map((a) => {
            const ext = Object.keys(a.extensions ?? {}).length;
            const name = a.batch_name ?? (a.user_ids.length ? `${a.user_ids.length} learner${a.user_ids.length === 1 ? "" : "s"}` : "Allocation");
            return (
              <li key={a.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-fg">
                    {name} {a.status === "revoked" ? <Badge>Revoked</Badge> : <Badge tone="success">Active</Badge>}
                  </p>
                  {a.status !== "revoked" ? (
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="secondary" onClick={() => setExtend(a)} aria-label={`Grant extension for ${name}`}>
                        Grant extension
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => setRevoke(a)} aria-label={`Revoke allocation for ${name}`}>
                        Revoke
                      </Button>
                    </div>
                  ) : null}
                </div>
                <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs text-fg-secondary sm:grid-cols-2">
                  <div>
                    <dt className="inline text-fg-muted">Visible: </dt>
                    <dd className="inline">
                      {a.visible_from ? formatDateTime(a.visible_from, { year: true }) : "now"} → {a.visible_until ? formatDateTime(a.visible_until, { year: true }) : "open-ended"}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline text-fg-muted">Can start: </dt>
                    <dd className="inline">{a.start_at ? formatDateTime(a.start_at, { year: true }) : "when visible"}</dd>
                  </div>
                  <div>
                    <dt className="inline text-fg-muted">Due: </dt>
                    <dd className="inline">{formatDateTime(a.due_at, { year: true })}</dd>
                  </div>
                  <div>
                    <dt className="inline text-fg-muted">Evaluators: </dt>
                    <dd className="inline">{a.evaluator_ids.length || "none added"}</dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="inline text-fg-muted">Engines: </dt>
                    <dd className="inline">
                      {Object.entries(a.section_engines ?? {})
                        .map(([sid, e]) => `${title(sid)} — ${engineLabel(e)}`)
                        .join("; ") || "—"}
                    </dd>
                  </div>
                  {ext ? (
                    <div className="sm:col-span-2">
                      <dt className="inline text-fg-muted">Extensions: </dt>
                      <dd className="inline">{ext} learner{ext === 1 ? "" : "s"}</dd>
                    </div>
                  ) : null}
                </dl>
              </li>
            );
          })}
        </ul>
      )}
      <Dialog
        open={revoke !== null}
        onClose={() => setRevoke(null)}
        dismissible={!busy}
        title="Revoke this allocation?"
        description="Learners in it lose access to the assignment. Work they already submitted is kept."
        footer={
          <>
            <Button variant="secondary" onClick={() => setRevoke(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void doRevoke()} loading={busy}>
              Revoke
            </Button>
          </>
        }
      />
      <ExtensionDialog allocation={extend} onClose={() => setExtend(null)} onDone={onChanged} />
    </Card>
  );
}
