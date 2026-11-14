/**
 * Calls & follow-ups › Call queue (/colleges/calls) — port of js/views/calls.js `render`.
 * A prioritised list of colleges to call: number to call, last outcome, call-back date and a fast "Log call".
 * Priority only orders this list; every number comes from GET /api/calls/queue (scoped by district).
 * URL: ?filter=&sort=&dir=&q=&page= (same keys as before). The section tabs are drawn by the shell.
 */
import "@/features/colleges/styles/views/calls.css";
import "@/features/colleges/styles/views/ops.css";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { CallStatusBadge, ContactStatusBadge, OutcomeBadge, TelLink, addContact, contactLabel, logCall } from "../forms";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { queryInt, useQueryState } from "../lib/query";
import { portalPath, toPortalHref } from "../lib/routes";
import { scopeRows } from "../lib/scope";
import type { Contact } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Badge, Chip, DataTable, EmptyState, Icon, Kpi, KpiRow, PageHeader, Provenance, StatusBadge, cx, type Column } from "../ui";

/** [server filter key, chip label]. Keys are the API's (GET /api/calls/queue?filter=); only the wording is ours. */
export const QUEUE_FILTERS: [string, string][] = [
  ["all", "All colleges"],
  ["pending", "To call"],
  ["high", "High priority"],
  ["working", "Has a working number"],
  ["interested", "Spoke to them"],
  ["confirmed", "College agreed"],
  ["invalid", "Has a bad number"],
];
const EMPTY: Record<string, [string, string]> = {
  all: ["No colleges match", "Clear the search, or widen the district scope at the top of the page."],
  working: ["No working numbers yet", "A number becomes “working” after a logged call where someone answered. Start with “All colleges” and log each call."],
  high: ["No high-priority colleges here", "High priority needs many eligible students, a number to call and no exams soon. Add contacts to move colleges up the list."],
  pending: ["Nothing to call", "Every college in view has been reached and has no call-back due."],
  invalid: ["No bad numbers", "Colleges with a wrong, out-of-service or unreachable number appear here so someone can find a new one."],
  interested: ["No conversations yet", "Colleges move here after a call where someone answered."],
  confirmed: ["No college has agreed yet", "Tick “The college agreed to take part” when logging a call, or record confirmed enrollments."],
};
/** column key → server sort and its natural direction */
const SORTS: Record<string, [string, "asc" | "desc"]> = { priority: ["priority", "desc"], next_action: ["next_action", "asc"], last_call: ["last_call", "desc"], name: ["name", "asc"] };
const SORT_LABEL: Record<string, string> = { priority: "highest priority first", next_action: "by call-back date", last_call: "by last call", name: "by name" };
const PAGE = 25;

interface PriorityPart {
  key?: string;
  label: string;
  points: number;
  max: number;
  detail: string;
  estimated?: boolean;
  basis?: string;
}
export interface QueueRow {
  college_id: string;
  name: string;
  short_name?: string | null;
  href?: string | null;
  city_name?: string | null;
  district_name?: string | null;
  district_id?: string;
  call_status?: string | null;
  op_status?: string | null;
  exam_state?: string | null;
  best_contact?: (Contact & { source_url?: string | null }) | null;
  contact_counts?: { total?: number; working?: number; untested?: number; non_working?: number; invalid?: number };
  last_call?: { outcome: string; called_at: string; caller?: string | null } | null;
  calls_total?: number;
  next_action?: { due_date?: string | null; overdue?: boolean; due?: boolean } | null;
  priority?: { score: number; tier: "high" | "medium" | "low"; parts?: PriorityPart[] } | null;
  [k: string]: unknown;
}
interface QueueAnswer {
  rows: QueueRow[];
  counts?: Record<string, number>;
  districts_filter?: string[];
}
interface TargetDashboard {
  calls?: { today?: number; last_7d?: number };
  contacts?: { working?: number; untested?: number; non_working?: number; invalid?: number };
  pending_calls?: { callbacks_due?: number; callbacks_scheduled?: number; never_called?: number };
}

