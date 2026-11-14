/**
 * Targets & performance › Performance (old js/views/targets.js renderPerf): programme card + one card per status
 * that occurs, filters (people / colleges / districts, programme / month / week, status, role, college, sort,
 * people who left) and the table. GET /api/performance computes actual / remaining / exceeded / % / status; this
 * screen only displays it. Servers without /api/performance fall back to the old rollups (programme only).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { PortalApiError } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { useQueryState } from "../../lib/query";
import { districtName } from "../../lib/scope";
import { portalPath, toPortalHref } from "../../lib/routes";
import { Button, DataTable, EmptyState, ErrorCard, Icon, ListEmpty, Section, Skeleton, WriteOnly, cx, toast } from "../../ui";
import { openTargetDialog } from "./TargetDialog";
import { LEADS, PerfBar, ROLE, STATE_ID, STATUS, STATUS_ORDER, TargetStatusChip, addDaysIso, arr, isNum, mondayOf, numOr, pctText, periodLabel, useServerToday } from "./common";

type Level = "person" | "college" | "district";
const SORTS: [string, string][] = [
  ["behind", "Furthest behind"],
  ["pct_asc", "% of target, low to high"],
  ["pct_desc", "% of target, high to low"],
  ["actual", "Most paid enrollments"],
  ["name", "Name A–Z"],
];
const PAGE = 25;
const PERIOD_RE = /^(programme|month:\d{4}-\d{2}|week:\d{4}-\d{2}-\d{2})$/;

/* eslint-disable @typescript-eslint/no-explicit-any -- API rows */
type Raw = Record<string, any>;
export interface PerfRow {
  id: string;
  name: string;
  level: Level;
  role: string | null;
  lead: boolean;
  personStatus: string | null;
  college: { id: string | null; name: string | null } | null;
  district: { id: string; name: string } | null;
  min: number | null;
  target: number | null;
  max: number | null;
  own: number | null;
  teamActual?: number | null;
  combinedActual?: number | null;
  actual: number | null;
  remaining: number | null;
  exceeded_by: number | null;
  pct: number | null;
  status: string;
  covers: { with_target: number; total: number } | null;
  team: Raw | null;
  combined: Raw | null;
  below_min: boolean;
  above_max: boolean;
  href: string | null;
  not_credited?: number | null;
  legacy?: boolean;
}

function normDistrict(v: unknown): { id: string; name: string } | null {
  if (v && typeof v === "object") {
    const o = v as Raw;
    return { id: String(o.id), name: String(o.name || o.label || o.id) };
  }
  return v ? { id: String(v), name: districtName(String(v)) } : null;
}
function normCollege(r: Raw): { id: string | null; name: string | null } | null {
  if (r.college && typeof r.college === "object") return { id: String(r.college.id), name: r.college.short_name || r.college.name };
  const id = r.college_id ?? null;
  const name = r.college_short_name || r.college_name || (typeof r.college === "string" ? r.college : null);
  return id || name ? { id: id ? String(id) : null, name } : null;
}
/** One /api/performance row (v4), displayed as-is: no recomputation of remaining / % / status. */
function normPerf(r: Raw, level: Level): PerfRow {
  const role = r.role || null;
  return {
    id: String(r.id ?? r.scope_id),
    name: r.name ?? r.label ?? r.full_name ?? String(r.id),
    level,
    role,
    lead: level === "person" && LEADS.has(role),
    personStatus: r.person_status ?? null,
    college: level === "person" ? normCollege(r) : null,
    district: normDistrict(r.district ?? r.district_id),
    min: numOr(r.min ?? r.target_min),
    target: numOr(r.target),
    max: numOr(r.max ?? r.target_max),
    own: numOr(r.actual_own),
    teamActual: numOr(r.actual_team),
    combinedActual: numOr(r.actual_combined),
    actual: numOr(r.actual ?? r.actual_own),
    remaining: numOr(r.remaining),
    exceeded_by: numOr(r.exceeded_by),
    pct: numOr(r.pct),
    status: r.status || (numOr(r.target) == null ? "no_target" : "open"),
    covers: r.covers || null,
    team: r.team || null,
    combined: r.combined || null,
    below_min: r.below_min === true,
    above_max: r.above_max === true,
    href: r.href || null,
    not_credited: numOr(r.not_credited),
  };
}
/** A server without /api/performance: programme period only, from the existing rollups. */
function legacyRow(r: Raw, level: Level): PerfRow {
  const t = numOr(r.target);
  const a = numOr(r.enrolled) ?? 0;
  const status = t == null ? "no_target" : t === 0 ? "zero_target" : a > t ? "exceeded" : a === t ? "met" : "open";
  return {
    id: String(r.id),
    name: r.full_name || r.name || r.label,
    level,
    role: r.role || null,
    lead: false,
    personStatus: level === "person" ? r.status : null,
    college: level === "person" ? normCollege(r) : null,
    district: normDistrict(r.district_id),
    min: null,
    target: t,
    max: null,
    own: a,
    team: null,
    combined: null,
    actual: a,
    below_min: false,
    above_max: false,
    remaining: t == null ? null : Math.max(t - a, 0),
    exceeded_by: t == null ? null : Math.max(a - t, 0),
    pct: t ? (isNum(r.pct) ? r.pct * 100 : null) : null,
    status,
    covers: null,
    legacy: true,
    href: r.href || null,
  };
}

