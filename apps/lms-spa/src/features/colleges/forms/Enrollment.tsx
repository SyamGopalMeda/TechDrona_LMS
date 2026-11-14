/**
 * Enrollment dialogs (old forms.recordEnrollment / forms.editEnrollment).
 *
 *   await recordEnrollment({ college_id: "c9", person_id: 12 })     // without college_id: pick the college first
 *   await editEnrollment(enrollment)                                 // or editEnrollment(id)
 */
import "../styles/views/ops.css";
import { useMemo, useState } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import type { CollegeDetail, Course, Enrollment, PortalMeta } from "../lib/types";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { confirm, toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { DialogForm, KEEP_OPEN, SelectField, TextAreaField, TextField } from "./kit";
import { STAGE_LABEL, STAGE_OPTS } from "./labels";
import { LoadingModal, META_TTL } from "./loading";
import { pickCollege } from "./PickCollege";
import { confirmInactiveCredit, personBranchIds, personOptLabel, type TeamPerson } from "./team";
import { branchOpts, errMsg, num, sortBranches, str, today, validationError, wholeOrNull } from "./util";

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const courseLabel = (c: Course) => `${c.name}${c.price_inr !== null && c.price_inr !== undefined ? ` — ${fmt.inr(c.price_inr)}` : ""}`;
const ROLE_RANK: Record<string, number> = { ambassador: 0, ambassador_lead: 1, college_lead: 2 };

export interface RecordEnrollmentOptions {
  college_id?: string | null;
  person_id?: number | string | null;
  branch_id?: number | string | null;
  course_id?: number | string | null;
  stage?: string | null;
  onSaved?: (e: Enrollment) => void;
}

/* ------------------------------------------------------------------ record */

export function RecordEnrollmentDialog({ open = true, collegeId, onDone, ...opts }: Omit<RecordEnrollmentOptions, "college_id"> & { open?: boolean; collegeId: string; onDone: (r: Enrollment | null) => void }) {
  const d = usePortalQuery<CollegeDetail>(`colleges/${encodeURIComponent(collegeId)}`);
  const m = usePortalQuery<PortalMeta>("meta", { ttl: META_TTL });
  const title = `Record enrollment — ${d.data?.college?.short_name || d.data?.college?.name || collegeId}`;
  if (!d.data || !m.data)
    return <LoadingModal open={open} title={title} error={d.error ?? m.error} loading={d.loading || m.loading} retry={() => void (d.data ? m.reload() : d.reload())} onClose={() => onDone(null)} />;
  return <RecordForm open={open} title={title} collegeId={collegeId} detail={d.data} meta={m.data} opts={opts} onDone={onDone} />;
}

function RecordForm({ open, title, collegeId, detail, meta, opts, onDone }: { open: boolean; title: string; collegeId: string; detail: CollegeDetail; meta: PortalMeta; opts: Omit<RecordEnrollmentOptions, "college_id">; onDone: (r: Enrollment | null) => void }) {
  const branches = useMemo(() => sortBranches(detail.branches ?? []), [detail.branches]);
  const people = useMemo(
    () =>
      ((detail.people ?? []) as unknown as TeamPerson[])
        .filter((p) => p.status !== "inactive" || (opts.person_id !== null && opts.person_id !== undefined && Number(p.id) === Number(opts.person_id)))
        .map((p) => ({ ...p, _b: personBranchIds(p, detail.branches as never) }))
        .sort((a, b) => (ROLE_RANK[a.role] ?? 0) - (ROLE_RANK[b.role] ?? 0) || a.full_name.localeCompare(b.full_name)),
    [detail, opts.person_id],
  );
  const courses = (meta.courses ?? []).filter((c) => c.active !== 0);
  const priceOf = (cid: string) => s(courses.find((c) => String(c.id) === String(cid))?.price_inr);
  const firstCourse = s(opts.course_id || (courses.length === 1 ? courses[0]!.id : ""));
  const credited = opts.person_id ? people.find((p) => Number(p.id) === Number(opts.person_id)) : null;
  const branch0 = s(opts.branch_id || (credited && credited._b.length === 1 ? credited._b[0] : ""));
  const [v, setV] = useState({
    stage: s(opts.stage) || "confirmed",
    enrolled_on: today(),
    course_id: firstCourse,
    amount_inr: firstCourse ? priceOf(firstCourse) : "",
    branch_id: branch0,
    person_id: s(opts.person_id),
    student_name: "",
    student_contact: "",
    notes: "",
  });
  const set = (k: keyof typeof v) => (x: string) => setV((p) => ({ ...p, [k]: x }));
  const amountRule = (x: string) => (x !== "" && Number.isNaN(wholeOrNull(x)) ? "Enter the amount in whole rupees (0 or more)." : "");
  const dateRule = (x: string) => (!x ? "Date is required." : x > today() ? "Date cannot be in the future." : "");
  // only people covering the chosen branch (college leads always)
  const creditOptions = people.map((p) => ({ value: String(p.id), label: personOptLabel(p), disabled: !!v.branch_id && p.role !== "college_lead" && !p._b.includes(Number(v.branch_id)) }));
  const visibleCredit = creditOptions.filter((o) => !o.disabled);

  return (
    <DialogForm<Enrollment>
      open={open}
      title={title}
      submitLabel="Save record"
      intro={
        <p className="vf-note">
          <Icon name="info" size={16} /> Store only what is needed. Student name and contact are optional — leave them blank unless the team needs them for follow-up.
        </p>
      }
      onDone={onDone}
      onSubmit={async (key) => {
        const errs: Record<string, string> = {};
        if (dateRule(v.enrolled_on)) errs.enrolled_on = dateRule(v.enrolled_on);
        if (amountRule(v.amount_inr)) errs.amount_inr = amountRule(v.amount_inr);
        if (courses.length && !v.course_id) errs.course_id = "Course is required";
        if (Object.keys(errs).length) throw validationError(errs);
        const who = people.find((p) => String(p.id) === v.person_id);
        if (!(await confirmInactiveCredit(who))) return KEEP_OPEN;
        const r = await portalApi.post<Enrollment>(
          "enrollments",
          {
            college_id: collegeId,
            branch_id: num(v.branch_id),
            course_id: num(v.course_id),
            person_id: num(v.person_id),
            stage: v.stage || "confirmed",
            enrolled_on: v.enrolled_on,
            amount_inr: wholeOrNull(v.amount_inr),
            student_name: str(v.student_name),
            student_contact: str(v.student_contact),
            notes: str(v.notes),
          },
          { idempotencyKey: key },
        );
        toast(`${v.stage && v.stage !== "confirmed" ? `${STAGE_LABEL[v.stage]} recorded` : "Enrollment recorded"}${who ? ` and credited to ${who.full_name}` : ""}`, "good");
        opts.onSaved?.(r);
        return r ?? (true as unknown as Enrollment);
      }}
    >
      {(err) => (
        <>
          <SelectField
            name="stage"
            label="Stage"
            required
            options={STAGE_OPTS}
            value={v.stage}
            onChange={set("stage")}
            help="Only a confirmed enrollment counts toward targets. Record a lead early and move the same record forward later."
            error={err.stage}
          />
          <TextField
            name="enrolled_on"
            label="Date"
            type="date"
            required
            max={today()}
            value={v.enrolled_on}
            onChange={set("enrolled_on")}
            help="The day this stage was reached (for a confirmed enrollment: the day the student confirmed)."
            error={err.enrolled_on}
          />
          <SelectField
            name="course_id"
            label="Course"
            required={courses.length > 0}
            placeholder={courses.length ? "Choose a course…" : "No courses yet"}
            options={courses.map((c) => ({ value: String(c.id), label: courseLabel(c) }))}
            value={v.course_id}
            onChange={(c) => setV((p) => ({ ...p, course_id: c, amount_inr: priceOf(c) }))}
            help={courses.length ? undefined : "Add courses and prices in Settings."}
            error={err.course_id}
          />
          <TextField
            name="amount_inr"
            label="Amount paid (₹)"
            type="number"
            min={0}
            step={1}
            value={v.amount_inr}
            onChange={set("amount_inr")}
            help="Filled in from the course price. Change it if a discount applied."
            error={err.amount_inr || amountRule(v.amount_inr)}
          />
          <SelectField
            name="branch_id"
            label="Student's branch"
            placeholder="— Branch not known —"
            options={branchOpts(branches)}
            value={v.branch_id}
            onChange={(b) =>
              setV((p) => {
                const still = !p.person_id || people.some((x) => String(x.id) === p.person_id && (!b || x.role === "college_lead" || x._b.includes(Number(b))));
                return { ...p, branch_id: b, person_id: still ? p.person_id : "" };
              })
            }
            error={err.branch_id}
          />
          <SelectField
            name="person_id"
            label="Credit to"
            placeholder="— No one credited —"
            options={visibleCredit}
            value={v.person_id}
            onChange={set("person_id")}
            help="Only people covering the chosen branch are listed (college leads always are)."
            error={err.person_id}
          />
          <TextField name="student_name" label="Student name" placeholder="Optional" value={v.student_name} onChange={set("student_name")} error={err.student_name} />
          <TextField name="student_contact" label="Student phone or email" placeholder="Optional" value={v.student_contact} onChange={set("student_contact")} error={err.student_contact} />
          <TextAreaField name="notes" label="Notes" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** Old API: forms.recordEnrollment(ctx, {college_id, person_id, branch_id, course_id, stage}). */
export async function recordEnrollment(opts: RecordEnrollmentOptions = {}): Promise<Enrollment | null> {
  const collegeId = opts.college_id || (await pickCollege("Record an enrollment"));
  if (!collegeId) return null;
  return openDialog<Enrollment>((done) => <RecordEnrollmentDialog {...opts} collegeId={collegeId} onDone={done} />);
}

/* ------------------------------------------------------------------ edit */

type Enr = Partial<Enrollment> & { id: number; [k: string]: unknown };

export function EditEnrollmentDialog({ open = true, enrollment, onSaved, onDone }: { open?: boolean; enrollment: Enr; onSaved?: (e: Enrollment) => void; onDone: (r: Enrollment | null) => void }) {
  const needLoad = !enrollment.college_id || enrollment.stage === undefined;
  const e = usePortalQuery<Enrollment>(needLoad ? `enrollments/${enrollment.id}` : null);
  const full: Enr | null = needLoad ? (e.data ? { ...enrollment, ...e.data } : null) : enrollment;
  const d = usePortalQuery<CollegeDetail>(full?.college_id ? `colleges/${encodeURIComponent(full.college_id)}` : null);
  const m = usePortalQuery<PortalMeta>("meta", { ttl: META_TTL });
  const title = `Edit enrollment — ${enrollment.student_name || `#${enrollment.id}`}`;
  if (!full || !d.data || !m.data) {
    const err = e.error ?? d.error ?? m.error;
    return <LoadingModal open={open} title={title} error={err} loading={e.loading || d.loading || m.loading} retry={() => void (e.error ? e.reload() : d.error ? d.reload() : m.reload())} onClose={() => onDone(null)} what="the enrollment" />;
  }
  return <EditForm open={open} e={full} detail={d.data} meta={m.data} onSaved={onSaved} onDone={onDone} />;
}

function EditForm({ open, e, detail, meta, onSaved, onDone }: { open: boolean; e: Enr; detail: CollegeDetail; meta: PortalMeta; onSaved?: (e: Enrollment) => void; onDone: (r: Enrollment | null) => void }) {
  const t = today();
  const branches = sortBranches(detail.branches ?? []);
  // same-college people only; the currently credited person stays listed even when inactive
  const people = ((detail.people ?? []) as unknown as TeamPerson[]).filter((p) => p.status !== "inactive" || Number(p.id) === Number(e.person_id));
  const courses = (meta.courses ?? []).filter((c) => c.active !== 0 || Number(c.id) === Number(e.course_id));
  const cname = detail.college?.short_name || detail.college?.name || "this college";
  const [v, setV] = useState({
    stage: s(e.stage) || "confirmed",
    confirmed_on: s(e.confirmed_on) || (e.stage === "confirmed" || !e.stage ? t : ""),
    enrolled_on: s(e.enrolled_on),
    course_id: e.course_id ? String(e.course_id) : "",
    amount_inr: s(e.amount_inr),
    branch_id: e.branch_id ? String(e.branch_id) : "",
    person_id: e.person_id ? String(e.person_id) : "",
    student_name: s(e.student_name),
    student_contact: s(e.student_contact),
    notes: s(e.notes),
  });
  const set = (k: keyof typeof v) => (x: string) => setV((p) => ({ ...p, [k]: x }));
  const [deleting, setDeleting] = useState(false);
  const dateRule = (x: string) => (!x ? "" : !/^\d{4}-\d{2}-\d{2}$/.test(x) ? "Use a date like 2026-11-07." : x > t ? "Date cannot be in the future." : "");

  const del = async () => {
    const ok = await confirm({
      title: "Delete this enrollment?",
      text: `${e.student_name || `Enrollment #${e.id}`} (${STAGE_LABEL[s(e.stage)] || e.stage}) is removed for good and stops counting toward targets. The change is kept in the audit history. To record a refund, set the stage to “Dropped / refunded” instead.`,
      confirmLabel: "Delete enrollment",
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await portalApi.del(`enrollments/${e.id}`);
      toast("Enrollment deleted", "good");
      onDone(null);
    } catch (x) {
      toast(errMsg(x), "bad");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <DialogForm<Enrollment>
      open={open}
      title={`Edit enrollment — ${e.student_name || `#${e.id}`}`}
      submitLabel="Save"
      extra={
        <div className="vf-danger v-person-dlg__danger">
          <span className="vx-small vx-muted">Recorded by mistake?</span>
          <Button tone="ghost" size="sm" icon="trash" busy={deleting} onClick={() => void del()}>
            Delete
          </Button>
        </div>
      }
      onDone={onDone}
      onSubmit={async (key) => {
        const errs: Record<string, string> = {};
        if (!v.enrolled_on) errs.enrolled_on = "Date is required.";
        else if (dateRule(v.enrolled_on)) errs.enrolled_on = dateRule(v.enrolled_on);
        if (v.stage === "confirmed" && v.confirmed_on && dateRule(v.confirmed_on)) errs.confirmed_on = dateRule(v.confirmed_on);
        if (v.stage === "confirmed" && v.confirmed_on && v.enrolled_on && v.confirmed_on < v.enrolled_on) errs.confirmed_on = "Cannot be before the first recorded date.";
        if (Number.isNaN(wholeOrNull(v.amount_inr))) errs.amount_inr = "Enter whole rupees (0 or more).";
        if (Object.keys(errs).length) throw validationError(errs);
        const next: Record<string, unknown> = {
          stage: v.stage,
          enrolled_on: v.enrolled_on,
          course_id: num(v.course_id),
          amount_inr: wholeOrNull(v.amount_inr),
          branch_id: num(v.branch_id),
          person_id: num(v.person_id),
          student_name: str(v.student_name),
          student_contact: str(v.student_contact),
          notes: str(v.notes),
        };
        if (v.stage === "confirmed" && v.confirmed_on) next.confirmed_on = v.confirmed_on;
        const body: Record<string, unknown> = {};
        for (const [k, val] of Object.entries(next)) if ((val ?? null) !== ((e as Record<string, unknown>)[k] ?? null)) body[k] = val;
        if (!Object.keys(body).length) {
          toast("No changes to save", "good");
          return true as unknown as Enrollment;
        }
        if ("person_id" in body && !(await confirmInactiveCredit(people.find((p) => String(p.id) === v.person_id)))) return KEEP_OPEN;
        const r = await portalApi.patch<Enrollment>(`enrollments/${e.id}`, body, { idempotencyKey: key });
        toast(`Saved · stage ${STAGE_LABEL[s(r?.stage ?? v.stage)] || r?.stage || ""}`, "good");
        onSaved?.(r);
        return r ?? (true as unknown as Enrollment);
      }}
    >
      {(err) => (
        <>
          <SelectField
            name="stage"
            label="Stage"
            required
            options={STAGE_OPTS}
            value={v.stage}
            onChange={(st) => setV((p) => ({ ...p, stage: st, confirmed_on: st === "confirmed" && !p.confirmed_on ? t : p.confirmed_on }))}
            help="Moving the stage updates this record. Only “Confirmed” counts toward targets."
            error={err.stage}
          />
          <TextField
            name="confirmed_on"
            label="Confirmed on"
            type="date"
            max={t}
            hidden={v.stage !== "confirmed"}
            value={v.confirmed_on}
            onChange={set("confirmed_on")}
            help="The day the student confirmed. Counts toward targets from this date."
            error={err.confirmed_on || dateRule(v.confirmed_on)}
          />
          <TextField name="enrolled_on" label="First recorded on" type="date" required max={t} value={v.enrolled_on} onChange={set("enrolled_on")} error={err.enrolled_on} />
          <SelectField
            name="course_id"
            label="Course"
            placeholder="— Course not set —"
            options={courses.map((c) => ({ value: String(c.id), label: courseLabel(c) }))}
            value={v.course_id}
            onChange={(cid) =>
              setV((p) => {
                const pr = courses.find((c) => String(c.id) === cid)?.price_inr;
                return { ...p, course_id: cid, amount_inr: !p.amount_inr && pr !== null && pr !== undefined ? String(pr) : p.amount_inr };
              })
            }
            error={err.course_id}
          />
          <TextField name="amount_inr" label="Amount paid (₹)" type="number" min={0} step={1} value={v.amount_inr} onChange={set("amount_inr")} error={err.amount_inr} />
          <SelectField name="branch_id" label="Student's branch" placeholder="— Branch not known —" options={branchOpts(branches)} value={v.branch_id} onChange={set("branch_id")} error={err.branch_id} />
          <SelectField
            name="person_id"
            label="Credit to"
            placeholder="— No one credited —"
            options={people.map((p) => ({ value: String(p.id), label: personOptLabel(p) }))}
            value={v.person_id}
            onChange={set("person_id")}
            help={`Only people of ${cname} can be credited.`}
            error={err.person_id}
          />
          <TextField name="student_name" label="Student name" value={v.student_name} onChange={set("student_name")} error={err.student_name} />
          <TextField name="student_contact" label="Student phone or email" value={v.student_contact} onChange={set("student_contact")} error={err.student_contact} />
          <TextAreaField name="notes" label="Notes" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** Old API: forms.editEnrollment(ctx, e | id). Resolves with the saved record (null when cancelled or deleted). */
export function editEnrollment(e: Enr | number, opts: { onSaved?: (e: Enrollment) => void } = {}): Promise<Enrollment | null> {
  const obj: Enr = typeof e === "object" && e ? e : { id: Number(e) };
  return openDialog<Enrollment>((done) => <EditEnrollmentDialog enrollment={obj} onSaved={opts.onSaved} onDone={done} />);
}