export function CallQueue() {
  const [q, setQuery] = useQueryState();
  const filter = QUEUE_FILTERS.some(([k]) => k === q.filter) ? q.filter! : "all";
  const sort = SORTS[q.sort ?? ""] ? q.sort! : "priority";
  const dir = q.dir === "asc" || q.dir === "desc" ? q.dir : null;
  const search = q.q ?? "";
  const page = queryInt(q.page);
  usePortalPage({ title: "Call queue", crumbs: [{ label: "Calls & follow-ups", to: portalPath.calls }, { label: "Call queue" }] });

  const { data, error, loading, reload } = usePortalQuery<QueueAnswer>("calls/queue", {
    scoped: true,
    query: { filter, sort: SORTS[sort]![0], q: search || undefined, limit: 1000 },
    keepPrevious: true,
  });
  const td = usePortalQuery<TargetDashboard>("target-dashboard", { scoped: true, query: { scope: "state" } });

  // servers that ignore `districts=`: filter rows here (counts would then cover every district, so they are hidden)
  const { rows, exactCounts } = useMemo(() => {
    const all = data?.rows ?? [];
    const kept = scopeRows(all as Record<string, unknown>[]) as QueueRow[];
    const out = dir && dir !== SORTS[sort]![1] ? [...kept].reverse() : kept;
    return { rows: out, exactCounts: kept.length === all.length || Array.isArray(data?.districts_filter) };
  }, [data, dir, sort]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const cur = Math.min(page, pages);
  const slice = rows.slice((cur - 1) * PAGE, cur * PAGE);

  const set = (patch: Record<string, string | number | null>) => setQuery(patch, { history: "auto" });
  const setFilter = (k: string) => k !== filter && set({ filter: k === "all" ? null : k, page: null });

  const columns: Column<QueueRow>[] = [
    {
      key: "name",
      label: "College",
      primary: true,
      priority: 1,
      minWidth: 340,
      render: (r) => (
        <div className="vcq-name">
          <Link to={r.href ? toPortalHref(r.href) : portalPath.college(r.college_id)}>{r.short_name || r.name}</Link>
          <span className="opk-muted vx-small">
            {[r.short_name && r.short_name !== r.name ? r.name : null, [r.city_name, r.district_name].filter(Boolean).join(", ")].filter(Boolean).join(" · ")}
          </span>
          <span className="vcq-badges">
            <CallStatusBadge status={r.call_status} />
            {r.op_status !== "operational" ? <StatusBadge kind="op_status" value={r.op_status} /> : null}
            {r.exam_state === "in_exams" || r.exam_state === "exams_soon" ? <StatusBadge kind="exam_state" value={r.exam_state} /> : null}
          </span>
        </div>
      ),
    },
    { key: "contact", label: "Number to call", sortable: false, priority: 1, minWidth: 230, render: (r) => <ContactCell r={r} /> },
    {
      key: "last_call",
      label: "Last call",
      priority: 2,
      minWidth: 160,
      render: (r) =>
        r.last_call ? (
          <div className="vcq-last">
            <OutcomeBadge outcome={r.last_call.outcome} />{" "}
            <span className="opk-muted vx-small">
              {`${fmt.date(r.last_call.called_at)}${r.last_call.caller ? ` · ${r.last_call.caller}` : ""}${(r.calls_total ?? 0) > 1 ? ` · ${fmt.plural(r.calls_total, "call")}` : ""}`}
            </span>
          </div>
        ) : (
          <span className="opk-muted">Not called yet</span>
        ),
    },
    { key: "next_action", label: "Call back on", priority: 2, minWidth: 150, render: (r) => <NextCell next={r.next_action} /> },
    { key: "priority", label: "Priority", priority: 3, minWidth: 150, render: (r) => <WhyPopover p={r.priority} /> },
  ];

  const afterSave = () => {
    void reload();
    void td.reload();
  };

  const t = td.data;
  const c = t?.calls;
  const k = t?.contacts ?? {};
  const p = t?.pending_calls ?? {};

  return (
    <div className="v-ops v-calls">
      <PageHeader title="Call queue" eyebrow="Calls & follow-ups" sub="Call the colleges most likely to bring students first, log every call, and set a call-back date." scope />
      <div className="vcq-kpis" aria-live="polite">
        {c ? (
          <KpiRow>
            <Kpi label="Calls today" value={fmt.num(c.today)} sub={`${fmt.num(c.last_7d)} in the last 7 days`} icon="phone" />
            <Kpi
              label="Call-backs due"
              value={fmt.num(p.callbacks_due)}
              sub={`${fmt.num(p.callbacks_scheduled)} scheduled later`}
              tone={p.callbacks_due ? "warn" : undefined}
              icon="clock"
              to={`${portalPath.followups}?tab=overdue`}
            />
            <Kpi label="Colleges not called yet" value={fmt.num(p.never_called)} sub="operating colleges only" icon="college" onClick={() => setFilter("pending")} />
            <Kpi
              label="Working numbers"
              value={fmt.num(k.working)}
              sub={`${fmt.num(k.untested)} not tried yet · ${fmt.num((k.non_working || 0) + (k.invalid || 0))} not working`}
              icon="check"
              tone={k.working ? "good" : undefined}
            />
          </KpiRow>
        ) : null}
      </div>
      <div className="vcq-toolbar">
        <SearchBox value={search} onChange={(v) => setQuery({ q: v || null, page: null })} />
        <div className="vcq-chips" role="toolbar" aria-label="Show">
          {QUEUE_FILTERS.map(([key, l]) => (
            <Chip key={key} label={exactCounts && data ? `${l} (${fmt.num(data.counts?.[key] ?? 0)})` : l} active={filter === key} tone={filter === key ? "brand" : "neutral"} onClick={() => setFilter(key)} />
          ))}
        </div>
      </div>
      <p className="vcq-note opk-muted" aria-live="polite">
        {rows.length ? `${fmt.plural(rows.length, "college")} · ${SORT_LABEL[sort]}${search ? ` · matching “${search}”` : ""}` : ""}
      </p>
      <DataTable<QueueRow>
        caption="Colleges to call"
        columns={columns}
        rows={data ? slice : undefined}
        rowKey={(r) => r.college_id}
        loading={loading && !data}
        error={data ? null : error}
        onRetry={() => void reload()}
        sort={{ key: sort, dir: (dir ?? SORTS[sort]![1]) as "asc" | "desc" }}
        onSort={(key, d) => {
          if (!SORTS[key]) return;
          set({ sort: key === "priority" ? null : key, dir: d && d !== SORTS[key]![1] ? d : null, page: null });
        }}
        page={cur}
        pageSize={PAGE}
        total={rows.length}
        pageLabel="colleges"
        onPage={(n) => set({ page: n > 1 ? n : null })}
        rowActions={(r) => [
          { label: "Log call", icon: "phone", tone: "primary", writeOnly: true, onClick: () => void logCall({ college_id: r.college_id, college_label: r.short_name || r.name, onSaved: afterSave }) },
          { label: "Add contact", icon: "plus", writeOnly: true, onClick: () => void addContact({ college_id: r.college_id, onSaved: afterSave }) },
        ]}
        empty={<EmptyState icon="phone" title={EMPTY[filter]![0]} text={EMPTY[filter]![1]} />}
        mobile="cards"
      />
    </div>
  );
}

/** Search box: types freely, updates the URL after 250 ms (replace, no Back step). */
function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text.trim() === value) return;
    const t = setTimeout(() => onChange(text.trim()), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return (
    <label className="vcq-searchwrap">
      <Icon name="search" size={16} />
      <input type="search" className="td-input vcq-search" placeholder="Search college, town or district" aria-label="Search colleges" enterKeyHint="search" value={text} onChange={(e) => setText(e.target.value)} />
    </label>
  );
}

