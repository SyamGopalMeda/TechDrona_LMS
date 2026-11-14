/**
 * Shared list / summary helpers: a React port of the helper exports of the old js/views/dashboard.js (the part
 * shared with geo.js and college.js). Every number comes from the API; these only format and pick wording.
 *
 *   <ProgressNode r={row} />     <StatusNode r={row} />     <PerfChip status="behind" />
 *   const plan = usePlanIndex(); pLevelOf(row, plan)
 */
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../../lib/cache";
import { daysUntil, fmt, today } from "../../lib/fmt";
import { portalPath, toPortalHref } from "../../lib/routes";
import type { AttentionItem, Person } from "../../lib/types";
import { Badge, EmptyState, StatusBadge, StatusChip, STATUS_META, cx, statusMeta, type Tone } from "../../ui";

/* ------------------------------------------------------------------ small value helpers */

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
type AnyRow = Record<string, unknown>;
export const rowId = (r: AnyRow): string => String(r.id ?? r.scope_id ?? r.key ?? "");
export const rowLabel = (r: AnyRow): string => String(r.label ?? r.name ?? r.full_name ?? rowId(r));

/** Rows from a list endpoint that returns either an array (v3) or {items, total} (v4 paged). */
export function itemsOf<T>(res: T[] | { items?: T[] } | null | undefined): T[] {
  if (Array.isArray(res)) return res;
  return res && Array.isArray(res.items) ? res.items : [];
}

/** fraction (0.0475) → "4.8%": THE shared rule. */
export const pctText = (x: number | null | undefined): string => fmt.pctOf(x);
/** percent number from /api/performance (4.8) → "4.8%". */
export const pctNumText = (p: number | null | undefined): string => fmt.pctPts(p);

/** D2: why a selection has no programme target (server `target_reason`), or null. */
export function noTargetReason(...objs: unknown[]): string | null {
  for (const o of objs) {
    if (!o || typeof o !== "object") continue;
    const x = o as AnyRow;
    if (x.target === null && x.target_reason) return String(x.target_reason);
    const p = x.program && typeof x.program === "object" ? (x.program as AnyRow) : null;
    if (p && p.target === null && p.target_reason && (x.target === null || x.target === undefined)) return String(p.target_reason);
  }
  return null;
}

/** rates (per week / per day): 1 decimal below 10, whole above. */
export const rateText = (x: number | null | undefined): string =>
  x === null || x === undefined || !Number.isFinite(Number(x)) ? "—" : x >= 10 ? fmt.num(x) : (Math.round(x * 10) / 10).toLocaleString("en-IN");

/** Days left always come from the API (inclusive of today). */
export function daysLeftText(daysLeft: number | null | undefined, deadline: string | null | undefined): string {
  if (isNum(daysLeft)) {
    if (daysLeft <= 0) return `Deadline passed${deadline ? ` (${fmt.date(deadline)})` : ""}`;
    return `${fmt.plural(daysLeft, "day")} left incl. today${deadline ? ` · deadline ${fmt.date(deadline)}` : ""}`;
  }
  return deadline ? `Deadline ${fmt.date(deadline)}` : "No deadline set";
}

/** Server reason strings carry ISO dates ("Exams start 2026-11-09"); show them as "9 Nov 2026". */
export const prettyReason = (t: unknown): string => String(t ?? "").replace(/\b(\d{4}-\d{2}-\d{2})\b/g, (m) => fmt.date(m));

/* ------------------------------------------------------------------ performance status */

type TargetLike = {
  target?: number | null;
  enrolled?: number | null;
  actual?: number | null;
  actual_combined?: number | null;
  remaining?: number | null;
  exceeded_by?: number | null;
  status?: string | null;
  pace_status?: string | null;
  on_track?: boolean | null;
  diagnosis?: string | null;
  [k: string]: unknown;
};

/** [label, tone] per performance status, from THE shared vocabulary (ui/status.ts). */
export const PERF_STATUS: Readonly<Record<string, [string, Tone]>> = Object.fromEntries(
  ["no_target", "zero_target", "too_early", "partial_target", "behind", "on_track", "met", "exceeded"].map((k): [string, [string, Tone]] => [k, [statusMeta(k).label, statusMeta(k).tone]]),
);

