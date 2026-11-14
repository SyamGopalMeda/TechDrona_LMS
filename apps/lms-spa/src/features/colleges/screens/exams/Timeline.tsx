/**
 * Exam timeline (port of exams.js gantt): one week back, 16 weeks ahead; per college two lanes (3-1 top, 4-1 bottom);
 * end-sem / mid / lab bars (labs hatched, planned dates dashed), "free for outreach" gaps when every semester is dated
 * or confirmed exam-free, today marker. Bars are buttons (click / Enter edits the row).
 */
import { useId, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { fmt, today } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import { cx } from "../../ui";
import { EXAM_STATE, addDays, dayIndex, fourOneDone, isExamState, isoOnly, windowsOf, type ExamCollege, type ExamRecord } from "./model";

const BACK = 7;
const DAYS = 7 + 112;
const HEAD = 46;
const ROW = 42;
const GROUP = 30;

export function Timeline({
  rows,
  districtName,
  width,
  coarse,
  canWrite,
  onEdit,
}: {
  rows: ExamCollege[];
  districtName: (id: string) => string;
  /** available width of the view (px) */
  width: number;
  coarse: boolean;
  canWrite: boolean;
  onEdit: (c: ExamCollege, r: ExamRecord) => void;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const t0 = addDays(today(), -BACK);
  const narrow = width < 760;
  const LABEL_W = narrow ? 140 : 280;
  const avail = (width || 1000) - LABEL_W - 2;
  const DW = Math.max(narrow ? 7 : 8, Math.floor(avail / DAYS));
  const W = DAYS * DW;
  const x = (iso: string) => Math.max(0, Math.min(DAYS, dayIndex(iso, t0))) * DW;
  const todayX = BACK * DW;

  const groups = new Map<string, ExamCollege[]>();
  for (const c of [...rows].sort((a, b) => districtName(a.district_id).localeCompare(districtName(b.district_id)) || a.name.localeCompare(b.name))) {
    const k = c.district_id || "";
    const g = groups.get(k);
    if (g) g.push(c);
    else groups.set(k, [c]);
  }
  let totalH = HEAD;
  for (const l of groups.values()) totalH += GROUP + l.length * ROW;

  const svg: ReactNode[] = [];
  svg.push(<rect key="head" x={0} y={0} width={W} height={HEAD} className="g-head" />);
  const monthStarts: number[] = [];
  for (let d = 0; d <= DAYS; d++) if (addDays(t0, d).endsWith("-01")) monthStarts.push(d);
  const first = monthStarts[0];
  const labelMonths = [0, ...monthStarts].filter((d, i) => (i === 0 ? first === undefined || first * DW > 70 : true));
  for (const d of labelMonths) {
    const dt = new Date(`${addDays(t0, d)}T00:00:00Z`);
    svg.push(
      <text key={`m${d}`} x={d * DW + 6} y={17} className="g-month">
        {dt.toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "UTC" })}
      </text>,
    );
  }
  for (const d of monthStarts) svg.push(<line key={`ml${d}`} x1={d * DW} x2={d * DW} y1={0} y2={totalH} className="g-month-line" />);
  for (let d = 0; d <= DAYS; d++) {
    const dt = new Date(`${addDays(t0, d)}T00:00:00Z`);
    if (dt.getUTCDay() !== 1) continue;
    svg.push(<line key={`wl${d}`} x1={d * DW} x2={d * DW} y1={HEAD} y2={totalH} className="g-week-line" />);
    if (Math.abs(d * DW - todayX) > 22)
      svg.push(
        <text key={`w${d}`} x={d * DW + 3} y={38} className="g-week">
          {String(dt.getUTCDate())}
        </text>,
      );
  }
  svg.push(<rect key="past" x={0} y={HEAD} width={todayX} height={totalH - HEAD} className="g-past" />);

  const labels: ReactNode[] = [];
  let y = HEAD;
  for (const [dk, list] of groups) {
    labels.push(
      <div key={`g-${dk}`} className="ex-gl-group" style={{ height: GROUP }}>
        {districtName(dk) || dk || "District not set"}
        <span className="adm-muted">{` · ${list.length}`}</span>
      </div>,
    );
    svg.push(<rect key={`grp-${dk}`} x={0} y={y} width={W} height={GROUP} className="g-group" />);
    y += GROUP;
    for (const c of list) {
      const done = fourOneDone(c);
      const st = isExamState(c.exam_state) ? EXAM_STATE[c.exam_state] : EXAM_STATE.unknown;
      labels.push(
        <div key={`r-${c.college_id}`} className={cx("ex-gl-row", done && "is-done41")} style={{ height: ROW }}>
          <div className="ex-gl-main">
            <Link to={portalPath.college(c.college_id)} title={c.name}>
              {c.name}
            </Link>
            <span className={cx("ex-gl-sub", `is-${st.tone}`)}>
              <i aria-hidden="true" />
              {done ? "4-1 done · reach out" : st.short}
            </span>
          </div>
          <span className="ex-gl-lanes" aria-hidden="true">
            <span>3-1</span>
            <span>4-1</span>
          </span>
        </div>,
      );
      const rowY = y;
      svg.push(<line key={`rl-${c.college_id}`} x1={0} x2={W} y1={rowY + ROW} y2={rowY + ROW} className="g-row-line" />);
      const exRows = c.rows ?? [];
      const wins = exRows.flatMap((r) => windowsOf(r).map((w) => ({ ...w, sem: r.semester, r })));
      // free-for-outreach gaps: only when every semester is either dated or confirmed exam-free
      const reliable =
        exRows.length > 0 &&
        exRows.some((r) => isoOnly(r.endsem_start) && isoOnly(r.endsem_end)) &&
        exRows.every((r) => r.status !== "Unverified" && (r.status === "No Current Exams Found" || r.status === "Completed" || (isoOnly(r.endsem_start) && isoOnly(r.endsem_end))));
      if (reliable) {
        const busy = wins
          .map((w) => [Math.max(dayIndex(w.start, t0), BACK), Math.min(dayIndex(w.end, t0) + 1, DAYS)] as const)
          .filter(([a, b]) => b > a)
          .sort((a, b) => a[0] - b[0]);
        let p = BACK;
        const gaps: [number, number][] = [];
        for (const [a, b] of busy) {
          if (a > p) gaps.push([p, a]);
          p = Math.max(p, b);
        }
        if (p < DAYS) gaps.push([p, DAYS]);
        for (const [a, b] of gaps) {
          svg.push(
            <rect key={`gap-${c.college_id}-${a}`} x={a * DW} y={rowY + ROW - 6} width={(b - a) * DW} height={4} rx={2} className="g-gap">
              <title>{`${c.name}: no exams ${fmt.date(addDays(t0, a))} – ${fmt.date(addDays(t0, b - 1))}`}</title>
            </rect>,
          );
        }
      }
      if (!wins.some((w) => dayIndex(w.end, t0) >= 0 && dayIndex(w.start, t0) <= DAYS)) {
        const msg = !wins.length ? (exRows.every((r) => r.status === "No Current Exams Found") ? "No exams announced" : "No confirmed dates yet") : "No exams in this period";
        svg.push(
          <text key={`pend-${c.college_id}`} x={todayX + 8} y={rowY + ROW / 2 + 4} className="g-pending">
            {msg}
          </text>,
        );
      }
      wins.forEach((w, i) => {
        if (dayIndex(w.end, t0) < 0 || dayIndex(w.start, t0) > DAYS) return;
        const cls = w.sem === "4-1" ? "s41" : "s31";
        const ly = rowY + 7 + (w.sem === "4-1" ? 15 : 0);
        const range = w.start === w.end ? fmt.date(w.start) : `${fmt.date(w.start)} – ${fmt.date(w.end)}`;
        const trustTxt = { confirmed: "", planned: " · planned, not confirmed", conflict: " · sources conflict" }[w.trust];
        const label = `${c.name}, ${w.sem}: ${w.text}, ${range}${trustTxt}.${canWrite ? " Press Enter to edit." : ""}`;
        const x1 = x(w.start);
        const x2 = w.openEnded && w.kind !== "endsem" ? x1 + DW : Math.max(x(addDays(w.end, 1)), x1 + 4);
        const edit = () => onEdit(c, w.r);
        const onKey = (e: KeyboardEvent<SVGRectElement>) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            edit();
          }
        };
        svg.push(
          <rect
            key={`bar-${c.college_id}-${i}`}
            x={x1}
            y={ly}
            width={x2 - x1}
            height={11}
            rx={3}
            tabIndex={canWrite ? 0 : undefined}
            role={canWrite ? "button" : "img"}
            aria-label={label}
            className={cx("g-bar", cls, `k-${w.kind}`, `t-${w.trust}`)}
            fill={w.kind === "lab" ? `url(#hatch-${cls}-${uid})` : undefined}
            onClick={canWrite ? edit : undefined}
            onKeyDown={canWrite ? onKey : undefined}
          >
            <title>{`${w.sem} · ${w.text}\n${range}${trustTxt}`}</title>
          </rect>,
        );
      });
      y += ROW;
    }
  }
  svg.push(<line key="today" x1={todayX} x2={todayX} y1={HEAD - 16} y2={totalH} className="g-today" />);
  const td = new Date(`${today()}T00:00:00Z`);
  svg.push(<rect key="todaypill" x={todayX - 17} y={HEAD - 21} width={34} height={16} rx={8} className="g-today-pill" />);
  svg.push(
    <text key="todaylabel" x={todayX} y={HEAD - 9.5} textAnchor="middle" className="g-today-label">
      {`${td.getUTCDate()} ${td.toLocaleDateString("en-IN", { month: "short", timeZone: "UTC" })}`}
    </text>,
  );

  const lg = (cls: string, text: string) => (
    <span key={cls}>
      <i className={cx("lg", cls)} aria-hidden="true" />
      {text}
    </span>
  );
  return (
    <div className="ex-timeline">
      <div className="ex-legend">
        {lg("lg-31", "3-1 (third year)")}
        {lg("lg-41", "4-1 (final year)")}
        {lg("lg-mid", "Mid exams")}
        {lg("lg-lab", "Labs / practicals")}
        {lg("lg-planned", "Planned — not confirmed")}
        {lg("lg-gap", "Free for outreach")}
        {lg("lg-today", "Today")}
      </div>
      <p className="adm-muted ex-hint">
        {coarse
          ? "Each college has two lanes: top 3-1, bottom 4-1. Tap a bar to see its dates and edit them. Swipe sideways for later weeks."
          : "Each college has two lanes: top 3-1, bottom 4-1. Hover a bar for dates; click it (or press Enter) to edit. Scroll sideways for later weeks."}
      </p>
      <div className="ex-gantt" tabIndex={0} role="region" aria-label="Exam timeline">
        <div className="ex-gantt-labels" style={{ width: LABEL_W }}>
          <div className="ex-gl-head" style={{ height: HEAD }}>
            <span>College</span>
            <span className="ex-gl-lanes">Year</span>
          </div>
          {labels}
        </div>
        <div className="ex-gantt-scroll">
          <svg
            className="ex-gantt-svg"
            width={W}
            height={totalH}
            viewBox={`0 0 ${W} ${totalH}`}
            role="group"
            aria-label={`Exam timeline from ${fmt.date(t0)} to ${fmt.date(addDays(t0, DAYS))}`}
          >
            <defs>
              {(["s31", "s41"] as const).map((cls) => (
                <pattern key={cls} id={`hatch-${cls}-${uid}`} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <rect width={6} height={6} className={`g-hatch-bg ${cls}`} />
                  <line x1={0} y1={0} x2={0} y2={6} className={`g-hatch ${cls}`} />
                </pattern>
              ))}
            </defs>
            {svg}
          </svg>
        </div>
      </div>
    </div>
  );
}
