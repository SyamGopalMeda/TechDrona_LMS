/**
 * Dependency-free, accessible SVG charts (React port of js/ui/charts.js). Every chart: an aria-labelled figure,
 * a visually-hidden data table, hover/focus tooltips, colours from the CSS tokens only, and an empty state.
 * Colour by job: one measure = one hue (--td-brand); a target is an outline, never a second hue; status hues
 * (good / warn / bad) only for state and always with a text label. CSS: styles/charts.css (imported here).
 *
 *   <BarChart data={[{ label: "Guntur", value: 42, secondary: 60, onClick… }]} valueLabel="Enrolled" secondaryLabel="Target" />
 *   <LineChart series={[{ name: "Enrolled", points: ts.map((p) => ({ x: p.date, y: p.enrolled })) }]} />
 *   <ColumnChart points={…} name="Calls" />   <Donut data={[{ label: "Verified", value: 12, tone: "good" }]} />
 *   <Funnel steps={[{ label: "Eligible", value: 900, basis: "estimated" }, …]} />
 *   <PaceMeter done={12} target={60} expected={20} />   <Sparkline points={[1, 3, 2]} />   <ProgressRing pct={0.42} />
 */
import { useEffect, useId, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode, type RefObject } from "react";
import "../styles/charts.css";
import { fmt } from "../lib/fmt";
import { Provenance } from "../ui/Badges";
import { cx } from "../ui/context";

