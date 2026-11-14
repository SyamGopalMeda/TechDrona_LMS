/**
 * Follow-up dialogs (old followups.js openFollowupForm / markDone / reschedule / bulkSnooze + forms.addFollowup):
 * ONE create / edit form used everywhere, "Mark follow-up done" (optionally scheduling the next one) and
 * "Reschedule" (one or many).
 *
 *   await addFollowup({ scope_type: "college", scope_id: "c9", label: "KLU" })
 *   await openFollowupForm({ row })                       // edit (with Delete)
 *   await markFollowupDone(row)  ·  await rescheduleFollowup(row)  ·  await rescheduleFollowups(ids)
 */
import "../styles/views/ops.css";
import { useMemo, useState } from "react";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { daysUntil, fmt } from "../lib/fmt";
import { usePortalSession } from "../lib/session";
import type { CollegeDetail, CollegeRow, Followup, Person } from "../lib/types";
import { Button } from "../ui/Button";
import { Field } from "../ui/Form";
import { confirm, toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { CheckField, DangerZone, DialogForm, QuickDates, SelectField, TextAreaField, TextField } from "./kit";
import { FOLLOWUP_SCOPE_LABEL, ISSUES, ISSUE_HELP, ROLE_LABEL } from "./labels";
import { addDays, errMsg, rowsOf, today, validationError } from "./util";

export type FollowupScope = "college" | "branch" | "person";

/** What the dialogs need to know about a follow-up row (a Followup plus the label of what it is about). */
export type FollowupRow = Followup & { _scope?: { label?: string | null } };

export interface FollowupPreset {
  scope_type?: FollowupScope;
  scope_id?: string | number | null;
  college_id?: string | null;
  title?: string | null;
  issue?: string | null;
}

export interface FollowupFormOptions {
  /** colleges / people lists the caller already has (else loaded) */
  data?: { colleges?: CollegeRow[]; people?: Person[] };
  /** edit this follow-up */
  row?: FollowupRow | null;
  preset?: FollowupPreset;
  /** new follow-up about a fixed record (preset scope) */
  lockScope?: boolean;
  scopeLabel?: string | null;
  onSaved?: () => void;
}

type PersonRow = Person & { college_short_name?: string | null };
const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));

/** Loads colleges + people for the follow-up form unless the caller passed them. */
function useLists(data: FollowupFormOptions["data"]) {
  const c = usePortalQuery<unknown>(data?.colleges ? null : "colleges", { ttl: 60_000 });
  const p = usePortalQuery<unknown>(data?.people ? null : "people", { query: { page_size: 1000 }, ttl: 60_000 });
  const colleges = useMemo(() => data?.colleges ?? rowsOf<CollegeRow>(c.data), [data?.colleges, c.data]);
  const people = useMemo(() => data?.people ?? rowsOf<PersonRow>(p.data), [data?.people, p.data]);
  return { colleges, people: people as PersonRow[], loading: (!data?.colleges && c.loading) || (!data?.people && p.loading) };
}

