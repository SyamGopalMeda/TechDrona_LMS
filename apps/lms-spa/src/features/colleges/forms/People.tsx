/**
 * Team dialogs (old forms.js "people" block, PLAN R1–R6): ONE person dialog (add + edit) plus Move college,
 * Replace lead, Deactivate / Reactivate, Delete and bulk "assign to lead". The server enforces the rules; the
 * dialogs explain them before saving and show what the server changed.
 *
 *   await personDialog({ id: 12 })                                  // edit
 *   await addPerson({ college_id: "c9", role: "ambassador" })       // add (no college_id → pick the college first)
 *   await movePerson(p) · deactivatePerson(p) · reactivatePerson(p) · replaceLead(p) · deletePerson(p, { onDeleted })
 */
import "../styles/views/ops.css";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { PortalApiError, portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { portalPath } from "../lib/routes";
import type { CollegeDetail, Person } from "../lib/types";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { confirm, toast } from "../ui/Overlay";
import { openDialog } from "./host";
import { DialogForm, KEEP_OPEN, MultiField, SelectField, TextAreaField, TextField } from "./kit";
import { PERSON_PHONE_RULE, PERSON_STATUS_OPTS, ROLE_LABEL, ROLE_OPTS, formatPhone, normEmail, normPhone } from "./labels";
import { LoadingModal } from "./loading";
import { pickCollege } from "./PickCollege";
import { saveTargetRow } from "./targets";
import { personBranchIds, type TeamPerson } from "./team";
import { EMAIL_RE, arr, branchOpts, errMsg, missingEndpoint, num, sortBranches, str, today, validationError, wholeOrNull } from "./util";

type P = TeamPerson & Partial<Person> & { reports_to_name?: string | null; designation?: string | null; college_short_name?: string | null; college_name?: string | null };
interface PersonDetail {
  person?: P;
  reports?: P[];
  branches?: { id: number; code?: string; name?: string }[];
  enrollments?: unknown[];
  activities?: unknown[];
  college?: { id: string; name?: string; short_name?: string | null } | null;
  [k: string]: unknown;
}
type Fate = "ambassador_lead" | "inactive";

const LEAD_ROLES = ["college_lead", "ambassador_lead"];
const ALLOWED_BOSS: Record<string, string[]> = { ambassador: ["ambassador_lead", "college_lead"], ambassador_lead: ["college_lead"], college_lead: [] };
const BRANCH_HELP: Record<string, string> = {
  college_lead: "Optional. A college lead covers the whole college — leave empty unless they also look after specific branches.",
  ambassador_lead: "Branches this lead looks after (can be several).",
  ambassador: "Branches where this ambassador talks to students. Enrollments can only be credited to people covering that branch.",
};
const BOSS_HELP: Record<string, string> = {
  ambassador: "An ambassador reports to an ambassador lead or the college lead.",
  ambassador_lead: "An ambassador lead reports to the college lead.",
};
const DESIGNATION_HELP = 'What they do in the team, e.g. "CSE 3rd-year coordinator" or "Hostel outreach".';

const isActive = (p: { status?: string | null } | null | undefined) => !!p && p.status !== "inactive";
const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const phoneDigits = (v: unknown) => String(v ?? "").replace(/\D/g, "");
const personOf = (pd: PersonDetail | P): P => ((pd as PersonDetail).person ?? pd) as P;
const errExisting = (e: unknown): number | null => {
  const d = (e as PortalApiError)?.data as { existing_id?: number } | null;
  return d?.existing_id ?? (e as { existing_id?: number })?.existing_id ?? null;
};

/** Rows from GET /people whatever its shape (v4 {items} or the older plain array). */
export const peopleRows = (r: unknown): P[] => (Array.isArray(r) ? r : Array.isArray((r as { items?: unknown })?.items) ? (r as { items: P[] }).items : []);

let v4Promise: Promise<boolean> | null = null;
/** true on v4+ servers (GET /api/health → version), cached for the session; false when unknown. */
export function serverIsV4(): Promise<boolean> {
  if (!v4Promise) {
    v4Promise = portalApi.get<{ version?: string }>("health").then(
      (x) => {
        const m = String(x?.version || "").match(/^v(\d+)/);
        return !!m && Number(m[1]) >= 4;
      },
      () => {
        v4Promise = null;
        return false;
      },
    );
  }
  return v4Promise;
}

/** Active/onboarding people anywhere with the same normalised phone or email (excluding selfId). */
export async function findDuplicatePeople({ phone, email }: { phone?: string | null; email?: string | null } = {}, selfId: number | null = null): Promise<(P & { _field: "phone" | "email" })[]> {
  const np = normPhone(phone);
  const ne = normEmail(email);
  const jobs: ["phone" | "email", string][] = [];
  if (np) jobs.push(["phone", np.slice(3)]);
  if (ne && EMAIL_RE.test(ne)) jobs.push(["email", ne]);
  const out = new Map<number, P & { _field: "phone" | "email" }>();
  await Promise.all(
    jobs.map(async ([kind, q]) => {
      let rows: P[] = [];
      try {
        rows = peopleRows(await portalApi.get("people", { query: { q, page_size: 50 } }));
      } catch {
        return;
      }
      for (const p of rows) {
        if (Number(p.id) === Number(selfId) || !isActive(p)) continue;
        const hit = kind === "phone" ? normPhone(p.phone) === np : String(p.email || "").trim().toLowerCase() === ne;
        if (hit) out.set(Number(p.id), { ...p, _field: kind });
      }
    }),
  );
  return [...out.values()];
}

/** Valid managers for a role inside one college (R2): active college lead / ambassador lead, never yourself. */
export function validLeads<T extends { id: number | string; role: string; status?: string | null }>(people: readonly T[] | null | undefined, role: string, selfId: number | string | null = null): T[] {
  const allowed = ALLOWED_BOSS[role] || [];
  return (people || []).filter((p) => allowed.includes(p.role) && isActive(p) && Number(p.id) !== Number(selfId));
}

/** Plain-language summary of PATCH/POST side effects returned by the v4 server. */
export function sideEffectText(res: unknown): string {
  const se = ((res as { side_effects?: Record<string, unknown[]> })?.side_effects ?? {}) as Record<string, unknown[] | undefined>;
  const parts: string[] = [];
  if (se.unassigned?.length) parts.push(`${se.unassigned.length} ${se.unassigned.length === 1 ? "person is" : "people are"} now unassigned`);
  if (se.removed_branches?.length) parts.push(`${se.removed_branches.length} branch link${se.removed_branches.length === 1 ? "" : "s"} removed`);
  if (se.reassigned?.length) parts.push(`${se.reassigned.length} moved to the new lead`);
  return parts.join(" · ");
}

/** POST /people/:old/replace-lead (R5). Falls back to the same steps one by one on servers without the endpoint. */
export async function replaceLeadRequest(oldId: number, newId: number, fate: Fate): Promise<unknown> {
  try {
    return await portalApi.post(`people/${oldId}/replace-lead`, { new_lead_id: Number(newId), old_lead_becomes: fate });
  } catch (e) {
    if (!missingEndpoint(e)) throw e;
  }
  // same steps one by one (old lead first, so there is never a second active college lead)
  const od = await portalApi.get<PersonDetail>(`people/${oldId}`);
  const reports = (od.reports || []).filter((r) => Number(r.id) !== Number(newId) && isActive(r));
  await portalApi.patch(`people/${oldId}`, fate === "inactive" ? { status: "inactive" } : { role: "ambassador_lead", reports_to: null });
  await portalApi.patch(`people/${newId}`, { role: "college_lead", reports_to: null, status: "active" });
  if (fate !== "inactive") await portalApi.patch(`people/${oldId}`, { reports_to: Number(newId) });
  const moved: number[] = [];
  for (const r of reports) {
    try {
      await portalApi.patch(`people/${r.id}`, { reports_to: Number(newId) });
      moved.push(r.id);
    } catch {
      /* left unassigned; shown in Team */
    }
  }
  return { moved };
}

/** Bulk "assign to lead": returns {ok:[ids], failed:[{id, message}]}. */
export async function assignToLead(ids: readonly (number | string)[], leadId: number | string | null): Promise<{ ok: (number | string)[]; failed: { id: number | string; message: string }[]; error?: unknown }> {
  try {
    const r = await portalApi.post<{ updated?: number[]; unchanged?: number[] }>("people/bulk-assign", { person_ids: ids.map(Number), reports_to: leadId === null || leadId === undefined ? null : Number(leadId) });
    return { ok: [...(r?.updated || []), ...(r?.unchanged || [])], failed: [] };
  } catch (e) {
    if (!missingEndpoint(e)) return { ok: [], failed: ids.map((id) => ({ id, message: errMsg(e) })), error: e };
  }
  const ok: (number | string)[] = [];
  const failed: { id: number | string; message: string }[] = [];
  for (const id of ids) {
    try {
      await portalApi.patch(`people/${id}`, { reports_to: leadId === null || leadId === undefined ? null : Number(leadId) });
      ok.push(id);
    } catch (e) {
      failed.push({ id, message: errMsg(e) });
    }
  }
  return { ok, failed };
}

/* ------------------------------------------------------------------ small dialogs */

function Choice({ name, value, checked, onChange, title, text }: { name: string; value: string; checked: boolean; onChange: () => void; title: ReactNode; text?: ReactNode }) {
  return (
    <label className="v-person-choice">
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} />
      <span>
        <strong>{title}</strong>
        {text ? <span className="vx-small vx-muted">{text}</span> : null}
      </span>
    </label>
  );
}

