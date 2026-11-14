/**
 * Target planner (/colleges/plan) — port of js/views/plan.js (+ js/plan/model.js → ./plan/model.ts).
 * GET /api/plan?districts=… gives the research rows + actual team / funnel counts; every planning number is
 * recomputed in the browser from the user's ASSUMPTIONS (saved in this browser only, `td.plan.assumptions`).
 * `?college=<id>` opens and scrolls to that college's row. It never sets anyone's target.
 */
import "@/features/colleges/styles/views/targets.css";
import "@/features/colleges/styles/views/plan.css";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../lib/cache";
import { fmt, today as browserToday } from "../lib/fmt";
import { prefersReducedMotion } from "../lib/prefs";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { districtName as scopeDistrictName, targetGroups, useDistrictScope } from "../lib/scope";
import { usePortalPage } from "../shell/page-context";
import { Funnel, PaceMeter } from "../charts";
import { Badge, Button, EmptyState, ErrorCard, Icon, Kv, PageHeader, Provenance, Section, Skeleton, Spinner, WriteOnly, cx, toast, type Tone } from "../ui";

import { addPerson } from "../forms";
import { computePlan, normalizeAssumptions, perRecruited, type Assumptions, type Plan as PlanModel, type PlanRow } from "./plan/model";
import { pctText, useServerToday } from "./targets/common";

/* eslint-disable @typescript-eslint/no-explicit-any -- /api/plan rows */
type Raw = Record<string, any>;

const LS_KEY = "td.plan.assumptions";
const LS_UI = "td.plan.ui";
const SC = ["min", "avg", "max"] as const;
const SC_LABEL: Record<string, string> = { min: "Minimum", avg: "Average", max: "Maximum" };
const STAGES: [string, string][] = [
  ["lead", "Lead"],
  ["interested", "Interested"],
  ["registered", "Registered"],
  ["applied", "Applied"],
  ["confirmed", "Confirmed"],
];
const RAG: Record<string, [string, Tone]> = { GREEN: ["Reachable", "good"], AMBER: ["Only with MoU", "warn"], RED: ["Not reachable", "bad"] };
const BASIS_TXT: Record<string, [string, string, string]> = {
  verified: ["✓", "Verified", "Verified — from an official document (AICTE EoA, NIRF, mandatory disclosure, annual report)."],
  estimated: ["≈", "Estimated", "Estimated — calculated from other numbers (for example current intake × fill). Treat as approximate."],
  unavailable: ["?", "Unavailable", "Unavailable — no figure found. Counted as 0; never guessed."],
};

