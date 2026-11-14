/**
 * /colleges/exams — Exams & outreach windows (port of js/views/exams.js render).
 * GET /api/exams (district scope) + /api/meta. Filters in the URL: ?state=&district=&q=&done41=1&view=timeline|list.
 * State cards, "When can we reach final-year students?", latest official exam notices, timeline or list, edit dialog.
 */
import "@/features/colleges/styles/views/admin.css";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../lib/cache";
import { daysUntil, debounce, fmt, today } from "../lib/fmt";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { scopeRows, useDistrictScope } from "../lib/scope";
import type { PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Badge, Button, DataTable, EmptyState, ErrorCard, ListEmpty, PageHeader, Section, Skeleton, StatusBadge, WriteOnly, cx, usePortalUi, type Tone } from "../ui";
import { ExamForm, type ExamFormTarget } from "./exams/ExamForm";
import { CONF_TONE, EXAM_STATUS_LABEL, EXAM_STATUS_TONE, SourceLinks, evidenceLabel } from "./exams/labels";
import { EXAM_STATE, countdown, fourOneDone, isExamState, isPending, isoOnly, semRow, trust, type ExamCollege, type ExamRecord } from "./exams/model";
import { Timeline } from "./exams/Timeline";
import { ExamNoticesCard } from "./live/ExamNoticesCard";

const VIEW_KEY = "td.exams.view";
type View = "timeline" | "list";
const readLS = (k: string): string => {
  try {
    return localStorage.getItem(k) || "";
  } catch {
    return "";
  }
};
const writeLS = (k: string, v: string): void => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* private mode */
  }
};
const arr = (x: unknown): ExamCollege[] => (Array.isArray(x) ? (x as ExamCollege[]) : x && Array.isArray((x as { rows?: unknown }).rows) ? ((x as { rows: ExamCollege[] }).rows) : []);

