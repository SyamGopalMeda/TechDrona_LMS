"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, Dialog, FormField, Input, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError, isApiError } from "@/lib/api/errors";
import { useTrainerBatches } from "@/features/trainer/lib/batches";
import type { BatchMember } from "@/features/batches/lib/types";
import { ENGINES, staffApi } from "./api";
import type { AllocationIn, AssignmentOut, GradingEngine } from "./types";
import { localInputToIso } from "@/lib/time";

export interface Person {
  user_id: string;
  full_name: string | null;
  email?: string | null;
  /** Batch role from an RBAC grant, when the name is not known (Admin view). */
  role?: string;
}

/**
 * Staff who can be named as evaluators for an allocation to `batchId` (WS4 `evaluator_ids`):
 *  - the batch's staff members (`GET batches/{id}/members`, member_role ≠ student), readable by
 *    the batch trainer;
 *  - for Admin (who can read RBAC grants), every trainer / evaluator granted on that batch.
 * The api re-checks each id (422 `not_evaluator`). The old `orgs/{id}/members` roster is gone.
 */
export function useEvaluatorPeople(batchId: string | null) {
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!batchId) {
      setPeople([]);
      return;
    }
    let live = true;
    const b = encodeURIComponent(batchId);
    setLoading(true);
    setError(null);
    const grants = api
      .get<{ data: { user_id: string; role_key: string }[] }>("rbac/grants", { query: { scope_type: "batch", scope_id: batchId } })
      .then((r) => r.data.filter((g) => GRADER_ROLES.has(g.role_key)))
      // Only Admin may read grants; trainers fall back to the batch roster alone.
      .catch(() => [] as { user_id: string; role_key: string }[]);
    Promise.all([api.get<{ data: BatchMember[] }>(`batches/${b}/members`), grants])
      .then(([members, granted]) => {
        if (!live) return;
        const out = new Map<string, Person>();
        for (const m of members.data ?? []) if (m.member_role !== "student") out.set(m.user_id, { user_id: m.user_id, full_name: m.full_name });
        for (const g of granted) if (!out.has(g.user_id)) out.set(g.user_id, { user_id: g.user_id, full_name: null, role: g.role_key });
        setPeople([...out.values()]);
      })
      .catch((err: unknown) => live && setError(err))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [batchId]);
  return { people, error, loading };
}

const GRADER_ROLES = new Set(["trainer", "evaluator"]);

/** Plain-language text for the WS4 allocation refusals. */
export function allocationErrorText(err: unknown): string | null {
  if (!isApiError(err)) return null;
  const codes = [err.code, ...(err.problem?.errors ?? []).map((f) => f.code)];
  if (codes.includes("not_evaluator")) return "One of the chosen evaluators can't grade (they need a Trainer or Evaluator role, or to be company staff). Remove them and try again.";
  if (codes.includes("conflict_of_interest")) return "You can't do this for yourself.";
  if (codes.includes("not_allocated")) return "That learner isn't in the batch this assignment is allocated to.";
  return null;
}

interface FormState {
  batch_id: string;
  visible_from: string;
  visible_until: string;
  start_at: string;
  due_at: string;
}

/** Client-side checks before POST /assignments/{id}/allocations (the api re-validates). */
export function validateAllocation(f: FormState): Record<string, string> {
  const errs: Record<string, string> = {};
  const t = (v: string) => (v ? Date.parse(v) : NaN);
  if (!f.batch_id) errs.batch_id = "Choose a batch.";
  if (!f.due_at) errs.due_at = "Choose when learners must submit by.";
  const vf = t(f.visible_from);
  const vu = t(f.visible_until);
  const st = t(f.start_at);
  const due = t(f.due_at);
  if (!Number.isNaN(vf) && !Number.isNaN(vu) && vu <= vf) errs.visible_until = "Must be after “Visible from”.";
  if (!Number.isNaN(st) && !Number.isNaN(vf) && st < vf) errs.start_at = "Can't be before “Visible from”.";
  if (!Number.isNaN(due) && !Number.isNaN(st) && due <= st) errs.due_at = "Must be after “Can start at”.";
  if (!Number.isNaN(due) && !Number.isNaN(vu) && due > vu) errs.due_at = "Must be on or before “Visible until”.";
  return errs;
}