const n1 = (v: unknown) => (v === null || v === undefined || !Number.isFinite(v as number) ? "—" : (v as number).toLocaleString("en-IN", { maximumFractionDigits: 1 }));
const val = (o: unknown) => (o && typeof o === "object" ? (o as Raw).value : o);
function lsGet(k: string): any {
  try {
    return JSON.parse(localStorage.getItem(k) || "null");
  } catch {
    return null;
  }
}
function lsSet(k: string, v: unknown): void {
  try {
    if (v === null) localStorage.removeItem(k);
    else localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* private mode */
  }
}
const offerCode = (t: unknown) => {
  const m = /^\((\w)\)/.exec(String(t || ""));
  return m ? m[1] : null;
};
/** first dialable number of a research phone field ("08645-350200 Extn 1409; 0863-…" → "08645350200") */
const telOf = (p: unknown) => {
  const d = String(p || "")
    .split(/[;,/]|\bext|\bx\b/i)[0]!
    .replace(/[^\d+]/g, "");
  return d.replace(/\D/g, "").length >= 8 ? d : null;
};
const safeUrl = (u: unknown) => (/^https?:\/\//i.test(String(u || "").trim()) ? String(u).trim() : null);
const smooth = (): ScrollBehavior => (prefersReducedMotion() ? "auto" : "smooth");
const districtName = (id: unknown) => {
  const n = scopeDistrictName(String(id || ""));
  return n || String(id || "—").replace(/-/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
};

/** compact provenance mark: ✓ verified · ≈ estimated · ? unavailable */
function Mark({ basis }: { basis: string }) {
  const b = BASIS_TXT[basis] ? basis : "unavailable";
  const [sym, label, tip] = BASIS_TXT[b]!;
  return (
    <span className={cx("td-prov", `td-prov--${b === "unavailable" ? "pending" : b}`, "vp-mark")} title={tip} role="img" aria-label={label}>
      {sym}
    </span>
  );
}
function NumB({ obj, strong }: { obj: unknown; strong?: boolean }) {
  const v = val(obj);
  const b = v === null || v === undefined ? "unavailable" : (obj as Raw)?.basis || "unavailable";
  return (
    <span className={cx("vp-nb", strong && "vp-nb--strong")}>
      <span className="td-num">{v === null || v === undefined ? "—" : fmt.num(v as number)}</span>
      <Mark basis={b} />
    </span>
  );
}
function SrcLink({ url, label = "source" }: { url: unknown; label?: string }) {
  const u = safeUrl(url);
  return u ? (
    <a href={u} target="_blank" rel="noopener noreferrer" className="vp-src">
      {label}
      <Icon name="external" size={12} />
    </a>
  ) : null;
}

/** research defaults, with the programme goal / deadline taken from the server when it has them */
function baseDefaults(data: Raw | undefined): Raw {
  const prog = data?.program || {};
  const d: Raw = {};
  const t = Number(prog.target);
  if (Number.isFinite(t) && t > 0) d.program_target = t;
  const dl = prog.deadline;
  if (typeof dl === "string" && /^\d{4}-\d{2}-\d{2}/.test(dl)) d.deadline = dl.slice(0, 10);
  return d;
}

interface UiState {
  q: string;
  p: string;
  show: string;
  sortKey: string;
  sortDir: number;
  distMode: string;
}

export function Plan() {
  usePortalPage({ title: "Target planner", crumbs: [{ label: "Targets & performance", to: portalPath.targets }, { label: "Planner", to: portalPath.plan }] });
  const [query] = useQueryState();
  useDistrictScope();
  const planQ = usePortalQuery<Raw>("plan", { scoped: true, keepPrevious: true });
  const serverToday = useServerToday();
  const data = planQ.data;
  const head = <PageHeader title="Target planner" sub="What-if model: how many colleges, College Leads and ambassadors it takes to reach the goal, recomputed as you change the assumptions. It never sets anyone’s target — real targets are set on Performance." />;

  if (!data) {
    if (planQ.error)
      return (
        <div className="v-plan">
          <PageHeader title="Target planner" sub="Plan colleges, College Leads and ambassadors for the 400-enrollment goal." />
          <ErrorCard
            title={(planQ.error as { status?: number }).status === 404 ? "The planner data is not available on this server yet" : "Could not load the plan"}
            error={planQ.error}
            retry={() => void planQ.reload()}
          />
        </div>
      );
    return (
      <div className="v-plan">
        <Skeleton lines={2} />
        <Skeleton lines={6} />
      </div>
    );
  }
  if (data.imported === false || !(data.colleges || []).length) {
    return (
      <div className="v-plan">
        <PageHeader title="Target planner" />
        <EmptyState
          icon="data"
          title={data.imported === false ? "Research data has not been imported yet" : "No researched colleges in this district selection"}
          text={
            data.imported === false
              ? data.message && !/node\s+server\//i.test(data.message)
                ? data.message
                : "The research plan has not been loaded yet. Ask an admin to import the research data once."
              : "Choose other districts with the district selector at the top of the page."
          }
        />
      </div>
    );
  }
  return (
    <div className="v-plan">
      {head}
      <PlanBody data={data} today={serverToday || browserToday()} focusCollege={query.college || null} />
    </div>
  );
}

function PlanBody({ data, today, focusCollege }: { data: Raw; today: string; focusCollege: string | null }) {
  const [A, setA] = useState<Assumptions>(() => normalizeAssumptions({ ...baseDefaults(data), ...(lsGet(LS_KEY) || {}) }));
  const ui0 = lsGet(LS_UI) || {};
  const [ui, setUi] = useState<UiState>(() => {
    const row = focusCollege ? (data.colleges || []).find((c: Raw) => c.college_id === focusCollege) : null;
    return { q: "", p: "", show: row && !row.targeted ? "all" : "targeted", sortKey: "rank", sortDir: 1, distMode: ui0.distMode || "groups" };
  });
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(focusCollege ? [focusCollege] : []));
  const [focus, setFocus] = useState<string | null>(focusCollege);
  const groups = targetGroups();
  const plan: PlanModel = useMemo(() => computePlan(data.colleges || [], A, { groups, today }), [data, A, groups, today]);
  // the cheap part (header strip + "what it takes") follows every keystroke; the tables follow when React is idle
  const heavyPlan: PlanModel = useDeferredValue(plan);
  const defaults = useMemo(() => JSON.stringify(normalizeAssumptions(baseDefaults(data))), [data]);
  const changed = JSON.stringify(A) !== defaults;

  const update = useCallback((fn: (a: Raw) => void) => {
    setA((prev: Raw) => {
      const next = JSON.parse(JSON.stringify(prev));
      fn(next);
      const norm = normalizeAssumptions(next);
      lsSet(LS_KEY, norm);
      return norm;
    });
  }, []);
  const resetA = () => {
    lsSet(LS_KEY, null);
    setA(normalizeAssumptions(baseDefaults(data)));
    toast("Assumptions reset to the research defaults", "info");
  };

  const openRow = (id: string) => {
    const r = plan.byId.get(id);
    if (r && !r.targeted) setUi((u) => ({ ...u, show: "all" }));
    setExpanded((s) => new Set(s).add(id));
    setFocus(id);
  };

  // scroll to the focused row once it is drawn
  useEffect(() => {
    if (!focus) return;
    const tr = document.querySelector<HTMLElement>(`tr[data-id="${CSS.escape(focus)}"]`);
    if (!tr) return;
    tr.scrollIntoView?.({ block: "start", behavior: smooth() });
    tr.classList.add("is-flash");
    tr.querySelector<HTMLElement>(".vp-exp")?.focus({ preventScroll: true });
    setFocus(null);
  });

  return (
    <>
      <div className="vp-strip" aria-live="polite">
        <Strip plan={plan} />
      </div>
      <AssumptionsPanel A={A} update={update} changed={changed} onReset={resetA} />
      <ReachSection plan={plan} />
      <DistrictSection
        plan={heavyPlan}
        mode={ui.distMode}
        onMode={(k) => {
          setUi((u) => ({ ...u, distMode: k }));
          lsSet(LS_UI, { ...(lsGet(LS_UI) || {}), distMode: k });
        }}
      />
      <CollegeSection
        plan={heavyPlan}
        ui={ui}
        setUi={setUi}
        expanded={expanded}
        toggle={(id) =>
          setExpanded((s) => {
            const n = new Set(s);
            if (n.has(id)) n.delete(id);
            else n.add(id);
            return n;
          })
        }
      />
      <AnalyticsSection plan={heavyPlan} onOpen={openRow} />
      <SourcesNote d={data} />
    </>
  );
}

const Tile = ({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string | null }) => (
  <div className={cx("vp-tile", tone && `vp-tile--${tone}`)}>
    <div className="vp-tile__label">{label}</div>
    <div className="vp-tile__value td-num">{value}</div>
    {sub ? <div className="vp-tile__sub">{sub}</div> : null}
  </div>
);

/* ------------------------------------------------------------------ a. header strip */
function Strip({ plan }: { plan: PlanModel }) {
  const T = plan.totals;
  const P = plan.progress;
  const A = plan.A;
  const pctTone = (p: number) => (p >= 1 ? "good" : p >= 0.8 ? "warn" : "bad");
  return (
    <>
      <Tile label="Goal" value={`${fmt.num(A.program_target)} paid`} sub={`by ${fmt.date(A.deadline)}`} tone="brand" />
      {SC.map((s) => (
        <Tile
          key={s}
          label={`Planned ${SC_LABEL[s]!.toLowerCase()}`}
          value={fmt.num(T[s])}
          sub={
            <span>
              <strong>{fmt.pct(T.pctOfTarget[s])}</strong> of goal · {T.gap[s] >= 0 ? `${fmt.num(T.gap[s])} above` : `${fmt.num(-T.gap[s])} short`}
            </span>
          }
          tone={pctTone(T.pctOfTarget[s])}
        />
      ))}
      <Tile label="Paid so far" value={fmt.num(P.confirmed)} sub={`${pctText(P.pct == null ? null : P.pct * 100)} of goal · ${fmt.num(P.remaining)} to go`} tone={P.confirmed ? "good" : null} />
      <Tile label="Days left" value={P.days_left === null ? "—" : fmt.num(P.days_left)} sub={P.required_weekly !== null ? `incl. today · ${n1(P.required_weekly)} confirmed / week needed` : "deadline passed"} />
    </>
  );
}

/* ------------------------------------------------------------------ b. assumptions */
function NumIn({ label, get, set, min, max, step, suffix, help }: { label: string; get: number; set: (v: number) => void; min: number; max: number; step: number; suffix?: string; help?: string }) {
  const [text, setText] = useState(String(+get.toFixed(4)));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(String(+get.toFixed(4)));
  }, [get]);
  return (
    <label className="vp-field">
      <span className="vp-field__label">{label}</span>
      <span className="vp-field__ctl">
        <input
          className="td-input vp-num"
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step={step}
          value={text}
          onFocus={() => (focused.current = true)}
          onBlur={() => {
            focused.current = false;
            setText(String(+get.toFixed(4)));
          }}
          onChange={(e) => {
            setText(e.target.value);
            const v = parseFloat(e.target.value);
            if (Number.isFinite(v) && v >= min && v <= max) set(v);
          }}
        />
        {suffix ? <span className="vp-field__suf">{suffix}</span> : null}
      </span>
      {help ? <span className="vp-field__help">{help}</span> : null}
    </label>
  );
}
function Slider({ label, get, set, min, max, step, show, help }: { label: string; get: number; set: (v: number) => void; min: number; max: number; step: number; show: (v: number) => string; help?: string }) {
  return (
    <label className="vp-field vp-field--range">
      <span className="vp-field__label">
        {label}
        <output className="vp-out td-num">{show(get)}</output>
      </span>
      <input type="range" className="vp-range" min={min} max={max} step={step} aria-label={label} aria-valuetext={show(get)} value={get} onChange={(e) => set(parseFloat(e.target.value))} />
      {help ? <span className="vp-field__help">{help}</span> : null}
    </label>
  );
}