function sortRows(rows: PerfRow[], sort: string): PerfRow[] {
  const coll = new Intl.Collator("en-IN", { numeric: true, sensitivity: "base" });
  const nullLast = (a: number | null, b: number | null, fn: (x: number, y: number) => number) => (a == null && b == null ? 0 : a == null ? 1 : b == null ? -1 : fn(a, b));
  const by: Record<string, (a: PerfRow, b: PerfRow) => number> = {
    behind: (a, b) => nullLast(a.remaining, b.remaining, (x, y) => y - x) || nullLast(a.pct, b.pct, (x, y) => x - y),
    pct_asc: (a, b) => nullLast(a.pct, b.pct, (x, y) => x - y),
    pct_desc: (a, b) => nullLast(a.pct, b.pct, (x, y) => y - x),
    actual: (a, b) => nullLast(a.actual, b.actual, (x, y) => y - x),
    name: () => 0,
  };
  const f = by[sort] ?? (() => 0);
  return rows.slice().sort((a, b) => f(a, b) || coll.compare(a.name, b.name));
}

const is404 = (e: unknown) => e instanceof PortalApiError && e.status === 404;

export function Performance() {
  const [q, setQuery] = useQueryState();
  const today = useServerToday();
  const level: Level = q.level === "college" || q.level === "district" ? q.level : "person";
  const period = PERIOD_RE.test(q.period || "") ? q.period! : "programme";
  const status = q.status || "";
  const role = q.role || "";
  const college = q.college || "";
  const search = q.q || "";
  const sort = SORTS.some(([k]) => k === q.sort) ? q.sort! : "behind";
  const inactive = q.inactive === "1";
  const page0 = Math.max(1, Number(q.page) || 1);

  const dash = usePortalQuery<Raw>("target-dashboard", { scoped: true, query: { scope: "state" } });
  const colleges = usePortalQuery<unknown>("colleges", { scoped: true });
  const perf = usePortalQuery<Raw>("performance", {
    scoped: true,
    keepPrevious: true,
    query: { level, period, role: level === "person" ? role : "", college_id: level === "person" ? college : "", include_inactive: level === "person" && inactive ? 1 : "" },
  });
  const legacy = !!perf.error && is404(perf.error);
  const legacyPath = !legacy ? null : level === "person" ? "people" : level === "college" ? "colleges" : "leaderboard";
  const legacyQ = usePortalQuery<unknown>(legacyPath, {
    scoped: true,
    query: level === "person" ? { role, college } : level === "district" ? { level: "district", scope: "state", limit: 500 } : {},
  });
  const v4 = legacy ? false : perf.data ? true : null;

  // a pre-v4 server has only the programme period
  useEffect(() => {
    if (legacy && period !== "programme") setQuery({ period: null }, { history: "replace" });
  }, [legacy, period, setQuery]);

  const rows: PerfRow[] | null = useMemo(() => {
    if (legacy) return legacyQ.data ? arr<Raw>(legacyQ.data).map((r) => legacyRow(level === "district" ? { ...r, district_id: r.id } : r, level)) : null;
    return perf.data ? arr<Raw>(perf.data).map((r) => normPerf(r, level)) : null;
  }, [legacy, legacyQ.data, perf.data, level]);
  const counts = useMemo(() => {
    if (!rows) return null;
    const c: Record<string, number> = {};
    for (const r of rows) c[r.status] = (c[r.status] || 0) + 1;
    return c;
  }, [rows]);

  const set = (patch: Record<string, string | number | boolean | null>, history: "auto" | "replace" = "auto") => setQuery({ tab: null, ...patch }, { history });
  const reload = (patch: Record<string, string | number | boolean | null>) => set({ ...patch, page: null });
  const clearAll = () => set({ status: null, role: null, college: null, q: null, page: null });

  const res = perf.data as Raw | undefined;
  const sub = `${{ person: "People", college: "Colleges", district: "Districts" }[level]} · ${periodLabel(period)}${
    !legacy && res?.period?.start
      ? ` · ${fmt.date(res.period.start)} – ${fmt.date(res.period.end)}${isNum(res.period.days_elapsed) ? ` (day ${fmt.num(res.period.days_elapsed)} of ${fmt.num(res.period.days_total)})` : ""}`
      : ""
  }`;

  return (
    <>
      <Summary dash={dash.data} error={dash.error} retry={() => void dash.reload()} counts={counts} status={status} onStatus={(st) => set({ status: status === st ? null : st, page: null })} />
      <Section title="Targets vs paid enrollments" sub={<span className="tgp-sub">{sub}</span>}>
        <Filters
          level={level}
          period={period}
          today={today}
          v4={v4 !== false}
          counts={counts}
          values={{ status, role, college, search, sort, inactive }}
          colleges={arr<Raw>(colleges.data)}
          onLevel={(v) => (v === level ? undefined : reload({ level: v === "person" ? null : v, role: null, college: null }))}
          onPeriod={(p) => {
            if (v4 === false && p !== "programme") return toast("Month and week periods need the server update (/api/performance).", "warn");
            reload({ period: p === "programme" ? null : p });
          }}
          onChange={(patch) => set({ ...patch, page: null })}
          onSearch={(text) => set({ q: text || null, page: null }, "replace")}
          onClear={() => reload({ status: null, role: null, college: null, q: null })}
        />
        <div className="tgp-tablehost">
          <PerfTable
            rows={rows}
            loading={!rows && !perf.error && !legacyQ.error}
            error={legacy ? legacyQ.error : perf.error}
            retry={() => void (legacy ? legacyQ.reload() : perf.reload())}
            level={level}
            period={period}
            v4={v4 !== false}
            legacy={legacy}
            filters={{ status, role, college, search, sort }}
            page={page0}
            onPage={(n) => set({ page: n > 1 ? n : null })}
            onClear={clearAll}
          />
        </div>
      </Section>
    </>
  );
}