export function PerfChip({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  return <StatusChip status={status} />;
}

/** "12 to go" / "Exceeded by 2" / "Target met" from server remaining + exceeded_by. */
export function remainingText(r: TargetLike | null | undefined): string | null {
  if (!r || r.target === null || r.target === undefined) return null;
  if (isNum(r.exceeded_by) && r.exceeded_by > 0) return `Exceeded by ${fmt.num(r.exceeded_by)}`;
  if (isNum(r.remaining)) return r.remaining > 0 ? `${fmt.num(r.remaining)} to go` : "Target met";
  return null;
}

/** Port of components.js `progress({target, done, size})` (the compact td-progress bar the old lists used). */
export function Progress({ target, done, size = "md", tone }: { target: number | null | undefined; done: number | null | undefined; size?: "sm" | "md" | "lg"; tone?: string }) {
  const d = Number(done) || 0;
  if (!(target !== null && target !== undefined && Number(target) > 0)) {
    return (
      <div className={cx("td-progress", `td-progress--${size}`, "td-progress--none")}>
        <div className="td-progress__meta">
          <span className="td-progress__nums td-num">
            <strong>{fmt.num(d)}</strong> enrolled
          </span>
          <span className="td-progress__pct td-muted">No target set</span>
        </div>
        <div className="td-progress__track" />
      </div>
    );
  }
  const t = Number(target);
  const pct = d / t;
  const tn = tone || (pct >= 0.6 ? "good" : pct >= 0.3 ? "warn" : "bad");
  const w = Math.max(0, Math.min(1, pct)) * 100;
  return (
    <div className={cx("td-progress", `td-progress--${size}`, `td-progress--${tn}`)}>
      <div className="td-progress__meta">
        <span className="td-progress__nums td-num">
          <strong>{fmt.num(d)}</strong>
          <span className="td-muted"> / {fmt.num(t)}</span>
        </span>
        <span className="td-progress__pct td-num">{fmt.pct(pct)}</span>
      </div>
      <div
        className="td-progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={t}
        aria-valuenow={d}
        aria-label={`${fmt.num(d)} enrolled of ${fmt.num(t)} target (${fmt.pct(pct)})`}
      >
        <div className="td-progress__bar" style={{ width: `${w}%` }} />
      </div>
    </div>
  );
}

/** Target / confirmed progress for any row or summary with {target, enrolled|actual, remaining}. */
export function ProgressNode({ r, size = "sm" }: { r: TargetLike | null | undefined; size?: "sm" | "md" | "lg" }) {
  const actual = r ? (r.actual ?? r.actual_combined ?? r.enrolled) : null;
  if (!r || !(Number(r.target) > 0)) {
    return (
      <span className="vd-noprog">
        <span className="vd-muted">{r && r.target === 0 ? STATUS_META.zero_target!.label : STATUS_META.no_target!.label}</span>
        {isNum(actual) && actual > 0 ? <span>{` · ${fmt.num(actual)} confirmed`}</span> : null}
      </span>
    );
  }
  const rt = remainingText(r);
  return (
    <div className="vd-prog">
      <Progress target={r.target} done={actual ?? 0} size={size} />
      {rt ? <span className="vd-muted vd-small">{rt}</span> : null}
    </div>
  );
}

/** Status chip (v4 status, else on-track + diagnosis), or "No target". */
export function StatusNode({ r }: { r: TargetLike | null | undefined }) {
  const st = r && (r.status || r.pace_status);
  if (st && PERF_STATUS[st]) return <PerfChip status={st} />;
  if (!r || !(Number(r.target) > 0)) return <Badge tone="neutral">{r && r.target === 0 ? STATUS_META.zero_target!.label : STATUS_META.no_target!.label}</Badge>;
  return (
    <span className="vd-status">
      <StatusBadge kind="on_track" value={r.on_track ?? null} />
      {r.on_track === false && r.diagnosis ? <StatusBadge kind="diagnosis" value={r.diagnosis} /> : null}
    </span>
  );
}

/* ------------------------------------------------------------------ team (college rows) */

export interface LeadInfo {
  id: number | string | null;
  name: string;
  phone: string | null;
}

/** Lead of a /api/colleges row: v4 `lead{id,name,phone}` or v3 `college_lead` (name string / object). */
export function leadOf(r: AnyRow | null | undefined): LeadInfo | null {
  if (r && r.lead && typeof r.lead === "object") {
    const l = r.lead as AnyRow;
    return { id: (l.id as number) ?? null, name: String(l.name ?? l.full_name ?? ""), phone: (l.phone as string) || null };
  }
  const l = r?.college_lead;
  if (!l) return null;
  if (typeof l === "object") {
    const o = l as AnyRow;
    return { id: (o.id as number) ?? null, name: String(o.full_name ?? o.name ?? ""), phone: (o.phone as string) || null };
  }
  return { id: (r!.college_lead_id as number) ?? null, name: String(l), phone: null };
}

export const ambCount = (r: AnyRow): number => (isNum(r.ambassador_count) ? r.ambassador_count : Number(r.ambassadors ?? 0) || 0);

export function LeadsNode({ r }: { r: AnyRow }) {
  const lead = leadOf(r);
  const need = Number(r.branches_needing_ambassadors) || 0;
  return (
    <div className="vd-leads">
      {lead ? <span className="vd-lead-name">{lead.name}</span> : <Badge tone="warn">No lead</Badge>}
      <span className="vd-muted">{`${fmt.plural(Number(r.ambassador_leads ?? 0), "amb. lead")} · ${fmt.plural(ambCount(r), "ambassador")}`}</span>
      {need > 0 ? <Badge tone="warn">{`${fmt.plural(need, "branch", "branches")} need${need === 1 ? "s" : ""} ambassadors`}</Badge> : null}
    </div>
  );
}

/** Due date of a row's next follow-up (object or plain date). */
export function nextFollowupDate(r: AnyRow): string | null {
  const f = r.next_followup;
  if (!f) return null;
  return typeof f === "object" ? (((f as AnyRow).due_date as string) ?? null) : String(f);
}

export function NextFollowupNode({ r }: { r: AnyRow }) {
  const f = r.next_followup;
  if (!f) return <span className="vd-muted">{Number(r.followups_open) ? `${fmt.num(Number(r.followups_open))} open` : "—"}</span>;
  const date = nextFollowupDate(r);
  const fo = typeof f === "object" ? (f as AnyRow) : null;
  const overdue = fo && fo.overdue !== undefined ? !!fo.overdue : (daysUntil(date) ?? 0) < 0;
  return (
    <span className={cx("vd-fu", overdue && "is-overdue")} title={fo && fo.title ? String(fo.title) : undefined}>
      {fmt.date(date)}
      {overdue ? <span className="vd-small"> · overdue</span> : null}
    </span>
  );
}

export function ExamNode({ r }: { r: AnyRow }) {
  const ne = r.next_exam as { semester?: string; kind?: string; start?: string | null; end?: string | null } | null | undefined;
  return (
    <div className="vd-exam">
      <StatusBadge kind="exam_state" value={(r.exam_state as string) || "unknown"} />
      {ne && ne.start ? (
        <div className="vd-muted vd-small">{`${ne.semester || ""} ${ne.kind || ""} ${ne.start <= today() && ne.end ? `ends ${fmt.date(ne.end)}` : fmt.date(ne.start)}`.trim()}</div>
      ) : null}
    </div>
  );
}

/** Unassigned ambassadors from /api/people rows (v4 assignment_status; on v3 rows rule R3). */
export function unassignedOf<P extends Pick<Person, "id" | "role" | "status" | "college_id" | "reports_to"> & { assignment_status?: string | null }>(people: P[] | null | undefined): P[] {
  const rows = people ?? [];
  if (rows.some((p) => p.assignment_status))
    return rows.filter((p) => p.role === "ambassador" && p.status !== "inactive" && p.assignment_status && p.assignment_status !== "assigned");
  const byId = new Map(rows.map((p) => [Number(p.id), p]));
  return rows.filter((p) => {
    if (p.role !== "ambassador" || p.status === "inactive") return false;
    if (!p.reports_to) return true;
    const m = byId.get(Number(p.reports_to));
    return !m || m.status === "inactive" || m.college_id !== p.college_id || !["college_lead", "ambassador_lead"].includes(m.role);
  });
}

export const ROLE_TIPS: Readonly<Record<string, string>> = {
  college_lead: "College lead: the student who runs Tech Drona outreach at one college. Ambassadors report to them.",
  ambassador: "Ambassador: a student who promotes Tech Drona in their own branch and brings in enrollments.",
};

/* ------------------------------------------------------------------ diagnosis */

export interface DiagInfo {
  title: string;
  text: string;
  cta: string;
  /** colleges-list filter [key, value] */
  filter?: [string, string];
  href?: string;
}
/** Plain-language meaning + next action for each diagnosis code (rollup.js order). */
export const DIAG_INFO: Readonly<Record<string, DiagInfo>> = {
  ambassador_gap: { title: "Ambassadors missing", text: "Some relevant branches have no active ambassador, so nobody is reaching those students.", cta: "Show these colleges", filter: ["diagnosis", "ambassador_gap"] },
  low_outreach: { title: "Too little outreach", text: "Fewer students have been reached than this point in the campaign needs.", cta: "Show these colleges", filter: ["diagnosis", "low_outreach"] },
  low_conversion: { title: "Low conversion", text: "Students are being reached, but too few of them are enrolling.", cta: "Show these colleges", filter: ["diagnosis", "low_conversion"] },
  unrealistic_target: { title: "Target looks too high", text: "The target is more than half of the likely prospects, so it is unlikely to be met.", cta: "Review targets", href: portalPath.targets },
  behind_pace: { title: "Behind pace", text: "Enrollments are behind the pace needed to reach the target by the deadline.", cta: "Show these colleges", filter: ["diagnosis", "behind_pace"] },
};
export const DIAG_ORDER = ["ambassador_gap", "low_outreach", "low_conversion", "unrealistic_target", "behind_pace"] as const;

/** Colleges list with exactly one filter applied (old goColleges). */
export function collegesHref(key?: string, value?: string): string {
  const k = key === "exam_state" ? "exam" : key === "op_status" ? "op" : key;
  return k && value !== undefined ? `${portalPath.colleges}?${encodeURIComponent(k)}=${encodeURIComponent(value)}` : portalPath.colleges;
}

/* ------------------------------------------------------------------ calling status (forms.js CALL_STATUS) */

/** THE calling-status vocabulary lives with the shared dialogs (forms/labels.tsx, same as old forms.js). */
export { CALL_STATUS, CallStatusBadge } from "../../forms/labels";

/* ------------------------------------------------------------------ research plan (P-level) */

export interface PlanCollege {
  college_id: string;
  p_level?: string | null;
  targeted?: boolean | number | null;
  hold_reason?: string | null;
  research_target?: { min?: number | null; max?: number | null; avg?: number | null } | null;
  ambassadors_research?: number | null;
  college_leads_research?: number | null;
  [k: string]: unknown;
}
type PlanRes = { colleges?: PlanCollege[] } | null;

const EMPTY_PLAN: ReadonlyMap<string, PlanCollege> = new Map();

/**
 * Research plan index (GET /plan?districts=all, falling back to /plan): college_id → plan row. Empty map while
 * loading or when the plan is unavailable (lists never wait for it). Cached 5 min like the old per-session cache.
 */
export function usePlanIndex(): ReadonlyMap<string, PlanCollege> {
  const all = usePortalQuery<PlanRes>("plan", { query: { districts: "all" }, ttl: 300_000 });
  const plain = usePortalQuery<PlanRes>(all.error ? "plan" : null, { ttl: 300_000 });
  const res = all.data ?? plain.data;
  return useMemo(() => {
    if (!res?.colleges?.length) return EMPTY_PLAN;
    const m = new Map<string, PlanCollege>();
    for (const c of res.colleges) m.set(c.college_id, c);
    return m;
  }, [res]);
}

export const P_LEVELS = ["P1", "P2", "P3", "Hold"] as const;
export function pLevelOf(r: AnyRow | null | undefined, plan: ReadonlyMap<string, PlanCollege> | null | undefined): string | null {
  if (r && r.p_level) return String(r.p_level);
  const p = plan && r ? plan.get(String(r.id ?? r.college_id ?? "")) : undefined;
  return p ? (p.p_level ?? null) : null;
}
/** "Priority P1" / "On hold" badge of a research P-level (null when none). */
export function PriorityBadge({ level, hold = "On hold" }: { level: string | null | undefined; hold?: string }) {
  if (!level) return null;
  return <Badge tone={level === "P1" ? "brand" : level === "Hold" ? "neutral" : "info"}>{level === "Hold" ? hold : `Priority ${level}`}</Badge>;
}

/* ------------------------------------------------------------------ verification state of a college row */

/** v4 `data_status` / `verified_fields`; null when the server has no such data. */
export function verifiedStateOf(r: AnyRow | null | undefined): "verified" | "partly" | "unverified" | string | null {
  if (!r) return null;
  if (r.data_status) return r.data_status === "partly_verified" ? "partly" : String(r.data_status);
  const vf = r.verified_fields;
  if (vf && typeof vf === "object") return Object.keys(vf).length ? "partly" : "unverified";
  return null;
}
export const VERIFIED_LABEL: Readonly<Record<string, [string, Tone]>> = { verified: ["Verified", "good"], partly: ["Partly verified", "info"], unverified: ["Unverified", "warn"] };
/** Badge of a college's overall verification state (old dashboard.js verifiedBadge). */
export function VerifiedStateBadge({ state }: { state: string | null | undefined }) {
  if (!state) return null;
  const [l, t] = VERIFIED_LABEL[state] ?? [state, "neutral" as Tone];
  return <Badge tone={t}>{l}</Badge>;
}

/* ------------------------------------------------------------------ attention list (/api/attention rows) */

const SEV_TEXT: Record<string, string> = { high: "Urgent", "3": "Urgent", critical: "Urgent", medium: "Soon", "2": "Soon", low: "Watch", "1": "Watch" };

/** In-portal link of a row of the given level (server `href` wins). */
export function hrefFor(level: string, r: AnyRow): string | null {
  if (r.href) return toPortalHref(String(r.href));
  const id = rowId(r);
  switch (level) {
    case "district":
      return portalPath.district(id);
    case "city": {
      const did = String(r.district_id ?? id.split("--")[0]);
      return portalPath.city(did, id);
    }
    case "college":
      return portalPath.college(id);
    case "branch":
      return r.college_id ? `${portalPath.college(String(r.college_id))}?tab=branches&branch=${encodeURIComponent(id)}` : null;
    case "person":
      return portalPath.person(id);
    default:
      return null;
  }
}

/** Attention items (groups first), `limit` shown with a "Show N more" toggle; at most 60. */
export function AttentionList({ rows, limit = 8, onHover }: { rows: AttentionItem[] | null | undefined; limit?: number; onHover?: (collegeId: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const all = [...(rows ?? []).filter((r) => r.type === "group"), ...(rows ?? []).filter((r) => r.type !== "group")];
  if (!all.length) return <EmptyState icon="check" title="Nothing urgent" text="No colleges are behind pace, missing leads or overdue right now." />;
  const items = all.slice(0, 60);
  const extra = items.length - limit;
  const shown = open || extra <= 0 ? items : items.slice(0, limit);
  const list = (
    <ul className="vd-attn">
      {shown.map((r, i) => {
        const sev = String(r.severity ?? "");
        return (
          <li key={`${r.type}-${r.id}-${i}`} className={cx("vd-attn-item", r.type === "group" && "is-group")} data-sev={sev}>
            <Link
              to={(r.href ? toPortalHref(r.href) : hrefFor(r.type, r)) || portalPath.home}
              className="vd-attn-link"
              onMouseEnter={() => r.type === "college" && onHover?.(r.id)}
              onMouseLeave={() => onHover?.(null)}
            >
              <div className="vd-attn-head">
                <strong>{r.label || rowLabel(r)}</strong>
                {SEV_TEXT[sev] ? <span className="td-sr-only"> ({SEV_TEXT[sev]})</span> : null}
                {r.type === "group" && isNum(r.count) ? <span className="vd-count">{fmt.plural(r.count, "college")}</span> : r.diagnosis ? <StatusBadge kind="diagnosis" value={r.diagnosis} /> : null}
              </div>
              {(r.reasons ?? []).length ? (
                <ul className="vd-attn-reasons">
                  {r.reasons.map((x, j) => (
                    <li key={j}>{prettyReason(x)}</li>
                  ))}
                </ul>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
  return (
    <div>
      {extra > 0 ? (
        <div className="vd-expandable">
          {list}
          <button type="button" className="td-btn td-btn--ghost td-btn--sm vd-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Show fewer" : `Show ${fmt.num(extra)} more`}
          </button>
        </div>
      ) : (
        list
      )}
      {all.length > 60 ? <p className="vd-muted vd-small">{`Showing the first 60 of ${fmt.num(all.length)}. Use the Colleges list filters to see the rest.`}</p> : null}
    </div>
  );
}

/** Small "x of y" helper used by summaries ("12 of 40"). */
export const ofText = (a: number | null | undefined, b: number | null | undefined): ReactNode => `${fmt.num(a)} of ${fmt.num(b)}`;
