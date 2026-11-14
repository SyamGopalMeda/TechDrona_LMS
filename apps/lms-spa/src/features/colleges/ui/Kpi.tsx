/**
 * KPI tiles, stat cards and progress bars (components.js kpi / kpiRow / statCard / progressBar / progress).
 *
 *   <KpiRow>
 *     <Kpi label="Colleges" value={142} icon="college" to={portalPath.colleges} />
 *     <Kpi label="Students" value={s.strength?.value} basis={s.strength?.basis} />
 *   </KpiRow>
 *   <ProgressBar actual={row.actual} target={row.target} min={row.min} max={row.max} status={row.status} pct={row.pct} />
 */
import type { ReactNode } from "react";
import { Link } from "react-router";
import { fmt } from "../lib/fmt";
import type { Basis } from "../lib/types";
import { Provenance } from "./Badges";
import { cx } from "./context";
import { Icon, type IconName } from "./Icon";

const isEmpty = (v: unknown) => v === null || v === undefined || v === "";

export interface KpiProps {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "good" | "warn" | "bad" | "info" | "brand" | "neutral";
  icon?: IconName;
  /** in-portal link (the tile becomes a link) */
  to?: string;
  onClick?: () => void;
  /** tooltip + info icon */
  help?: string;
  loading?: boolean;
  basis?: Basis | null;
}

export function Kpi({ label, value, sub, tone, icon, to, onClick, help, loading, basis }: KpiProps) {
  const unknown = isEmpty(value);
  const action = !!(to || onClick);
  const cls = cx("td-kpi", tone && `td-kpi--${tone}`, action && "td-kpi--action");
  const body = (
    <>
      <div className="td-kpi__head">
        {icon ? (
          <span className="td-kpi__icon">
            <Icon name={icon} size={16} />
          </span>
        ) : null}
        <span className="td-kpi__label">{label}</span>
        {help ? <Icon name="info" size={14} className="td-kpi__help" /> : null}
        {action ? <Icon name="chevron" size={14} className="td-kpi__go" /> : null}
      </div>
      {loading ? (
        <div className="td-skel" style={{ width: "60%", height: 28, margin: "6px 0" }} />
      ) : (
        <div className="td-kpi__value td-num">{unknown ? "—" : typeof value === "number" ? fmt.num(value) : value}</div>
      )}
      {(sub || basis) && !loading ? (
        <div className="td-kpi__sub">
          {sub}
          {basis ? <Provenance basis={unknown ? "pending" : basis} /> : null}
        </div>
      ) : null}
    </>
  );
  if (to)
    return (
      <Link to={to} className={cls} title={help} aria-busy={loading || undefined}>
        {body}
      </Link>
    );
  if (onClick)
    return (
      <button type="button" className={cls} onClick={onClick} title={help} aria-busy={loading || undefined}>
        {body}
      </button>
    );
  return (
    <div className={cls} title={help} aria-busy={loading || undefined}>
      {body}
    </div>
  );
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className="td-kpi-row">{children}</div>;
}