/** Programme card + status counts. Programme numbers come from /api/target-dashboard (server TODAY). */
function Summary({ dash, error, retry, counts, status, onStatus }: { dash: Raw | undefined; error: unknown; retry: () => void; counts: Record<string, number> | null; status: string; onStatus: (st: string) => void }) {
  if (!dash && !error)
    return (
      <div className="tgp-summary" aria-live="polite">
        <Skeleton lines={2} card={false} />
      </div>
    );
  const d: Raw = dash || {};
  const progNA = !!d.program && (d.program.applies === false || (d.program.target === null && !!d.program.target_reason));
  const p: Raw = progNA ? d : d.program || d;
  const target = numOr(p.target !== undefined ? p.target : d.target);
  const confirmed = numOr(p.confirmed ?? d.confirmed);
  const partialT = progNA && d.target_status === "partial_target";
  const remaining = partialT ? null : numOr(p.remaining ?? d.remaining);
  const pct = target && !partialT ? (isNum(p.pct) ? p.pct * 100 : null) : null;
  const noTargetReason = !error && target == null ? d.target_reason || d.program?.target_reason || p.reason || "The programme target covers the target districts, not this selection." : null;
  const pg: Raw = d.program || p;
  const nSel = Array.isArray(pg.selected_districts) ? pg.selected_districts.length : 0;
  const selLabel = pg.selected_districts && !pg.all_districts ? ` · ${pg.is_default_selection ? "target districts" : fmt.plural(nSel, "selected district")}` : "";
  const headLabel = progNA ? `Targets · ${fmt.plural(nSel, "selected district")}` : `Programme target${selLabel}`;
  let prog: ReactNode;
  if (error) {
    prog = (
      <div className="tgp-prog">
        <ErrorCard title="Could not load the programme target" error={error} retry={retry} />
      </div>
    );
  } else if (noTargetReason) {
    prog = (
      <div className="tgp-prog">
        <div className="tgp-prog__head">
          <span className="tgp-card__label">{headLabel}</span>
        </div>
        <div className="tgp-prog__nums">
          <strong className="tgp-prog__big">No target for this selection</strong>
          <span className="td-num tgp-muted"> · {fmt.plural(confirmed ?? 0, "confirmed enrollment")}</span>
        </div>
        <p className="tgp-muted tgp-small">{noTargetReason} Targets set on the districts, colleges or people in this selection are listed below.</p>
      </div>
    );
  } else if (partialT) {
    prog = (
      <div className="tgp-prog">
        <div className="tgp-prog__head">
          <span className="tgp-card__label">{headLabel}</span>
          <TargetStatusChip status="partial_target" />
        </div>
        <div className="tgp-prog__nums">
          <strong className="td-num tgp-prog__big">{fmt.num(confirmed)}</strong>
          <span className="td-num"> paid · target {fmt.num(target)}</span>
          {d.covers && isNum(d.covers.total) ? <span className="td-num tgp-muted"> · covers {fmt.num(d.covers.with_target)} of {fmt.num(d.covers.total)} · not judged</span> : null}
        </div>
        <p className="tgp-muted tgp-small">{STATUS.partial_target![2]} No %, remaining or pace is shown until every part has a target.</p>
      </div>
    );
  } else {
    prog = (
      <div className="tgp-prog">
        <div className="tgp-prog__head">
          <span className="tgp-card__label">{headLabel}</span>
          {progNA ? null : (
            <WriteOnly>
              <button type="button" className="tgp-link" onClick={() => void openTargetDialog({ scope_type: "state", scope_id: STATE_ID, label: "the programme", period: "programme" })}>
                Change
              </button>
            </WriteOnly>
          )}
        </div>
        <div className="tgp-prog__nums">
          <strong className="td-num tgp-prog__big">{fmt.num(confirmed)}</strong>
          <span className="td-num">
            {" "}
            of {fmt.num(target)} paid · <strong>{pctText(pct)}</strong>
          </span>
          <span className="td-num tgp-muted"> · {fmt.num(remaining)} to go</span>
        </div>
        <PerfBar r={{ actual: confirmed, target, label: progNA ? "Selected districts" : "Programme" }} lg />
        <p className="tgp-muted tgp-small">
          {d.days_left != null ? `${fmt.num(d.days_left)} days left including today (to ${fmt.date(p.deadline || d.deadline)})` : `Deadline ${fmt.date(p.deadline || d.deadline)}`}
          {isNum(d.required_weekly) ? ` · ${d.required_weekly.toLocaleString("en-IN", { maximumFractionDigits: 1 })} confirmed / week needed` : ""}. Only confirmed (paid) enrollments dated today or earlier count.
        </p>
      </div>
    );
  }
  // one card per status that occurs, so the cards always add up to the number of rows
  const SUB: Record<string, string> = {
    exceeded: "more than their target",
    met: "exactly on target",
    on_track: "keeping pace with the deadline",
    behind: "slower than the pace needed",
    too_early: "target set under 7 days ago, not judged yet",
    partial_target: "only part of the group has a target",
    zero_target: "target set to 0",
    no_target: "no target set yet",
    open: "below target (no pace on this server)",
  };
  const order = ["behind", "on_track", "too_early", "met", "exceeded", "partial_target", "zero_target", "no_target", "open"];
  const extra = counts ? Object.keys(counts).filter((k) => !order.includes(k)) : [];
  const shown = counts ? [...order, ...extra].filter((k) => counts[k]) : [];
  const toneOf = (k: string) => {
    const t = (STATUS[k] || [])[1];
    return t === "neutral" ? null : t;
  };
  return (
    <div className="tgp-summary" aria-live="polite">
      {prog}
      {shown.length ? (
        <div className="tgp-cards">
          {shown.map((k) => (
            <button key={k} type="button" className={cx("tgp-card", toneOf(k) && `is-${toneOf(k)}`, "is-action")} aria-pressed={status === k} onClick={() => onStatus(k)}>
              <span className="tgp-card__label">{(STATUS[k] || [k.replace(/_/g, " ")])[0]}</span>
              <strong className="tgp-card__value td-num">{fmt.num(counts![k] || 0)}</strong>
              {SUB[k] ? <span className="tgp-card__sub">{SUB[k]}</span> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SegCtl<V extends string>({ name, options, value, onPick }: { name: string; options: [V, string][]; value: string; onPick: (v: V) => void }) {
  return (
    <div className="tgp-segctl" role="radiogroup" aria-label={name}>
      {options.map(([v, l]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} className={cx("tgp-segctl__btn", value === v && "is-on")} onClick={() => onPick(v)}>
          {l}
        </button>
      ))}
    </div>
  );
}

function Sel({ label, options, value, onChange, className }: { label: string; options: [string, string][]; value: string; onChange: (v: string) => void; className?: string }) {
  return (
    <label className={cx("tgp-fl", className)}>
      <span className="tgp-fl__label">{label}</span>
      <select className="td-input td-select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

function Filters({
  level,
  period,
  today,
  v4,
  counts,
  values,
  colleges,
  onLevel,
  onPeriod,
  onChange,
  onSearch,
  onClear,
}: {
  level: Level;
  period: string;
  today: string | null;
  v4: boolean;
  counts: Record<string, number> | null;
  values: { status: string; role: string; college: string; search: string; sort: string; inactive: boolean };
  colleges: Raw[];
  onLevel: (v: Level) => void;
  onPeriod: (p: string) => void;
  onChange: (patch: Record<string, string | null>) => void;
  onSearch: (text: string) => void;
  onClear: () => void;
}) {
  const pk = String(period).split(":")[0]!;
  const [text, setText] = useState(values.search);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => setText(values.search), [values.search]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const base = today || new Date().toISOString().slice(0, 10);
  let pick: ReactNode = null;
  if (pk === "month") {
    pick = (
      <input
        type="month"
        className="td-input tgp-pick"
        aria-label="Month"
        defaultValue={period.slice(6)}
        key={period}
        onChange={(e) => {
          if (/^\d{4}-\d{2}$/.test(e.target.value)) onPeriod(`month:${e.target.value}`);
        }}
      />
    );
  } else if (pk === "week") {
    const wk = period.slice(5);
    pick = (
      <div className="tgp-weekpick">
        <Button tone="ghost" size="sm" ariaLabel="Previous week" onClick={() => onPeriod(`week:${addDaysIso(wk, -7)}`)}>
          ‹
        </Button>
        <span className="td-num">{periodLabel(period)}</span>
        <Button tone="ghost" size="sm" icon="chevron" ariaLabel="Next week" onClick={() => onPeriod(`week:${addDaysIso(wk, 7)}`)} />
      </div>
    );
  }
  const statusOpts: [string, string][] = [["", "All statuses"], ...STATUS_ORDER.filter((k) => k !== "open" || !v4).map((k) => [k, `${STATUS[k]![0]}${counts ? ` (${counts[k] || 0})` : ""}`] as [string, string])];
  const collegeList = colleges.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const nActive = [values.status, values.role, values.college, values.search].filter(Boolean).length;
  return (
    <div className="tgp-filters">
      <div className="tgp-filters__row">
        <SegCtl<Level>
          name="Show performance by"
          options={[
            ["person", "People"],
            ["college", "Colleges"],
            ["district", "Districts"],
          ]}
          value={level}
          onPick={onLevel}
        />
        <div className="tgp-period">
          <SegCtl
            name="Period"
            options={[
              ["programme", "Programme"],
              ["month", "Month"],
              ["week", "Week"],
            ]}
            value={pk}
            onPick={(v) => onPeriod(v === "programme" ? "programme" : v === "month" ? `month:${base.slice(0, 7)}` : `week:${mondayOf(base)}`)}
          />
          {pick}
        </div>
      </div>
      <div className="tgp-filters__row">
        <label className="tgp-fl tgp-fl--search">
          <span className="tgp-fl__label">Search</span>
          <input
            type="search"
            className="td-input"
            placeholder={level === "person" ? "Search name, college…" : "Search…"}
            aria-label="Search"
            value={text}
            onChange={(e) => {
              const v = e.target.value;
              setText(v);
              clearTimeout(timer.current);
              timer.current = setTimeout(() => onSearch(v.trim()), 200);
            }}
          />
        </label>
        <Sel label="Status" options={statusOpts} value={values.status} onChange={(v) => onChange({ status: v || null })} />
        {level === "person" ? <Sel label="Role" options={[["", "All roles"], ...(Object.entries(ROLE) as [string, string][])]} value={values.role} onChange={(v) => onChange({ role: v || null })} /> : null}
        {level === "person" ? (
          <Sel
            label="College"
            className="tgp-fl--college"
            options={[["", "All colleges"], ...collegeList.map((c) => [String(c.id), String(c.short_name || c.name)] as [string, string])]}
            value={values.college}
            onChange={(v) => onChange({ college: v || null })}
          />
        ) : null}
        <Sel label="Sort" options={SORTS} value={values.sort} onChange={(v) => onChange({ sort: v === "behind" ? null : v })} />
        {level === "person" && v4 ? (
          <label className="tgp-check">
            <input type="checkbox" className="td-check" checked={values.inactive} onChange={(e) => onChange({ inactive: e.target.checked ? "1" : null })} />
            <span>Include people who left</span>
          </label>
        ) : null}
        {nActive ? (
          <Button tone="ghost" size="sm" onClick={onClear}>
            Clear filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function PerfTable({
  rows,
  loading,
  error,
  retry,
  level,
  period,
  v4,
  legacy,
  filters,
  page: page0,
  onPage,
  onClear,
}: {
  rows: PerfRow[] | null;
  loading: boolean;
  error: unknown;
  retry: () => void;
  level: Level;
  period: string;
  v4: boolean;
  legacy: boolean;
  filters: { status: string; role: string; college: string; search: string; sort: string };
  page: number;
  onPage: (n: number) => void;
  onClear: () => void;
}) {
  const top = useRef<HTMLDivElement>(null);
  if (error && !rows) return <ErrorCard title="Could not load performance" error={error} retry={retry} />;
  if (loading || !rows) return <Skeleton lines={6} card={false} />;
  const qq = filters.search.toLowerCase();
  let list = rows;
  if (filters.status) list = list.filter((r) => r.status === filters.status);
  if (qq) list = list.filter((r) => [r.name, r.college?.name, r.district?.name, r.role ? ROLE[r.role] : null].filter(Boolean).join(" ").toLowerCase().includes(qq));
  if (level === "person" && filters.role) list = list.filter((r) => !r.role || r.role === filters.role);
  if (level === "person" && filters.college) list = list.filter((r) => !r.college?.id || r.college.id === filters.college);
  list = sortRows(list, filters.sort);
  const total = list.length;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const page = Math.min(page0, pages);
  const pageRows = list.slice((page - 1) * PAGE, page * PAGE);

  const notes: ReactNode[] = [];
  if (legacy)
    notes.push(
      <div key="legacy" className="tgp-note is-warn" role="status">
        <Icon name="info" size={16} />
        <span>
          <strong>Limited view. </strong>This server does not have the performance service yet, so only programme-to-date figures are shown — no month/week periods, min/max, team totals or pace status. Numbers come from the
          existing server rollups.
        </span>
      </div>,
    );
  const partial = rows.filter((r) => r.covers && isNum(r.covers.total) && isNum(r.covers.with_target) && r.covers.with_target < r.covers.total && r.target != null);
  if (partial.length && level !== "person") {
    const part = level === "district" ? "towns" : "branches";
    notes.push(
      <div key="partial" className="tgp-note" role="note">
        <Icon name="info" size={16} />
        <span>
          {fmt.num(partial.length)} {level === "district" ? "district" : "college"}
          {partial.length === 1 ? "" : "s"} ha{partial.length === 1 ? "s" : "ve"} no own target, so the target is the sum of the {part} that have one. Actual, % and remaining then count only those {part}; the full confirmed count is shown
          underneath (&quot;all&quot;).
        </span>
      </div>,
    );
  }
  if (level === "person" && rows.some((r) => r.lead))
    notes.push(
      <p key="lead" className="tgp-muted tgp-small">
        For college leads and ambassador leads: <strong>Own</strong> = enrollments credited to the lead personally (the row’s target, % and status are for these). <strong>Team</strong> = the active ambassadors who report to them.{" "}
        <strong>Total</strong> = own + team. Hover over Team or Total (on touch: press and hold) to see their %.
      </p>,
    );
  if (!rows.length) {
    return (
      <>
        {notes}
        <EmptyState
          icon="target"
          title={level === "person" ? "No people yet" : "Nothing to show"}
          text={level === "person" ? "Add College Leads and Ambassadors in Team; their targets and confirmed enrollments appear here." : "No places in this district selection."}
        />
      </>
    );
  }

  const hrefOf = (r: PerfRow) => (r.href ? toPortalHref(r.href) : r.level === "person" ? portalPath.person(r.id) : r.level === "college" ? portalPath.college(r.id) : portalPath.district(r.id));
  const subOf = (r: PerfRow) => (r.level === "person" ? [r.role ? ROLE[r.role] || r.role : null, r.college?.name].filter(Boolean).join(" · ") : r.level === "college" ? r.district?.name || "—" : null);
  const covOf = (r: PerfRow) => {
    const cov =
      r.covers && isNum(r.covers.total) && r.covers.total > 0 && r.target != null
        ? `target covers ${fmt.num(r.covers.with_target)} of ${fmt.num(r.covers.total)} ${r.level === "district" ? "towns" : r.level === "college" ? "branches" : "parts"}`
        : null;
    return cov ? <span className={cx("tgp-cov", r.covers!.with_target < r.covers!.total && "is-partial")}>{cov}</span> : null;
  };
  const tagsOf = (r: PerfRow) => {
    const flag: ReactNode[] = [];
    if (r.personStatus && r.personStatus !== "active")
      flag.push(
        <span key="st" className="tgp-tag">
          {r.personStatus === "inactive" ? "Inactive" : r.personStatus}
        </span>,
      );
    if (r.below_min)
      flag.push(
        <span key="min" className="tgp-tag is-warn">
          below min
        </span>,
      );
    if (r.above_max)
      flag.push(
        <span key="max" className="tgp-tag is-good">
          above max
        </span>,
      );
    return flag.length ? <span className="tgp-tags">{flag}</span> : null;
  };
  const teamTitle = (tm: Raw) => {
    const cov = tm.covers && isNum(tm.covers.total) ? ` · ${fmt.num(tm.covers.with_target)} of ${fmt.num(tm.covers.total)} members have a target` : "";
    return `Team of ${fmt.num(tm.size)}: ${fmt.num(tm.actual)}${tm.target != null ? ` of ${fmt.num(tm.target)} (${pctText(tm.pct)})` : ", no team targets"}${tm.status ? ` · ${(STATUS[tm.status] || [tm.status])[0]}` : ""}${cov}`;
  };
  const chipOf = (r: PerfRow) => (
    <TargetStatusChip status={r.status} title={r.status === "partial_target" && r.covers && isNum(r.covers.total) ? `${STATUS.partial_target![2]} Target covers ${fmt.num(r.covers.with_target)} of ${fmt.num(r.covers.total)}.` : undefined} />
  );
  const nameCell = (r: PerfRow) => {
    const sub = subOf(r);
    return (
      <div className="tgp-namecell">
        <Link to={hrefOf(r)}>{r.name}</Link>
        {tagsOf(r)}
        {sub ? <span className="tgp-subline">{sub}</span> : null}
        {covOf(r)}
      </div>
    );
  };
  const stillCell = (r: PerfRow) =>
    r.exceeded_by != null && r.exceeded_by > 0 ? (
      <strong className="tgp-good" title="Paid enrollments above the target">
        +{fmt.num(r.exceeded_by)} over
      </strong>
    ) : r.remaining == null ? (
      <span className="tgp-muted">—</span>
    ) : (
      fmt.num(r.remaining)
    );
  const tgtCell = (r: PerfRow) => {
    const rng = fmt.range(r.min, r.max);
    return r.target == null ? (
      <span className="tgp-muted">not set</span>
    ) : (
      <span>
        <strong>{fmt.num(r.target)}</strong>
        {rng ? <small className="tgp-why">{rng}</small> : null}
      </span>
    );
  };
  const pctCell = (r: PerfRow) => {
    const why = r.pct == null ? (r.target == null ? "no target" : r.target === 0 ? "target is 0" : r.status === "partial_target" ? "not judged — partly targeted" : "") : "";
    return r.pct == null ? (
      <span className="tgp-muted" title={why}>
        —{why ? <small className="tgp-why">{why}</small> : null}
      </span>
    ) : (
      pctText(r.pct)
    );
  };
  const actualCell = (r: PerfRow) => {
    const tm = r.team;
    const cb = r.combined;
    if (r.lead)
      return (
        <span className="tgp-act">
          <span>
            <small>Own </small>
            <strong>{fmt.num(r.actual ?? 0)}</strong>
          </span>
          <span title={tm ? teamTitle(tm) : ""}>
            <small>Team{tm && isNum(tm.size) ? ` (${tm.size})` : ""} </small>
            {fmt.num(tm ? tm.actual : (r.teamActual ?? 0))}
            {tm && tm.target != null ? <small> / {fmt.num(tm.target)}</small> : null}
            {tm && tm.covers && isNum(tm.covers.total) && tm.covers.total > 0 && tm.covers.with_target < tm.covers.total ? (
              <small className="tgp-why">
                {fmt.num(tm.covers.with_target)} of {fmt.num(tm.covers.total)} with a target
              </small>
            ) : null}
          </span>
          <span
            title={
              cb ? `Total: ${fmt.num(cb.actual)}${cb.target != null ? ` of ${fmt.num(cb.target)} (${pctText(cb.pct)})${cb.status ? ` · ${(STATUS[cb.status] || [cb.status])[0]}` : ""}` : ", no target"}` : ""
            }
          >
            <small>Total </small>
            {fmt.num(cb ? cb.actual : (r.combinedActual ?? 0))}
            {cb && cb.target != null ? <small> / {fmt.num(cb.target)}</small> : null}
          </span>
        </span>
      );
    return (
      <span>
        <strong>{fmt.num(r.actual ?? 0)}</strong>
        {r.own != null && r.own !== r.actual && r.level !== "person" ? (
          <small className="tgp-why" title="All confirmed enrollments here, including places without a target">
            {fmt.num(r.own)} all
          </small>
        ) : null}
        {r.not_credited ? (
          <small className="tgp-why" title="Confirmed enrollments of this college not credited to any person">
            {fmt.num(r.not_credited)} not credited
          </small>
        ) : null}
      </span>
    );
  };
  const from = total ? (page - 1) * PAGE + 1 : 0;
  const go = (n: number) => {
    onPage(n);
    top.current?.scrollIntoView?.({ block: "start" });
  };
  return (
    <div ref={top}>
      {notes}
      <div className="tgp-dt">
        <DataTable<PerfRow>
          caption={`Performance by ${level}, ${periodLabel(period)}`}
          rows={pageRows}
          rowKey={(r) => `${r.level}:${r.id}`}
          cardSort={false}
          empty={<ListEmpty filtered noun={level === "person" ? "people" : level === "college" ? "colleges" : "districts"} onClear={onClear} />}
          columns={[
            { key: "name", label: level === "person" ? "Name · role · college" : level === "college" ? "College · district" : "District", primary: true, priority: 1, minWidth: 230, sortable: false, render: nameCell },
            { key: "target", label: "Target", align: "right", priority: 2, minWidth: 90, sortable: false, render: tgtCell },
            { key: "actual", label: "Paid enrollments", phoneLabel: level === "person" ? "Paid enrollments (own · team · total)" : "Paid enrollments", align: "right", priority: 1, minWidth: 120, sortable: false, render: actualCell },
            { key: "remaining", label: "Still needed", align: "right", priority: 2, minWidth: 96, sortable: false, render: stillCell },
            { key: "pct", label: "% of target", align: "right", priority: 2, minWidth: 90, sortable: false, render: pctCell },
            { key: "status", label: "Status", priority: 1, minWidth: 130, sortable: false, cardHidden: true, render: chipOf },
          ]}
          cardTitle={(r) => (
            <span>
              <Link to={hrefOf(r)}>{r.name}</Link>
              {tagsOf(r)}
            </span>
          )}
          cardSubtitle={(r) => subOf(r)}
          cardMeta={(r) => [chipOf(r)]}
          rowActions={(r) => [
            {
              label: r.target == null ? "Set target" : "Edit target",
              icon: "target",
              writeOnly: true,
              onClick: () => void openTargetDialog({ scope_type: r.level, scope_id: r.id, label: r.name, period, row: r, v4 }),
            },
          ]}
        />
      </div>
      <div className="tgp-pager">
        <span className="td-num tgp-muted">
          {total ? `${fmt.num(from)}–${fmt.num(Math.min(total, page * PAGE))} of ${fmt.num(total)}` : "0 rows"}
          {total !== rows.length ? ` (filtered from ${fmt.num(rows.length)})` : ""}
        </span>
        {pages > 1 ? (
          <div className="tgp-pager__btns">
            <Button size="sm" disabled={page <= 1} onClick={() => go(page - 1)}>
              ‹ Previous
            </Button>
            <span className="td-num">
              Page {page} of {pages}
            </span>
            <Button size="sm" disabled={page >= pages} onClick={() => go(page + 1)}>
              Next
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