type ToneName = "good" | "warn" | "bad" | "info" | "brand" | "brand2" | "accent" | "neutral" | "muted";
const TONE: Record<ToneName, string> = {
  good: "var(--td-good)",
  warn: "var(--td-warn)",
  bad: "var(--td-bad)",
  info: "var(--td-info)",
  brand: "var(--td-brand)",
  brand2: "var(--td-brand-2)",
  accent: "var(--td-accent)",
  neutral: "var(--td-muted)",
  muted: "var(--td-muted)",
};
/** Fixed categorical order (never cycled past 4: fold extras into "Other"). */
const SERIES = ["var(--td-brand)", "var(--td-accent)", "var(--td-info)", "var(--td-brand-2)"];
const toneColor = (t: string | undefined, i = 0) => (t && t in TONE ? TONE[t as ToneName] : SERIES[i % SERIES.length]!);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
type Fmt = (v: number | null | undefined) => string;
const defFmt: Fmt = (v) => fmt.num(v);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function shortDate(d: string): string {
  const t = Date.parse(`${String(d).slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(t)) return String(d);
  const dt = new Date(t);
  return `${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]}`;
}
/** 1.2Cr / 3.4L / 12K / 9,999 */
export function compactNum(v: number): string {
  return v >= 1e7 ? `${(v / 1e7).toFixed(1).replace(/\.0$/, "")}Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1).replace(/\.0$/, "")}L` : v >= 1e4 ? `${(v / 1e3).toFixed(0)}K` : fmt.num(v);
}
/** Axis ticks on a 1-2-5 ladder (whole numbers). */
export function niceTicks(maxVal: number, target = 4): { max: number; ticks: number[] } {
  const v = maxVal > 0 ? maxVal : 1;
  const raw = v / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const n = raw / p;
  let step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
  if (step < 1) step = 1;
  const max = Math.ceil(v / step) * step;
  const ticks: number[] = [];
  for (let t = 0; t <= max + 1e-9; t += step) ticks.push(t);
  return { max, ticks };
}

/* ------------------------------------------------------------------ shared pieces */

export function EmptyChart({ text = "No data yet", title, action }: { text?: ReactNode; title?: ReactNode; action?: ReactNode }) {
  return (
    <div className="tdc tdc-empty" role="note">
      <span
        className="tdc-empty-mark"
        aria-hidden="true"
        dangerouslySetInnerHTML={{
          __html:
            '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
        }}
      />
      <div className="tdc-empty-body">
        {title ? <strong className="tdc-empty-title">{title}</strong> : null}
        <span>{text}</span>
        {action}
      </div>
    </div>
  );
}

function SrTable({ caption, headers, rows }: { caption: string; headers: string[]; rows: string[][] }) {
  return (
    <div className="tdc-sr">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            {headers.map((x) => (
              <th key={x} scope="col">
                {x}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) =>
                j === 0 ? (
                  <th key={j} scope="row">
                    {c}
                  </th>
                ) : (
                  <td key={j}>{c}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface TipState {
  content: ReactNode;
  x: number;
  y: number;
}

/** Tooltip positioned inside `host` (flips left near the right edge). */
function useTip() {
  const host = useRef<HTMLElement | null>(null);
  const tipEl = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TipState | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number }>({ left: 0, top: 0 });
  useEffect(() => {
    if (!tip || !tipEl.current) return;
    const W = host.current?.clientWidth || 300;
    const tw = tipEl.current.offsetWidth;
    const th = tipEl.current.offsetHeight;
    let left = tip.x + 14;
    if (left + tw > W) left = Math.max(0, tip.x - tw - 14);
    setPos({ left, top: Math.max(0, tip.y - th - 10) });
  }, [tip]);
  const showFromEvent = (content: ReactNode, e: { clientX?: number; clientY?: number; currentTarget: Element }) => {
    const r = host.current?.getBoundingClientRect();
    if (!r) return;
    if (e.clientX) setTip({ content, x: e.clientX - r.left, y: (e.clientY ?? 0) - r.top });
    else {
      const t = e.currentTarget.getBoundingClientRect();
      setTip({ content, x: t.left - r.left + t.width / 2, y: t.top - r.top });
    }
  };
  const node = (
    <div ref={tipEl} className="tdc-tip" aria-hidden="true" hidden={!tip} style={{ left: pos.left, top: pos.top }}>
      {tip?.content}
    </div>
  );
  return { host, show: setTip, showFromEvent, hide: () => setTip(null), node };
}

function TipLine({ label, value, color }: { label: ReactNode; value: ReactNode; color?: string | null }) {
  return (
    <div className="tdc-tip-row">
      {color ? <span className="tdc-key" style={{ background: color }} /> : null}
      <span className="tdc-tip-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Legend({ items }: { items: { label: string; color: string; hollow?: boolean }[] }) {
  return (
    <ul className="tdc-legend">
      {items.map((it) => (
        <li key={it.label}>
          <span className={cx("tdc-key", it.hollow && "tdc-key-hollow")} style={it.hollow ? { borderColor: it.color } : { background: it.color }} />
          {it.label}
        </li>
      ))}
    </ul>
  );
}

/** Width of an element, re-measured on resize (first render assumes 640 like the old charts). */
function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [w, setW] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const x = Math.round(el.clientWidth);
      if (x) setW((prev) => (Math.abs(prev - x) < 2 ? prev : x));
    };
    measure();
    if (typeof ResizeObserver !== "function") return;
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(measure);
    });
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [ref]);
  return w;
}

/* ------------------------------------------------------------------ bar chart */

export interface BarDatum {
  label: string;
  value: number | null;
  /** e.g. the target: an outlined track behind the bar */
  secondary?: number | null;
  sub?: string;
  tone?: string;
  [k: string]: unknown;
}

/** Horizontal bars; `secondary` (target) draws an outline track and "value / secondary · pct". */
export function BarChart({
  data,
  format = defFmt,
  onClick,
  label = "Bar chart",
  valueLabel = "Value",
  secondaryLabel = "Target",
  empty = "No data yet",
  max: maxIn,
}: {
  data: BarDatum[];
  format?: Fmt;
  onClick?: (d: BarDatum) => void;
  label?: string;
  valueLabel?: string;
  secondaryLabel?: string;
  empty?: ReactNode;
  max?: number;
}) {
  const t = useTip();
  const rows = (data ?? []).filter((d) => d && (isNum(d.value) || isNum(d.secondary)));
  if (!rows.length) return typeof empty === "string" ? <EmptyChart text={empty} /> : <>{empty}</>;
  const hasSec = rows.some((d) => isNum(d.secondary));
  const max = maxIn || Math.max(1, ...rows.map((d) => Math.max(d.value || 0, d.secondary || 0)));
  return (
    <figure className="tdc tdc-bar" role="group" aria-label={label} ref={t.host}>
      {hasSec ? (
        <Legend
          items={[
            { label: valueLabel, color: SERIES[0]! },
            { label: secondaryLabel, color: "var(--td-border-strong, var(--td-muted))", hollow: true },
          ]}
        />
      ) : null}
      <ul className="tdc-bars" aria-hidden={onClick ? undefined : true}>
        {rows.map((d, i) => {
          const v = isNum(d.value) ? d.value : 0;
          const pctOf = d.secondary ? v / d.secondary : null;
          const valueText = hasSec ? `${format(d.value)} / ${isNum(d.secondary) ? format(d.secondary) : "—"}` : format(d.value);
          const tipContent = (
            <>
              <div className="tdc-tip-title">{d.label}</div>
              <TipLine label={valueLabel} value={format(d.value)} color={SERIES[0]} />
              {hasSec ? <TipLine label={secondaryLabel} value={isNum(d.secondary) ? format(d.secondary) : "not set"} /> : null}
              {pctOf !== null ? <TipLine label="Progress" value={fmt.pct(pctOf)} /> : null}
              {d.sub ? <div className="tdc-tip-sub">{d.sub}</div> : null}
            </>
          );
          return (
            <li
              key={`${d.label}-${i}`}
              className={cx("tdc-bar-row", onClick && "is-click")}
              tabIndex={onClick ? 0 : undefined}
              role={onClick ? "button" : undefined}
              aria-label={onClick ? `${d.label}: ${valueText}${pctOf !== null ? ` (${fmt.pct(pctOf)})` : ""}. Open.` : undefined}
              onClick={onClick ? () => onClick(d) : undefined}
              onKeyDown={
                onClick
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onClick(d);
                      }
                    }
                  : undefined
              }
              onPointerMove={(e) => t.showFromEvent(tipContent, e)}
              onPointerLeave={t.hide}
              onFocus={(e) => t.showFromEvent(tipContent, e)}
              onBlur={t.hide}
            >
              <span className="tdc-bar-label" title={d.label}>
                <span className="tdc-bar-name">{d.label}</span>
                {d.sub ? <small>{d.sub}</small> : null}
              </span>
              <span className="tdc-bar-track">
                {isNum(d.secondary) ? <span className="tdc-bar-sec" style={{ width: `${Math.min(100, (d.secondary / max) * 100)}%` }} /> : null}
                {v > 0 ? <span className="tdc-bar-fill" style={{ width: `${Math.max(0.8, Math.min(100, (v / max) * 100))}%`, background: d.tone ? toneColor(d.tone) : SERIES[0] }} /> : null}
              </span>
              <span className="tdc-bar-value">
                {valueText}
                {pctOf !== null ? <small>{fmt.pct(pctOf)}</small> : null}
              </span>
            </li>
          );
        })}
      </ul>
      {t.node}
      <SrTable
        caption={label}
        headers={hasSec ? ["Name", valueLabel, secondaryLabel] : ["Name", valueLabel]}
        rows={rows.map((d) => (hasSec ? [d.label, format(d.value), isNum(d.secondary) ? format(d.secondary) : "—"] : [d.label, format(d.value)]))}
      />
    </figure>
  );
}

/* ------------------------------------------------------------------ x/y frame */

interface FrameGeo {
  W: number;
  H: number;
  m: { l: number; r: number; t: number; b: number };
  iw: number;
  ih: number;
}

function Frame({ geo, xs, yTicks, Y, X }: { geo: FrameGeo; xs: string[]; yTicks: number[]; Y: (v: number) => number; X: (i: number) => number }) {
  const { W, H, m, iw } = geo;
  const n = Math.max(2, Math.min(xs.length, Math.floor(iw / 84)));
  const idx = [...new Set(Array.from({ length: n }, (_, k) => (xs.length === 1 ? 0 : Math.round((k / (n - 1)) * (xs.length - 1)))))];
  return (
    <>
      {yTicks.map((v) => (
        <g key={`y${v}`}>
          <line x1={m.l} x2={W - m.r} y1={Y(v)} y2={Y(v)} className={v === 0 ? "tdc-base" : "tdc-grid"} />
          <text x={m.l - 8} y={Y(v) + 4} textAnchor="end" className="tdc-axis">
            {compactNum(v)}
          </text>
        </g>
      ))}
      {idx.map((i) => (
        <text key={`x${i}`} x={X(i)} y={H - 8} textAnchor={xs.length === 1 ? "middle" : i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle"} className="tdc-axis">
          {shortDate(xs[i]!)}
        </text>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ line chart */

export interface LineSeries {
  name: string;
  points: { x: string; y: number | null }[];
  tone?: string;
}

/** Dates on x; area for one series, lines for up to four. Arrow keys read values. */
export function LineChart({ series, format = defFmt, label = "Trend", height = 220, empty = "No activity recorded yet" }: { series: LineSeries[]; format?: Fmt; label?: string; height?: number; empty?: string }) {
  const plot = useRef<HTMLDivElement>(null);
  const W = useWidth(plot);
  const t = useTip();
  const [cur, setCur] = useState<number | null>(null);
  const titleId = useId();
  const ser = (series ?? []).filter((x) => x && Array.isArray(x.points) && x.points.length).slice(0, 4);
  const xs = [...new Set(ser.flatMap((x) => x.points.map((p) => String(p.x))))].sort();
  const allY = ser.flatMap((x) => x.points.map((p) => p.y)).filter(isNum);
  if (!xs.length || !allY.length) return <EmptyChart text={empty} />;
  const lookup = ser.map((x) => new Map(x.points.map((p) => [String(p.x), p.y])));
  const { max: yMax, ticks } = niceTicks(Math.max(...allY, 0));
  const geo: FrameGeo = { W, H: height, m: { l: 44, r: 16, t: 12, b: 28 }, iw: 0, ih: 0 };
  geo.iw = Math.max(10, W - geo.m.l - geo.m.r);
  geo.ih = height - geo.m.t - geo.m.b;
  const X = (i: number) => geo.m.l + (xs.length === 1 ? geo.iw / 2 : (i / (xs.length - 1)) * geo.iw);
  const Y = (v: number) => geo.m.t + geo.ih - (v / yMax) * geo.ih;

  const showAt = (i: number) => {
    const c = Math.max(0, Math.min(xs.length - 1, i));
    setCur(c);
    let topY = geo.m.t + geo.ih;
    lookup.forEach((mp) => {
      const y = mp.get(xs[c]!);
      if (isNum(y)) topY = Math.min(topY, Y(y));
    });
    const scale = (plot.current?.clientWidth || W) / W;
    t.show({
      content: (
        <>
          <div className="tdc-tip-title">{fmt.date(xs[c])}</div>
          {ser.map((x, si) => (
            <TipLine key={x.name} label={x.name} value={format(lookup[si]!.get(xs[c]!) ?? null)} color={ser.length > 1 ? toneColor(x.tone, si) : null} />
          ))}
        </>
      ),
      x: X(c) * scale,
      y: topY * scale,
    });
  };
  const hide = () => {
    setCur(null);
    t.hide();
  };
  const onMove = (e: RPointerEvent<SVGRectElement>) => {
    const r = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    showAt(xs.length === 1 ? 0 : Math.round(((px - geo.m.l) / geo.iw) * (xs.length - 1)));
  };

  return (
    <figure className="tdc tdc-line" role="group" aria-label={label}>
      {ser.length > 1 ? <Legend items={ser.map((x, i) => ({ label: x.name, color: toneColor(x.tone, i) }))} /> : null}
      <div className="tdc-plot" ref={(el) => { plot.current = el; t.host.current = el; }}>
        <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} role="img" aria-labelledby={titleId} className="tdc-svg">
          <title id={titleId}>{`${label}: ${ser.map((x) => x.name).join(", ")}, ${shortDate(xs[0]!)} to ${shortDate(xs[xs.length - 1]!)}`}</title>
          <Frame geo={geo} xs={xs} yTicks={ticks} X={X} Y={Y} />
          {ser.map((x, si) => {
            const color = toneColor(x.tone, si);
            const pts = xs.map((d, i) => [i, lookup[si]!.get(d)] as const).filter((p): p is readonly [number, number] => isNum(p[1]));
            if (!pts.length) return null;
            const dLine = pts.map(([i, y], k) => `${k ? "L" : "M"}${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join("");
            const last = pts[pts.length - 1]!;
            return (
              <g key={x.name}>
                {ser.length === 1 && pts.length > 1 ? (
                  <path d={`${dLine}L${X(last[0]).toFixed(1)},${Y(0)}L${X(pts[0]![0]).toFixed(1)},${Y(0)}Z`} className="tdc-area" style={{ fill: color }} />
                ) : null}
                <path d={dLine} className="tdc-line" style={{ stroke: color }} />
                <circle cx={X(last[0])} cy={Y(last[1])} r={4} className="tdc-dot" style={{ fill: color }} />
              </g>
            );
          })}
          {cur !== null ? (
            <>
              <line x1={X(cur)} x2={X(cur)} y1={geo.m.t} y2={geo.m.t + geo.ih} className="tdc-cross" />
              {ser.map((x, si) => {
                const y = lookup[si]!.get(xs[cur]!);
                return isNum(y) ? <circle key={x.name} cx={X(cur)} cy={Y(y)} r={4.5} className="tdc-dot" style={{ fill: toneColor(x.tone, si) }} /> : null;
              })}
            </>
          ) : null}
          <rect
            x={geo.m.l}
            y={geo.m.t}
            width={geo.iw}
            height={geo.ih}
            className="tdc-overlay"
            tabIndex={0}
            aria-label={`${label}. Use left and right arrow keys to read values.`}
            onPointerMove={onMove}
            onPointerLeave={hide}
            onFocus={() => showAt(cur ?? xs.length - 1)}
            onBlur={hide}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") {
                e.preventDefault();
                showAt((cur ?? xs.length - 1) - 1);
              }
              if (e.key === "ArrowRight") {
                e.preventDefault();
                showAt((cur ?? xs.length - 1) + 1);
              }
            }}
          />
        </svg>
        {t.node}
      </div>
      <SrTable caption={label} headers={["Date", ...ser.map((x) => x.name)]} rows={xs.map((d) => [fmt.date(d), ...lookup.map((mp) => format(mp.get(d) ?? null))])} />
    </figure>
  );
}

