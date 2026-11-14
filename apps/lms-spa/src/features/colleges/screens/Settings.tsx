/**
 * Settings (/colleges/settings) — port of js/views/admin.js `renderSettings` (LMS proxy mode only: the portal
 * name / passcode / sign-in / sign-out controls of the standalone portal are not ported — the LMS signs people
 * in and its name goes into the audit log).
 * Sections: Programme target (target, deadline, start, target district groups), Your account, Courses & prices,
 * Alerts & defaults (fallback deadline, low-conversion alert, unanswered calls before "Not working"),
 * Branch relevance (category names as in branch.js) and Appearance (theme, per device).
 */
import "@/features/colleges/styles/views/admin.css";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { CATEGORY } from "../forms";
import { portalApi } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { clearTheme, prefersReducedMotion, setTheme, useTheme } from "../lib/prefs";
import { portalPath } from "../lib/routes";
import { usePortalSession } from "../lib/session";
import type { Course, PortalMeta, Program } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Button, ErrorCard, Field, Kv, PageHeader, Section, Skeleton, confirm, cx, toast, usePortalUi } from "../ui";

const msgOf = (e: unknown) => (e instanceof Error ? e.message : "Could not save");
const fieldsOf = (e: unknown): Record<string, string> => ((e as { fields?: Record<string, string> })?.fields ?? {});

function useBusy(): [boolean, (fn: () => Promise<void>) => Promise<void>] {
  const [busy, setBusy] = useState(false);
  return [
    busy,
    async (fn) => {
      setBusy(true);
      try {
        await fn();
      } finally {
        setBusy(false);
      }
    },
  ];
}

/** Labelled input (old admin.js `field`). */
function F({ label, help, error, req, full, children }: { label: ReactNode; help?: ReactNode; error?: string; req?: boolean; full?: boolean; children: (id: string, describedBy: string) => ReactNode }) {
  return (
    <Field label={label} help={help} error={error} required={req} full={full}>
      {children}
    </Field>
  );
}

const SECTIONS: [string, string][] = [
  ["programme", "Programme"],
  ["you", "Your account"],
  ["courses", "Courses"],
  ["targets", "Alerts"],
  ["relevance", "Branch relevance"],
  ["look", "Appearance"],
];