/** Older stat card (components.js statCard) kept for screens that used it. */
export function StatCard({ label, value, sub, basis, tone, icon, onClick }: { label: ReactNode; value: ReactNode; sub?: ReactNode; basis?: Basis | null; tone?: string; icon?: IconName; onClick?: () => void }) {
  const unknown = value === null || value === undefined;
  const cls = cx("td-stat", tone && `td-stat--${tone}`, onClick && "td-stat--action");
  const inner = (
    <>
      <div className="td-stat__head">
        {icon ? (
          <span className="td-stat__icon">
            <Icon name={icon} size={18} />
          </span>
        ) : null}
        <span className="td-stat__label">{label}</span>
        {onClick ? <Icon name="chevron" size={16} className="td-stat__go" /> : null}
      </div>
      <div className="td-stat__value td-num">{unknown ? "—" : value}</div>
      {sub || basis ? (
        <div className="td-stat__sub">
          {sub ? <span>{sub}</span> : null}
          {basis ? <Provenance basis={unknown ? "pending" : basis} /> : null}
        </div>
      ) : null}
    </>
  );
  return onClick ? (
    <button type="button" className={cls} onClick={onClick}>
      {inner}
    </button>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

export interface ProgressBarProps {
  actual: number | null | undefined;
  target: number | null | undefined;
  min?: number | null;
  max?: number | null;
  label?: ReactNode;
  size?: "sm" | "md" | "lg";
  showNumbers?: boolean;
  unit?: string;
  /** server performance status (behind / on_track / too_early / partial_target …) */
  status?: string | null;
  /** server pct (a PERCENT) — wins over the computed one so the bar and the "Achieved" figure agree */
  pct?: number | null;
}

/** Actual vs target (+ optional min / max ticks). Never divides by zero; 'partial_target' is "Not judged". */
export function ProgressBar({ actual, target, min, max, label, size = "md", showNumbers = true, unit = "", status, pct }: ProgressBarProps) {
  const a = Number(actual) || 0;
  const hasT = !isEmpty(target) && Number.isFinite(Number(target));
  const t = hasT ? Number(target) : null;
  const base = cx("td-pbar", `td-pbar--${size}`);
  const labelEl = label ? <span className="td-pbar__label">{label}</span> : null;
  if (t === null || t === 0) {
    return (
      <div className={cx(base, "td-pbar--none")}>
        {showNumbers ? (
          <div className="td-pbar__meta">
            <span className="td-pbar__nums td-num">
              {labelEl}
              <strong>{fmt.num(a)}</strong>
              {unit ? ` ${unit}` : ""}
            </span>
            <span className="td-pbar__pct td-muted">{t === 0 ? "Target is 0" : "No target"}</span>
          </div>
        ) : null}
        <div className="td-pbar__track" aria-hidden="true" />
      </div>
    );
  }
  if (status === "partial_target") {
    return (
      <div className={cx(base, "td-pbar--none", "td-pbar--partial")}>
        {showNumbers ? (
          <div className="td-pbar__meta">
            <span className="td-pbar__nums td-num">
              {labelEl}
              <strong>{fmt.num(a)}</strong>
              <span className="td-muted"> / {fmt.num(t)}</span>
              {unit ? <span className="td-muted"> {unit}</span> : null}
            </span>
            <span className="td-pbar__pct td-muted">Not judged</span>
          </div>
        ) : null}
        <div className="td-pbar__track" aria-hidden="true" />
      </div>
    );
  }
  const p = pct !== undefined && pct !== null && Number.isFinite(Number(pct)) ? Number(pct) : Math.round((a / t) * 1000) / 10;
  const hi = Number.isFinite(Number(max)) && Number(max) > t ? Number(max) : t;
  const scale = Math.max(hi, 1);
  const fill = Math.max(0, Math.min(1, a / scale)) * 100;
  const over = a > t;
  const remaining = Math.max(t - a, 0);
  const tone = status === "behind" ? "bad" : status === "too_early" ? "info" : a >= t || status === "on_track" ? "good" : "brand";
  const ticks: ["min" | "target", number][] = [];
  if (min !== null && min !== undefined && Number(min) > 0 && Number(min) < scale) ticks.push(["min", Number(min)]);
  if (hi > t) ticks.push(["target", t]);
  const pTxt = fmt.pctPts(p);
  const aria = `${fmt.num(a)} of ${fmt.num(t)}${unit ? ` ${unit}` : ""} (${pTxt})${over ? `, ${fmt.num(a - t)} over target` : `, ${fmt.num(remaining)} remaining`}`;
  return (
    <div className={cx(base, `td-pbar--${tone}`, over && "is-over")}>
      {showNumbers ? (
        <div className="td-pbar__meta">
          <span className="td-pbar__nums td-num">
            {labelEl}
            <strong>{fmt.num(a)}</strong>
            <span className="td-muted"> / {fmt.num(t)}</span>
            {unit ? <span className="td-muted"> {unit}</span> : null}
          </span>
          <span className="td-pbar__pct td-num">{pTxt}</span>
        </div>
      ) : null}
      <div className="td-pbar__track" role="progressbar" aria-valuemin={0} aria-valuemax={t} aria-valuenow={Math.min(a, t)} aria-label={aria}>
        <div className="td-pbar__fill" style={{ width: `${fill}%` }} />
        {ticks.map(([k, v]) => (
          <span key={k} className={`td-pbar__tick td-pbar__tick--${k}`} style={{ left: `${(v / scale) * 100}%` }} title={`${k === "min" ? "Minimum" : "Target"}: ${fmt.num(v)}`} />
        ))}
      </div>
      {showNumbers ? (
        <div className="td-pbar__sub td-muted">
          {over ? <span className="td-pbar__over">+{fmt.num(a - t)} over target</span> : <span>{fmt.num(remaining)} to go</span>}
          {!isEmpty(min) || !isEmpty(max) ? <span>{fmt.range(min, max)}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