function AssumptionsPanel({ A, update, changed, onReset }: { A: Raw; update: (fn: (a: Raw) => void) => void; changed: boolean; onReset: () => void }) {
  const phone = typeof matchMedia === "function" && matchMedia("(max-width: 699px)").matches;
  const [open, setOpen] = useState<boolean>(() => lsGet(LS_UI)?.assumeOpen ?? !phone);
  return (
    <details
      className="vp-assume td-card"
      open={open}
      onToggle={(e) => {
        const o = (e.currentTarget as HTMLDetailsElement).open;
        setOpen(o);
        lsSet(LS_UI, { ...(lsGet(LS_UI) || {}), assumeOpen: o });
      }}
    >
      <summary className="vp-assume__sum">
        <span className="vp-assume__title">
          <Icon name="settings" size={18} />
          Assumptions
        </span>
        <span className="td-badge td-badge--warn">Assumptions — not measured yet</span>
        <span className="td-badge td-badge--info" hidden={!changed}>
          Changed from research defaults
        </span>
        <span className="vp-assume__chev" aria-hidden="true">
          <Icon name="chevron" size={16} />
        </span>
      </summary>
      <div className="vp-assume__body">
        <p className="vp-assume__note">
          These are planning assumptions from the research (v2, 7 Nov 2026), not measured results. Replace them with Tech Drona’s own conversion and ambassador numbers after two weeks of selling. Changes are saved in this browser
          only.
        </p>
        <div className="vp-assume__grid">
          <fieldset className="vp-fs">
            <legend>Year groups in scope</legend>
            {(
              [
                ["final", "Final year (2027 batch)"],
                ["third", "3rd year (half weight)"],
                ["second", "2nd year (half weight)"],
              ] as const
            ).map(([k, l]) => (
              <label key={k} className="vp-check">
                <input
                  type="checkbox"
                  checked={!!A.years[k]}
                  onChange={(e) => {
                    const c = e.target.checked;
                    update((a) => {
                      a.years[k] = c;
                    });
                  }}
                />
                <span>{l}</span>
              </label>
            ))}
          </fieldset>
          <fieldset className="vp-fs vp-fs--rates">
            <legend>Conversion to paid (% of IT students)</legend>
            <div className="vp-rates" role="group">
              <span />
              {SC.map((s) => (
                <span key={s} className="vp-rates__hd">
                  {SC_LABEL[s]}
                </span>
              ))}
              {(
                [
                  ["final", "Final year"],
                  ["third", "3rd year"],
                  ["second", "2nd year"],
                ] as const
              ).map(([k, l]) => (
                <RateRow key={k} k={k} label={l} A={A} update={update} />
              ))}
            </div>
            <p className="vp-field__help">Multiplied by the college-type factor and the contact factor (1.0 verified placement line · 0.8 office line · 0.6 none). Research anchor: ~1% lead-to-enrollment industry index.</p>
          </fieldset>
          <fieldset className="vp-fs">
            <legend>Ambassador productivity</legend>
            <Slider label="Paid enrollments per active ambassador" min={1} max={20} step={0.5} get={A.paid_per_active} set={(v) => update((a) => void (a.paid_per_active = v))} show={n1} />
            <Slider label="Share of ambassadors who stay active" min={0.1} max={1} step={0.05} get={A.active_share} set={(v) => update((a) => void (a.active_share = v))} show={(v) => `${Math.round(v * 100)}%`} />
            <p className="vp-derived">= {n1(perRecruited(A))} paid enrollments per recruited ambassador (research: 2.5)</p>
            <Slider label="Buffer on the minimum" min={1} max={2} step={0.05} get={A.buffer} set={(v) => update((a) => void (a.buffer = v))} show={(v) => `× ${n1(v)}`} help="Recruit against buffer × minimum to absorb drop-outs." />
          </fieldset>
          <fieldset className="vp-fs">
            <legend>Team structure</legend>
            <div className="vp-grid2">
              <NumIn label="Min. ambassadors per college" min={1} max={50} step={1} get={A.min_ambassadors} set={(v) => update((a) => void (a.min_ambassadors = v))} />
              <NumIn label="Standby: 1 per" min={1} max={50} step={1} suffix="ambassadors" get={A.standby_per} set={(v) => update((a) => void (a.standby_per = v))} />
              <NumIn
                label="Own College Lead from"
                min={1}
                max={50}
                step={1}
                suffix="ambassadors"
                get={A.own_lead_from}
                set={(v) => update((a) => void (a.own_lead_from = v))}
                help="Smaller colleges share a Lead with one college in the same town."
              />
              <NumIn label="Lead capacity (span)" min={2} max={50} step={1} suffix="ambassadors" get={A.lead_span} set={(v) => update((a) => void (a.lead_span = v))} help="Above this, ambassador leads are added (research: 7)." />
              <NumIn label="College Leads per District Lead" min={1} max={50} step={1} get={A.district_lead_span} set={(v) => update((a) => void (a.district_lead_span = v))} />
            </div>
          </fieldset>
          <fieldset className="vp-fs">
            <legend>Personal targets per ambassador</legend>
            <div className="vp-grid3">
              {(
                [
                  ["min", "Minimum"],
                  ["standard", "Standard"],
                  ["stretch", "Stretch"],
                ] as const
              ).map(([k, l]) => (
                <NumIn key={k} label={l} min={0} max={1000} step={1} get={A.amb_targets[k]} set={(v) => update((a) => void (a.amb_targets[k] = v))} />
              ))}
            </div>
            <NumIn label="Programme goal (paid enrollments)" min={1} max={100000} step={1} get={A.program_target} set={(v) => update((a) => void (a.program_target = v))} />
          </fieldset>
        </div>
        <div className="vp-assume__foot">
          <Button icon="refresh" onClick={onReset}>
            Reset to research defaults
          </Button>
        </div>
      </div>
    </details>
  );
}

function RateRow({ k, label, A, update }: { k: "final" | "third" | "second"; label: string; A: Raw; update: (fn: (a: Raw) => void) => void }) {
  return (
    <>
      <span className="vp-rates__row">{label}</span>
      {SC.map((s, i) => (
        <RateIn key={s} label={`${label} ${SC_LABEL[s]} conversion, percent`} get={A.rates[k][i] * 100} set={(v) => update((a) => void (a.rates[k][i] = v / 100))} />
      ))}
    </>
  );
}
function RateIn({ label, get, set }: { label: string; get: number; set: (v: number) => void }) {
  const [text, setText] = useState(String(+get.toFixed(3)));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(String(+get.toFixed(3)));
  }, [get]);
  return (
    <input
      className="td-input vp-num"
      type="number"
      inputMode="decimal"
      min={0}
      max={100}
      step={0.05}
      aria-label={label}
      value={text}
      onFocus={() => (focused.current = true)}
      onBlur={() => {
        focused.current = false;
        setText(String(+get.toFixed(3)));
      }}
      onChange={(e) => {
        setText(e.target.value);
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v) && v >= 0 && v <= 100) set(v);
      }}
    />
  );
}

const Cell = ({ label, v, sub }: { label: string; v: ReactNode; sub?: string }) => (
  <div className="vp-kpi">
    <div className="vp-kpi__v td-num">{v}</div>
    <div className="vp-kpi__l">{label}</div>
    {sub ? <div className="vp-kpi__s">{sub}</div> : null}
  </div>
);

