/**
 * Shared bits of Targets & performance and the Planner (old js/views/targets.js top block): vocabulary, periods,
 * server TODAY, the target-vs-actual bar and the status chip.
 */
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import type { PortalMeta } from "../../lib/types";
import { StatusChip, STATUS_META, PERF_STATUS_ORDER, cx } from "../../ui";

export const STATE_ID = "ap"; // the server stores the state / programme scope as 'ap'
export const CHILD: Record<string, string> = { state: "districts", district: "cities / towns", city: "colleges", college: "relevant branches", branch: "ambassadors" };
export const LEVEL: Record<string, string> = { state: "The programme (all target districts)", district: "A district", city: "A city / town", college: "A college", branch: "A branch" };
export const TYPE_LABEL: Record<string, string> = { state: "Programme", district: "District", city: "City / town", college: "College", branch: "Branch", person: "Person" };
export const METHOD: Record<string, [string, string]> = {
  eligible: ["By likely prospects", "More where more final-year students in target branches can enrol. Recommended."],
  strength: ["By total strength", "More where the total number of students is higher."],
  equal: ["Equal split", "Everyone gets the same number. Handy for ambassadors."],
};
export const ROLE: Record<string, string> = { college_lead: "College lead", ambassador_lead: "Ambassador lead", ambassador: "Ambassador" };
export const LEADS = new Set(["college_lead", "ambassador_lead"]);

/** status → [label, tone, explanation] from THE shared vocabulary; 'open' only on pre-v4 servers. */
export const STATUS: Record<string, [string, string, string]> = {
  ...Object.fromEntries(PERF_STATUS_ORDER.map((k) => [k, [STATUS_META[k]!.label, STATUS_META[k]!.tone, STATUS_META[k]!.tip] as [string, string, string]])),
  open: ["Not met yet", "warn", "Pace is not available from this server version."],
};
export const STATUS_ORDER = [...PERF_STATUS_ORDER, "open"];

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const numOr = (v: unknown): number | null => (v === null || v === undefined || v === "" ? null : Number.isFinite(Number(v)) ? Number(v) : null);
export const arr = <T = Record<string, unknown>,>(x: unknown): T[] =>
  Array.isArray(x) ? x : x && Array.isArray((x as { rows?: unknown }).rows) ? (x as { rows: T[] }).rows : x && Array.isArray((x as { items?: unknown }).items) ? (x as { items: T[] }).items : [];

/** One rule for % on every page: value is a PERCENT (4.75 → "4.8%"). */
export const pctText = (p: number | null | undefined): string => (isNum(p) ? fmt.pctPts(p) : "—");

/* ---------------------------------------------------------------- dates / periods (server TODAY, never the browser clock) */
const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
const parseD = (s: string) => new Date(`${String(s).slice(0, 10)}T00:00:00Z`);
export function mondayOf(s: string): string {
  const d = parseD(s);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return iso(d);
}
export function addDaysIso(s: string, n: number): string {
  const d = parseD(s);
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD' → label */
export function periodLabel(p: string | null | undefined): string {
  if (!p || p === "programme") return "Programme to date";
  const [k, v = ""] = String(p).split(":");
  if (k === "month") {
    const [y, m] = v.split("-");
    return `${MONTHS[Number(m) - 1]} ${y}`;
  }
  if (k === "week") return `Week of ${fmt.date(v)} – ${fmt.date(addDaysIso(v, 6))}`;
  return String(p);
}
/** a stored target row → 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD' */
export function periodKey(t: Record<string, unknown>): string {
  if (t.period_key) return String(t.period_key);
  const p = String(t.period || "programme");
  if (p === "programme" || p.includes(":")) return p;
  const start = String(t.period_start || t.period_key || "");
  if (p === "month") return `month:${start.slice(0, 7)}`;
  if (p === "week") return `week:${start.slice(0, 10)}`;
  return p;
}

/** The server's TODAY (/api/meta, else /api/health); null until known. */
export function useServerToday(): string | null {
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 }).data;
  const fromMeta = typeof meta?.today === "string" ? meta.today : null;
  const health = usePortalQuery<{ today?: string; version?: string }>(meta && !fromMeta ? "health" : null, { ttl: 300_000 }).data;
  return fromMeta || health?.today || null;
}
/** "55 days left (incl. today)" — same inclusive rule as /api/target-dashboard and the planner. */
export function daysLeftFrom(today: string | null, deadline: string | null | undefined): string {
  if (!today || !deadline) return "";
  const n = Math.round((Date.parse(`${String(deadline).slice(0, 10)}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000) + 1;
  return n > 0 ? `${fmt.num(n)} days left (incl. today)` : "deadline passed";
}

/** Status chip (one vocabulary); 'open' only on pre-v4 servers. */
export function TargetStatusChip({ status, title }: { status: string; title?: string }) {
  return <StatusChip status={status} size="sm" label={status === "open" ? STATUS.open![0] : undefined} title={title || (status === "open" ? STATUS.open![2] : undefined)} />;
}

/** Target-vs-actual bar with min / target / max markers. Scale = the largest of actual, target, max. */
export function PerfBar({ r, lg }: { r: { actual?: number | null; target?: number | null; min?: number | null; max?: number | null; status?: string | null; label?: string }; lg?: boolean }) {
  const a = Number(r.actual) || 0;
  const t = r.target;
  const mn = r.min;
  const mx = r.max;
  if (t === null || t === undefined) return <span className="tgp-muted tgp-small">{fmt.num(a)} enrolled · no target</span>;
  const scale = Math.max(a, t, mx || 0, 1);
  const pos = (v: number) => `${Math.min(100, (v / scale) * 100).toFixed(2)}%`;
  const tone = t === 0 ? "neutral" : a >= t ? "good" : r.status === "behind" ? "bad" : r.status === "on_track" ? "info" : "warn";
  const label = `${fmt.num(a)} of ${t === 0 ? "a target of 0" : fmt.num(t)}${mn != null ? `, minimum ${fmt.num(mn)}` : ""}${mx != null ? `, maximum ${fmt.num(mx)}` : ""}`;
  return (
    <span className={cx("tgp-bar", lg && "tgp-bar--lg")} role="img" aria-label={label} title={label}>
      <span className="tgp-bar__track">
        <i className={`tgp-bar__fill is-${tone}`} style={{ width: pos(a) }} />
        {mn != null ? <b className="tgp-bar__mk is-min" style={{ left: pos(mn) }} /> : null}
        {t > 0 ? <b className="tgp-bar__mk is-target" style={{ left: pos(t) }} /> : null}
        {mx != null ? <b className="tgp-bar__mk is-max" style={{ left: pos(mx) }} /> : null}
      </span>
    </span>
  );
}