function OldLeadFateDialog({ oldLead, newName, onDone }: { oldLead: P; newName: string | null; onDone: (f: Fate | null) => void }) {
  const [pick, setPick] = useState<Fate>("ambassador_lead");
  return (
    <DialogForm<Fate> title="Replace the college lead?" submitLabel="Replace lead" bare onDone={onDone} onSubmit={() => pick}>
      {() => (
        <div className="v-person-dlg">
          <p>{`${oldLead.full_name} is the college lead here. A college can have only one active college lead, so ${newName || "the new person"} replaces them.`}</p>
          <fieldset className="v-person-choices">
            <legend>{`What should happen to ${oldLead.full_name}?`}</legend>
            <Choice
              name="td-oldlead"
              value="ambassador_lead"
              checked={pick === "ambassador_lead"}
              onChange={() => setPick("ambassador_lead")}
              title="Keep them as an ambassador lead"
              text="They stay in the team, reporting to the new college lead. Their direct reports move to the new college lead."
            />
            <Choice name="td-oldlead" value="inactive" checked={pick === "inactive"} onChange={() => setPick("inactive")} title="Set them inactive" text="History and credited enrollments are kept. Their direct reports move to the new college lead." />
          </fieldset>
        </div>
      )}
    </DialogForm>
  );
}

/** Asks what happens to the current college lead (R5). Resolves 'ambassador_lead' | 'inactive' | null (cancel). */
export function askOldLeadFate(oldLead: P, newName: string | null): Promise<Fate | null> {
  return openDialog<Fate>((done) => <OldLeadFateDialog oldLead={oldLead} newName={newName} onDone={done} />);
}

