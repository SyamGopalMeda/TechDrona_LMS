/**
 * "Log activity" (old forms.logActivity): a campus visit, call, session… with students reached.
 *
 *   await logActivity({ college_id: "c9", type: "visit" })      // without college_id: pick the college first
 */
import { useState } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import type { Activity, CollegeDetail } from "../lib/types";
import { toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { DialogForm, SelectField, TextAreaField, TextField } from "./kit";
import { ACT_OPTS, ROLE_LABEL } from "./labels";
import { LoadingModal } from "./loading";
import { pickCollege } from "./PickCollege";
import { branchOpts, num, str, today, validationError, wholeOrNull } from "./util";

export interface LogActivityOptions {
  college_id?: string | null;
  type?: string;
  branch_id?: number | string | null;
  person_id?: number | string | null;
  onSaved?: (a: Activity) => void;
}

const reachRule = (v: string) => (v !== "" && Number.isNaN(wholeOrNull(v)) ? "Enter a whole number (0 or more)." : "");
const dateRule = (v: string) => (!v ? "Date is required." : v > today() ? "Date cannot be in the future." : "");

export function ActivityDialog({ open = true, collegeId, onDone, ...opts }: Omit<LogActivityOptions, "college_id"> & { open?: boolean; collegeId: string; onDone: (r: Activity | null) => void }) {
  const { data, error, loading, reload } = usePortalQuery<CollegeDetail>(`colleges/${encodeURIComponent(collegeId)}`);
  const title = `Log activity — ${data?.college?.short_name || data?.college?.name || collegeId}`;
  const [v, setV] = useState({
    type: opts.type || "visit",
    on_date: today(),
    branch_id: opts.branch_id ? String(opts.branch_id) : "",
    person_id: opts.person_id ? String(opts.person_id) : "",
    students_reached: "",
    notes: "",
  });
  const set = (k: keyof typeof v) => (x: string) => setV((p) => ({ ...p, [k]: x }));
  if (!data) return <LoadingModal open={open} title={title} error={error} loading={loading} retry={() => void reload()} onClose={() => onDone(null)} />;
  const people = (data.people ?? []).filter((p) => p.status !== "inactive");
  return (
    <DialogForm<Activity>
      open={open}
      title={title}
      submitLabel="Log activity"
      onDone={onDone}
      onSubmit={async (key) => {
        const errs: Record<string, string> = {};
        if (reachRule(v.students_reached)) errs.students_reached = reachRule(v.students_reached);
        if (dateRule(v.on_date)) errs.on_date = dateRule(v.on_date);
        if (Object.keys(errs).length) throw validationError(errs);
        const r = await portalApi.post<Activity>(
          "activities",
          { college_id: collegeId, branch_id: num(v.branch_id), person_id: num(v.person_id), on_date: v.on_date, type: v.type, students_reached: wholeOrNull(v.students_reached) ?? 0, notes: str(v.notes) },
          { idempotencyKey: key },
        );
        const n = wholeOrNull(v.students_reached);
        toast(`Activity logged${n ? ` — ${fmt.num(n)} students reached` : ""}`, "good");
        opts.onSaved?.(r);
        return r ?? (true as unknown as Activity);
      }}
    >
      {(err) => (
        <>
          <SelectField name="type" label="What happened?" required options={ACT_OPTS} value={v.type} onChange={set("type")} error={err.type} />
          <TextField name="on_date" label="Date" type="date" required max={today()} value={v.on_date} onChange={set("on_date")} error={err.on_date || (v.on_date ? dateRule(v.on_date) : "")} />
          <SelectField name="branch_id" label="Branch" placeholder="— Whole college —" options={branchOpts(data.branches)} value={v.branch_id} onChange={set("branch_id")} error={err.branch_id} />
          <SelectField
            name="person_id"
            label="Done by"
            placeholder="— Tech Drona staff / not listed —"
            options={people.map((p) => ({ value: String(p.id), label: `${p.full_name} (${ROLE_LABEL[p.role] ?? p.role})` }))}
            value={v.person_id}
            onChange={set("person_id")}
            error={err.person_id}
          />
          <TextField
            name="students_reached"
            label="Students reached"
            type="number"
            min={0}
            step={1}
            placeholder="0"
            help="How many students heard about the courses. Leave blank if none."
            value={v.students_reached}
            onChange={set("students_reached")}
            error={err.students_reached || reachRule(v.students_reached)}
          />
          <TextAreaField name="notes" label="Notes" placeholder="What was discussed? What happens next?" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** Old API: forms.logActivity(ctx, {college_id, type, branch_id, person_id}). */
export async function logActivity(opts: LogActivityOptions = {}): Promise<Activity | null> {
  const collegeId = opts.college_id || (await pickCollege("Log an activity"));
  if (!collegeId) return null;
  return openDialog<Activity>((done) => <ActivityDialog {...opts} collegeId={collegeId} onDone={done} />);
}