const Card = ({ plan, s }: { plan: PlanModel; s: "min" | "avg" }) => {
  const r = plan.reach[s];
  return (
    <article className={cx("vp-reach", r.reached ? "is-ok" : "is-short")}>
      <h3 className="vp-reach__title">
        {SC_LABEL[s]} scenario
        <Badge tone={r.reached ? "good" : "bad"}>{r.reached ? "Goal reached" : "Goal not reached"}</Badge>
      </h3>
      {r.reached ? (
        <p className="vp-reach__lead">
          The top <strong>{fmt.plural(r.colleges, "college")}</strong> by priority reach {fmt.num(r.total)} on the {SC_LABEL[s]!.toLowerCase()} scenario.
        </p>
      ) : (
        <p className="vp-reach__lead vp-reach__lead--bad">
          Even all {fmt.plural(r.colleges, "targeted college")} reach only {fmt.num(r.total)} on the {SC_LABEL[s]!.toLowerCase()} scenario — <strong>{fmt.num(r.shortfall)} short</strong>.
        </p>
      )}
      <div className="vp-kpis">
        <Cell label="Colleges" v={fmt.num(r.colleges)} />
        <Cell label="College Leads" v={fmt.num(r.college_leads)} sub="shared Leads count once" />
        <Cell label="Ambassador leads" v={fmt.num(r.ambassador_leads)} />
        <Cell label="Ambassadors" v={fmt.num(r.ambassadors)} sub={`+ ${fmt.num(r.standby)} standby`} />
      </div>
      <table className="vp-mini">
        <caption className="td-sr-only">Expected output per person, {SC_LABEL[s]} scenario</caption>
        <thead>
          <tr>
            <th scope="col">Expected paid</th>
            {SC.map((x) => (
              <th key={x} scope="col" className="td-al-right">
                {SC_LABEL[x]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Per ambassador</th>
            {SC.map((x) => (
              <td key={x} className="td-al-right td-num">
                {n1(r.perAmbassador[x])}
              </td>
            ))}
          </tr>
          <tr>
            <th scope="row">Per College Lead (team)</th>
            {SC.map((x) => (
              <td key={x} className="td-al-right td-num">
                {n1(r.perLead[x])}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </article>
  );
};

/* ------------------------------------------------------------------ c. what it takes */
function ReachSection({ plan }: { plan: PlanModel }) {
  const A = plan.A;
  const T = plan.totals;
  return (
    <Section title={`What it takes to reach ${fmt.num(A.program_target)}`} sub="Colleges are added in priority order until the scenario total reaches the goal. Minimum is the planning number; recruit against the buffered minimum.">
      <div className="vp-reach-grid">
        <Card plan={plan} s="min" />
        <Card plan={plan} s="avg" />
      </div>
      <div className="vp-reach-all">
        <table className="vp-mini vp-mini--wide">
          <caption>Whole selection ({fmt.plural(T.targeted, "targeted college")})</caption>
          <thead>
            <tr>
              <th scope="col" />
              {SC.map((x) => (
                <th key={x} scope="col" className="td-al-right">
                  {SC_LABEL[x]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Paid enrollments</th>
              {SC.map((x) => (
                <td key={x} className="td-al-right td-num">
                  {fmt.num(T[x])}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Per ambassador</th>
              {SC.map((x) => (
                <td key={x} className="td-al-right td-num">
                  {n1(plan.perAmbassador[x])}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Per College Lead (team incl. own sales)</th>
              {SC.map((x) => (
                <td key={x} className="td-al-right td-num">
                  {n1(plan.perLead[x])}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        <div>
          <h3 className="vp-h4">Full team for the selection</h3>
          <ul className="vp-team">
            <li>
              <strong className="td-num">{fmt.num(T.college_leads)}</strong> College Leads
            </li>
            <li>
              <strong className="td-num">{fmt.num(T.ambassador_leads)}</strong> ambassador leads
            </li>
            <li>
              <strong className="td-num">{fmt.num(T.ambassadors)}</strong> ambassadors + <strong className="td-num">{fmt.num(T.standby)}</strong> standby
            </li>
            <li>
              <strong className="td-num">{fmt.num(T.district_leads)}</strong> District/City Leads
            </li>
            <li>
              Personal targets: <strong>{`${A.amb_targets.min} / ${A.amb_targets.standard} / ${A.amb_targets.stretch}`}</strong> paid (min / standard / stretch)
            </li>
          </ul>
        </div>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ d. districts */
function DistrictSection({ plan, mode, onMode }: { plan: PlanModel; mode: string; onMode: (m: string) => void }) {
  const rows: Raw[] = (mode === "groups" ? plan.groups : plan.districts).filter((g: Raw) => g.colleges > 0);
  const groups = targetGroups();
  const label = (g: Raw) => (mode === "groups" ? g.key : districtName(g.key));
  const sub = (g: Raw) =>
    mode === "groups" ? (groups[g.key] || []).map((id) => districtName(id)).join(", ") : plan.colleges.find((r: Raw) => r.district_id === g.key)?.group || "not a target district";
  const max = Math.max(1, ...rows.map((g) => g.max));
  const target = plan.A.program_target;
  const toggle = (
    <div className="vp-seg" role="group" aria-label="Group districts by">
      {(
        [
          ["groups", "Target groups"],
          ["districts", "Present-day districts"],
        ] as const
      ).map(([k, l]) => (
        <button key={k} type="button" className={cx("vp-seg__b", mode === k && "is-on")} aria-pressed={mode === k} onClick={() => onMode(k)}>
          {l}
        </button>
      ))}
    </div>
  );
  const COLS: [string, string?][] = [
    [mode === "groups" ? "Target group" : "District"],
    ["Open colleges", "Colleges that are still running"],
    ["Targeted", "Colleges chosen for outreach"],
    ["IT students", "IT-branch students in the year groups ticked in Assumptions"],
    ["Planned paid (min)", "Minimum scenario: the planning number"],
    ["Planned paid (avg)"],
    ["Planned paid (max)"],
    ["College leads needed", "A college shared by two leads counts 0.5"],
    ["Ambassadors needed"],
    ["Ambassadors recruited", "Ambassadors already added in Team"],
    ["Paid so far"],
  ];
  const numCells = (g: Raw) => [
    ...[g.colleges, g.targeted, g.pool, g.min, g.avg, g.max].map((v, i) => (
      <td key={i} className="td-al-right td-num">
        {fmt.num(v)}
      </td>
    )),
    <td key="cl" className="td-al-right td-num">
      {n1(g.college_leads)}
    </td>,
    <td key="amb" className="td-al-right td-num">
      {fmt.num(g.ambassadors)}
    </td>,
    <td key="rec" className="td-al-right td-num">
      {fmt.num(g.recruited)}
    </td>,
    <td key="conf" className="td-al-right td-num">
      {fmt.num(g.confirmed)}
    </td>,
  ];
  return (
    <Section
      title="District breakdown"
      sub="Target groups are the old undivided districts (they include districts formed in 2022: Palnadu, Bapatla, NTR, Eluru). A college shared by two Leads counts 0.5."
      actions={toggle}
    >
      {rows.length ? (
        <>
          <figure className="vp-range-chart" role="group" aria-label="Planned paid enrollments by district: minimum to maximum, average marked">
            <div className="vp-rc-legend" aria-hidden="true">
              <span>
                <i className="vp-rc-key vp-rc-key--range" />
                Min – max
              </span>
              <span>
                <i className="vp-rc-key vp-rc-key--avg" />
                Average
              </span>
              <span>% = average as a share of the {fmt.num(target)} goal</span>
            </div>
            <ul className="vp-rc" aria-hidden="true">
              {rows.map((g) => (
                <li key={g.key} className="vp-rc__row">
                  <span className="vp-rc__label">{label(g)}</span>
                  <span className="vp-rc__track">
                    <span className="vp-rc__range" style={{ left: `${(g.min / max) * 100}%`, width: `${Math.max(0.6, ((g.max - g.min) / max) * 100)}%` }} />
                    <span className="vp-rc__avg" style={{ left: `${(g.avg / max) * 100}%` }} />
                  </span>
                  <span className="vp-rc__val td-num">
                    {`${fmt.num(g.min)}–${fmt.num(g.avg)}–${fmt.num(g.max)}`}
                    <small>{fmt.pct(g.shareOfTarget.avg)}</small>
                  </span>
                </li>
              ))}
            </ul>
            <figcaption className="td-sr-only">{rows.map((g) => `${label(g)}: ${g.min} to ${g.max}, average ${g.avg}`).join("; ")}</figcaption>
          </figure>
          <div className="vp-scroll" tabIndex={0} role="region" aria-label="District breakdown table">
            <table className="vp-table">
              <thead>
                <tr>
                  {COLS.map(([x, tip], i) => (
                    <th key={x} scope="col" className={i ? "td-al-right" : undefined} title={tip}>
                      {x}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((g) => (
                  <tr key={g.key}>
                    <th scope="row">
                      <span className="vp-strong">{label(g)}</span>
                      <small className="vp-sub">{sub(g)}</small>
                    </th>
                    {numCells(g)}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Selection</th>
                  {numCells(plan.totals)}
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      ) : (
        <EmptyState title="No colleges in this district selection" text="Choose districts with the district selector at the top of the page." />
      )}
    </Section>
  );
}

/* ------------------------------------------------------------------ e. colleges */
const COLS = [
  { key: "rank", label: "#", num: true, tip: "Rank by research priority" },
  { key: "p", label: "Priority", tip: "P1 = call first, then P2, P3; Hold = not targeted for now" },
  { key: "name", label: "College" },
  { key: "it_branch_count", label: "IT branches", num: true, tip: "Research count: computer branches only" },
  { key: "it_fy", label: "Final-year IT students", num: true },
  { key: "reachable", label: "Reachable students", num: true, tip: "IT students in the selected year groups × contact factor" },
  { key: "min", label: "Planned paid", num: true, tip: "Minimum scenario (the planning number). Expand the row for average and maximum." },
  { key: "amb", label: "Ambassadors (have / need)", num: true },
  { key: "lead", label: "College lead" },
  { key: "confirmed", label: "Paid so far", num: true },
  { key: "act", label: "Actions", nosort: true },
] as const;
const P_ORDER: Record<string, number> = { P1: 1, P2: 2, P3: 3, Hold: 4 };
function sortValue(r: Raw, k: string): unknown {
  const c = r.college;
  switch (k) {
    case "p":
      return P_ORDER[c.p_level] ?? 9;
    case "name":
      return (c.short_name || c.name || "").toLowerCase();
    case "it_branch_count":
      return c.it_branch_count;
    case "it_fy":
    case "it_3rd":
    case "it_2nd":
      return val(c[k]);
    case "amb":
      return r.ambassadors;
    case "lead":
      return r.college_leads;
    case "rag":
      return ({ GREEN: 1, AMBER: 2, RED: 3 } as Record<string, number>)[r.rag];
    case "offer":
      return offerCode(c.lead_offer);
    default:
      return r[k];
  }
}
const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9 ]/g, " ");

function filteredRows(plan: PlanModel, ui: UiState): PlanRow[] {
  const words = norm(ui.q.trim()).split(/\s+/).filter(Boolean);
  let rows: Raw[] = plan.colleges.filter((r: Raw) => r.college.status_final === "active" || r.targeted);
  if (ui.show === "targeted") rows = rows.filter((r) => r.targeted);
  if (ui.show === "hold") rows = rows.filter((r) => !r.targeted);
  if (ui.p) rows = rows.filter((r) => (r.college.p_level || "Hold") === ui.p);
  if (words.length) {
    rows = rows.filter((r) => {
      const c = r.college;
      const hay = norm([c.name, c.short_name, c.city, districtName(c.district_id), r.group, c.college_id].filter(Boolean).join(" "));
      return words.every((w) => hay.includes(w));
    });
  }
  const coll = new Intl.Collator("en-IN", { numeric: true, sensitivity: "base" });
  return rows.slice().sort((a, b) => {
    const x = sortValue(a, ui.sortKey);
    const y = sortValue(b, ui.sortKey);
    const xn = x === null || x === undefined || x === "";
    const yn = y === null || y === undefined || y === "";
    if (xn && yn) return (a.rank ?? 999) - (b.rank ?? 999);
    if (xn) return 1;
    if (yn) return -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : coll.compare(String(x), String(y));
    return c * ui.sortDir || (a.rank ?? 999) - (b.rank ?? 999);
  });
}

function CollegeSection({ plan, ui, setUi, expanded, toggle }: { plan: PlanModel; ui: UiState; setUi: (f: (u: UiState) => UiState) => void; expanded: Set<string>; toggle: (id: string) => void }) {
  const [text, setText] = useState(ui.q);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const rows = filteredRows(plan, ui);
  const sortBy = (key: string, num: boolean) =>
    setUi((u) => (u.sortKey === key ? { ...u, sortDir: -u.sortDir } : { ...u, sortKey: key, sortDir: num && key !== "rank" ? -1 : 1 }));
  return (
    <Section title="Colleges" sub="Only IT branches count (CSE, IT, AI/ML, DS, Cyber Security, CSBS, IoT, AI&DS …). Expand a row for its branches and its College Lead → ambassador team.">
      <div className="vp-toolbar">
        <input
          className="td-input vp-search"
          type="search"
          placeholder="Search college, town or district"
          aria-label="Search colleges"
          value={text}
          onChange={(e) => {
            const v = e.target.value;
            setText(v);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => setUi((u) => ({ ...u, q: v })), 120);
          }}
        />
        <select className="td-input td-select vp-sel" aria-label="Show" value={ui.show} onChange={(e) => setUi((u) => ({ ...u, show: e.target.value }))}>
          <option value="targeted">Targeted</option>
          <option value="hold">On hold</option>
          <option value="all">All active</option>
        </select>
        <select className="td-input td-select vp-sel" aria-label="Priority" value={ui.p} onChange={(e) => setUi((u) => ({ ...u, p: e.target.value }))}>
          <option value="">All priorities</option>
          {["P1", "P2", "P3", "Hold"].map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
      </div>
      <p className="vp-legend">
        <span className="vp-legend__k">Source of each figure:</span>
        {["verified", "estimated", "unavailable"].map((b) => (
          <span key={b} className="vp-legend__i">
            <Mark basis={b} />
            {BASIS_TXT[b]![1]}
          </span>
        ))}
      </p>
      <div className="vp-ctable">
        <p className="vp-count" role="status">
          {fmt.plural(rows.length, "college")} shown
        </p>
        {!rows.length ? (
          <EmptyState title="No colleges match" text="Clear the search or change the filters above." />
        ) : (
          <div className="vp-scroll vp-scroll--tall" tabIndex={0} role="region" aria-label="College plan table">
            <table className="vp-table vp-table--colleges">
              <thead>
                <tr>
                  {COLS.map((c) => (
                    <th
                      key={c.key}
                      scope="col"
                      className={cx("num" in c && c.num && "td-al-right", `vp-c-${c.key}`)}
                      aria-sort={ui.sortKey === c.key ? (ui.sortDir === 1 ? "ascending" : "descending") : "none"}
                      title={"tip" in c ? c.tip : undefined}
                    >
                      {"nosort" in c ? (
                        <span className="td-sr-only">{c.label}</span>
                      ) : (
                        <button type="button" className="td-th-sort" onClick={() => sortBy(c.key, "num" in c && !!c.num)}>
                          <span>{c.label}</span>
                          <span className="td-th-sort__ind" aria-hidden="true" />
                        </button>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const open = expanded.has(r.id);
                  return [<CollegeRow key={r.id} r={r} open={open} onToggle={() => toggle(r.id)} />, open ? <DetailRow key={`${r.id}-d`} r={r} /> : null];
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}

function CollegeRow({ r, open, onToggle }: { r: Raw; open: boolean; onToggle: () => void }) {
  const c = r.college;
  const pTone = (({ P1: "brand", P2: "info", P3: "neutral", Hold: "warn" } as Record<string, Tone>)[c.p_level] || "neutral") as Tone;
  const leadTxt = !r.targeted ? "—" : r.college_leads === 1 ? (r.ambassador_leads ? `Own + ${r.ambassador_leads} amb. leads` : "Own") : "Shared (½)";
  const actualLead = (c.actual?.college_leads || 0) > 0;
  const tel = c.contact?.verified ? telOf(c.contact.phone) : null;
  // column class + label on every cell: the phone layout turns each row into a labelled card
  const td = (key: string, children: ReactNode, cls?: string) => {
    const col = COLS.find((x) => x.key === key)!;
    return (
      <td className={cx(cls, `vp-c-${key}`)} data-label={col.label}>
        {children}
      </td>
    );
  };
  return (
    <tr data-id={r.id} className={cx(open && "is-open", !r.targeted && "is-hold")}>
      {td(
        "rank",
        <span className="vp-rankcell">
          <button type="button" className="vp-exp" aria-expanded={open} aria-controls={`vp-d-${r.id}`} aria-label={`${open ? "Hide" : "Show"} branches and team for ${c.name}`} onClick={onToggle}>
            <Icon name="chevron" size={16} />
          </button>
          <span className="td-num">{c.rank ?? "—"}</span>
        </span>,
      )}
      {td("p", <Badge tone={pTone}>{c.p_level || "Hold"}</Badge>)}
      {td(
        "name",
        <>
          <Link to={portalPath.college(r.id)} className="vp-strong vp-name" title={c.name}>
            {c.short_name || c.name}
          </Link>
          <small className="vp-sub">
            {[c.city, districtName(c.district_id)].filter(Boolean).join(" · ")}
            {c.verify_flag ? (
              <span className="vp-flag" title={c.verify_flag}>
                {" "}
                · <Icon name="warn" size={12} /> check
              </span>
            ) : null}
          </small>
        </>,
      )}
      {td("it_branch_count", c.it_branch_count ?? "—", "td-al-right td-num")}
      {td("it_fy", <NumB obj={c.it_fy} strong />, "td-al-right")}
      {td("reachable", r.reachable === null ? "—" : fmt.num(r.reachable), "td-al-right td-num")}
      {td("min", fmt.num(r.min), "td-al-right td-num vp-strong")}
      {td(
        "amb",
        <span className="vp-amb">
          <span className={cx("td-num", r.recruited >= r.ambassadors && r.ambassadors && "vp-ok")}>{fmt.num(r.recruited)}</span>
          <span className="vp-muted"> / {fmt.num(r.ambassadors)}</span>
          {r.standby ? <small className="vp-sub">+{r.standby} standby</small> : null}
        </span>,
        "td-al-right",
      )}
      {td(
        "lead",
        <span className="vp-lead">
          {leadTxt}
          {actualLead ? <Badge tone="good">appointed</Badge> : r.targeted ? <small className="vp-sub">not appointed</small> : null}
        </span>,
      )}
      {td("confirmed", fmt.num(r.confirmed), "td-al-right td-num")}
      {td(
        "act",
        <span className="vp-actions">
          {tel ? (
            <a
              className="td-btn td-btn--secondary td-btn--sm vp-call"
              href={`tel:${tel}`}
              aria-label={`Call ${c.name}${c.contact.role ? ` (${c.contact.role})` : ""}`}
              title={`${c.contact.phone}${c.contact.role ? ` · ${c.contact.role}` : ""}`}
            >
              <Icon name="phone" size={16} />
              <span>Call</span>
            </a>
          ) : (
            <span className="vp-nocall" title="No verified phone number yet">
              No verified no.
            </span>
          )}
          <Link className="td-btn td-btn--ghost td-btn--sm td-btn--icon" to={portalPath.college(r.id)} aria-label={`Open ${c.name}`} title="Open college page">
            <Icon name="arrow" size={16} />
          </Link>
        </span>,
        "vp-c-act",
      )}
    </tr>
  );
}

const rgTip = (k: string) =>
  ({ GREEN: "Average ≥ 400 from individual sign-ups", AMBER: "400 only via an institutional MoU covering ~half the IT students, from Jan 2027", RED: "Not reachable by any modelled route" })[k] || "";

function DetailRow({ r }: { r: Raw }) {
  const c = r.college;
  const it: Raw[] = (c.branches || []).filter((b: Raw) => b.is_it);
  const hidden = (c.branches || []).length - it.length;
  return (
    <tr className="vp-detail" id={`vp-d-${r.id}`}>
      <td colSpan={COLS.length}>
        <div className="vp-detail__grid">
          <div className="vp-detail__col">
            <h3 className="vp-h4">Team for this college</h3>
            <div className="vp-tree-host">
              <TeamTree r={r} />
            </div>
          </div>
          <div className="vp-detail__col">
            <h3 className="vp-h4">IT strength</h3>
            {it.length ? (
              <div className="vp-xscroll">
                <table className="vp-mini vp-mini--branches">
                  <caption>
                    IT branches ({it.length}){hidden ? <small className="vp-sub"> · {hidden} non-IT branches hidden</small> : null}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Branch</th>
                      <th scope="col" className="td-al-right" title="Seats / year of the 2023-24 entry batch = this year’s final-year students">
                        Final-year students
                      </th>
                      <th scope="col" className="td-al-right">
                        Seats / year (latest)
                      </th>
                      <th scope="col">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {it.map((b, i) => (
                      <tr key={`${b.name}-${i}`}>
                        <th scope="row">{b.name}</th>
                        <td className="td-al-right">
                          <NumB obj={{ value: b.intake_2023_24, basis: b.basis }} />
                        </td>
                        <td className="td-al-right td-num">{b.intake_latest == null ? "—" : fmt.num(b.intake_latest)}</td>
                        <td>{safeUrl(b.source) ? <SrcLink url={b.source} /> : <span className="vp-muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="vp-muted">No IT branch list in the research for this college.</p>
            )}
          </div>
          <div className="vp-detail__col">
            <h3 className="vp-h4">Plan for this college</h3>
            <Kv
              pairs={[
                ["IT branches", c.it_branch_count == null ? "—" : fmt.num(c.it_branch_count)],
                [
                  "IT students (final · 3rd · 2nd yr)",
                  <span key="it">
                    <NumB obj={c.it_fy} /> · <NumB obj={c.it_3rd} /> · <NumB obj={c.it_2nd} />
                  </span>,
                ],
                ["Reachable", r.reachable === null ? "—" : fmt.num(r.reachable)],
                ["Planned paid (min · avg · max)", `${fmt.num(r.min)} · ${fmt.num(r.avg)} · ${fmt.num(r.max)}`],
                ["Paid so far", fmt.num(r.confirmed)],
                ["Research rating (can this college alone reach the goal?)", c.status_final === "active" ? `${(RAG[r.rag] || ["—"])[0]} — ${rgTip(r.rag)}` : "—"],
              ]}
            />
            <h3 className="vp-h4 vp-h4--gap">Research facts</h3>
            <Kv
              pairs={[
                [
                  "IT final-year pool",
                  <span key="a">
                    <NumB obj={c.it_fy} /> <SrcLink url={c.it_fy?.source} />
                  </span>,
                ],
                [
                  "All-branch final year",
                  <span key="b">
                    <NumB obj={c.fy_pool} /> <SrcLink url={c.fy_pool?.source} />
                  </span>,
                ],
                [
                  "Total students",
                  <span key="c">
                    <NumB obj={c.total_students} />
                    {c.total_students?.year ? <small className="vp-sub"> {c.total_students.year}</small> : null} <SrcLink url={c.total_students?.source} />
                  </span>,
                ],
                ["Type · contact factor", `${c.type ? String(c.type).toUpperCase() : "—"} · × ${c.access_x ?? "—"}`],
                ["Research target (min/avg/max)", c.research_target ? `${fmt.num(c.research_target.min)} / ${fmt.num(c.research_target.avg)} / ${fmt.num(c.research_target.max)}` : "—"],
                ["MoU pipeline from Jan 2027", c.mou ? `${fmt.num(c.mou.min)} / ${fmt.num(c.mou.avg)} / ${fmt.num(c.mou.max)} seats` : "—"],
                ["Final-year exams end", c.exam_4_1_end ? fmt.date(c.exam_4_1_end) : c.exam_4_1_note || "—"],
                ["Placement", c.placement_tier || "—"],
                ["Lead offer", c.lead_offer || "—"],
                c.hold_reason ? ["Why on hold", c.hold_reason] : null,
                c.verify_flag ? ["To verify", c.verify_flag] : null,
                [
                  "Contact",
                  c.contact ? (
                    <span key="k">
                      {[c.contact.name, c.contact.role].filter(Boolean).join(" · ") || "College office"}{" "}
                      {c.contact.phone ? (
                        c.contact.verified && telOf(c.contact.phone) ? (
                          <a href={`tel:${telOf(c.contact.phone)}`}>{c.contact.phone}</a>
                        ) : (
                          <span>
                            {c.contact.phone} <Provenance basis="pending" />
                          </span>
                        )
                      ) : null}
                      {c.contact.verified ? (
                        <>
                          {" "}
                          <Provenance basis="verified" />
                        </>
                      ) : null}{" "}
                      <SrcLink url={c.contact.source} />
                    </span>
                  ) : (
                    "No contact in the research"
                  ),
                ],
              ]}
            />
          </div>
        </div>
      </td>
    </tr>
  );
}

const SCX = ["min", "avg", "max"] as const;
const Person = ({ p, roleLabel }: { p: Raw; roleLabel: string }) => (
  <li className="vp-node vp-node__row">
    <span className="vp-node__dot is-filled" aria-hidden="true" />
    <Link to={portalPath.person(p.id)} className="vp-strong">
      {p.full_name || `Person ${p.id}`}
    </Link>
    <small className="vp-sub">{` ${roleLabel}${p.status && p.status !== "active" ? ` · ${p.status}` : ""}${p.enrolled != null ? ` · ${fmt.num(p.enrolled)} confirmed` : ""}`}</small>
  </li>
);

const AddBtn = ({ r, label, role, reports_to }: { r: Raw; label: string; role: string; reports_to?: number | string | null }) => (
  <WriteOnly>
    <button type="button" className="td-btn td-btn--ghost td-btn--sm vp-add" onClick={() => void addPerson({ college_id: r.id, role, reports_to: reports_to ?? null })} aria-label={`Add ${label.toLowerCase()} at ${r.college.name}`}>
      <Icon name="plus" size={14} />
      <span>Add person</span>
    </button>
  </WriteOnly>
);

const Vacancies = ({ r, n, label, role, reports_to }: { r: Raw; n: number; label: string; role: string; reports_to?: number | string | null }) =>
  n > 0 ? (
    <li className="vp-node vp-node--vacant">
      <span className="vp-slots" role="img" aria-label={`${n} vacant ${label.toLowerCase()} ${n === 1 ? "slot" : "slots"}`}>
        {Array.from({ length: Math.min(n, 24) }, (_, i) => (
          <span key={i} className="vp-slot" aria-hidden="true" />
        ))}
        {n > 24 ? <small>+{n - 24}</small> : null}
      </span>
      <span className="vp-muted vp-slots__t">{`${n} vacant ${n === 1 ? label.toLowerCase() : `${label.toLowerCase()}s`}`}</span>
      <AddBtn r={r} label={label} role={role} reports_to={reports_to} />
    </li>
  ) : null;

function TeamTree({ r }: { r: Raw }) {
  const inline = Array.isArray(r.college.actual?.people) ? (r.college.actual.people as Raw[]) : null;
  const q = usePortalQuery<unknown>(inline ? null : "people", { query: { college: r.id } });
  if (!inline && q.loading) return <Spinner label="Loading team…" size="sm" />;
  if (!inline && q.error) return <p className="vp-muted">Could not load the team: {(q.error as Error).message || String(q.error)}</p>;
  const st: Raw[] = inline ?? (Array.isArray(q.data) ? (q.data as Raw[]) : ((q.data as Raw)?.rows ?? (q.data as Raw)?.items ?? []));
  const people = st.filter((p) => p.status !== "inactive");
  const leads = people.filter((p) => p.role === "college_lead");
  const aLeads = people.filter((p) => p.role === "ambassador_lead");
  const ambs = people.filter((p) => p.role === "ambassador");
  if (!r.targeted && !people.length) return <p className="vp-muted">Not targeted under the current assumptions, so no team is planned.</p>;
  const lead = leads[0];
  const needAL = r.ambassador_leads;
  const needAmb = r.ambassadors;
  const vacantAmb = Math.max(0, needAmb - ambs.length);
  let subTree: ReactNode;
  if (needAL || aLeads.length) {
    const nAL = Math.max(needAL, aLeads.length);
    const alIds = new Set(aLeads.map((p) => p.id));
    const direct = ambs.filter((p) => !alIds.has(p.reports_to));
    const per = Array.from({ length: nAL }, (_, i) => ({
      people: aLeads[i] ? ambs.filter((p) => p.reports_to === aLeads[i]!.id) : [],
      vacant: Math.floor(vacantAmb / nAL) + (i < vacantAmb % nAL ? 1 : 0),
    }));
    subTree = (
      <ul className="vp-tree">
        {direct.map((p) => (
          <Person key={p.id} p={p} roleLabel="Ambassador (reports to the College Lead)" />
        ))}
        {per.map((g, i) => (
          <li key={`al${i}`} className="vp-node vp-node--branch">
            {aLeads[i] ? (
              <span className="vp-node__row">
                <span className="vp-node__dot is-filled" aria-hidden="true" />
                <Link to={portalPath.person(aLeads[i]!.id)} className="vp-strong">
                  {aLeads[i]!.full_name}
                </Link>
                <small className="vp-sub"> Ambassador lead</small>
              </span>
            ) : (
              <span className="vp-node__row">
                <span className="vp-node__dot" aria-hidden="true" />
                <span className="vp-muted">{`Vacant — Ambassador lead ${i + 1}`}</span>
                <AddBtn r={r} label="Ambassador lead" role="ambassador_lead" reports_to={lead?.id} />
              </span>
            )}
            <ul className="vp-tree">
              {g.people.map((p) => (
                <Person key={p.id} p={p} roleLabel="Ambassador" />
              ))}
              <Vacancies r={r} n={g.vacant} label="Ambassador" role="ambassador" reports_to={aLeads[i]?.id || lead?.id} />
            </ul>
          </li>
        ))}
      </ul>
    );
  } else
    subTree = (
      <ul className="vp-tree">
        {ambs.map((p) => (
          <Person key={p.id} p={p} roleLabel="Ambassador" />
        ))}
        <Vacancies r={r} n={vacantAmb} label="Ambassador" role="ambassador" reports_to={lead?.id} />
      </ul>
    );
  return (
    <>
      <p className="vp-team-sum">
        {`Needs 1 College Lead${r.college_leads < 1 ? " (shared with a nearby college)" : ""}`}
        {needAL ? `, ${needAL} ambassador leads` : ""}
        {`, ${fmt.num(needAmb)} ambassadors + ${fmt.num(r.standby)} standby. Recruited: ${fmt.plural(ambs.length, "ambassador")}.`}
        {r.lead_note ? <small className="vp-sub"> ({r.lead_note})</small> : null}
      </p>
      <ul className="vp-tree vp-tree--root" aria-label={`Team hierarchy for ${r.college.name}`}>
        <li className="vp-node vp-node--root">
          {lead ? (
            <span className="vp-node__row">
              <span className="vp-node__dot is-filled" aria-hidden="true" />
              <Link to={portalPath.person(lead.id)} className="vp-strong">
                {lead.full_name}
              </Link>
              <small className="vp-sub"> College Lead</small>
            </span>
          ) : (
            <span className="vp-node__row">
              <span className="vp-node__dot" aria-hidden="true" />
              <span className="vp-muted">Vacant — College Lead</span>
              <AddBtn r={r} label="College Lead" role="college_lead" />
            </span>
          )}
          {subTree}
        </li>
      </ul>
      {r.ambassadors ? <p className="vp-sub">{`Expected per ambassador: ${SCX.map((s) => n1(r.perAmb[s])).join(" / ")} (min / avg / max)`}</p> : null}
    </>
  );
}

/* ------------------------------------------------------------------ f. progress & analytics */
function AnalyticsSection({ plan, onOpen }: { plan: PlanModel; onOpen: (id: string) => void }) {
  const stage: Record<string, number> = Object.fromEntries(STAGES.map(([k]) => [k, 0]));
  let dropped = 0;
  let calls = 0;
  for (const r of plan.colleges as Raw[]) {
    const a = r.college.actual || {};
    for (const [k] of STAGES) stage[k]! += a.leads_by_stage?.[k] || 0;
    dropped += a.leads_by_stage?.dropped || 0;
    calls += a.calls || 0;
  }
  const any = STAGES.some(([k]) => stage[k]! > 0);
  const P = plan.progress;
  const T = plan.totals;
  const weeks = P.days_left ? P.days_left / 7 : null;
  const paceRows: [string, number][] = [
    ["Goal", plan.A.program_target],
    ["Planned minimum", T.min],
    ["Buffered minimum (recruit against this)", T.buffered],
  ];
  const withPeople = (plan.colleges as Raw[]).filter((r) => (r.college.actual?.ambassadors || 0) > 0 || (r.college.actual?.college_leads || 0) > 0);
  return (
    <Section title="Progress & analytics" sub="Actual numbers recorded in the portal for this district selection (not estimates).">
      <div className="vp-an-grid">
        <div>
          <h3 className="vp-h4">Student funnel</h3>
          {any ? (
            <Funnel
              label="Student funnel for this selection (students who reached at least each stage)"
              steps={STAGES.map(([, l], i) => ({ label: l, value: STAGES.slice(i).reduce((s, [kk]) => s + stage[kk]!, 0) }))}
            />
          ) : (
            <EmptyState icon="list" title="No students recorded yet" text="Lead → interested → registered → applied → confirmed counts appear here as the team records students on each college page." />
          )}
          {any ? <p className="vp-sub">Each step counts students who reached at least that stage.</p> : null}
          {dropped ? <p className="vp-sub">{fmt.num(dropped)} dropped / refunded (not counted).</p> : null}
        </div>
        <div>
          <h3 className="vp-h4">Confirmed vs required pace</h3>
          <div>
            <PaceMeter done={P.confirmed} target={plan.A.program_target} label="Confirmed paid enrollments vs goal" />
            <table className="vp-mini">
              <caption className="td-sr-only">Required pace</caption>
              <thead>
                <tr>
                  <th scope="col">Aim</th>
                  <th scope="col" className="td-al-right">
                    Target
                  </th>
                  <th scope="col" className="td-al-right">
                    Still needed
                  </th>
                  <th scope="col" className="td-al-right">
                    Per week
                  </th>
                </tr>
              </thead>
              <tbody>
                {paceRows.map(([l, tgt]) => (
                  <tr key={l}>
                    <th scope="row">{l}</th>
                    <td className="td-al-right td-num">{fmt.num(tgt)}</td>
                    <td className="td-al-right td-num">{fmt.num(Math.max(0, tgt - P.confirmed))}</td>
                    <td className="td-al-right td-num">{weeks ? n1(Math.max(0, tgt - P.confirmed) / weeks) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="vp-sub">
              {P.days_left ?? "—"} days left including today (to {fmt.date(plan.A.deadline)}). Only confirmed (verified payment) enrollments count. Calls logged in this selection: {fmt.num(calls)}.
            </p>
          </div>
        </div>
        <div className="vp-an-wide">
          <h3 className="vp-h4">Ambassador performance</h3>
          {withPeople.length ? (
            <div className="vp-scroll" tabIndex={0} role="region" aria-label="Ambassador performance">
              <table className="vp-table">
                <thead>
                  <tr>
                    {["College", "Ambassadors (active / recruited / needed)", "Confirmed", "Per recruited ambassador", "Plan per ambassador (min)", "Status"].map((x, i) => (
                      <th key={x} scope="col" className={i ? "td-al-right" : undefined}>
                        {x}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {withPeople
                    .slice()
                    .sort((a, b) => b.confirmed - a.confirmed)
                    .map((r) => {
                      const a = r.college.actual || {};
                      const per = a.ambassadors ? r.confirmed / a.ambassadors : null;
                      const planPer = r.perAmb.min;
                      const tone: Tone = per === null ? "neutral" : per >= (planPer || 0) ? "good" : "warn";
                      return (
                        <tr key={r.id}>
                          <th scope="row">
                            <a
                              href={`${portalPath.plan}?college=${encodeURIComponent(r.id)}`}
                              onClick={(e) => {
                                e.preventDefault();
                                onOpen(r.id);
                              }}
                            >
                              {r.college.short_name || r.college.name}
                            </a>
                          </th>
                          <td className="td-al-right td-num">{`${fmt.num(a.active_ambassadors || 0)} / ${fmt.num(a.ambassadors || 0)} / ${fmt.num(r.ambassadors)}`}</td>
                          <td className="td-al-right td-num">{fmt.num(r.confirmed)}</td>
                          <td className="td-al-right td-num">{n1(per)}</td>
                          <td className="td-al-right td-num">{n1(planPer)}</td>
                          <td className="td-al-right">
                            <Badge tone={tone}>{per === null ? "No ambassadors" : tone === "good" ? "On plan" : "Below plan"}</Badge>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="people"
              title="No College Leads or ambassadors recruited yet"
              text={`The plan needs ${fmt.num(T.college_leads)} College Leads and ${fmt.num(T.ambassadors)} ambassadors in this selection. Open a college row above and use “Add person” to start filling the vacancies.`}
            />
          )}
        </div>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ sources */
function SourcesNote({ d }: { d: Raw }) {
  const T = d.totals_research;
  return (
    <footer className="vp-sources">
      <h3 className="vp-h4">Where these numbers come from</h3>
      <ul>
        <li>{`Research ${d.research_version || "v2"}${d.source_report ? ` — report “${String(d.source_report).split(/[\\/]/).pop()}”` : ""}${d.generated_at ? `, loaded ${fmt.date(d.generated_at)}` : ""}.`}</li>
        {T ? (
          <li>
            {`Research totals for the ${fmt.num(T.targeted ?? 0)} targeted colleges in this district selection: ${fmt.num(T.min)} / ${fmt.num(T.avg)} / ${fmt.num(T.max)} paid (min / avg / max), ${fmt.num(T.ambassadors)} ambassadors, ${fmt.num(T.college_leads)} College Leads. With the default assumptions this page reproduces them exactly (all districts: 377 / 655 / 1,143, 299 ambassadors, 64 College Leads).`}
          </li>
        ) : null}
        <li>Student strength: AICTE EoA, NIRF, mandatory disclosures and annual reports (verified); intake × fill or regional IT share (estimated). Each figure links its source in the expanded row.</li>
        <li>Conversion rates are planning assumptions anchored on an industry lead-to-enrollment index of about 1%; replace them with measured rates. Nothing on this page is a promise of enrollments.</li>
      </ul>
    </footer>
  );
}