function NextCell({ next }: { next: QueueRow["next_action"] }) {
  if (!next?.due_date) return <span className="opk-muted">No call-back set</span>;
  return (
    <span className={cx("vcq-next", next.overdue && "is-overdue", next.due && !next.overdue && "is-due")}>
      <Icon name="clock" size={14} />
      <span>
        {next.overdue ? "Overdue · " : next.due ? "Today · " : ""}
        {fmt.date(next.due_date)}
      </span>
    </span>
  );
}

function ContactCell({ r }: { r: QueueRow }) {
  const k = r.best_contact;
  const cc = r.contact_counts ?? {};
  if (!k) {
    return <span className="opk-muted vx-small">{cc.total ? `No working number (${fmt.plural((cc.non_working || 0) + (cc.invalid || 0), "bad number")})` : "No contact yet"}</span>;
  }
  return (
    <div className="vcq-contact">
      <div className="vcq-reach">
        {k.phone ? <TelLink phone={k.phone} /> : null}
        {k.email ? (
          <a href={`mailto:${k.email}`} className="vx-tel" title={k.email} aria-label={`Email ${k.email}`}>
            <Icon name="mail" size={16} />
            {k.phone ? null : <span>{k.email}</span>}
          </a>
        ) : null}
      </div>
      <span className="vx-small">
        {contactLabel(k)} <ContactStatusBadge status={k.status} />
        {k.basis === "verified" ? (
          <>
            {" "}
            <Provenance basis="verified" />
          </>
        ) : null}
      </span>
    </div>
  );
}

function WhyPopover({ p }: { p: QueueRow["priority"] }) {
  if (!p) return <span className="opk-muted">—</span>;
  const tone = p.tier === "high" ? "brand" : p.tier === "medium" ? "info" : "neutral";
  const tier = p.tier === "high" ? "High" : p.tier === "medium" ? "Medium" : "Low";
  return (
    <details className="vcq-why">
      <summary aria-label={`Priority ${p.score} of 100, ${p.tier}. Show why`}>
        <Badge tone={tone}>{`${tier} · ${p.score}`}</Badge>
        <span className="vcq-why-q">Why?</span>
      </summary>
      <div className="vcq-why-pop" role="note">
        <strong>{`Priority ${p.score} / 100`}</strong>
        <ul>
          {(p.parts ?? []).map((x, i) => (
            <li key={x.key ?? i}>
              <span className="vcq-why-k">{x.label}</span>
              <span className="vcq-why-pts td-num">{`${x.points}/${x.max}`}</span>
              <span className="vcq-why-d">
                {x.detail}
                {x.estimated ? (
                  <>
                    {" "}
                    <Provenance basis="estimated" />
                  </>
                ) : null}
                {x.basis === "pending" ? (
                  <>
                    {" "}
                    <Provenance basis="pending" />
                  </>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
        <p className="opk-muted vx-small">High is 60 or more, medium 40–59. It only decides the order of this list.</p>
      </div>
    </details>
  );
}
