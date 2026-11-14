"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, FormField, Input, LinkButton, LoadingBlock, Select, useToast } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { useTeachingQuery, useTrainerBatches } from "@/features/trainer/lib/batches";
import { useMyGrants } from "@/features/trainer/shared/grants";
import { useApi } from "@/features/trainer/shared/use-api";
import { StatusBadge, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import { isStructured, staffApi } from "./api";
import type { StaffAssignmentRow } from "./types";

export const rowId = (a: StaffAssignmentRow): string => a.id ?? a.assignment_id ?? "";

/**
 * Where the signed-in staff member may create assignments: their trainer batches, plus
 * "Company-wide" (no batch, no course) for staff holding a platform-scope grant (WS4: the api
 * stamps company-wide assignments with the company org and requires platform scope).
 */
function useOwnerScopes() {
  const grants = useMyGrants();
  const { batches } = useTrainerBatches();
  return useMemo(
    () => ({ platform: (grants.data?.data ?? []).some((g) => g.scope_type === "platform"), batches: batches ?? [] }),
    [grants.data, batches],
  );
}

function NewAssignmentDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const { platform, batches } = useOwnerScopes();
  const [title, setTitle] = useState("");
  const [total, setTotal] = useState("100");
  const [owner, setOwner] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  // Owner = a batch, or company-wide (platform-scope staff only).
  const ownerOptions = useMemo(
    () => [
      ...(platform ? [{ value: "company:", label: "Company-wide (no batch)" }] : []),
      ...batches.map((b) => ({ value: `batch:${b.id}`, label: `Batch: ${b.name}` })),
    ],
    [platform, batches],
  );
  const effectiveOwner = owner || (batches[0] ? `batch:${batches[0].id}` : platform ? "company:" : "");

  const submit = async () => {
    const errs: Record<string, string> = {};
    const marks = Number(total);
    if (!title.trim()) errs.title = "Enter a name for the assignment.";
    if (!total.trim() || !Number.isFinite(marks) || marks <= 0) errs.max_score = "Total marks must be more than 0.";
    if (!effectiveOwner) errs.owner = "Choose where this assignment belongs.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const [kind, id] = effectiveOwner.split(":") as ["company" | "batch", string];
      const created = await staffApi.create({
        title: title.trim(),
        submission_type: "structured",
        max_score: marks,
        ...(kind === "batch" ? { batch_id: id } : {}),
      });
      toast.show({ tone: "success", title: "Assignment created", description: "Now add sections and questions." });
      onClose();
      router.push(`/trainer/assignments/${encodeURIComponent(created.id)}`);
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors({ ...fe, owner: fe.batch_id ?? "" });
      else fail(err, "Couldn't create the assignment");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title="New assignment"
      description="Give it a name and the total marks. You'll add sections and questions next."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Assignment name" required error={errors.title}>
          {(p) => <Input {...p} value={title} maxLength={200} placeholder="e.g. Week 4 — Arrays practice" onChange={(e) => setTitle(e.target.value)} />}
        </FormField>
        <FormField label="Total marks" required error={errors.max_score}>
          {(p) => <Input {...p} type="number" min={1} inputMode="numeric" value={total} onChange={(e) => setTotal(e.target.value)} />}
        </FormField>
        {ownerOptions.length !== 1 || errors.owner ? (
          <FormField label="Belongs to" required error={errors.owner || undefined} hint="Learners are chosen later, when you allocate it.">
            {(p) => <Select {...p} value={effectiveOwner} onChange={(e) => setOwner(e.target.value)} placeholder="Choose…" options={ownerOptions} />}
          </FormField>
        ) : null}
      </div>
    </Dialog>
  );
}

/** Trainer assignment manager list: structured assignments as cards with Edit / Clone / Evaluate. */
export function AssignmentManagerList() {
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const list = useApi<{ data: StaffAssignmentRow[] }>("assignments", { scope: "mine", limit: 100, ...useTeachingQuery() });
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [cloning, setCloning] = useState<string | null>(null);

  const rows = (list.data?.data ?? []).filter(isStructured).filter((a) => a.title.toLowerCase().includes(search.trim().toLowerCase()));

  const clone = async (a: StaffAssignmentRow) => {
    setCloning(rowId(a));
    try {
      const c = await staffApi.clone(rowId(a));
      toast.show({ tone: "success", title: "Assignment cloned" });
      router.push(`/trainer/assignments/${encodeURIComponent(c.id)}`);
    } catch (err) {
      fail(err, "Couldn't clone the assignment");
    } finally {
      setCloning(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="w-full max-w-sm">
          <FormField label="Search assignments">
            {(p) => <Input {...p} type="search" value={search} onChange={(e) => setSearch(e.target.value)} />}
          </FormField>
        </div>
        {/* The one primary action of this view; card actions stay secondary. */}
        <Button onClick={() => setOpen(true)}>New assignment</Button>
      </div>
      {list.error ? (
        isApiError(list.error) && list.error.status === 403 ? (
          <EmptyState title="You can't manage assignments here" description="Ask a Tech Drona admin for trainer access to a batch." />
        ) : (
          <ErrorState error={list.error} onRetry={() => void list.reload()} />
        )
      ) : list.loading && !list.data ? (
        <LoadingBlock rows={3} label="Loading" size="row" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={search ? "No assignments match" : "No structured assignments yet"}
          description={search ? undefined : "Create one, add sections and questions, then allocate it to a batch."}
          action={search ? undefined : <Button variant="secondary" onClick={() => setOpen(true)}>New assignment</Button>}
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Structured assignments">
          {rows.map((a) => {
            const id = rowId(a);
            const sections = a.section_count ?? 0;
            const items = a.item_count ?? 0;
            return (
              <li key={id}>
                <Card className="flex h-full flex-col">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-display text-base font-semibold text-fg">{a.title}</h3>
                    <StatusBadge status={a.status ?? "draft"} />
                  </div>
                  <p className="mt-1 text-sm text-fg-muted">
                    {sections} section{sections === 1 ? "" : "s"} · {items} question{items === 1 ? "" : "s"}
                    {typeof a.max_score === "number" ? ` · ${a.max_score} marks` : ""}
                  </p>
                  {a.grades_released ? <Badge tone="success" className="mt-2 self-start">Results published</Badge> : null}
                  <div className="mt-auto flex flex-wrap gap-2 pt-4">
                    <LinkButton size="sm" variant="secondary" href={`/trainer/assignments/${encodeURIComponent(id)}`} aria-label={`Edit ${a.title}`}>
                      Edit
                    </LinkButton>
                    <Button size="sm" variant="secondary" loading={cloning === id} onClick={() => void clone(a)} aria-label={`Clone ${a.title}`}>
                      Clone
                    </Button>
                    <LinkButton size="sm" variant="secondary" href={`/trainer/grading/assignments/${encodeURIComponent(id)}`} aria-label={`Evaluate ${a.title}`}>
                      Evaluate
                    </LinkButton>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      <NewAssignmentDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