export function Settings() {
  usePortalPage({ title: "Settings", crumbs: [{ label: "Settings" }] });
  const meta = usePortalQuery<PortalMeta>("meta");
  const program = usePortalQuery<Program & { start?: string | null; program_start?: string | null; note?: string | null }>("program");
  const { canWrite } = usePortalUi();
  const head = <PageHeader title="Settings" sub="The programme target, the courses you sell, and how alerts are worked out. Every change is recorded in the audit log." />;
  if (!meta.data) {
    return (
      <div className="v-adm v-adm-settings">
        {head}
        {meta.error ? <ErrorCard title="Could not load settings" error={meta.error} retry={() => void meta.reload()} /> : <Skeleton lines={6} />}
      </div>
    );
  }
  const jump = (id: string) => document.querySelector(`[data-sec="${id}"]`)?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  return (
    <div className="v-adm v-adm-settings">
      {head}
      <nav className="ad-jump" aria-label="Settings sections">
        {SECTIONS.map(([id, l]) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={(e) => {
              e.preventDefault();
              jump(id);
            }}
          >
            {l}
          </a>
        ))}
        <Link to={`${portalPath.data}?tab=export`}>Export &amp; backup</Link>
        <Link to={`${portalPath.audit}?entity=setting`}>Settings history</Link>
      </nav>
      {!canWrite ? <p className="ad-warnline">You have view-only access. Settings can be viewed but not changed; ask an LMS super admin for edit access.</p> : null}
      <div data-sec="programme">
        <Section title="Programme target" sub="The headline goal every page measures against.">
          {program.data ? (
            <ProgramSection key={JSON.stringify(program.data)} program={program.data} canWrite={canWrite} />
          ) : program.loading ? (
            <Skeleton lines={2} card={false} />
          ) : (
            <p className="adm-muted">This server does not expose the programme settings yet.</p>
          )}
        </Section>
      </div>
      <div data-sec="you">
        <Section title="Your account">
          <AccountSection />
        </Section>
      </div>
      <div data-sec="courses">
        <Section title="Courses & prices" sub="What your team sells. Revenue = enrollments × price.">
          <Courses courses={meta.data.courses ?? []} />
        </Section>
      </div>
      <div data-sec="targets">
        <Section title="Alerts & defaults">
          <Alerts key={JSON.stringify(meta.data.settings ?? {})} s={meta.data.settings ?? {}} />
        </Section>
      </div>
      <div data-sec="relevance">
        <Section title="Branch relevance">
          <Relevance key={JSON.stringify(meta.data.settings?.relevance_factors ?? {})} s={meta.data.settings ?? {}} />
        </Section>
      </div>
      <div data-sec="look">
        <Section title="Appearance" sub="Saved on this device.">
          <ThemePicker />
        </Section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ your account (LMS) */

function AccountSection() {
  const { user, role } = usePortalSession();
  return (
    <div className="ad-you">
      <div className="ad-you__col">
        <div className="ad-access">
          <Kv
            pairs={[
              ["Signed in as", user || "—"],
              ["Access", role === "viewer" ? "View only" : "Can edit"],
              ["Sign-in", "Through Tech Drona LMS. Your LMS name is recorded with every change."],
            ]}
          />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ programme */

function ProgramSection({ program, canWrite }: { program: Program & { start?: string | null; program_start?: string | null; note?: string | null }; canWrite: boolean }) {
  const hasStart = "start" in program || "program_start" in program;
  const curStart = program.start || program.program_start || "";
  const [target, setTarget] = useState(program.target === null || program.target === undefined ? "" : String(program.target));
  const [deadline, setDeadline] = useState(program.deadline || "");
  const [start, setStart] = useState(curStart);
  const [groups, setGroups] = useState<Record<string, string[]>>(() => JSON.parse(JSON.stringify(program.target_district_groups || {})) as Record<string, string[]>);
  const [newName, setNewName] = useState("");
  const [err, setErr] = useState<Record<string, string>>({});
  const [formErr, setFormErr] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const names = Object.keys(groups);
  const groupOf = (id: string) => names.find((n) => (groups[n] ?? []).includes(id)) || "";
  const districts = [...(program.districts ?? [])].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const dis = !canWrite || undefined;

  const addGroup = () => {
    const n = newName.trim();
    const e = (m: string) => setErr({ groups: m });
    if (!n) return e("Type a group name first.");
    if (n.length > 60) return e("Use at most 60 characters.");
    if (names.some((x) => x.toLowerCase() === n.toLowerCase())) return e("A group with that name exists.");
    if (names.length >= 12) return e("At most 12 groups.");
    setErr({});
    setGroups({ ...groups, [n]: [] });
    setNewName("");
    toast(`Group “${n}” added. Pick its districts below.`, "info");
  };
  const pick = (id: string, g: string) => {
    const next = Object.fromEntries(names.map((n) => [n, (groups[n] ?? []).filter((x) => x !== id)]));
    if (g) next[g] = [...(next[g] ?? []), id];
    setGroups(next);
  };

  const save = () =>
    run(async () => {
      setErr({});
      setFormErr(null);
      const body: Record<string, unknown> = {};
      const n = Number(target);
      if (target === "" || !Number.isInteger(n) || n < 1 || n > 1000000) return setErr({ target: "Enter a whole number from 1 to 10,00,000." });
      if (!deadline) return setErr({ deadline: "Pick the deadline." });
      if (hasStart && start && start >= deadline) return setErr({ start: "The start must be before the deadline." });
      const clean = Object.fromEntries(names.filter((k) => (groups[k] ?? []).length).map((k) => [k, groups[k]!]));
      if (!Object.keys(clean).length) return setErr({ groups: "Keep at least one district in a target group." });
      if (n !== program.target) body.target = n;
      if (deadline !== program.deadline) body.deadline = deadline;
      if (hasStart && start && start !== curStart) body.start = start;
      if (JSON.stringify(clean) !== JSON.stringify(program.target_district_groups || {})) body.target_district_groups = clean;
      if (!Object.keys(body).length) {
        toast("Nothing changed", "info");
        return;
      }
      const lines: string[] = [];
      if (body.target) lines.push(`Target: ${fmt.num(program.target)} → ${fmt.num(body.target as number)} paid enrollments`);
      if (body.deadline) lines.push(`Deadline: ${fmt.date(program.deadline)} → ${fmt.date(body.deadline as string)}`);
      if (body.start) lines.push(`Start: ${fmt.date(curStart)} → ${fmt.date(body.start as string)}`);
      if (body.target_district_groups)
        lines.push(`Target districts: ${Object.values(program.target_district_groups || {}).flat().length} → ${Object.values(clean).flat().length} (${Object.keys(clean).join(", ")})`);
      const ok = await confirm({
        title: "Change the programme?",
        text: "Every page, pace and “remaining” figure is recalculated from this. The change is recorded in the audit log.",
        body: (
          <ul className="ad-confirm-list">
            {lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        ),
        confirmLabel: "Save changes",
        tone: "primary",
      });
      if (!ok) return;
      try {
        await portalApi.patch("program", body);
        toast("Programme saved", "good");
      } catch (e) {
        const fe = fieldsOf(e);
        setErr({ target: fe.target ?? "", deadline: fe.deadline ?? "", start: fe.start ?? "", groups: fe.target_district_groups ?? "" });
        if (!Object.keys(fe).length || fe._body) setFormErr(msgOf(e));
      }
    });

  return (
    <div className="ad-stack ad-program">
      <div className="td-form__grid ad-grid3">
        <F label="Paid enrollments target" req help={`Now ${fmt.num(program.target)}.`} error={err.target}>
          {(id, d) => <input id={id} type="number" className="td-input td-num" min={1} max={1000000} step={1} inputMode="numeric" value={target} disabled={dis} aria-describedby={d} onChange={(e) => setTarget(e.target.value)} />}
        </F>
        <F label="Deadline" req help={`Now ${fmt.date(program.deadline)}.`} error={err.deadline}>
          {(id, d) => <input id={id} type="date" className="td-input td-num" value={deadline} disabled={dis} aria-describedby={d} onChange={(e) => setDeadline(e.target.value)} />}
        </F>
        {hasStart ? (
          <F label="Programme start" help="Pace is measured from this date." error={err.start}>
            {(id, d) => <input id={id} type="date" className="td-input td-num" value={start} disabled={dis} aria-describedby={d} onChange={(e) => setStart(e.target.value)} />}
          </F>
        ) : null}
      </div>
      <div className="ad-sub">
        <h3>Target districts</h3>
        <p className="adm-muted">{program.note || "Districts are grouped under the old district names. The default district selection on every page is these districts."}</p>
        {canWrite ? (
          <div className="ad-row ad-groups__add">
            <input type="text" className="td-input" maxLength={60} placeholder="New group name, e.g. Prakasam" aria-label="New group name" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <Button icon="plus" size="sm" onClick={addGroup}>
              Add group
            </Button>
          </div>
        ) : null}
        <div className="td-field__error" aria-live="polite">
          {err.groups ?? ""}
        </div>
        <div className="ad-groups">
          <div className="ad-groups__chips">
            {names.length ? (
              names.map((n) => <span key={n} className="adm-pill">{`${n}: ${(groups[n] ?? []).length} district${(groups[n] ?? []).length === 1 ? "" : "s"}`}</span>)
            ) : (
              <span className="adm-muted">No target districts yet.</span>
            )}
          </div>
          <div className="ad-groups__grid">
            {districts.map((d) => (
              <label key={d.id} className={cx("ad-groups__row", groupOf(d.id) && "is-on")}>
                <span>
                  {d.name}
                  {d.old_district ? <small className="adm-muted">{` (old ${String(d.old_district)})`}</small> : null}
                </span>
                <select className="td-input td-select td-input--sm" aria-label={`Target group for ${d.name}`} disabled={dis} value={groupOf(d.id)} onChange={(e) => pick(d.id, e.target.value)}>
                  <option value="">Not a target</option>
                  {names.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </div>
      </div>
      {formErr ? (
        <div className="td-form__error" role="alert">
          {formErr}
        </div>
      ) : null}
      {canWrite ? (
        <div className="ad-row">
          <Button tone="primary" busy={busy} onClick={() => void save()}>
            Save programme
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ courses */

const wholeRupees = (v: string) => v !== "" && Number(v) >= 0 && Number.isInteger(Number(v));

function CourseRow({ c }: { c: Course }) {
  const [name, setName] = useState(c.name);
  const [price, setPrice] = useState(c.price_inr === null || c.price_inr === undefined ? "" : String(c.price_inr));
  const [active, setActive] = useState(!!c.active);
  const [err, setErr] = useState("");
  const [busy, run] = useBusy();
  const dirty = name.trim() !== c.name || price !== String(c.price_inr ?? "") || active !== !!c.active;
  const save = () =>
    run(async () => {
      setErr("");
      if (!name.trim()) return setErr("The course needs a name.");
      if (!wholeRupees(price)) return setErr("Enter the price in whole rupees.");
      try {
        await portalApi.patch(`courses/${c.id}`, { name: name.trim(), price_inr: Number(price), active: active ? 1 : 0 });
        toast(`${name.trim()} saved`, "good");
      } catch (e) {
        setErr(msgOf(e));
      }
    });
  const del = async () => {
    if (!(await confirm({ title: `Delete "${c.name}"?`, text: "Targets for this course are removed too. If students already enrolled in it, keep it and mark it inactive instead.", confirmLabel: "Delete course" }))) return;
    try {
      await portalApi.del(`courses/${c.id}`);
      toast("Course deleted", "good");
    } catch (e) {
      if ((e as { status?: number })?.status === 409) {
        const off = await confirm({
          title: "This course is in use",
          text: `${msgOf(e)} Inactive courses stay in past records but can no longer be chosen for new enrollments or targets.`,
          confirmLabel: "Mark inactive",
          tone: "primary",
        });
        if (off) {
          try {
            await portalApi.patch(`courses/${c.id}`, { active: 0 });
            toast(`${c.name} is now inactive`, "good");
          } catch (e2) {
            toast(msgOf(e2), "bad");
          }
        }
      } else toast(msgOf(e), "bad");
    }
  };
  return (
    <div className={cx("ad-course", !c.active && "is-off")}>
      <div className="ad-course__name">
        <input type="text" className="td-input td-input--sm" value={name} aria-label={`Name of ${c.name}`} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="ad-course__price">
        <span className="ad-rupee" aria-hidden="true">
          ₹
        </span>
        <input type="number" min={0} step={1} inputMode="numeric" className="td-input td-input--sm td-num ad-price" value={price} aria-label={`Price of ${c.name} in rupees`} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <label className="adm-toggle ad-course__active">
        <input type="checkbox" className="td-check" checked={active} onChange={(e) => setActive(e.target.checked)} />
        <span>Offered</span>
      </label>
      <div className="ad-course__acts">
        <Button size="sm" tone={dirty ? "primary" : "secondary"} busy={busy} onClick={() => void save()}>
          Save
        </Button>
        <Button icon="trash" tone="ghost" size="sm" ariaLabel={`Delete ${c.name}`} onClick={() => void del()} />
      </div>
      <div className="td-field__error" aria-live="polite">
        {err}
      </div>
    </div>
  );
}

function Courses({ courses }: { courses: Course[] }) {
  const { canWrite } = usePortalUi();
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [err, setErr] = useState("");
  const [busy, run] = useBusy();
  const add = () =>
    run(async () => {
      setErr("");
      if (!name.trim()) return setErr("Give the course a name.");
      if (!wholeRupees(price)) return setErr("Enter the price in whole rupees, e.g. 5000.");
      try {
        await portalApi.post("courses", { name: name.trim(), price_inr: Number(price), active: 1 });
        toast(`${name.trim()} added`, "good");
        setName("");
        setPrice("");
      } catch (e) {
        setErr(msgOf(e));
      }
    });
  return (
    <div>
      {courses.length ? (
        <div className="ad-courses">
          <div className="ad-course ad-course--head" aria-hidden="true">
            <span>Course</span>
            <span>Price per student</span>
            <span>Status</span>
            <span />
          </div>
          {courses.map((c) => (
            <CourseRow key={`${c.id}|${c.name}|${c.price_inr}|${c.active}`} c={c} />
          ))}
        </div>
      ) : (
        <p className="adm-muted">No courses yet. Add the courses your team sells, for example a ₹5,000 course and a ₹20,000 course. Targets and revenue use these.</p>
      )}
      {canWrite ? (
        <div className="ad-course ad-course--add">
          <div className="ad-course__name">
            <input type="text" className="td-input td-input--sm" placeholder="Course name, e.g. Full-Stack Development" aria-label="New course name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="ad-course__price">
            <span className="ad-rupee" aria-hidden="true">
              ₹
            </span>
            <input type="number" min={0} step={1} inputMode="numeric" className="td-input td-input--sm td-num ad-price" placeholder="5000" aria-label="New course price in rupees" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <span />
          <div className="ad-course__acts">
            <Button icon="plus" tone="primary" size="sm" busy={busy} onClick={() => void add()}>
              Add course
            </Button>
          </div>
          <div className="td-field__error" aria-live="polite">
            {err}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ alerts & defaults (org_name is not shown: nothing displays it; the stored value is kept) */

function Alerts({ s }: { s: Record<string, unknown> }) {
  const { canWrite } = usePortalUi();
  const mc0 = s.min_conversion === null || s.min_conversion === undefined ? "" : String(+(Number(s.min_conversion) * 100).toFixed(2));
  const [dl, setDl] = useState(String(s.state_target_deadline ?? ""));
  const [mc, setMc] = useState(mc0);
  const [ua, setUa] = useState(String(s.unreachable_after_attempts ?? 6));
  const [err, setErr] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const save = () =>
    run(async () => {
      setErr(null);
      const pct = Number(mc);
      const tries = Number(ua);
      if (!dl) return setErr("Choose a fallback deadline.");
      if (mc === "" || Number.isNaN(pct) || pct < 0 || pct > 100) return setErr("The low-conversion alert must be between 0 and 100 %.");
      if (ua === "" || !Number.isInteger(tries) || tries < 0 || tries > 50) return setErr("Unanswered calls: use a whole number from 0 to 50.");
      try {
        await portalApi.patch("settings", { state_target_deadline: dl, min_conversion: pct / 100, unreachable_after_attempts: tries });
        toast("Settings saved", "good");
      } catch (e) {
        setErr([msgOf(e), ...Object.values(fieldsOf(e))].join(" — "));
      }
    });
  return (
    <div className="ad-stack">
      <div className="td-form__grid ad-grid3">
        <F label="Fallback deadline" help={`Used for a college or person target that has no deadline of its own${s.state_target_deadline ? ` (now ${fmt.date(String(s.state_target_deadline))})` : ""}.`}>
          {(id, d) => <input id={id} type="date" className="td-input td-num" value={dl} aria-describedby={d} onChange={(e) => setDl(e.target.value)} />}
        </F>
        <F label="Low-conversion alert (%)" help="A place is flagged “few reached students enrol” when fewer than this share of the students reached go on to enrol. Default 5 %.">
          {(id, d) => <input id={id} type="number" min={0} max={100} step={0.5} inputMode="decimal" className="td-input td-num" value={mc} aria-describedby={d} onChange={(e) => setMc(e.target.value)} />}
        </F>
        <F label='Unanswered calls before a number is "Not working"' help="After this many calls in a row with no answer, busy, switched off or not reachable, the number is marked not working. 0 = never. Default 6.">
          {(id, d) => <input id={id} type="number" min={0} max={50} step={1} inputMode="numeric" className="td-input td-num" value={ua} aria-describedby={d} onChange={(e) => setUa(e.target.value)} />}
        </F>
      </div>
      {err ? (
        <div className="td-form__error" role="alert">
          {err}
        </div>
      ) : null}
      {canWrite ? (
        <div className="ad-row">
          <Button tone="primary" size="sm" busy={busy} onClick={() => void save()}>
            Save
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ branch relevance */

function Relevance({ s }: { s: Record<string, unknown> }) {
  const { canWrite } = usePortalUi();
  const rf0 = { it_core: 1, it_allied: 1, circuit: 0.6, core: 0.15, other: 0.15, ...((s.relevance_factors as Record<string, number>) ?? {}) } as Record<string, number>;
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(Object.keys(CATEGORY).map((k) => [k, rf0[k] === undefined ? "" : String(rf0[k])])));
  const [err, setErr] = useState<string | null>(null);
  const [busy, run] = useBusy();
  const save = () =>
    run(async () => {
      setErr(null);
      const v: Record<string, number> = {};
      for (const [k, raw] of Object.entries(vals)) {
        const n = Number(raw);
        if (raw === "" || Number.isNaN(n) || n < 0 || n > 1) return setErr(`${CATEGORY[k]![0]}: use a number from 0 to 1.`);
        v[k] = n;
      }
      try {
        await portalApi.patch("settings", { relevance_factors: v });
        toast("Factors saved — eligible-student estimates were recalculated", "good");
      } catch (e) {
        setErr(msgOf(e));
      }
    });
  return (
    <div className="ad-stack">
      <p className="adm-muted">
        For each type of branch: what share of final-year students could realistically buy a tech course? 1 = everyone, 0.5 = half, 0 = nobody. &quot;Eligible students&quot; = final-year students × this number. It drives the &quot;By eligible students&quot; split in Targets, the call order in the call queue and the &quot;target may be too high&quot; warning.
      </p>
      <div className="ad-rf td-form__grid">
        {Object.entries(CATEGORY).map(([k, [l, help]]) => (
          <F key={k} label={l} help={help}>
            {(id, d) => <input id={id} type="number" min={0} max={1} step={0.05} inputMode="decimal" className="td-input td-num" value={vals[k] ?? ""} aria-describedby={d} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} />}
          </F>
        ))}
      </div>
      {err ? (
        <div className="td-form__error" role="alert">
          {err}
        </div>
      ) : null}
      {canWrite ? (
        <div className="ad-row">
          <Button tone="primary" size="sm" busy={busy} onClick={() => void save()}>
            Save factors
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ appearance */

const readStoredTheme = (): string => {
  try {
    return localStorage.getItem("td.theme") || "system";
  } catch {
    return "system";
  }
};

function ThemePicker() {
  useTheme();
  const [cur, setCur] = useState(readStoredTheme);
  const choose = (v: "light" | "dark" | "system") => {
    // "Match device": no stored choice, so the portal follows the OS live (lib/prefs.ts)
    if (v === "system") clearTheme();
    else setTheme(v);
    setCur(v);
  };
  return (
    <div className="adm-seg" role="radiogroup" aria-label="Theme">
      {(
        [
          ["light", "Light"],
          ["dark", "Dark"],
          ["system", "Match device"],
        ] as const
      ).map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={cur === v} className={cx("adm-seg__btn", cur === v && "is-on")} onClick={() => choose(v)}>
          {l}
        </button>
      ))}
    </div>
  );
}