export function FollowupDialog({ open = true, onDone, ...opts }: FollowupFormOptions & { open?: boolean; onDone: (saved: boolean | null) => void }) {
  const { colleges, people, loading } = useLists(opts.data);
  const { user } = usePortalSession();
  const row = opts.row ?? null;
  const preset = Object.fromEntries(Object.entries(opts.preset ?? {}).filter(([, v]) => v !== undefined && v !== null)) as FollowupPreset;
  const init = { scope_type: "college" as FollowupScope, issue: "other", due_date: addDays(today(), 3), ...preset, ...(row ?? {}) } as FollowupPreset & Partial<Followup>;
  const lock = !!opts.lockScope && !row;

  const initCollege = (() => {
    if (init.scope_type === "college") return s(init.scope_id);
    if (init.college_id) return s(init.college_id);
    if (init.scope_type === "person") return s(people.find((p) => String(p.id) === String(init.scope_id))?.college_id);
    return "";
  })();

  const [scopeType, setScopeType] = useState<FollowupScope>(init.scope_type ?? "college");
  const [college, setCollege] = useState(initCollege);
  const [branch, setBranch] = useState(init.scope_type === "branch" ? s(init.scope_id) : "");
  const [person, setPerson] = useState(init.scope_type === "person" ? s(init.scope_id) : "");
  const [issue, setIssue] = useState(s(init.issue) || "other");
  const [title, setTitle] = useState(s(init.title));
  const [owner, setOwner] = useState<string | null>(null);
  const [due, setDue] = useState(s(init.due_date));
  const [last, setLast] = useState(s(init.last_contact));
  const [notes, setNotes] = useState(s(init.notes));
  const [deleting, setDeleting] = useState(false);

  // people may load after mount: the person's college and the owner name follow them until edited
  const collegeVal = college || initCollege;
  const ownerInit = s(init.owner_name) || s(people.find((p) => String(p.id) === String(init.owner_person_id))?.full_name) || (row ? "" : (user ?? ""));
  const ownerVal = owner ?? ownerInit;

  const br = usePortalQuery<CollegeDetail>(!lock && scopeType === "branch" && collegeVal ? `colleges/${encodeURIComponent(collegeVal)}` : null);
  const branchOptions = useMemo(
    () =>
      (br.data?.branches ?? [])
        .slice()
        .sort((a, b) => (b.is_relevant ? 1 : 0) - (a.is_relevant ? 1 : 0) || String(a.code).localeCompare(String(b.code)))
        .map((b) => ({ value: String(b.id), label: `${b.code ? `${b.code} — ` : ""}${b.name}` })),
    [br.data],
  );
  const sortedCols = useMemo(
    () => [...colleges].sort((a, b) => (b.targeted ? 1 : 0) - (a.targeted ? 1 : 0) || String(a.short_name || a.name).localeCompare(String(b.short_name || b.name))),
    [colleges],
  );
  const peopleSorted = useMemo(() => people.slice().sort((a, b) => String(a.full_name).localeCompare(String(b.full_name))), [people]);
  const scopeCollege = scopeType === "person" ? people.find((p) => String(p.id) === person)?.college_id : collegeVal;
  const ownerList = useMemo(() => {
    const active = peopleSorted.filter((p) => p.status !== "inactive");
    const near = scopeCollege ? active.filter((p) => p.college_id === scopeCollege) : [];
    return [...near, ...active.filter((p) => !near.includes(p))];
  }, [peopleSorted, scopeCollege]);
  const listId = useMemo(() => `fu-owner-list-${Math.random().toString(36).slice(2, 7)}`, []);

  const lockedLabel =
    opts.scopeLabel ||
    (init.scope_type === "college"
      ? (() => {
          const c = colleges.find((x) => String(x.id) === String(init.scope_id));
          return c?.short_name || c?.name;
        })()
      : init.scope_type === "person"
        ? people.find((p) => String(p.id) === String(init.scope_id))?.full_name
        : null) ||
    `${FOLLOWUP_SCOPE_LABEL[init.scope_type ?? "college"] ?? init.scope_type} ${s(init.scope_id)}`;

  const del = async () => {
    if (!row) return;
    const ok = await confirm({ title: "Delete follow-up?", text: `"${row.title || "Follow-up"}" will be removed permanently.`, confirmLabel: "Delete" });
    if (!ok) return;
    setDeleting(true);
    try {
      await portalApi.del(`followups/${row.id}`);
      toast("Follow-up deleted", "good");
      opts.onSaved?.();
      onDone(true);
    } catch (e) {
      toast(errMsg(e), "bad");
    } finally {
      setDeleting(false);
    }
  };

  const fieldMap = { scope_id: scopeType === "college" ? "college" : scopeType, owner_person_id: "owner_name" };

  return (
    <DialogForm<boolean>
      open={open}
      title={row ? "Edit follow-up" : lock && opts.scopeLabel ? `New follow-up — ${opts.scopeLabel}` : "New follow-up"}
      className="fu-form"
      submitLabel={row ? "Save changes" : "Add follow-up"}
      fieldMap={fieldMap}
      extra={
        row ? (
          <DangerZone title="Delete this follow-up" text="Use this for mistakes. To finish a follow-up, mark it done instead so the history is kept.">
            <Button tone="danger" size="sm" icon="trash" busy={deleting} onClick={() => void del()}>
              Delete
            </Button>
          </DangerZone>
        ) : null
      }
      onDone={onDone}
      onSubmit={async (key) => {
        const t = lock ? (init.scope_type ?? "college") : scopeType;
        const scope_id = lock ? s(init.scope_id) : t === "college" ? collegeVal : t === "branch" ? branch : person;
        const errs: Record<string, string> = {};
        if (!title.trim()) errs.title = "Describe what needs to happen.";
        if (!scope_id) errs[t === "college" ? "college" : t] = `Choose the ${t === "person" ? "person" : t}.`;
        if (t === "branch" && !collegeVal) errs.college = "Choose the college first.";
        if (!due) errs.due_date = "Set a due date.";
        else if (!row && due < today()) errs.due_date = "The due date cannot be in the past.";
        if (last && last > today()) errs.last_contact = "Cannot be in the future.";
        if (Object.keys(errs).length) throw validationError(errs);
        const match = people.find((p) => p.full_name === ownerVal.trim());
        const body = {
          scope_type: t,
          scope_id: String(scope_id),
          issue,
          title: title.trim(),
          owner_name: ownerVal.trim() || null,
          owner_person_id: match ? match.id : null,
          due_date: due,
          last_contact: last || null,
          notes: notes.trim() || null,
        };
        if (row) await portalApi.patch(`followups/${row.id}`, body, { idempotencyKey: key });
        else await portalApi.post("followups", { ...body, status: "open" }, { idempotencyKey: key });
        toast(row ? "Follow-up updated" : `Follow-up added — due ${fmt.date(due)}`, "good");
        opts.onSaved?.();
        return true;
      }}
    >
      {(err) => (
        <>
          <TextField name="title" label="What needs to happen?" required full value={title} onChange={setTitle} maxLength={300} placeholder="e.g. Call the principal about a seminar slot" error={err.title} />
          {lock ? (
            <div className="td-field td-field--full fu-about">
              <span className="td-field__label">About</span>
              <div className="fu-about-val">
                <span className="fu-chip">{FOLLOWUP_SCOPE_LABEL[init.scope_type ?? "college"] ?? init.scope_type}</span> <strong>{lockedLabel}</strong>
              </div>
            </div>
          ) : (
            <>
              <SelectField
                name="scope_type"
                label="This follow-up is about"
                required
                value={scopeType}
                onChange={(v) => setScopeType(v as FollowupScope)}
                options={[
                  { value: "college", label: "A college" },
                  { value: "branch", label: "A branch of a college" },
                  { value: "person", label: "A team member" },
                ]}
                error={err.scope_type}
              />
              <SelectField
                name="college"
                label="College"
                required
                hidden={scopeType === "person"}
                placeholder={loading && !colleges.length ? "Loading colleges…" : "Choose a college…"}
                value={collegeVal}
                onChange={(v) => {
                  setCollege(v);
                  setBranch("");
                }}
                options={sortedCols.map((c) => ({ value: String(c.id), label: `${c.short_name || c.name}${c.targeted ? "" : " (not targeted)"}` }))}
                error={err.college}
              />
              <SelectField
                name="branch"
                label="Branch"
                required
                hidden={scopeType !== "branch"}
                placeholder={!collegeVal ? "Choose a college first" : br.loading ? "Loading branches…" : br.error ? "Could not load branches" : branchOptions.length ? "Choose a branch…" : "No branches recorded for this college"}
                value={branch}
                onChange={setBranch}
                options={branchOptions}
                error={err.branch}
              />
              <SelectField
                name="person"
                label="Person"
                required
                hidden={scopeType !== "person"}
                placeholder={loading && !people.length ? "Loading people…" : "Choose a person…"}
                value={person}
                onChange={setPerson}
                options={peopleSorted.map((p) => ({ value: String(p.id), label: `${p.full_name}${p.college_short_name || p.college_name ? ` — ${p.college_short_name || p.college_name}` : ""}` }))}
                error={err.person}
              />
            </>
          )}
          <SelectField name="issue" label="Reason" value={issue} onChange={setIssue} options={Object.entries(ISSUES).map(([value, [label]]) => ({ value, label }))} help={ISSUE_HELP[issue] || " "} error={err.issue} />
          <TextField name="due_date" label="Due date" type="date" required value={due} onChange={setDue} min={row ? undefined : today()} error={err.due_date} />
          <QuickDates onPick={setDue} />
          <Field name="owner_name" label="Assigned to" help="Who will do it. Pick a team member or type any name." error={err.owner_name}>
            {(id, describedBy) => (
              <div>
                <input id={id} type="text" className="td-input" list={listId} value={ownerVal} placeholder="Type a name" autoComplete="off" aria-describedby={describedBy} onChange={(e) => setOwner(e.target.value)} />
                <datalist id={listId}>
                  {ownerList.map((p) => (
                    <option key={p.id} value={p.full_name}>{`${ROLE_LABEL[p.role] ?? ""}${p.college_short_name ? ` · ${p.college_short_name}` : ""}`}</option>
                  ))}
                </datalist>
              </div>
            )}
          </Field>
          <TextField name="last_contact" label="Last spoke to them on" type="date" value={last} onChange={setLast} max={today()} help="Optional." error={err.last_contact} />
          <TextAreaField name="notes" label="Notes" value={notes} onChange={setNotes} placeholder="Anything the person doing it needs to know" error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/* ------------------------------------------------------------------ mark done */

export function MarkDoneDialog({ open = true, row, onSaved, onDone }: { open?: boolean; row: FollowupRow; onSaved?: () => void; onDone: (r: boolean | null) => void }) {
  const [note, setNote] = useState("");
  const [next, setNext] = useState(true);
  const [nextDate, setNextDate] = useState(addDays(today(), 7));
  return (
    <DialogForm<boolean>
      open={open}
      title="Mark follow-up done"
      className="fu-form"
      submitLabel="Mark done"
      intro={
        <p className="fu-modal-ctx">
          <strong>{row.title || "Follow-up"}</strong>
          {row._scope?.label ? ` — ${row._scope.label}` : ""}
        </p>
      }
      onDone={onDone}
      onSubmit={async (key) => {
        if (next && !nextDate) throw validationError({ next_date: 'Pick a date, or untick "Schedule the next follow-up".' });
        if (next && nextDate < today()) throw validationError({ next_date: "The next follow-up cannot be in the past." });
        const stamp = today();
        const extra = note.trim();
        await portalApi.patch(
          `followups/${row.id}`,
          { status: "done", last_contact: stamp, notes: extra ? [row.notes, `[${stamp}] ${extra}`].filter(Boolean).join("\n") : row.notes },
          { idempotencyKey: key },
        );
        if (next && nextDate) {
          await portalApi.post("followups", {
            scope_type: row.scope_type,
            scope_id: String(row.scope_id),
            owner_person_id: row.owner_person_id ?? null,
            owner_name: row.owner_name ?? null,
            issue: row.issue || "other",
            title: row.title || "Follow-up",
            due_date: nextDate,
            last_contact: stamp,
            status: "open",
            notes: extra ? `Previous: ${extra}` : null,
          });
        }
        toast(next && nextDate ? `Done — next follow-up on ${fmt.date(nextDate)}` : "Marked done", "good");
        onSaved?.();
        return true;
      }}
    >
      {(err) => (
        <>
          <TextAreaField name="note" label="What happened?" value={note} onChange={setNote} placeholder="What happened? (optional)" help="Added to the notes with today's date." error={err.note} />
          <CheckField name="next" label="Schedule the next follow-up (same person and reason)" full checked={next} onChange={setNext} />
          <TextField name="next_date" label="Next follow-up on" type="date" hidden={!next} value={nextDate} onChange={setNextDate} min={today()} error={err.next_date} />
          <QuickDates
            hidden={!next}
            onPick={setNextDate}
            list={[
              ["+3 days", 3],
              ["+1 week", 7],
              ["+2 weeks", 14],
            ]}
          />
        </>
      )}
    </DialogForm>
  );
}

/* ------------------------------------------------------------------ reschedule (one or many) */

export interface BulkResult {
  ok: number;
  failed: { id: number; message: string }[];
}

/** PATCH several follow-ups; toasts "N follow-ups <verb>" and the first failure (old runBulk). */
export async function patchFollowups(ids: readonly number[], body: Record<string, unknown> | ((id: number) => Record<string, unknown>), verb: string): Promise<BulkResult> {
  const res = await Promise.allSettled(ids.map((id) => portalApi.patch(`followups/${id}`, typeof body === "function" ? body(id) : body)));
  const failed = res.flatMap((x, i) => (x.status === "rejected" ? [{ id: ids[i]!, message: errMsg(x.reason, "error") }] : []));
  const ok = res.length - failed.length;
  if (ok) toast(`${fmt.num(ok)} follow-up${ok === 1 ? "" : "s"} ${verb}`, "good");
  if (failed.length) toast(`${failed.length} could not be updated: ${failed[0]!.message}`, "bad");
  return { ok, failed };
}

export function RescheduleDialog({ open = true, row, ids, onSaved, onDone }: { open?: boolean; row?: FollowupRow | null; ids?: readonly number[]; onSaved?: () => void; onDone: (r: boolean | null) => void }) {
  const bulk = !row;
  const n = ids?.length ?? 0;
  const [date, setDate] = useState(() => (row ? (row.due_date && (daysUntil(row.due_date) ?? -1) >= 0 ? addDays(row.due_date, 1) : addDays(today(), 1)) : addDays(today(), 7)));
  const [why, setWhy] = useState("");
  return (
    <DialogForm<boolean>
      open={open}
      title={bulk ? `Reschedule ${n} follow-up${n === 1 ? "" : "s"}` : "Reschedule follow-up"}
      className="fu-form"
      submitLabel="Reschedule"
      intro={
        row ? (
          <p className="fu-modal-ctx">
            <strong>{row.title || "Follow-up"}</strong>
            {row._scope?.label ? ` — ${row._scope.label}` : ""}
            {row.due_date ? ` · currently due ${fmt.date(row.due_date)}` : ""}
          </p>
        ) : null
      }
      onDone={onDone}
      onSubmit={async (key) => {
        if (!date) throw validationError({ due_date: "Pick a date." });
        if (date < today()) throw validationError({ due_date: "Pick today or a later date." });
        if (bulk) {
          await patchFollowups(ids ?? [], { due_date: date }, `moved to ${fmt.date(date)}`);
          onSaved?.();
          return true;
        }
        const body: Record<string, unknown> = { due_date: date };
        if (why.trim()) body.notes = [row!.notes, `[${today()}] Moved to ${date}: ${why.trim()}`].filter(Boolean).join("\n");
        await portalApi.patch(`followups/${row!.id}`, body, { idempotencyKey: key });
        toast(`Moved to ${fmt.date(date)}`, "good");
        onSaved?.();
        return true;
      }}
    >
      {(err) => (
        <>
          <TextField name="due_date" label="New due date" type="date" required value={date} onChange={setDate} min={today()} error={err.due_date} />
          <QuickDates onPick={setDate} />
          {bulk ? null : <TextField name="reason" label="Why?" full value={why} onChange={setWhy} maxLength={300} placeholder="e.g. Principal on leave until Monday" help="Optional. Saved in the notes." error={err.reason} />}
        </>
      )}
    </DialogForm>
  );
}

/* ------------------------------------------------------------------ imperative API (old names) */

/** Create / edit follow-up (old followups.openFollowupForm). Resolves true when saved or deleted. */
export function openFollowupForm(opts: FollowupFormOptions = {}): Promise<boolean | null> {
  return openDialog<boolean>((done) => <FollowupDialog {...opts} onDone={done} />);
}

/** Old forms.addFollowup(ctx, {scope_type, scope_id, college_id, label, title, issue, onSaved}). */
export function addFollowup(opts: { scope_type?: FollowupScope; scope_id?: string | number | null; college_id?: string | null; label?: string | null; title?: string | null; issue?: string | null; onSaved?: () => void } = {}): Promise<boolean | null> {
  const scope_type = opts.scope_type || "college";
  const sid = opts.scope_id ?? opts.college_id;
  return openFollowupForm({
    preset: { scope_type, scope_id: sid === null || sid === undefined ? "" : String(sid), college_id: opts.college_id, title: opts.title, issue: opts.issue },
    lockScope: sid !== null && sid !== undefined && sid !== "",
    scopeLabel: opts.label,
    onSaved: opts.onSaved,
  });
}

export function markFollowupDone(row: FollowupRow, opts: { onSaved?: () => void } = {}): Promise<boolean | null> {
  return openDialog<boolean>((done) => <MarkDoneDialog row={row} onSaved={opts.onSaved} onDone={done} />);
}

export function rescheduleFollowup(row: FollowupRow, opts: { onSaved?: () => void } = {}): Promise<boolean | null> {
  return openDialog<boolean>((done) => <RescheduleDialog row={row} onSaved={opts.onSaved} onDone={done} />);
}

export function rescheduleFollowups(ids: readonly number[], opts: { onSaved?: () => void } = {}): Promise<boolean | null> {
  return openDialog<boolean>((done) => <RescheduleDialog ids={ids} onSaved={opts.onSaved} onDone={done} />);
}

/** Reopen a done follow-up. */
export async function reopenFollowup(row: Pick<Followup, "id">): Promise<boolean> {
  try {
    await portalApi.patch(`followups/${row.id}`, { status: "open" });
    toast("Follow-up reopened", "good");
    return true;
  } catch (e) {
    toast(errMsg(e), "bad");
    return false;
  }
}
