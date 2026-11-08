"use client";

import { useState } from "react";
import { Button, ErrorState, FormField, Input, Pagination, Select, Table, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog } from "@/features/admin/components/console-ui";
import { cleanQuery, toOutcome, useCursorList } from "@/features/admin/lib/console";
import { useApi } from "@/features/trainer/shared/use-api";
import { Boundary, LoadingBlock, TextArea, formatDate } from "@/features/trainer/shared/ui";
import { BATCH_STAFF_ROLES, archivedBatchGuard } from "../lib/api";
import type { Batch, BatchMember, BatchStaffGrant, UserHit } from "../lib/types";

/**
 * Admin batch management (plan §3): edit, archive, add / move / remove members, and assign
 * trainers / evaluators at batch scope. Archived batches are read-only server-side.
 */
export function BatchActions({ batch, onChanged }: { batch: Batch; onChanged: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState<"edit" | "archive" | null>(null);
  const [f, setF] = useState({ name: "", academic_year: "", graduation_year: "", starts_on: "", ends_on: "", status: "" });
  if (batch.status === "archived") return null;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const startEdit = () => {
    setF({
      name: batch.name,
      academic_year: batch.academic_year ?? "",
      graduation_year: batch.graduation_year ? String(batch.graduation_year) : "",
      starts_on: batch.starts_on ?? "",
      ends_on: batch.ends_on ?? "",
      status: batch.status,
    });
    setOpen("edit");
  };
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="secondary" onClick={startEdit}>
        Edit batch
      </Button>
      <Button size="sm" variant="secondary" onClick={() => setOpen("archive")}>
        Archive batch
      </Button>
      <ActionDialog
        open={open === "edit"}
        onClose={() => setOpen(null)}
        title="Edit batch"
        submitLabel="Save"
        validate={() => {
          if (!f.name.trim()) return "Enter a batch name.";
          if (f.starts_on && f.ends_on && f.ends_on < f.starts_on) return "End date is before the start date.";
          return null;
        }}
        onSubmit={async () =>
          toOutcome(
            await archivedBatchGuard(
              api.patch<Batch>(`batches/${encodeURIComponent(batch.id)}`, {
                name: f.name.trim(),
                academic_year: f.academic_year.trim() || null,
                graduation_year: f.graduation_year ? Number(f.graduation_year) : null,
                starts_on: f.starts_on || null,
                ends_on: f.ends_on || null,
                status: f.status,
              }),
            ),
          )
        }
        onDone={(o) => {
          if (o.kind !== "ok") return;
          toast.show({ tone: "success", title: "Batch updated" });
          onChanged();
        }}
      >
        <div className="space-y-3">
          <FormField label="Name" required>
            {(p) => <Input {...p} value={f.name} onChange={set("name")} maxLength={200} />}
          </FormField>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Intake" hint="e.g. 2026-27">
              {(p) => <Input {...p} value={f.academic_year} onChange={set("academic_year")} maxLength={9} />}
            </FormField>
            <FormField label="Graduation year">
              {(p) => <Input {...p} type="number" inputMode="numeric" min={1990} max={2100} value={f.graduation_year} onChange={set("graduation_year")} />}
            </FormField>
            <FormField label="Starts on">{(p) => <Input {...p} type="date" value={f.starts_on} onChange={set("starts_on")} />}</FormField>
            <FormField label="Ends on">{(p) => <Input {...p} type="date" value={f.ends_on} onChange={set("ends_on")} />}</FormField>
          </div>
          <FormField label="Status">
            {(p) => (
              <Select
                {...p}
                value={f.status}
                onChange={set("status")}
                options={[
                  { value: "planned", label: "Planned" },
                  { value: "active", label: "Active" },
                  { value: "completed", label: "Completed" },
                ]}
              />
            )}
          </FormField>
        </div>
      </ActionDialog>
      <ActionDialog
        open={open === "archive"}
        onClose={() => setOpen(null)}
        title={`Archive ${batch.name}?`}
        description="An archived batch becomes read-only: members can no longer be added, moved or removed, and it can't be edited."
        submitLabel="Archive batch"
        danger
        onSubmit={async () => toOutcome(await archivedBatchGuard(api.post<Batch>(`batches/${encodeURIComponent(batch.id)}/archive`, {})))}
        onDone={(o) => {
          if (o.kind !== "ok") return;
          toast.show({ tone: "success", title: "Batch archived" });
          onChanged();
        }}
      />
    </div>
  );
}

