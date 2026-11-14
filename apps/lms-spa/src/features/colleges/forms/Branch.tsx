/**
 * Branch add / edit (old forms.addBranch / forms.editBranch). Edit has "Delete branch".
 *
 *   await addBranch({ college_id: "c9" })
 *   await editBranch(branch)     // or editBranch(branchId)
 */
import { useState } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import type { Branch } from "../lib/types";
import { Button } from "../ui/Button";
import { confirm, toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { DialogForm, SelectField, TextAreaField, TextField } from "./kit";
import { BASIS_OPTS, CATEGORY_OPTS } from "./labels";
import { LoadingModal } from "./loading";
import { errMsg, num, str, validationError } from "./util";

type B = Partial<Branch> & Record<string, unknown>;
export type BranchVals = {
  code: string;
  name: string;
  category: string;
  is_relevant: string;
  intake_per_year: string;
  intake_basis: string;
  intake_source: string;
  intake_year: string;
  strength_total: string;
  final_year: string;
  notes: string;
};

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const YN_DEFAULT = [
  { value: "1", label: "Yes" },
  { value: "0", label: "No" },
];

/** Initial values (old branchFields): verified totals only; estimates are left blank so they keep being estimated. */
export function branchVals(b: B = {}): BranchVals {
  return {
    code: s(b.code),
    name: s(b.name),
    category: s(b.category) || "other",
    is_relevant: b.is_relevant === null || b.is_relevant === undefined ? "" : String(b.is_relevant ? 1 : 0),
    intake_per_year: s(b.intake_per_year),
    intake_basis: s(b.intake_basis) || (b.intake_per_year !== null && b.intake_per_year !== undefined ? "estimated" : "pending"),
    intake_source: s(b.intake_source),
    intake_year: s(b.intake_year),
    strength_total: b.strength_basis === "verified" ? s(b.strength_total) : "",
    final_year: b.final_year_basis === "verified" ? s(b.final_year) : "",
    notes: s(b.notes),
  };
}

/** Request body (old branchBody). */
export function branchBody(v: BranchVals): Record<string, unknown> {
  const body: Record<string, unknown> = {
    code: str(v.code)?.toUpperCase() ?? null,
    name: str(v.name),
    category: v.category,
    intake_per_year: num(v.intake_per_year),
    intake_basis: num(v.intake_per_year) === null ? "pending" : v.intake_basis,
    intake_source: str(v.intake_source),
    intake_year: str(v.intake_year),
    notes: str(v.notes),
  };
  if (v.is_relevant !== "") body.is_relevant = Number(v.is_relevant) ? 1 : 0;
  else body.is_relevant = ["it_core", "it_allied", "circuit"].includes(v.category) ? 1 : 0;
  if (num(v.strength_total) !== null) {
    body.strength_total = num(v.strength_total);
    body.strength_basis = "verified";
  }
  if (num(v.final_year) !== null) {
    body.final_year = num(v.final_year);
    body.final_year_basis = "verified";
  }
  return body;
}

/** Field checks (old checkBranch); throws a validationError. */
export function checkBranch(v: BranchVals): void {
  const errs: Record<string, string> = {};
  if (!str(v.code)) errs.code = "Code is required.";
  if (!str(v.name)) errs.name = "Name is required.";
  if (!CATEGORY_OPTS.some((o) => o.value === v.category)) errs.category = "Choose a category.";
  for (const k of ["intake_per_year", "strength_total", "final_year"] as const) if (num(v[k]) !== null && num(v[k])! < 0) errs[k] = "Cannot be negative.";
  if (num(v.intake_per_year) !== null && v.intake_basis === "verified" && !str(v.intake_source)) errs.intake_source = "Verified figures need a source.";
  if (Object.keys(errs).length) throw validationError(errs);
}

function BranchForm({ open, branch, collegeId, onSaved, onDone }: { open: boolean; branch: B | null; collegeId?: string; onSaved?: (b: Branch) => void; onDone: (r: Branch | null) => void }) {
  const edit = !!branch;
  const [v, setV] = useState<BranchVals>(() => branchVals(branch ?? {}));
  const set = (k: keyof BranchVals) => (x: string) => setV((p) => ({ ...p, [k]: x }));
  const [deleting, setDeleting] = useState(false);

  const del = async () => {
    if (!branch) return;
    const ok = await confirm({ title: "Delete branch?", text: `Delete branch ${branch.code || branch.name}? People keep their records, but the branch link is removed.`, confirmLabel: "Delete" });
    if (!ok) return;
    setDeleting(true);
    try {
      await portalApi.del(`branches/${branch.id}`);
      toast("Branch deleted", "good");
      onDone(null);
    } catch (e) {
      toast(errMsg(e), "bad");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <DialogForm<Branch>
      open={open}
      title={edit ? `Edit branch — ${branch!.code || branch!.name}` : "Add branch"}
      submitLabel={edit ? "Save branch" : "Add branch"}
      extra={
        edit ? (
          <div className="vx-form-danger">
            <Button tone="danger" size="sm" busy={deleting} onClick={() => void del()}>
              Delete branch
            </Button>
          </div>
        ) : null
      }
      onDone={onDone}
      onSubmit={async (key) => {
        checkBranch(v);
        const r = edit
          ? await portalApi.patch<Branch>(`branches/${branch!.id}`, branchBody(v), { idempotencyKey: key })
          : await portalApi.post<Branch>("branches", { college_id: collegeId, ...branchBody(v) }, { idempotencyKey: key });
        toast(edit ? "Branch updated" : `Branch ${v.code.trim().toUpperCase()} added`, "good");
        onSaved?.(r);
        return r ?? (true as unknown as Branch);
      }}
    >
      {(err) => (
        <>
          <TextField name="code" label="Branch code" required value={v.code} onChange={set("code")} help="e.g. CSE, CSM, ECE" error={err.code} />
          <TextField name="name" label="Branch name" required value={v.name} onChange={set("name")} error={err.name} />
          <SelectField
            name="category"
            label="Category"
            required
            placeholder="Choose a category…"
            options={CATEGORY_OPTS}
            value={v.category}
            onChange={set("category")}
            help="Decides whether it is a target branch by default."
            error={err.category}
          />
          <SelectField name="is_relevant" label="Target branch?" placeholder="Default for category" options={YN_DEFAULT} value={v.is_relevant} onChange={set("is_relevant")} error={err.is_relevant} />
          <TextField name="intake_per_year" label="Seats / year" type="number" value={v.intake_per_year} onChange={set("intake_per_year")} error={err.intake_per_year} />
          <SelectField name="intake_basis" label="Seats basis" options={BASIS_OPTS} value={v.intake_basis} onChange={set("intake_basis")} error={err.intake_basis} />
          <TextField name="intake_source" label="Seats source (URL or document)" value={v.intake_source} onChange={set("intake_source")} error={err.intake_source} />
          <TextField name="intake_year" label="Seats year" value={v.intake_year} onChange={set("intake_year")} help="Academic year of the seats figure, e.g. 2023-24" error={err.intake_year} />
          <TextField name="strength_total" label="Total strength, all years (if known)" type="number" value={v.strength_total} onChange={set("strength_total")} help="Leave blank to estimate as intake × 4." error={err.strength_total} />
          <TextField name="final_year" label="Students completing 4-1 (if known)" type="number" value={v.final_year} onChange={set("final_year")} help="Leave blank to estimate from intake." error={err.final_year} />
          <TextAreaField name="notes" label="Notes" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** Edit a branch; loads it when only the id (or a row without `code`) is given. */
export function BranchDialog({ open = true, branch, branchId, collegeId, onSaved, onDone }: { open?: boolean; branch?: B | null; branchId?: number | string | null; collegeId?: string; onSaved?: (b: Branch) => void; onDone: (r: Branch | null) => void }) {
  const needLoad = !!branchId && (!branch || branch.code === undefined);
  const q = usePortalQuery<{ branch: Branch }>(needLoad ? `branches/${branchId}` : null);
  if (needLoad && !q.data) return <LoadingModal open={open} title="Edit branch" error={q.error} loading={q.loading} retry={() => void q.reload()} onClose={() => onDone(null)} what="the branch" />;
  const b = needLoad ? (q.data!.branch as B) : (branch ?? null);
  return <BranchForm open={open} branch={b} collegeId={collegeId} onSaved={onSaved} onDone={onDone} />;
}

/** Old API: forms.addBranch(ctx, {college_id}). */
export function addBranch(opts: { college_id: string; onSaved?: (b: Branch) => void } | string): Promise<Branch | null> {
  const o = typeof opts === "object" ? opts : { college_id: opts };
  if (!o.college_id) {
    toast("Open a college first", "warn");
    return Promise.resolve(null);
  }
  return openDialog<Branch>((done) => <BranchDialog collegeId={o.college_id} onSaved={o.onSaved} onDone={done} />);
}

/** Old API: forms.editBranch(ctx, branch | id). */
export function editBranch(b: B | number | string, opts: { onSaved?: (b: Branch) => void } = {}): Promise<Branch | null> {
  const obj = typeof b === "object" && b ? b : null;
  const id = obj ? obj.id : b;
  return openDialog<Branch>((done) => <BranchDialog branch={obj} branchId={id as number} onSaved={opts.onSaved} onDone={done} />);
}