/* ------------------------------------------------------------------ THE person dialog */

export interface PersonDialogOptions {
  /** edit this person */
  id?: number | string | null;
  /** add: the college (else picked first) */
  college_id?: string | null;
  role?: string | null;
  reports_to?: number | string | null;
  branch_ids?: (number | string)[];
  onSaved?: (p: P) => void;
  /** after "Delete this record" (e.g. leave the person page) */
  onDeleted?: () => void;
}

type DupState = { kind: "list"; list: (P & { _field: string })[] } | { kind: "samename"; name: string; id: number | null } | { kind: "lead_exists"; name: string } | null;

function DupNotice({ list, onOpen }: { list: (P & { _field: string })[]; onOpen: () => void }) {
  if (!list.length) return null;
  return (
    <div className="vf-note vf-note--warn v-person-dup" role="alert">
      <div>
        <strong>{list.length === 1 ? "Already in the team" : `${list.length} people already use these details`}</strong>
        <ul>
          {list.map((p) => (
            <li key={p.id}>
              {`${p.full_name || "Unnamed"} — ${ROLE_LABEL[p.role] || p.role}, ${p.college_short_name || (p.college as { name?: string } | null)?.name || p.college_name || p.college_id || "college unknown"}`}
              {` (same ${p._field === "email" ? "email" : "mobile number"}) `}
              <Link to={portalPath.person(p.id)} className="v-person-dup__open" onClick={onOpen}>
                Open existing
              </Link>
            </li>
          ))}
        </ul>
        <p className="vx-small">Edit the existing record instead of adding the same person twice.</p>
      </div>
    </div>
  );
}

export function PersonDialog({ open = true, onDone, ...opts }: PersonDialogOptions & { open?: boolean; onDone: (r: P | null) => void }) {
  const editing = opts.id !== null && opts.id !== undefined && opts.id !== "";
  const pq = usePortalQuery<PersonDetail>(editing ? `people/${opts.id}` : null);
  const collegeId = editing ? s(pq.data ? personOf(pq.data).college_id : "") : s(opts.college_id);
  const cq = usePortalQuery<CollegeDetail>(collegeId ? `colleges/${encodeURIComponent(collegeId)}` : null);
  const title = editing ? (pq.data ? `Edit ${personOf(pq.data).full_name}` : "Edit person") : "Add a person";
  if ((editing && !pq.data) || !cq.data) {
    const q = editing && !pq.data ? pq : cq;
    return <LoadingModal open={open} title={title} error={q.error} loading={q.loading || (!collegeId && !q.error)} retry={() => void q.reload()} onClose={() => onDone(null)} what={editing && !pq.data ? "the person" : "the college"} />;
  }
  return <PersonForm open={open} opts={opts} pd={editing ? pq.data! : null} d={cq.data} collegeId={collegeId} onDone={onDone} />;
}