/* ------------------------------------------------------------------ column chart */

/** Vertical columns for counts per day / week. `xLabel(x)` formats the tooltip title ("Week of …"). */
export function ColumnChart({
  points,
  name = "Value",
  format = defFmt,
  label = "Columns",
  height = 220,
  xLabel,
  empty = "No activity recorded yet",
}: {
  points: { x: string; y: number | null }[];
  name?: string;
  format?: Fmt;
  label?: string;
  height?: number;
  xLabel?: (x: string) => string;
  empty?: string;
}) {
  const plot = useRef<HTMLDivElement>(null);
  const W = useWidth(plot);
  const t = useTip();
  const [cur, setCur] = useState<number | null>(null);
  const titleId = useId();
  const pts = (points ?? []).filter((p) => p && p.x);
  const ys = pts.map((p) => p.y).filter(isNum);
  if (!pts.length || !ys.length) return <EmptyChart text={empty} />;
  const xs = pts.map((p) => String(p.x));
  const { max: yMax, ticks } = niceTicks(Math.max(...ys, 0));
  const title = (x: string) => (xLabel ? xLabel(x) : fmt.date(x));
  const geo: FrameGeo = { W, H: height, m: { l: 44, r: 16, t: 12, b: 28 }, iw: 0, ih: 0 };
  geo.iw = Math.max(10, W - geo.m.l - geo.m.r);
  geo.ih = height - geo.m.t - geo.m.b;
  const slot = geo.iw / xs.length;
  const bw = Math.max(1, Math.min(28, slot - Math.min(2, slot * 0.25)));
  const X = (i: number) => geo.m.l + slot * i + slot / 2;
  const Y = (v: number) => geo.m.t + geo.ih - (v / yMax) * geo.ih;
  const showAt = (i: number) => {
    const c = Math.max(0, Math.min(xs.length - 1, i));
    setCur(c);
    const v = pts[c]!.y;
    const scale = (plot.current?.clientWidth || W) / W;
    t.show({
      content: (
        <>
          <div className="tdc-tip-title">{title(xs[c]!)}</div>
          <TipLine label={name} value={format(isNum(v) ? v : 0)} />
        </>
      ),
      x: X(c) * scale,
      y: Y(isNum(v) ? v : 0) * scale,
    });
  };
  const hide = () => {
    setCur(null);
    t.hide();
  };
  return (
    <figure className="tdc tdc-column" role="group" aria-label={label}>
      <div className="tdc-plot" ref={(el) => { plot.current = el; t.host.current = el; }}>
        <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} role="img" aria-labelledby={titleId} className="tdc-svg">
          <title id={titleId}>{`${label}, ${shortDate(xs[0]!)} to ${shortDate(xs[xs.length - 1]!)}. Total ${format(ys.reduce((a, b) => a + b, 0))}.`}</title>
          <Frame geo={geo} xs={xs} yTicks={ticks} X={X} Y={Y} />
          {pts.map((p, i) => {
            const v = isNum(p.y) ? p.y : 0;
            if (!(v > 0)) return null;
            const x0 = X(i) - bw / 2;
            const y0 = Y(v);
            const r = Math.min(4, bw / 2, Y(0) - y0);
            const d = `M${x0},${Y(0)}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + bw - r}Q${x0 + bw},${y0} ${x0 + bw},${y0 + r}V${Y(0)}Z`;
            return <path key={i} d={d} className={cx("tdc-col", cur !== null && cur !== i && "is-dim")} style={{ fill: SERIES[0] }} />;
          })}
          <rect
            x={geo.m.l}
            y={geo.m.t}
            width={geo.iw}
            height={geo.ih}
            className="tdc-overlay"
            tabIndex={0}
            aria-label={`${label}. Use left and right arrow keys to read values.`}
            onPointerMove={(e) => {
              const r = (e.currentTarget.ownerSVGElement ?? e.currentTarget).getBoundingClientRect();
              showAt(Math.floor((((e.clientX - r.left) / r.width) * W - geo.m.l) / slot));
            }}
            onPointerLeave={hide}
            onFocus={() => showAt(cur ?? xs.length - 1)}
            onBlur={hide}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") {
                e.preventDefault();
                showAt((cur ?? xs.length - 1) - 1);
              }
              if (e.key === "ArrowRight") {
                e.preventDefault();
                showAt((cur ?? xs.length - 1) + 1);
              }
            }}
          />
        </svg>
        {t.node}
      </div>
      <SrTable caption={label} headers={["Date", name]} rows={pts.map((p) => [title(p.x), format(isNum(p.y) ? p.y : 0)])} />
    </figure>
  );
}