/** Search active accounts (ADM-02 `admin/users?q=`) and pick one. */
export function UserPicker({ value, onChange, exclude, label = "Find a person" }: { value: UserHit | null; onChange: (u: UserHit | null) => void; exclude?: Set<string>; label?: string }) {
  const [q, setQ] = useState("");
  const term = q.trim();
  const list = useCursorList<UserHit>(term.length >= 2 ? "admin/users" : null, cleanQuery({ q: term, status: "active" }));
  const hits = (list.rows ?? []).filter((u) => !exclude?.has(u.user_id));
  return (
    <div className="space-y-2">
      <FormField label={label} hint="Type at least 2 characters of a name or email address.">
        {(p) => <Input {...p} type="search" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />}
      </FormField>
      {value ? (
        <p className="text-sm text-fg" aria-live="polite">
          Selected: <strong>{value.display_name ?? value.email ?? "Unnamed"}</strong>
          {value.email ? ` (${value.email})` : null}{" "}
          <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
            Clear
          </Button>
        </p>
      ) : null}
      {term.length < 2 ? null : list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : list.loading && !list.rows ? (
        <LoadingBlock rows={2} />
      ) : hits.length ? (
        <ul className="divide-y divide-line rounded-md border border-line" aria-label="Matching people">
          {hits.map((u) => (
            <li key={u.user_id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
              <span>
                <span className="font-medium text-fg">{u.display_name ?? "Unnamed"}</span>
                {u.email ? <span className="block text-fg-muted">{u.email}</span> : null}
              </span>
              <Button size="sm" variant={value?.user_id === u.user_id ? "primary" : "secondary"} onClick={() => onChange(u)} aria-label={`Choose ${u.display_name ?? u.email ?? "this person"}`}>
                {value?.user_id === u.user_id ? "Chosen" : "Choose"}
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fg-muted">No matching active accounts.</p>
      )}
      {list.hasMore || list.hasPrevious ? <Pagination label="Search result pages" hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} loading={list.loading} /> : null}
    </div>
  );
}

/** Add one existing account to the batch as a student (plan §3, D4: one by one + search). */
export function AddMemberDialog({ batchId, existing, open, onClose, onDone }: { batchId: string; existing: Set<string>; open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [picked, setPicked] = useState<UserHit | null>(null);
  const close = () => {
    setPicked(null);
    onClose();
  };
  return (
    <ActionDialog
      open={open}
      onClose={close}
      title="Add a student to this batch"
      submitLabel="Add to batch"
      validate={() => (picked ? null : "Choose a person to add.")}
      onSubmit={async () => toOutcome(await archivedBatchGuard(api.post<{ added: number }>(`batches/${encodeURIComponent(batchId)}/members`, { user_ids: [picked!.user_id], member_role: "student" })))}
      onDone={(o) => {
        if (o.kind !== "ok") return;
        toast.show({ tone: "success", title: `Added ${picked?.display_name ?? "student"}` });
        setPicked(null);
        onDone();
      }}
    >
      {open ? <UserPicker value={picked} onChange={setPicked} exclude={existing} /> : null}
    </ActionDialog>
  );
}

/** Remove or move one member. */
export function MemberActionDialog({ batchId, member, kind, onClose, onDone }: { batchId: string; member: BatchMember | null; kind: "remove" | "move" | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const batches = useApi<{ data: Batch[] }>(kind === "move" ? "batches" : null);
  const [target, setTarget] = useState("");
  const targets = (batches.data?.data ?? []).filter((b) => b.id !== batchId && b.status !== "archived");
  const name = member?.full_name ?? "this member";
  if (kind === "move")
    return (
      <ActionDialog
        open={member !== null}
        onClose={() => {
          setTarget("");
          onClose();
        }}
        title={`Move ${name} to another batch`}
        submitLabel="Move"
        validate={() => (target ? null : "Choose a batch.")}
        onSubmit={async () =>
          toOutcome(await archivedBatchGuard(api.post<{ added: number }>(`batches/${encodeURIComponent(target)}/members`, { user_ids: [member!.user_id], member_role: member!.member_role, move_from_batch_id: batchId })))
        }
        onDone={(o) => {
          if (o.kind !== "ok") return;
          toast.show({ tone: "success", title: `Moved ${name}` });
          setTarget("");
          onDone();
        }}
      >
        {batches.error ? (
          <ErrorState error={batches.error} onRetry={() => void batches.reload()} />
        ) : (
          <FormField label="Move to batch" required>
            {(p) => <Select {...p} value={target} onChange={(e) => setTarget(e.target.value)} options={[{ value: "", label: batches.loading ? "Loading…" : "Choose a batch" }, ...targets.map((b) => ({ value: b.id, label: b.name }))]} />}
          </FormField>
        )}
      </ActionDialog>
    );
  return (
    <ActionDialog
      open={member !== null && kind === "remove"}
      onClose={onClose}
      title={`Remove ${name} from this batch?`}
      description="Only this batch membership ends; the account itself is not changed."
      submitLabel="Remove from batch"
      danger
      onSubmit={async () => toOutcome(await archivedBatchGuard(api.delete<{ removed: boolean }>(`batches/${encodeURIComponent(batchId)}/members/${encodeURIComponent(member!.user_id)}`)))}
      onDone={(o) => {
        if (o.kind !== "ok") return;
        toast.show({ tone: "success", title: `Removed ${name} from the batch` });
        onDone();
      }}
    />
  );
}

const ROLE_LABEL: Record<string, string> = Object.fromEntries(BATCH_STAFF_ROLES.map((r) => [r.value, r.label]));

/** Trainers and evaluators of a batch = RBAC grants at batch scope; assign and revoke. */
export function BatchStaff({ batchId, readOnly }: { batchId: string; readOnly?: boolean }) {
  const toast = useToast();
  const grants = useApi<{ data: BatchStaffGrant[] }>("rbac/grants", { scope_type: "batch", scope_id: batchId });
  const rows = (grants.data?.data ?? []).filter((g) => g.role_key in ROLE_LABEL);
  const [assigning, setAssigning] = useState(false);
  const [role, setRole] = useState<string>("trainer");
  const [user, setUser] = useState<UserHit | null>(null);
  const [reason, setReason] = useState("");
  const [revoke, setRevoke] = useState<BatchStaffGrant | null>(null);
  const [revokeReason, setRevokeReason] = useState("");
  const resetAssign = () => {
    setAssigning(false);
    setUser(null);
    setReason("");
    setRole("trainer");
  };
  return (
    <section aria-labelledby="batch-staff-h" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="batch-staff-h" className="text-base font-semibold text-fg">
          Trainers and evaluators
        </h2>
        {readOnly ? null : <Button onClick={() => setAssigning(true)}>Assign trainer or evaluator</Button>}
      </div>
      <Boundary state={grants} rows={2}>
        {() => (
          <Table
            caption="Trainers and evaluators"
            columns={[
              { key: "u", header: "Person", cell: (g: BatchStaffGrant) => <span className="font-mono text-xs">{g.user_id}</span> },
              { key: "r", header: "Role", cell: (g) => ROLE_LABEL[g.role_key] ?? g.role_key },
              { key: "d", header: "Since", cell: (g) => formatDate(g.granted_at) },
              ...(readOnly
                ? []
                : [
                    {
                      key: "a",
                      header: <span className="sr-only">Actions</span>,
                      align: "right" as const,
                      cell: (g: BatchStaffGrant) => (
                        <Button size="sm" variant="secondary" onClick={() => setRevoke(g)} aria-label={`Remove ${ROLE_LABEL[g.role_key] ?? g.role_key} ${g.user_id}`}>
                          Remove
                        </Button>
                      ),
                    },
                  ]),
            ]}
            rows={rows}
            rowKey={(g) => g.grant_id}
            empty={{ title: "No trainer or evaluator assigned yet" }}
          />
        )}
      </Boundary>
      <ActionDialog
        open={assigning}
        onClose={resetAssign}
        title="Assign a trainer or evaluator"
        description="Trainers author and grade for this batch. Evaluators grade and publish results but cannot author content."
        submitLabel="Assign"
        validate={() => (!user ? "Choose a person." : !reason.trim() ? "Enter a reason." : null)}
        onSubmit={async () => toOutcome(await api.post("rbac/grants", { user_id: user!.user_id, role_key: role, scope_type: "batch", scope_id: batchId, expires_at: null, reason: reason.trim() }, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind !== "ok") return;
          toast.show({ tone: "success", title: `${ROLE_LABEL[role]} assigned` });
          resetAssign();
          void grants.reload();
        }}
      >
        <div className="space-y-3">
          <FormField label="Role" required>
            {(p) => <Select {...p} value={role} onChange={(e) => setRole(e.target.value)} options={BATCH_STAFF_ROLES.map((r) => ({ value: r.value, label: r.label }))} />}
          </FormField>
          {assigning ? <UserPicker value={user} onChange={setUser} /> : null}
          <FormField label="Reason" required>
            {(p) => <TextArea {...p} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}
          </FormField>
        </div>
      </ActionDialog>
      <ActionDialog
        open={revoke !== null}
        onClose={() => {
          setRevoke(null);
          setRevokeReason("");
        }}
        title="Remove this assignment?"
        submitLabel="Remove"
        danger
        validate={() => (revokeReason.trim() ? null : "Enter a reason.")}
        onSubmit={async () => toOutcome(await api.post(`rbac/grants/${encodeURIComponent(revoke!.grant_id)}/revoke`, { reason: revokeReason.trim() }, { idempotencyKey: true }))}
        onDone={(o) => {
          if (o.kind !== "ok") return;
          toast.show({ tone: "success", title: "Assignment removed" });
          setRevokeReason("");
          void grants.reload();
        }}
      >
        <FormField label="Reason" required>
          {(p) => <TextArea {...p} value={revokeReason} onChange={(e) => setRevokeReason(e.target.value)} maxLength={500} />}
        </FormField>
      </ActionDialog>
    </section>
  );
}