function PersonForm({ open, opts, pd, d, collegeId, onDone }: { open: boolean; opts: PersonDialogOptions; pd: PersonDetail | null; d: CollegeDetail; collegeId: string; onDone: (r: P | null) => void }) {
  const editing = !!pd;
  const p: P = pd ? personOf(pd) : ({} as P);
  const branches = d.branches || [];
  const people = (d.people || []) as unknown as P[];
  const cname = d.college?.short_name || d.college?.name || collegeId;
  const currentLead = people.find((x) => x.role === "college_lead" && isActive(x) && Number(x.id) !== Number(p.id));
  const role0 = editing ? p.role : opts.role || (currentLead ? "ambassador" : "college_lead");

  // D4: v4 servers always store a designation — offer it for the first person of a college too
  const knownDesignation = "designation" in p || people.some((x) => "designation" in x);
  const [v4, setV4] = useState(false);
  useEffect(() => {
    if (knownDesignation) return;
    let live = true;
    void serverIsV4().then((x) => live && setV4(x));
    return () => {
      live = false;
    };
  }, [knownDesignation]);
  const supportsDesignation = knownDesignation || v4;

  // F6: the stored phone (perhaps an older landline) passes unchanged; only a NEW number must be a mobile
  const storedPhone = editing && p.phone ? String(p.phone) : "";
  const phoneUnchanged = (val: string) => !!storedPhone && phoneDigits(val) !== "" && (phoneDigits(val) === phoneDigits(storedPhone) || phoneDigits(val) === phoneDigits(formatPhone(storedPhone)));
  const phoneErr = (val: string) => (str(val) && !normPhone(val) && !phoneUnchanged(val) ? PERSON_PHONE_RULE : "");

  // Reports-to options: every valid lead of THIS college; an invalid current link stays visible (never silently cleared).
  const leadOpts = useMemo(() => {
    const list: { value: string; label: string; role: string }[] = people
      .filter((x) => LEAD_ROLES.includes(x.role) && isActive(x) && Number(x.id) !== Number(p.id))
      .map((x) => ({ value: String(x.id), label: `${x.full_name} (${ROLE_LABEL[x.role] || x.role}${x.status === "onboarding" ? ", onboarding" : ""})`, role: x.role }));
    return list;
  }, [people, p.id]);
  const cur = editing && p.reports_to ? people.find((x) => Number(x.id) === Number(p.reports_to)) : null;
  const curValid = !!cur && leadOpts.some((x) => Number(x.value) === Number(cur.id));
  const why = !cur ? "not in this college" : !isActive(cur) ? "inactive" : "not a lead";
  const invalidCur = editing && p.reports_to && !curValid ? { value: String(p.reports_to), label: `${cur?.full_name || p.reports_to_name || `#${p.reports_to}`} (${why} — choose a valid lead)`, role: "__current" } : null;
  const allLeadOpts = invalidCur ? [...leadOpts, invalidCur] : leadOpts;

  const current = editing ? personBranchIds({ ...p, branches: (pd?.branches as unknown) ?? p.branches }, branches as never) : (opts.branch_ids || []).map(Number);
  const brs = sortBranches(branches);
  const firstReports = (role: string, rt: string) => {
    if (editing || rt || role === "college_lead") return rt;
    const valid = validLeads(people, role, p.id ?? null);
    return valid.length === 1 ? String(valid[0]!.id) : rt;
  };

  const [v, setV] = useState(() => ({
    full_name: s(p.full_name),
    role: role0,
    reports_to: firstReports(role0, editing ? (p.reports_to ? String(p.reports_to) : "") : opts.reports_to ? String(opts.reports_to) : ""),
    phone: p.phone ? formatPhone(p.phone) : "",
    email: s(p.email),
    designation: s(p.designation),
    status: s(p.status) || "active",
    joined_on: s(p.joined_on) || (editing ? "" : today()),
    target: "",
    notes: s(p.notes),
  }));
  const [branchIds, setBranchIds] = useState<string[]>(current.map(String));
  const set = (k: keyof typeof v) => (x: string) => setV((o) => ({ ...o, [k]: x }));
  const setRole = (role: string) =>
    setV((o) => {
      const allowed = ALLOWED_BOSS[role] || [];
      const keep = allLeadOpts.some((x) => x.value === o.reports_to && (allowed.includes(x.role) || x.role === "__current"));
      return { ...o, role, reports_to: firstReports(role, keep ? o.reports_to : "") };
    });

  const [dup, setDup] = useState<DupState>(null);
  const allowSameName = useRef(false);
  const close = () => onDone(null);

  // live duplicate warning (debounced)
  useEffect(() => {
    let live = true;
    const t = setTimeout(async () => {
      const ok = normPhone(v.phone) || (normEmail(v.email) && EMAIL_RE.test(normEmail(v.email)!));
      const list = ok ? await findDuplicatePeople({ phone: v.phone, email: v.email }, p.id ?? null) : [];
      if (live) setDup((cur0) => (cur0 && cur0.kind !== "list" ? cur0 : list.length ? { kind: "list", list } : null));
    }, 450);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [v.phone, v.email, p.id]);

  const role = v.role;
  const valid = validLeads(people, role, p.id ?? null);
  const showLeadNote = role === "college_lead" && !!currentLead && !(editing && p.role === "college_lead");
  const showNoLead = !!role && role !== "college_lead" && !valid.length;
  const phoneHelp = v.phone.trim()
    ? normPhone(v.phone)
      ? `Will be saved as ${formatPhone(normPhone(v.phone))}.`
      : phoneUnchanged(v.phone)
        ? "Stored number (not a mobile) — kept as it is. A new number must be a 10-digit mobile."
        : "10-digit Indian mobile, e.g. 98765 43210."
    : "10-digit Indian mobile. Saved as +91 XXXXX XXXXX.";
  const statusOpts = editing && p.status === "inactive" ? PERSON_STATUS_OPTS : PERSON_STATUS_OPTS.filter((o) => editing || o.value !== "inactive");
  const canDelete = editing && !(pd?.enrollments || []).length && !(pd?.activities || []).length;

  const errorsOf = () => {
    const errs: Record<string, string> = {};
    if (!str(v.full_name)) errs.full_name = "Name is required.";
    if (phoneErr(v.phone)) errs.phone = phoneErr(v.phone);
    if (str(v.email) && !EMAIL_RE.test(v.email.trim())) errs.email = "Enter a valid email address, e.g. name@college.edu.in.";
    if (Number.isNaN(wholeOrNull(v.target))) errs.target = "Enter a whole number (0 or more).";
    if (v.joined_on && !/^\d{4}-\d{2}-\d{2}$/.test(v.joined_on)) errs.joined_on = "Use a date like 2026-11-07.";
    else if (v.joined_on && v.joined_on > today()) errs.joined_on = "Joining date cannot be in the future.";
    return errs;
  };

  /** 409 from the server: show who already has these details. */
  const on409 = async (e: PortalApiError) => {
    const id = errExisting(e);
    const name = String((e.data as { existing_name?: string } | null)?.existing_name || "Someone");
    if (e.code === "possible_duplicate_name") return setDup({ kind: "samename", name, id });
    if (e.code === "lead_exists") return setDup({ kind: "lead_exists", name });
    let list: (P & { _field: string })[] = [];
    if (id) {
      try {
        const x = await portalApi.get<PersonDetail>(`people/${id}`);
        list = [{ ...personOf(x), _field: e.fields?.email && !e.fields?.phone ? "email" : "phone" }];
      } catch {
        /* ignore */
      }
    }
    if (!list.length) list = await findDuplicatePeople({ phone: v.phone, email: v.email }, p.id ?? null);
    if (list.length) setDup({ kind: "list", list });
  };

  const dupNode =
    dup?.kind === "list" ? (
      <DupNotice list={dup.list} onOpen={close} />
    ) : dup?.kind === "samename" ? (
      <div className="vf-note vf-note--warn v-person-dup" role="alert">
        <div>
          <strong>{`${dup.name} with the same name is already at ${cname}.`}</strong>{" "}
          {dup.id ? (
            <Link to={portalPath.person(dup.id)} className="v-person-dup__open" onClick={close}>
              Open existing
            </Link>
          ) : null}
          <div className="vx-row">
            <Button
              size="sm"
              onClick={(e) => {
                allowSameName.current = true;
                e.currentTarget.form?.requestSubmit();
              }}
            >
              It is a different person — save anyway
            </Button>
          </div>
        </div>
      </div>
    ) : dup?.kind === "lead_exists" ? (
      <p className="vf-note vf-note--warn" role="alert">{`${dup.name} is already the college lead here. Choose another role, or use “Replace lead” on their page.`}</p>
    ) : null;

  return (
    <DialogForm<P>
      open={open}
      title={editing ? `Edit ${p.full_name}` : `Add a person — ${cname}`}
      className="v-person-form"
      submitLabel={editing ? "Save changes" : "Add person"}
      intro={
        <div className="v-person-dlg">
          <div className="v-person-dlg__college">
            <Icon name="college" />
            <span>
              College: <strong>{d.college?.name || cname}</strong>
            </span>
            {editing ? (
              <button
                type="button"
                className="vx-linkbtn td-linkbtn v-person-dlg__move"
                onClick={() => {
                  close();
                  void movePerson(p);
                }}
              >
                Move to another college…
              </button>
            ) : null}
          </div>
          {invalidCur ? (
            <p className="vf-note vf-note--warn" role="status">{`${p.full_name} currently reports to someone who is ${why}. Choose a valid lead below, or leave it to keep the record as it is.`}</p>
          ) : null}
          {showLeadNote ? (
            <p className="vf-note vf-note--warn" role="status">{`${currentLead!.full_name} is the college lead of ${cname}. Saving will ask whether they become an ambassador lead or inactive — a college has one active college lead.`}</p>
          ) : null}
          {showNoLead ? (
            <p className="vf-note" role="status">
              {role === "ambassador_lead"
                ? `${cname} has no active college lead yet. An ambassador lead reports to the college lead — appoint one first, or save now and assign later (they will show as unassigned).`
                : `${cname} has no active lead yet. The ambassador will show as unassigned until you appoint a college lead and assign them.`}
            </p>
          ) : null}
        </div>
      }
      extra={
        canDelete ? (
          <div className="vf-danger v-person-dlg__danger">
            <span className="vx-small vx-muted">Added by mistake?</span>
            <Button tone="ghost" size="sm" onClick={() => void deletePerson(p, { close, onDeleted: opts.onDeleted })}>
              Delete this record
            </Button>
          </div>
        ) : null
      }
      onDone={onDone}
      onSubmit={async (key) => {
        const errs = errorsOf();
        if (Object.keys(errs).length) throw validationError(errs);
        const wantsLead = role === "college_lead" && !!currentLead && !(editing && p.role === "college_lead");
        let fate: Fate | null = null;
        if (wantsLead) {
          fate = await askOldLeadFate(currentLead!, str(v.full_name));
          if (!fate) return KEEP_OPEN;
        }
        const next: Record<string, unknown> = {
          role,
          full_name: str(v.full_name),
          phone: str(v.phone) ? normPhone(v.phone) || (phoneUnchanged(v.phone) ? normPhone(storedPhone) || storedPhone : null) : null,
          email: normEmail(v.email),
          reports_to: role === "college_lead" ? null : num(v.reports_to),
          status: v.status || "active",
          joined_on: str(v.joined_on),
          notes: str(v.notes),
        };
        if (supportsDesignation) next.designation = str(v.designation);
        const sameName = allowSameName.current ? { allow_same_name: true } : {};
        allowSameName.current = false;
        try {
          if (!editing) {
            const body: Record<string, unknown> = { college_id: collegeId, ...next, branch_ids: arr(branchIds), ...sameName };
            // replacing a lead: add as ambassador lead under the current lead, then swap roles in one server call
            if (wantsLead) {
              body.role = "ambassador_lead";
              body.reports_to = Number(currentLead!.id);
            }
            const saved = await portalApi.post<P | { person: P }>("people", body, { idempotencyKey: key });
            const sp = personOf(saved as PersonDetail);
            const pid = sp?.id;
            let addedRole = role;
            if (wantsLead && pid !== null && pid !== undefined) {
              try {
                await replaceLeadRequest(currentLead!.id, pid, fate!);
              } catch (e) {
                toast(`Added ${String(next.full_name)} as ambassador lead, but replacing the college lead failed: ${errMsg(e)}`, "warn");
                addedRole = "ambassador_lead";
              }
            }
            const t = wholeOrNull(v.target);
            if (pid !== null && pid !== undefined && t !== null) {
              try {
                await saveTargetRow({ scope_type: "person", scope_id: pid, period: "programme", target: t });
              } catch (e) {
                toast(`Person added, but the target could not be saved: ${errMsg(e)}`, "warn");
              }
            }
            const se = sideEffectText(saved);
            toast(`${String(next.full_name)} added as ${(ROLE_LABEL[addedRole] || addedRole).toLowerCase()} at ${cname}${se ? ` · ${se}` : ""}`, "good");
            opts.onSaved?.(sp);
            return sp ?? (true as unknown as P);
          }
          // edit: send only what changed (never clears an untouched invalid link)
          const before: Record<string, unknown> = { ...p, phone: p.phone ? normPhone(p.phone) || p.phone : null, email: p.email ? String(p.email).toLowerCase() : null };
          const body: Record<string, unknown> = {};
          for (const [k, val] of Object.entries(next)) if ((val ?? null) !== (before[k] ?? null)) body[k] = val;
          const nb = arr(branchIds).sort((a, b) => a - b);
          if (nb.join(",") !== current.slice().sort((a, b) => a - b).join(",")) body.branch_ids = nb;
          if (wantsLead) {
            delete body.role;
            delete body.reports_to;
          }
          if (!Object.keys(body).length && !wantsLead) {
            toast("No changes to save", "good");
            return p;
          }
          let saved: unknown = p;
          if (Object.keys(body).length) saved = await portalApi.patch(`people/${p.id}`, { ...body, ...(body.full_name ? sameName : {}) }, { idempotencyKey: key });
          if (wantsLead) await replaceLeadRequest(currentLead!.id, p.id, fate!);
          const se = sideEffectText(saved);
          toast(`${String(next.full_name)} updated${se ? ` · ${se}` : ""}`, "good");
          const sp = personOf(saved as PersonDetail);
          opts.onSaved?.(sp);
          return sp ?? (true as unknown as P);
        } catch (e) {
          if (e instanceof PortalApiError && e.status === 409) await on409(e);
          throw e;
        }
      }}
    >
      {(err) => (
        <>
          <TextField name="full_name" label="Full name" required value={v.full_name} onChange={set("full_name")} placeholder="e.g. Sai Kiran Reddy" maxLength={200} error={err.full_name} />
          <SelectField name="role" label="Role" required options={ROLE_OPTS} value={v.role} onChange={setRole} error={err.role} />
          <SelectField
            name="reports_to"
            label="Reports to"
            hidden={!role || role === "college_lead"}
            placeholder="— No lead yet (unassigned) —"
            options={allLeadOpts.filter((o) => (ALLOWED_BOSS[role] || []).includes(o.role) || o.role === "__current")}
            value={v.reports_to}
            onChange={set("reports_to")}
            help={BOSS_HELP[role] || ""}
            error={err.reports_to}
          />
          <TextField name="phone" label="Mobile number" type="tel" value={v.phone} onChange={set("phone")} placeholder="98765 43210" help={phoneHelp} error={err.phone || (v.phone ? phoneErr(v.phone) : "")} />
          <TextField name="email" label="Email" autoComplete="email" value={v.email} onChange={set("email")} placeholder="name@college.edu.in" help="Saved in lower case." maxLength={200} error={err.email} />
          {dupNode ? (
            <div className="td-field td-field--full v-person-dupwrap">
              <div className="v-person-dupbox" aria-live="polite">
                {dupNode}
              </div>
            </div>
          ) : null}
          {supportsDesignation ? (
            <TextField name="designation" label="Designation / responsibility" value={v.designation} onChange={set("designation")} placeholder="Optional" help={DESIGNATION_HELP} maxLength={120} error={err.designation} />
          ) : null}
          <MultiField name="branch_ids" label="Branches covered" options={branchOpts(brs)} value={branchIds} onChange={setBranchIds} help={BRANCH_HELP[role] || BRANCH_HELP.ambassador} error={err.branch_ids} />
          <SelectField
            name="status"
            label="Status"
            required
            options={statusOpts}
            value={v.status}
            onChange={set("status")}
            help={editing ? "To deactivate, use “Deactivate” on their page — it also handles the people who report to them." : "Use Onboarding until they have been briefed."}
            error={err.status}
          />
          <TextField name="joined_on" label="Joined on" type="date" max={today()} value={v.joined_on} onChange={set("joined_on")} error={err.joined_on} />
          {editing ? null : (
            <TextField
              name="target"
              label="Programme target (optional)"
              type="number"
              min={0}
              step={1}
              placeholder="e.g. 5"
              value={v.target}
              onChange={set("target")}
              help="Confirmed enrollments expected by the programme deadline. Monthly or weekly targets: use “Set target” on their page."
              error={err.target}
            />
          )}
          <TextAreaField name="notes" label="Notes" value={v.notes} onChange={set("notes")} error={err.notes} />
        </>
      )}
    </DialogForm>
  );
}

/** THE person dialog (old forms.personDialog): {id} to edit, or {college_id, role, reports_to, branch_ids} to add. */
export async function personDialog(opts: PersonDialogOptions | number | string = {}): Promise<P | null> {
  const o: PersonDialogOptions = typeof opts === "object" && opts ? opts : { id: opts };
  const editing = o.id !== null && o.id !== undefined && o.id !== "";
  let college_id = o.college_id;
  if (!editing && !college_id) {
    college_id = await pickCollege("Add a person — choose their college");
    if (!college_id) return null;
  }
  return openDialog<P>((done) => <PersonDialog {...o} college_id={college_id} onDone={done} />);
}

/** Old API: forms.addPerson(ctx, {college_id, role, reports_to, branch_ids}). */
export function addPerson(opts: Omit<PersonDialogOptions, "id"> = {}): Promise<P | null> {
  return personDialog({ ...opts, id: undefined });
}
/** Old API: forms.editPerson(ctx, p | id). */
export function editPerson(p: { id: number | string } | number | string, opts: Pick<PersonDialogOptions, "onSaved" | "onDeleted"> = {}): Promise<P | null> {
  const id = typeof p === "object" && p ? p.id : p;
  return personDialog({ ...opts, id });
}

/* ------------------------------------------------------------------ move / deactivate / reactivate / replace / delete */

/** Move a person to another college (R4): their lead and branch links are cleared; people reporting to them become unassigned. */
export async function movePerson(p0: { id: number | string } | number | string): Promise<unknown> {
  const id = typeof p0 === "object" && p0 ? p0.id : p0;
  let pd: PersonDetail;
  try {
    pd = await portalApi.get<PersonDetail>(`people/${id}`);
  } catch (e) {
    toast(errMsg(e), "bad");
    return null;
  }
  const p = personOf(pd);
  const target = await pickCollege(`Move ${p.full_name} to another college`);
  if (!target) return null;
  if (target === p.college_id) {
    toast(`${p.full_name} is already at this college`, "info");
    return null;
  }
  let nd: CollegeDetail;
  try {
    nd = await portalApi.get<CollegeDetail>(`colleges/${encodeURIComponent(target)}`);
  } catch (e) {
    toast(errMsg(e), "bad");
    return null;
  }
  const oldName = pd.college?.short_name || pd.college?.name || p.college_short_name || p.college_id;
  const newName = nd.college?.short_name || nd.college?.name || target;
  const reports = (pd.reports || []).filter(isActive);
  const brs = (pd.branches || (p.branches as { code?: string; name?: string }[]) || []) as { code?: string; name?: string }[];
  const newLead = ((nd.people || []) as unknown as P[]).find((x) => x.role === "college_lead" && isActive(x));
  const items = [
    p.reports_to ? `Their lead (${p.reports_to_name || `#${p.reports_to}`}) is cleared — choose a lead at ${newName} next.` : null,
    brs.length ? `Branch links at ${oldName} are removed (${brs.map((b) => b.code || b.name).join(", ")}).` : null,
    reports.length ? `${reports.length} ${reports.length === 1 ? "person reports" : "people report"} to them and will become unassigned: ${reports.map((r) => r.full_name).join(", ")}.` : null,
    p.role === "college_lead" && newLead ? `${newName} already has a college lead (${newLead.full_name}); the move will be refused. Change their role first, or use “Replace lead” there.` : null,
    "Enrollments already credited stay on record.",
  ].filter((x): x is string => !!x);
  const ok = await confirm({
    title: `Move ${p.full_name} to ${newName}?`,
    body: (
      <div className="v-person-dlg">
        <p>{`From ${oldName} to ${newName}. What changes:`}</p>
        <ul className="v-person-list">
          {items.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </div>
    ),
    confirmLabel: "Move",
    danger: false,
  });
  if (!ok) return null;
  let res: unknown;
  try {
    try {
      res = await portalApi.post(`people/${p.id}/move`, { college_id: target });
    } catch (e) {
      if (!missingEndpoint(e)) throw e;
      for (const r of reports) await portalApi.patch(`people/${r.id}`, { reports_to: null });
      res = await portalApi.patch(`people/${p.id}`, { college_id: target, reports_to: null, branch_ids: [] });
    }
  } catch (e) {
    toast(errMsg(e), "bad");
    return null;
  }
  const se = sideEffectText(res);
  toast(`${p.full_name} moved to ${newName}${se ? ` · ${se}` : ""}`, "good");
  // assign a lead at the new college straight away (not for college leads)
  if (p.role !== "college_lead") setTimeout(() => void personDialog({ id: p.id }), 250);
  return res;
}

function DeactivateDialog({ p, pd, d, onDone }: { p: P; pd: PersonDetail; d: CollegeDetail; onDone: (r: unknown) => void }) {
  const reports = (pd.reports || []).filter(isActive);
  const needsCollegeLead = reports.some((r) => r.role === "ambassador_lead");
  const cands = ((d.people || []) as unknown as P[]).filter(
    (x) =>
      isActive(x) &&
      Number(x.id) !== Number(p.id) &&
      (needsCollegeLead ? x.role === "college_lead" : LEAD_ROLES.includes(x.role)) &&
      !reports.some((r) => Number(r.id) === Number(x.id) && x.role !== "ambassador_lead"),
  );
  const [to, setTo] = useState("");
  return (
    <DialogForm<unknown>
      title={`Deactivate ${p.full_name}?`}
      submitLabel="Deactivate"
      danger
      bare
      onDone={onDone}
      onSubmit={async (key) => {
        const toId = to ? Number(to) : null;
        for (const r of reports) {
          if (toId && Number(r.id) === toId) continue;
          await portalApi.patch(`people/${r.id}`, { reports_to: toId });
        }
        const res = await portalApi.patch(`people/${p.id}`, { status: "inactive" }, { idempotencyKey: key });
        const moved = toId ? reports.filter((r) => Number(r.id) !== toId).length : 0;
        toast(
          `${p.full_name} set inactive — history kept${moved ? ` · ${moved} moved to ${cands.find((c) => Number(c.id) === toId)?.full_name}` : reports.length ? ` · ${reports.length} now unassigned` : ""}`,
          "good",
        );
        return res ?? true;
      }}
    >
      {() => (
        <div className="v-person-dlg">
          <p>{`${p.full_name} will be set inactive. Their history, branches and credited enrollments are kept, and you can reactivate them any time.`}</p>
          {reports.length ? (
            <>
              <p>
                <strong>{`${reports.length} ${reports.length === 1 ? "person reports" : "people report"} to ${p.full_name}:`}</strong>
              </p>
              <ul className="v-person-list">
                {reports.map((r) => (
                  <li key={r.id}>{`${r.full_name} — ${ROLE_LABEL[r.role] || r.role}`}</li>
                ))}
              </ul>
              <label className="v-person-field">
                <span>Move them to</span>
                <select className="td-input td-select" aria-label="Reassign their team to" value={to} onChange={(e) => setTo(e.target.value)}>
                  <option value="">— Leave them unassigned —</option>
                  {cands.map((c) => (
                    <option key={c.id} value={String(c.id)}>{`${c.full_name} (${ROLE_LABEL[c.role]})`}</option>
                  ))}
                </select>
              </label>
              <p className="vx-small vx-muted">{cands.length ? "Leave unassigned to sort it out later — they will show under “Unassigned” in Team." : "No other active lead at this college, so they will become unassigned."}</p>
            </>
          ) : (
            <p className="vx-muted">Nobody reports to them.</p>
          )}
        </div>
      )}
    </DialogForm>
  );
}

/** Deactivate (R5): lists the people who report to this person and optionally reassigns them first. */
export async function deactivatePerson(p0: { id: number | string } | number | string): Promise<unknown> {
  const id = typeof p0 === "object" && p0 ? p0.id : p0;
  let pd: PersonDetail;
  let d: CollegeDetail;
  try {
    pd = await portalApi.get<PersonDetail>(`people/${id}`);
    d = await portalApi.get<CollegeDetail>(`colleges/${encodeURIComponent(String(personOf(pd).college_id))}`);
  } catch (e) {
    toast(errMsg(e), "bad");
    return null;
  }
  return openDialog<unknown>((done) => <DeactivateDialog p={personOf(pd)} pd={pd} d={d} onDone={done} />);
}

/** Reactivate; a second active college lead is refused by the server (409) and explained here. */
export async function reactivatePerson(p0: Pick<P, "id" | "full_name" | "role" | "reports_to"> | number): Promise<unknown> {
  const p = typeof p0 === "object" && p0 ? p0 : { id: p0, full_name: `#${p0}`, role: "", reports_to: null };
  try {
    const r = await portalApi.patch(`people/${p.id}`, { status: "active" });
    toast(`${p.full_name} reactivated${p.role !== "college_lead" && !p.reports_to ? " — assign them a lead" : ""}`, "good");
    return r ?? true;
  } catch (e) {
    toast(e instanceof PortalApiError && e.status === 409 && p.role === "college_lead" ? `${e.message} Use “Replace lead” on the current college lead instead.` : errMsg(e), "bad");
    return null;
  }
}

function ReplaceLeadDialog({ old, d, onDone }: { old: P; d: CollegeDetail; onDone: (r: unknown) => void }) {
  const cands = ((d.people || []) as unknown as P[]).filter((x) => isActive(x) && Number(x.id) !== Number(old.id));
  const [sel, setSel] = useState("");
  const [fate, setFate] = useState<Fate>("ambassador_lead");
  return (
    <DialogForm<unknown>
      title={`Replace ${old.full_name} as college lead`}
      submitLabel="Replace lead"
      bare
      onDone={onDone}
      onSubmit={async () => {
        if (!sel) throw validationError({ new_lead: "Choose the new college lead." });
        const r = await replaceLeadRequest(old.id, Number(sel), fate);
        const se = sideEffectText(r);
        toast(`${cands.find((c) => String(c.id) === sel)?.full_name} is now the college lead${se ? ` · ${se}` : ""}`, "good");
        return r ?? true;
      }}
    >
      {(err) => (
        <div className="v-person-dlg">
          <p>{`Choose who becomes the college lead of ${d.college?.short_name || d.college?.name} instead of ${old.full_name}.`}</p>
          <SelectField
            name="new_lead"
            label="New college lead"
            placeholder={cands.length ? "Choose a person…" : "Nobody else at this college yet"}
            options={cands.map((c) => ({ value: String(c.id), label: `${c.full_name} (${ROLE_LABEL[c.role]})` }))}
            value={sel}
            onChange={setSel}
            error={err.new_lead}
          />
          <button
            type="button"
            className="vx-linkbtn td-linkbtn"
            onClick={() => {
              onDone(null);
              void personDialog({ college_id: old.college_id, role: "college_lead" });
            }}
          >
            Or add a new person as college lead…
          </button>
          <fieldset className="v-person-choices">
            <legend>{`${old.full_name} then`}</legend>
            <Choice name="td-fate" value="ambassador_lead" checked={fate === "ambassador_lead"} onChange={() => setFate("ambassador_lead")} title="stays as an ambassador lead under the new lead" />
            <Choice name="td-fate" value="inactive" checked={fate === "inactive"} onChange={() => setFate("inactive")} title="is set inactive (history kept)" />
            <p className="vx-small vx-muted">Either way, the people who reported to them move to the new college lead.</p>
          </fieldset>
        </div>
      )}
    </DialogForm>
  );
}

/** Replace a college lead from their page: pick an existing person of the college (or add a new one) and decide the old lead's fate. */
export async function replaceLead(p0: { id: number | string } | number | string): Promise<unknown> {
  const id = typeof p0 === "object" && p0 ? p0.id : p0;
  let pd: PersonDetail;
  let d: CollegeDetail;
  try {
    pd = await portalApi.get<PersonDetail>(`people/${id}`);
    d = await portalApi.get<CollegeDetail>(`colleges/${encodeURIComponent(String(personOf(pd).college_id))}`);
  } catch (e) {
    toast(errMsg(e), "bad");
    return null;
  }
  return openDialog<unknown>((done) => <ReplaceLeadDialog old={personOf(pd)} d={d} onDone={done} />);
}

/** Delete a person added by mistake (server refuses with 409 when they have history; then offer Deactivate). */
export async function deletePerson(p: Pick<P, "id" | "full_name">, opts: { close?: () => void; onDeleted?: () => void } = {}): Promise<boolean> {
  const ok = await confirm({
    title: `Delete ${p.full_name}?`,
    text: "Only for a record added by mistake. This permanently removes the person and their branch links; anyone reporting to them becomes unassigned. This cannot be undone.",
    confirmLabel: "Delete permanently",
  });
  if (!ok) return false;
  try {
    await portalApi.del(`people/${p.id}`);
    toast(`${p.full_name} deleted`, "good");
    opts.close?.();
    opts.onDeleted?.();
    return true;
  } catch (e) {
    if (e instanceof PortalApiError && e.status === 409) {
      const again = await confirm({ title: "This person cannot be deleted", text: `${e.message} Deactivate ${p.full_name} instead? Their history is kept.`, confirmLabel: "Deactivate…", tone: "primary" });
      if (again) {
        opts.close?.();
        await deactivatePerson(p);
      }
    } else toast(errMsg(e), "bad");
    return false;
  }
}