export interface AllocateDialogProps {
  open: boolean;
  onClose: () => void;
  assignment: AssignmentOut;
  sections: { id: string; title: string }[];
  marksOk: boolean;
  onAllocated: () => void | Promise<void>;
}

export function AllocateDialog({ open, onClose, assignment, sections, marksOk, onAllocated }: AllocateDialogProps) {
  const toast = useToast();
  const { batches, loading: batchesLoading } = useTrainerBatches();
  const [f, setF] = useState<FormState>({ batch_id: assignment.batch_id ?? "", visible_from: "", visible_until: "", start_at: "", due_at: "" });
  const [engines, setEngines] = useState<Record<string, GradingEngine>>({});
  const [evaluators, setEvaluators] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setF({ batch_id: assignment.batch_id ?? "", visible_from: "", visible_until: "", start_at: "", due_at: "" });
      setEngines({});
      setEvaluators([]);
      setErrors({});
      setFormError(null);
      setSearch("");
    }
  }, [open, assignment.batch_id]);

  const people = useEvaluatorPeople(open && f.batch_id ? f.batch_id : null);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return people.people.filter((p) => !q || (p.full_name ?? "").toLowerCase().includes(q) || (p.email ?? "").toLowerCase().includes(q));
  }, [people.people, search]);

  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  const submit = async () => {
    setFormError(null);
    const errs = validateAllocation(f);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const body: AllocationIn = {
      batch_id: f.batch_id,
      visible_from: localInputToIso(f.visible_from),
      visible_until: localInputToIso(f.visible_until),
      start_at: localInputToIso(f.start_at),
      due_at: localInputToIso(f.due_at)!,
      section_engines: Object.fromEntries(sections.map((s) => [s.id, engines[s.id] ?? "pure_ai"])),
      evaluator_ids: evaluators,
    };
    setBusy(true);
    try {
      await staffApi.allocate(assignment.id, body);
      toast.show({ tone: "success", title: "Assignment allocated" });
      onClose();
      await onAllocated();
    } catch (err) {
      const known = allocationErrorText(err);
      if (known && err instanceof ApiError && err.problem?.errors?.some((e) => e.field.replace(/^body\./, "").startsWith("evaluator_ids"))) {
        setErrors({ evaluator_ids: known });
      } else if (known) {
        setFormError(known);
      } else if (err instanceof ApiError && err.problem?.errors?.length) {
        const fe: Record<string, string> = {};
        const general: string[] = [];
        for (const e of err.problem.errors) {
          const key = e.field.replace(/^body\./, "");
          if (key in f || key.startsWith("section_engines") || key === "evaluator_ids") fe[key.split(".")[0]!] ??= e.message;
          else general.push(e.message);
        }
        setErrors(fe);
        setFormError(general.join(" ") || (Object.keys(fe).length ? null : err.detail));
      } else if (err instanceof ApiError) {
        setFormError(err.detail);
      } else {
        setFormError("Couldn't allocate the assignment. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  const dateField = (k: keyof FormState, label: string, hint: string, required = false) => (
    <FormField label={label} hint={hint} error={errors[k]} required={required}>
      {(p) => <Input {...p} type="datetime-local" value={f[k]} onChange={set(k)} />}
    </FormField>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title={`Allocate “${assignment.title}”`}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            Allocate to batch
          </Button>
        </>
      }
    >
      <div className="max-h-[70vh] space-y-5 overflow-y-auto pr-1">
        {!marksOk ? (
          <p role="status" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
            Question marks don&apos;t add up to the total yet. Fix them in the editor before allocating.
          </p>
        ) : null}
        {formError ? (
          <p role="alert" className="rounded-md border border-danger-border bg-danger-subtle p-3 text-sm text-danger-fg">
            {formError}
          </p>
        ) : null}
        <FormField label="Batch" required error={errors.batch_id}>
          {(p) => (
            <Select
              {...p}
              value={f.batch_id}
              onChange={set("batch_id")}
              placeholder={batchesLoading ? "Loading batches…" : "Choose a batch…"}
              options={(batches ?? []).map((b) => ({ value: b.id, label: b.name }))}
            />
          )}
        </FormField>

        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold text-fg">Schedule</legend>
          <p className="text-xs text-fg-muted">
            The assignment appears to learners from “Visible from” until “Visible until”. They can open the questions once “Can start at” passes and must hand
            in before “Must submit by”. You can give individual learners extra time later.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {dateField("visible_from", "Visible from", "Leave empty to show it right away.")}
            {dateField("visible_until", "Visible until", "Leave empty to keep it listed.")}
            {dateField("start_at", "Can start at", "Leave empty to allow starting as soon as it's visible.")}
            {dateField("due_at", "Must submit by", "Submissions close at this time.", true)}
          </div>
        </fieldset>

        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold text-fg">Grading engine per section</legend>
          {errors.section_engines ? (
            <p role="alert" className="text-xs font-medium text-danger-fg">
              {errors.section_engines}
            </p>
          ) : null}
          {sections.length === 0 ? <p className="text-sm text-fg-muted">Add a section first.</p> : null}
          {sections.map((s) => {
            const value = engines[s.id] ?? "pure_ai";
            return (
              <FormField key={s.id} label={s.title} hint={ENGINES.find((e) => e.value === value)?.description}>
                {(p) => (
                  <Select
                    {...p}
                    value={value}
                    onChange={(e) => setEngines((x) => ({ ...x, [s.id]: e.target.value as GradingEngine }))}
                    options={ENGINES.map((e) => ({ value: e.value, label: e.label }))}
                  />
                )}
              </FormField>
            );
          })}
        </fieldset>

        <fieldset className="space-y-3 rounded-lg border border-line p-3">
          <legend className="px-1 text-sm font-semibold text-fg">Evaluators (optional)</legend>
          <FormField label="Search people">
            {(p) => <Input {...p} type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or email" />}
          </FormField>
          {errors.evaluator_ids ? (
            <p role="alert" className="text-xs font-medium text-danger-fg">
              {errors.evaluator_ids}
            </p>
          ) : null}
          {!f.batch_id ? (
            <p className="text-sm text-fg-muted">Choose a batch to list its staff.</p>
          ) : people.loading ? (
            <p className="text-sm text-fg-muted" role="status">
              Loading people…
            </p>
          ) : people.error ? (
            <p className="text-sm text-fg-muted">We couldn&apos;t load the staff list. You can allocate without extra evaluators.</p>
          ) : shown.length === 0 ? (
            <p className="text-sm text-fg-muted">No staff found.</p>
          ) : (
            <ul className="max-h-48 space-y-1 overflow-y-auto" aria-label="Staff">
              {shown.map((p) => {
                const id = `eval-${p.user_id}`;
                return (
                  <li key={p.user_id} className="flex items-center gap-2">
                    <input
                      id={id}
                      type="checkbox"
                      className="h-4 w-4 accent-[var(--td-brand)]"
                      checked={evaluators.includes(p.user_id)}
                      onChange={(e) => setEvaluators((x) => (e.target.checked ? [...x, p.user_id] : x.filter((y) => y !== p.user_id)))}
                    />
                    <label htmlFor={id} className="text-sm text-fg">
                      {p.full_name ?? (p.role ? `${p.role === "evaluator" ? "Evaluator" : "Trainer"} · ${p.user_id.slice(0, 8)}` : "Unnamed")}
                      {p.email ? <span className="text-fg-muted"> · {p.email}</span> : null}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </fieldset>
      </div>
    </Dialog>
  );
}