/** Width of an element, kept current (the timeline's day width follows it). */
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1000));
  useLayoutEffect(() => {
    const el = ref.current;
    const measure = () => setW(el?.clientWidth || (typeof window !== "undefined" ? window.innerWidth : 1000));
    measure();
    if (typeof ResizeObserver === "undefined" || !el) {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** "When can we reach final-year students?" — open now (4-1 finished) and opening in the next 60 days. */
function OutreachPanel({ rows, districtName }: { rows: ExamCollege[]; districtName: (id: string) => string }) {
  const openNow = rows.filter(fourOneDone).sort((a, b) => a.name.localeCompare(b.name));
  const soon = rows
    .filter((c) => {
      if (fourOneDone(c) || !c.outreach_from) return false;
      const n = daysUntil(c.outreach_from);
      return n !== null && n >= 0 && n <= 60;
    })
    .sort((a, b) => String(a.outreach_from).localeCompare(String(b.outreach_from)) || a.name.localeCompare(b.name));
  return (
    <Section title="When can we reach final-year students?" sub="Final-year (4-1) students are the main audience. Outreach is easiest once their 4-1 end-sem exams are over.">
      <div className="ex-out">
        <OutCol
          title="Open now — 4-1 exams finished"
          tone="good"
          list={openNow}
          sub={(c) => (c.outreach_from ? `since ${fmt.date(c.outreach_from)}` : "")}
          emptyText="No college in this view has finished 4-1 end-sem exams yet."
          districtName={districtName}
        />
        <OutCol
          title="Opening in the next 60 days"
          tone="info"
          list={soon}
          sub={(c) => `from ${fmt.date(c.outreach_from)} (${fmt.days(c.outreach_from)})`}
          emptyText="No 4-1 end dates are published for the next 60 days in this view."
          districtName={districtName}
        />
      </div>
    </Section>
  );
}

function OutCol({
  title,
  tone,
  list,
  sub,
  emptyText,
  districtName,
}: {
  title: string;
  tone: Tone;
  list: ExamCollege[];
  sub: (c: ExamCollege) => string;
  emptyText: string;
  districtName: (id: string) => string;
}) {
  const [n, setN] = useState(5);
  return (
    <div className={cx("ex-out__col", `is-${tone}`)}>
      <h3 className="ex-out__title">
        {title}
        <span className="adm-pill td-num">{fmt.num(list.length)}</span>
      </h3>
      {list.length ? (
        <ul className="ex-out__list">
          {list.slice(0, n).map((c) => {
            const s = sub(c);
            return (
              <li key={c.college_id}>
                <Link to={portalPath.college(c.college_id)}>{c.name}</Link>
                <span className="adm-muted">{`${districtName(c.district_id)}${s ? " · " : ""}${s}`}</span>
              </li>
            );
          })}
          {list.length > n ? (
            <li>
              <Button tone="ghost" size="sm" onClick={() => setN(list.length)}>
                {`Show all ${list.length}`}
              </Button>
            </li>
          ) : null}
        </ul>
      ) : (
        <p className="adm-muted ex-out__empty">{emptyText}</p>
      )}
    </div>
  );
}

function SemCell({ c, sem, onEdit }: { c: ExamCollege; sem: string; onEdit: (c: ExamCollege, r: ExamRecord) => void }) {
  const r = semRow(c, sem);
  const edit = (
    <WriteOnly>
      <Button tone="ghost" size="sm" icon={r._missing ? "plus" : "edit"} ariaLabel={`${r._missing ? "Add" : "Edit"} ${sem} exam details for ${c.name}`} onClick={() => onEdit(c, r)}>
        {r._missing ? "Add dates" : "Edit"}
      </Button>
    </WriteOnly>
  );
  if (r._missing)
    return (
      <div className="ex-sem is-missing">
        <span className="adm-muted">Not tracked yet</span>
        {edit}
      </div>
    );
  const cd = countdown(r);
  const s = r.endsem_start;
  const e = r.endsem_end;
  const show = (v: string | null | undefined) => (isoOnly(v) ? fmt.date(v) : v ? `“${v}”` : "?");
  const tr = trust(r);
  const pending = isPending(r);
  return (
    <div className="ex-sem">
      <div className="ex-sem__top">
        <Badge tone={pending ? "neutral" : (r.status && EXAM_STATUS_TONE[r.status]) || "neutral"}>{pending ? "Dates not confirmed" : (r.status && EXAM_STATUS_LABEL[r.status]) || r.status || "—"}</Badge>
        {tr !== "confirmed" && !pending && (s || e || r.mid_window) ? <span className="ex-flag">{tr === "conflict" ? "sources conflict" : "planned"}</span> : null}
      </div>
      {s || e ? <span className="ex-sem__dates">{s && e ? `${show(s)} – ${show(e)}` : show(s || e)}</span> : null}
      <span className={cx("ex-sem__cd", `is-${cd.tone}`)}>{cd.text}</span>
      <div className="ex-sem__src">
        {r.confidence ? (
          <span
            className={cx("ex-conf", `is-${CONF_TONE[r.confidence] || "neutral"}`)}
            title={`${r.evidence ? evidenceLabel(r.evidence) : "No evidence recorded"} — ${r.confidence} confidence`}
          >{`${r.confidence} confidence`}</span>
        ) : null}
        <SourceLinks text={r.source_url} />
        {r.verified_on ? <span className="adm-muted">{`checked ${fmt.date(r.verified_on)}`}</span> : null}
      </div>
      {edit}
    </div>
  );
}

const ORDER: Record<string, number> = { in_exams: 0, exams_soon: 1, clear: 2, unknown: 3 };

function ExamList({ rows, districtName, onEdit }: { rows: ExamCollege[]; districtName: (id: string) => string; onEdit: (c: ExamCollege, r: ExamRecord) => void }) {
  return (
    <DataTable<ExamCollege>
      caption="Exam dates by college"
      rowKey={(c) => c.college_id}
      mobile="cards"
      rows={rows}
      empty="No colleges match"
      columns={[
        {
          key: "name",
          label: "College",
          primary: true,
          priority: 1,
          minWidth: 220,
          sortValue: (c) => c.name,
          render: (c) => (
            <div className="ex-col">
              <Link to={portalPath.college(c.college_id)}>{c.name}</Link>
              <span className="adm-muted">{districtName(c.district_id)}</span>
            </div>
          ),
        },
        { key: "state", label: "Right now", priority: 1, minWidth: 140, sortValue: (c) => ORDER[String(c.exam_state)] ?? 9, render: (c) => <StatusBadge kind="exam_state" value={c.exam_state} /> },
        {
          key: "s31",
          label: "3-1 (third year)",
          priority: 2,
          minWidth: 220,
          sortValue: (c) => isoOnly(semRow(c, "3-1").endsem_start) || "9999",
          render: (c) => <SemCell c={c} sem="3-1" onEdit={onEdit} />,
        },
        {
          key: "s41",
          label: "4-1 (final year)",
          priority: 1,
          minWidth: 220,
          sortValue: (c) => isoOnly(semRow(c, "4-1").endsem_start) || "9999",
          render: (c) => <SemCell c={c} sem="4-1" onEdit={onEdit} />,
        },
        {
          key: "outreach",
          label: "Final-year outreach",
          priority: 2,
          minWidth: 160,
          sortValue: (c) => (fourOneDone(c) ? "0000" : c.outreach_from || null),
          render: (c) =>
            fourOneDone(c) ? (
              <span className="ex-out-ok">Open now</span>
            ) : c.outreach_from ? (
              <span>
                {`from ${fmt.date(c.outreach_from)}`}
                <small className="adm-muted">{` ${fmt.days(c.outreach_from)}`}</small>
              </span>
            ) : (
              <span className="adm-muted">4-1 dates not known</span>
            ),
        },
      ]}
    />
  );
}

export function Exams() {
  usePortalPage({ crumbs: [{ label: "Exams" }] });
  const [query, setQuery] = useQueryState();
  const scope = useDistrictScope();
  const { canWrite, coarse } = usePortalUi();
  const [rootRef, width] = useWidth<HTMLDivElement>();
  const { data, error, loading, reload } = usePortalQuery<unknown>("exams", { scoped: true });
  const { data: meta } = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const [editing, setEditing] = useState<ExamFormTarget | null>(null);

  const rows = useMemo(() => scopeRows(arr(data)), [data]);
  const dName = useMemo(() => new Map((meta?.districts ?? []).map((d) => [d.id, d.name])), [meta]);
  const districtName = useCallback((id: string) => dName.get(id) ?? "", [dName]);

  const stateF = isExamState(query.state) ? query.state : "";
  // a district picked earlier that is no longer inside the scope would hide everything: ignore it
  const district = query.district && rows.some((c) => c.district_id === query.district) ? query.district : "";
  const done41 = query.done41 === "1";
  const qText = query.q ?? "";
  const view: View = query.view === "list" || query.view === "timeline" ? query.view : readLS(VIEW_KEY) === "list" || readLS(VIEW_KEY) === "timeline" ? (readLS(VIEW_KEY) as View) : width < 760 ? "list" : "timeline";

  const [text, setText] = useState(qText);
  useEffect(() => setText(qText), [qText]);
  const pushQ = useMemo(() => debounce((v: string) => setQuery({ q: v.trim() || null }, { history: "replace" }), 200), [setQuery]);
  useEffect(() => () => pushQ.cancel(), [pushQ]);

  const clearAll = () => {
    pushQ.cancel();
    setText("");
    setQuery({ district: null, state: null, q: null, done41: null }, { history: "auto" });
  };

  const match = (c: ExamCollege, skipState: boolean) => {
    const q = qText.trim().toLowerCase();
    return (
      (!district || c.district_id === district) &&
      (skipState || !stateF || c.exam_state === stateF) &&
      (!q || `${c.name} ${c.short_name ?? ""}`.toLowerCase().includes(q)) &&
      (!done41 || fourOneDone(c))
    );
  };
  const base = rows.filter((c) => match(c, true));
  const shown = base.filter((c) => match(c, false));
  const counts: Record<string, number> = { in_exams: 0, exams_soon: 0, clear: 0, unknown: 0 };
  for (const c of base) if (c.exam_state) counts[c.exam_state] = (counts[c.exam_state] ?? 0) + 1;
  const active = !!(district || stateF || qText || done41);
  const districts = [...(meta?.districts ?? [])].filter((d) => rows.some((c) => c.district_id === d.id)).sort((a, b) => a.name.localeCompare(b.name));

  const onEdit = useCallback((c: ExamCollege, r: ExamRecord) => setEditing({ college: { college_id: c.college_id, name: c.name }, row: r }), []);

  const head = (
    <PageHeader
      title="Exams & outreach windows"
      sub="Which colleges are writing exams, and when final-year students are free to meet us. Only published notices or academic calendars count; planned dates are marked."
      actions={
        <p className="adm-asof">
          As of <strong>{fmt.date(today())}</strong>
        </p>
      }
      scope
    />
  );

  let body;
  if (error && !data) {
    body = <ErrorCard title="Could not load the exam calendar" error={error} retry={() => void reload()} />;
  } else if (loading || data === undefined) {
    body = (
      <>
        <Skeleton lines={2} />
        <Skeleton lines={6} />
      </>
    );
  } else if (!rows.length) {
    body = (
      <EmptyState
        icon="exam"
        title={scope.all ? "No exam information yet" : "No colleges in the selected districts"}
        text={
          scope.all
            ? "Exam dates come from the research files; ask an admin to re-import them. You can also add dates for one college from its page."
            : "Widen the district selection at the top of the page to see more colleges."
        }
      />
    );
  } else {
    body = (
      <>
        <div className="adm-states" role="group" aria-label="Filter by exam state">
          {Object.entries(EXAM_STATE).map(([k, s]) => (
            <button
              key={k}
              type="button"
              className={cx("adm-state", `is-${s.tone}`, stateF === k && "is-on")}
              aria-pressed={stateF === k}
              title={s.help}
              onClick={() => setQuery({ state: stateF === k ? null : k }, { history: "auto" })}
            >
              <span className="adm-state__dot" aria-hidden="true" />
              <span className="adm-state__label">{s.label}</span>
              <strong className="adm-state__n td-num">{fmt.num(counts[k] ?? 0)}</strong>
            </button>
          ))}
        </div>
        <OutreachPanel rows={base} districtName={districtName} />
        <ExamNoticesCard />
        <div className="adm-toolbar">
          <div className="adm-toolbar__filters">
            <input
              type="search"
              className="td-input"
              placeholder="Search college…"
              aria-label="Search college"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                pushQ(e.target.value);
              }}
            />
            <select className="td-input td-select" aria-label="District" value={district} onChange={(e) => setQuery({ district: e.target.value || null }, { history: "auto" })}>
              <option value="">{scope.all ? "All districts" : "All selected districts"}</option>
              {districts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <label className="adm-toggle">
              <input type="checkbox" className="td-check" checked={done41} onChange={(e) => setQuery({ done41: e.target.checked ? "1" : null }, { history: "auto" })} />
              <span>Only colleges that finished 4-1</span>
            </label>
          </div>
          <div className="adm-toolbar__end">
            <span className="adm-count" aria-live="polite">{`${fmt.num(shown.length)} of ${fmt.num(rows.length)} colleges`}</span>
            {active ? (
              <Button tone="ghost" size="sm" icon="close" onClick={clearAll}>
                Clear filters
              </Button>
            ) : null}
            <div className="adm-seg" role="group" aria-label="Layout">
              {(
                [
                  ["timeline", "Timeline"],
                  ["list", "List"],
                ] as const
              ).map(([id, l]) => (
                <button
                  key={id}
                  type="button"
                  className={cx("adm-seg__btn", view === id && "is-on")}
                  aria-pressed={view === id}
                  onClick={() => {
                    writeLS(VIEW_KEY, id);
                    setQuery({ view: id }, { history: "auto" });
                  }}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="ex-body">
          {!shown.length ? (
            <ListEmpty filtered noun="colleges" text="Clear a filter or search for another name." onClear={clearAll} />
          ) : view === "timeline" ? (
            <Timeline rows={shown} districtName={districtName} width={width} coarse={coarse} canWrite={canWrite} onEdit={onEdit} />
          ) : (
            <ExamList rows={shown} districtName={districtName} onEdit={onEdit} />
          )}
        </div>
      </>
    );
  }

  return (
    <div className="v-adm v-adm-exams" ref={rootRef}>
      {head}
      {body}
      <ExamForm target={editing} onClose={() => setEditing(null)} />
    </div>
  );
}