/* ------------------------------------------------------------------ pace meter */

/** Enrolled vs target with an "expected by today" tick (all three from the API). null without a target. */
export function PaceMeter({ done, target, expected, tone, format = defFmt, label = "Progress to target" }: { done: number | null | undefined; target: number | null | undefined; expected?: number | null; tone?: "good" | "bad"; format?: Fmt; label?: string }) {
  if (!(isNum(target) && target > 0)) return null;
  const d = isNum(done) ? done : 0;
  const frac = Math.max(0, Math.min(1, d / target));
  const exp = isNum(expected) && expected > 0 ? Math.max(0, Math.min(1, expected / target)) : null;
  const text = `${format(d)} of ${format(target)} enrolled (${fmt.pct(d / target)})${exp !== null ? `; about ${format(expected)} expected by today` : ""}`;
  return (
    <div className={cx("tdc-pace", tone && `tdc-pace--${tone}`)} role="img" aria-label={`${label}: ${text}`}>
      <div className="tdc-pace-track">
        {frac > 0 ? <span className="tdc-pace-fill" style={{ width: `${Math.max(1.2, frac * 100)}%` }} /> : null}
        {exp !== null ? <span className="tdc-pace-mark" style={{ left: `${exp * 100}%` }} /> : null}
      </div>
      <div className="tdc-pace-scale" aria-hidden="true">
        <span>{`${format(d)} enrolled · ${fmt.pct(d / target)}`}</span>
        {exp !== null ? <span className="tdc-pace-exp">{`Expected by today ≈ ${format(expected)}`}</span> : null}
        <span>{`Target ${format(target)}`}</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ donut */

/** Parts of one whole: data [{label, value, tone?}]. */
export function Donut({ data, centerLabel = "Total", format = defFmt, label = "Breakdown", empty = "Nothing to show yet" }: { data: { label: string; value: number | null; tone?: string }[]; centerLabel?: string; format?: Fmt; label?: string; empty?: string }) {
  const t = useTip();
  const titleId = useId();
  const rows = (data ?? []).filter((d): d is { label: string; value: number; tone?: string } => !!d && isNum(d.value) && d.value > 0);
  const total = rows.reduce((a, d) => a + d.value, 0);
  if (!rows.length || !total) return <EmptyChart text={empty} />;
  const R = 46;
  const C = 2 * Math.PI * R;
  const GAP = rows.length > 1 ? 2 : 0;
  let acc = 0;
  return (
    <figure className="tdc tdc-donut" role="group" aria-label={label} ref={t.host}>
      <div className="tdc-donut-wrap">
        <svg viewBox="0 0 120 120" className="tdc-svg tdc-donut-svg" role="img" aria-labelledby={titleId}>
          <title id={titleId}>{`${label}: ${rows.map((d) => `${d.label} ${format(d.value)}`).join(", ")}`}</title>
          <circle cx={60} cy={60} r={R} className="tdc-ring-bg" />
          {rows.map((d, i) => {
            const len = (d.value / total) * C;
            const color = toneColor(d.tone, i);
            const off = acc;
            acc += len;
            const tipC = (
              <>
                <div className="tdc-tip-title">{d.label}</div>
                <TipLine label={format(d.value)} value={fmt.pct(d.value / total)} color={color} />
              </>
            );
            return (
              <circle
                key={d.label}
                cx={60}
                cy={60}
                r={R}
                className="tdc-seg"
                tabIndex={0}
                strokeDasharray={`${Math.max(0.5, len - GAP)} ${C - Math.max(0.5, len - GAP)}`}
                strokeDashoffset={-off}
                transform="rotate(-90 60 60)"
                style={{ stroke: color }}
                aria-label={`${d.label}: ${format(d.value)} (${fmt.pct(d.value / total)})`}
                onPointerMove={(e) => t.showFromEvent(tipC, e)}
                onFocus={(e) => t.showFromEvent(tipC, e)}
                onPointerLeave={t.hide}
                onBlur={t.hide}
              />
            );
          })}
          <text x={60} y={60} textAnchor="middle" className="tdc-center-val">
            {compactNum(total)}
          </text>
          <text x={60} y={76} textAnchor="middle" className="tdc-center-lbl">
            {centerLabel}
          </text>
        </svg>
        <ul className="tdc-donut-legend">
          {rows.map((d, i) => (
            <li key={d.label}>
              <span className="tdc-key" style={{ background: toneColor(d.tone, i) }} />
              <span className="tdc-dl-label">{d.label}</span>
              <span className="tdc-dl-val">
                {format(d.value)}
                <small>{fmt.pct(d.value / total)}</small>
              </span>
            </li>
          ))}
        </ul>
      </div>
      {t.node}
      <SrTable caption={label} headers={["Part", "Value", "Share"]} rows={rows.map((d) => [d.label, format(d.value), fmt.pct(d.value / total)])} />
    </figure>
  );
}

/* ------------------------------------------------------------------ funnel */

export interface FunnelStep {
  label: string;
  value: number | null;
  basis?: string | null;
  hint?: string;
}

/** e.g. eligible → reached → enrolled, with step-to-step conversion and provenance. */
export function Funnel({ steps, format = defFmt, label = "Funnel", empty = "Nothing to show yet" }: { steps: FunnelStep[]; format?: Fmt; label?: string; empty?: string }) {
  const t = useTip();
  const rows = (steps ?? []).filter(Boolean);
  if (!rows.length) return <EmptyChart text={empty} />;
  const max = Math.max(1, ...rows.map((d) => (isNum(d.value) ? d.value : 0)));
  return (
    <figure className="tdc tdc-funnel" role="group" aria-label={label} ref={t.host}>
      <ol className="tdc-funnel-list">
        {rows.map((d, i) => {
          const known = isNum(d.value);
          const prevStep = i > 0 ? rows[i - 1]! : null;
          const prev = prevStep?.value;
          const conv = known && isNum(prev) && prev > 0 && (d.value as number) > 0 ? (d.value as number) / prev : null;
          const digits = conv !== null && conv < 0.1 ? 1 : 0;
          const tipC = (
            <>
              <div className="tdc-tip-title">{d.label}</div>
              <TipLine label="Count" value={known ? format(d.value) : "— (pending)"} />
              {conv !== null && prevStep ? <TipLine label={`Of ${prevStep.label.toLowerCase()}`} value={fmt.pct(conv, digits)} /> : null}
            </>
          );
          return (
            <li
              key={`${d.label}-${i}`}
              className="tdc-funnel-step"
              tabIndex={0}
              aria-label={`${d.label}: ${known ? format(d.value) : "unknown, pending"}${conv !== null ? `, ${fmt.pct(conv, digits)} of previous step` : ""}`}
              onPointerMove={(e) => t.showFromEvent(tipC, e)}
              onPointerLeave={t.hide}
              onFocus={(e) => t.showFromEvent(tipC, e)}
              onBlur={t.hide}
            >
              <div className="tdc-funnel-head">
                <span className="tdc-funnel-label">{d.label}</span>
                <span className="tdc-funnel-val">
                  {known ? format(d.value) : "—"} {known ? (d.basis ? <Provenance basis={d.basis} /> : null) : <Provenance basis="pending" />}
                </span>
              </div>
              <div className="tdc-funnel-track">{known && (d.value as number) > 0 ? <span className="tdc-funnel-fill" style={{ width: `${Math.max(1, ((d.value as number) / max) * 100)}%` }} /> : null}</div>
              {conv !== null && prevStep ? (
                <span className="tdc-funnel-conv">{`${fmt.pct(conv, digits)} of ${prevStep.label.toLowerCase()}`}</span>
              ) : d.hint ? (
                <span className="tdc-funnel-conv">{d.hint}</span>
              ) : null}
            </li>
          );
        })}
      </ol>
      {t.node}
      <SrTable caption={label} headers={["Step", "Count", "Basis"]} rows={rows.map((d) => [d.label, isNum(d.value) ? format(d.value) : "—", d.basis || (isNum(d.value) ? "" : "pending")])} />
    </figure>
  );
}

/* ------------------------------------------------------------------ sparkline, progress ring */

export function Sparkline({ points, label = "Trend", tone = "brand" }: { points: (number | { y: number | null } | null)[]; label?: string; tone?: string }) {
  const ys = (points ?? []).map((p) => (isNum(p) ? p : p && typeof p === "object" ? p.y : null)).filter(isNum);
  if (ys.length < 2)
    return (
      <span className="tdc-spark tdc-spark-empty" aria-label={`${label}: not enough data`}>
        —
      </span>
    );
  const max = Math.max(...ys);
  const min = Math.min(0, ...ys);
  const span = max - min || 1;
  const W = 100;
  const H = 28;
  const d = ys.map((y, i) => `${i ? "L" : "M"}${((i / (ys.length - 1)) * W).toFixed(2)},${(H - 2 - ((y - min) / span) * (H - 4)).toFixed(2)}`).join("");
  return (
    <svg className="tdc-spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${label}: from ${fmt.num(ys[0])} to ${fmt.num(ys[ys.length - 1])}`}>
      <title>{`${label}: ${ys.map((y) => fmt.num(y)).join(", ")}`}</title>
      <path d={d} className="tdc-spark-line" vectorEffect="non-scaling-stroke" style={{ stroke: toneColor(tone) }} />
    </svg>
  );
}

/** pct is a fraction (0.42) or null (unknown → "—"). */
export function ProgressRing({ pct, label = "Progress", tone, size }: { pct: number | null | undefined; label?: string; tone?: string; size?: number }) {
  const known = isNum(pct);
  const R = 50;
  const C = 2 * Math.PI * R;
  const frac = known ? Math.max(0, Math.min(1, pct)) : 0;
  const color = toneColor(tone || (known && pct >= 1 ? "good" : "brand"));
  const text = known ? fmt.pct(pct) : "—";
  return (
    <figure className="tdc tdc-ring" style={size ? { width: size } : undefined} role="img" aria-label={`${label}: ${known ? text : "not set yet"}`}>
      <svg viewBox="0 0 120 120" className="tdc-svg" aria-hidden="true">
        <circle cx={60} cy={60} r={R} className="tdc-ring-bg" />
        {frac > 0 ? <circle cx={60} cy={60} r={R} className="tdc-ring-fg" transform="rotate(-90 60 60)" strokeDasharray={`${frac * C} ${C}`} style={{ stroke: color }} /> : null}
        <text x={60} y={62} textAnchor="middle" dominantBaseline="middle" className="tdc-ring-val">
          {text}
        </text>
        <text x={60} y={84} textAnchor="middle" className="tdc-ring-lbl">
          {known ? label : "No target yet"}
        </text>
      </svg>
    </figure>
  );
}
