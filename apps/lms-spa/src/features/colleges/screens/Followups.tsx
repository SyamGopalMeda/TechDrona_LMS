/**
 * Calls & follow-ups › Follow-ups (/colleges/followups) — port of js/views/followups.js `render`.
 * Tabs Overdue / Today / Next 14 days / All open / Done, search + "Assigned to" + "Reason" filters, bulk
 * mark-done / reschedule, row actions (Done, Reschedule; Reopen, Edit on Done), row click edits, and
 * "Targeted colleges with nothing scheduled". URL: ?tab=&q=&owner=&issue=&sort=&dir=&page= (same keys as before).
 * Respects the district scope (GET /api/followups?districts=…). The create / edit form lives in forms/Followup.tsx.
 */
import "@/features/colleges/styles/views/ops.css";
import "@/features/colleges/styles/views/calls.css";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { ISSUES, ReasonBadge, isCallBack, markFollowupDone, openFollowupForm, reasonOf, reopenFollowup, rescheduleFollowup, rescheduleFollowups, patchFollowups, addDays, rowsOf, type FollowupRow } from "../forms";
import { usePortalQuery } from "../lib/cache";
import { daysUntil, fmt, today } from "../lib/fmt";
import { queryInt, useQueryState } from "../lib/query";
import { portalPath, toPortalHref } from "../lib/routes";
import { scopeRows } from "../lib/scope";
import type { CollegeRow, Followup, Person, PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Badge, Button, DataTable, EmptyState, ErrorCard, FilterBar, Kpi, KpiRow, PageHeader, Section, Segmented, Skeleton, StatusChip, WriteOnly, confirm, type Column } from "../ui";

export const FOLLOWUP_TABS: [string, string][] = [
  ["overdue", "Overdue"],
  ["today", "Today"],
  ["fortnight", "Next 14 days"],
  ["open", "All open"],
  ["done", "Done"],
];
const SCOPE_LABEL: Record<string, string> = { college: "College", branch: "Branch", person: "Team member" };
const PAGE = 25;

type Bucket = "done" | "open" | "overdue" | "today" | "fortnight";
export type FuItem = FollowupRow & {
  _scope: { label: string; href: string | null; college?: CollegeRow };
  _bucket: Bucket;
  district_id?: string | null;
  college_id?: string | null;
  is_demo?: number | boolean;
};

type Lists = Record<"overdue" | "today" | "fortnight" | "open" | "done", FuItem[]>;

export function bucketOf(r: Pick<Followup, "status" | "due_date">): Bucket {
  if (r.status === "done") return "done";
  const d = daysUntil(r.due_date);
  if (d === null) return "open";
  if (d < 0) return "overdue";
  if (d === 0) return "today";
  if (d <= 14) return "fortnight";
  return "open";
}

/** GET a list in full (a paged answer {items,total} is fetched again with page_size = total). */
function useAll<T>(path: string, opts: { scoped?: boolean; query?: Record<string, string | number> } = {}) {
  const first = usePortalQuery<unknown>(path, { scoped: opts.scoped, query: opts.query });
  const o = first.data as { items?: unknown[]; total?: number } | undefined;
  const paged = !!o && !Array.isArray(o) && Array.isArray(o.items) && Number(o.total) > o.items.length;
  const full = usePortalQuery<unknown>(paged ? path : null, { scoped: opts.scoped, query: { ...opts.query, page: 1, page_size: Math.min(Number(o?.total ?? 0), 5000) } });
  const data = useMemo(() => (paged ? (full.data === undefined ? undefined : rowsOf<T>(full.data)) : first.data === undefined ? undefined : rowsOf<T>(first.data)), [paged, first.data, full.data]);
  return { data, error: first.error ?? full.error, loading: first.loading || (paged && full.loading), reload: () => Promise.all([first.reload(), paged ? full.reload() : null]).then(() => undefined) };
}

export function Followups() {
  const [q, setQuery] = useQueryState();
  usePortalPage({ title: "Follow-ups", crumbs: [{ label: "Calls & follow-ups", to: portalPath.calls }, { label: "Follow-ups" }] });
  const fu = useAll<Followup>("followups", { scoped: true });
  const cols = useAll<CollegeRow>("colleges", { scoped: true });
  const ppl = useAll<Person>("people", { query: { page_size: 1000 } });
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });

  const search = q.q ?? "";
  const owner = q.owner ?? "";
  const issue = ISSUES[q.issue ?? ""] || q.issue === "callback" ? q.issue! : "";
  const sort = q.sort || "due_date";
  const dir = q.dir === "desc" ? "desc" : "asc";
  const page = queryInt(q.page);
  const [selKey, setSelKey] = useState(0);
  const [sel, setSel] = useState<number[]>([]);

  const data = useMemo(() => {
    if (!fu.data) return null;
    // old servers ignore districts=: filter here (a follow-up without a district — e.g. a deleted record — stays visible)
    const all = scopeRows(fu.data as unknown as Record<string, unknown>[]) as unknown as Followup[];
    const colleges = scopeRows((cols.data ?? []) as unknown as Record<string, unknown>[]) as unknown as CollegeRow[];
    const people = ppl.data ?? [];
    const colMap = new Map(colleges.map((c) => [String(c.id), c]));
    const peopleMap = new Map(people.map((p) => [String(p.id), p]));
    const districtName = new Map((meta.data?.districts ?? []).map((d) => [d.id, d.name]));
    const items: FuItem[] = all.map((r) => ({ ...r, _scope: scopeInfo(r, colMap, peopleMap), _bucket: bucketOf(r) }));
    return { items, colleges, people, peopleMap, districtName };
  }, [fu.data, cols.data, ppl.data, meta.data]);

  const ownerName = (r: Followup) => r.owner_name || data?.peopleMap.get(String(r.owner_person_id))?.full_name || "";

  const lists = useMemo((): Lists => {
    const empty: Lists = { overdue: [], today: [], fortnight: [], open: [], done: [] };
    if (!data) return empty;
    const words = search.toLowerCase().split(/\s+/).filter(Boolean);
    const items = data.items.filter((r) => {
      const c = r._scope.college;
      if (owner && (ownerName(r) || "__none") !== owner) return false;
      // 'callback' is a view-only reason (call-backs are stored as 'other'); 'other' then means the remaining general items
      if (issue === "callback" ? !isCallBack(r) : issue && ((r.issue || "other") !== issue || (issue === "other" && isCallBack(r)))) return false;
      if (words.length) {
        const hay = [r.title, r.notes, r._scope.label, c?.name, c?.short_name, ownerName(r), reasonOf(r)[0]].filter(Boolean).join(" ").toLowerCase();
        if (!words.every((w) => hay.includes(w))) return false;
      }
      return true;
    });
    const open = items.filter((r) => r.status !== "done");
    return {
      overdue: open.filter((r) => r._bucket === "overdue"),
      today: open.filter((r) => r._bucket === "today"),
      fortnight: open.filter((r) => r._bucket === "today" || r._bucket === "fortnight"),
      open,
      done: items.filter((r) => r.status === "done"),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, search, owner, issue]);

  const tab = FOLLOWUP_TABS.some(([k]) => k === q.tab) ? q.tab! : lists.overdue.length ? "overdue" : lists.today.length ? "today" : lists.fortnight.length ? "fortnight" : "open";
  const done = tab === "done";

  const sorted = useMemo(() => {
    const f: Record<string, (r: FuItem) => string> = {
      due_date: (r) => (done ? String(r.done_at || "") : String(r.due_date || "9999")),
      title: (r) => String(r.title || "").toLowerCase(),
      about: (r) => String(r._scope.label || "").toLowerCase(),
      issue: (r) => reasonOf(r)[0],
      owner: (r) => (ownerName(r) || "~").toLowerCase(),
      last_contact: (r) => String(r.last_contact || ""),
    };
    const key = f[sort] ? sort : "due_date";
    const get = f[key]!;
    // Done tab: newest first by default
    const d = (key === "due_date" && done ? -1 : 1) * (dir === "desc" ? -1 : 1);
    return [...(lists[tab as keyof Lists] ?? [])].sort((a, b) => (get(a) < get(b) ? -1 : get(a) > get(b) ? 1 : 0) * d || a.id - b.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lists, tab, sort, dir, done]);

  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const cur = Math.min(page, pages);
  const slice = sorted.slice((cur - 1) * PAGE, cur * PAGE);

  const clearSel = () => {
    setSel([]);
    setSelKey((k) => k + 1);
  };
  const set = (patch: Record<string, string | number | null>, history: "auto" | "replace" = "auto") => {
    clearSel();
    setQuery(patch, { history });
  };
  const setTab = (id: string) => set({ tab: id, page: null });
  const reload = () => {
    void fu.reload();
  };
  const formData = data ? { colleges: data.colleges, people: data.people } : undefined;
  const edit = (r: FuItem) => void openFollowupForm({ data: formData, row: r, onSaved: reload });

  if (!data) {
    return (
      <div className="v-ops v-followups">
        <Head onNew={null} />
        {fu.error ? <ErrorCard title="Could not load follow-ups" error={fu.error} retry={() => void fu.reload()} /> : <Skeleton lines={4} />}
      </div>
    );
  }

  const weekAgo = addDays(today(), -6);
  const doneThisWeek = lists.done.filter((r) => r.done_at && String(r.done_at).slice(0, 10) >= weekAgo).length;
  const filtered = !!(search || owner || issue);
  const ownerOpts = (() => {
    const names = [...new Set(data.items.filter((r) => r.status !== "done").map((r) => ownerName(r)).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    if (owner && owner !== "__none" && !names.includes(owner)) names.push(owner);
    return [{ value: "__none", label: "Not assigned" }, ...names.map((n) => ({ value: n, label: n }))];
  })();
  const msgs: [string, string] = filtered
    ? ["No follow-ups match these filters", "Clear the search, “Assigned to” or “Reason” filter to see more."]
    : ({
        overdue: ["Nothing overdue", "Every open follow-up is on schedule."],
        today: ["Nothing due today", "Check “Next 14 days”, or add a new follow-up."],
        fortnight: ["Nothing due in the next 14 days", "Schedule check-ins for targeted colleges from the list below."],
        open: ["No open follow-ups", "Use “New follow-up”, or log a call with a call-back date."],
        done: ["Nothing completed yet", "Items you mark done appear here."],
      }[tab] as [string, string]);

  const columns: (Column<FuItem> | null)[] = [
    { key: "due_date", label: done ? "Done on" : "Due", priority: 1, minWidth: 130, render: (r) => <DueCell r={r} /> },
    {
      key: "title",
      label: "What",
      primary: true,
      priority: 1,
      minWidth: 300,
      render: (r) => (
        <div className="fu-what">
          <strong>{r.title || reasonOf(r)[0] || "Follow-up"}</strong>
          {r.notes ? (
            <span className="fu-notes opk-muted" title={r.notes}>
              {r.notes.length > 110 ? `${r.notes.slice(0, 110)}…` : r.notes}
            </span>
          ) : null}
          {r.is_demo ? <Badge tone="bad">DEMO</Badge> : null}
        </div>
      ),
    },
    {
      key: "about",
      label: "About",
      priority: 2,
      minWidth: 200,
      render: (r) => (
        <div className="fu-about-cell">
          {r._scope.href ? (
            <Link to={r._scope.href} onClick={(e) => e.stopPropagation()}>
              {r._scope.label}
            </Link>
          ) : (
            <span>{r._scope.label}</span>
          )}
          <span className="opk-muted vx-small">
            {SCOPE_LABEL[r.scope_type] || r.scope_type}
            {r.scope_type !== "college" && r._scope.college ? ` · ${r._scope.college.short_name || r._scope.college.name}` : ""}
            {r.district_id && data.districtName.get(r.district_id) ? ` · ${data.districtName.get(r.district_id)}` : ""}
          </span>
        </div>
      ),
    },
    { key: "issue", label: "Reason", priority: 3, minWidth: 130, render: (r) => <ReasonBadge row={r} /> },
    { key: "owner", label: "Assigned to", priority: 2, minWidth: 140, render: (r) => ownerName(r) || <em className="opk-muted">Not assigned</em> },
    // on the Done tab this is the day it was marked done (same as "Done on"), so the column is left out there
    done
      ? null
      : {
          key: "last_contact",
          label: "Last spoke to them",
          priority: 3,
          minWidth: 140,
          hideOnPhone: true,
          render: (r) =>
            r.last_contact ? (
              <span>
                {fmt.date(r.last_contact)}
                <small className="opk-muted">{` ${fmt.days(r.last_contact)}`}</small>
              </span>
            ) : (
              <span className="opk-muted">—</span>
            ),
        },
  ];

  const bulkDone = async (ids: number[]) => {
    const ok = await confirm({
      title: `Mark ${ids.length} follow-up${ids.length === 1 ? "" : "s"} done?`,
      text: "Today is saved as the day you last spoke to them. No next follow-ups are scheduled; use “Done” on a single item to schedule the next step.",
      confirmLabel: "Mark done",
      tone: "primary",
    });
    if (!ok) return;
    await patchFollowups(ids, { status: "done", last_contact: today() }, "marked done");
    clearSel();
    reload();
  };

  return (
    <div className="v-ops v-followups">
      <div className="fu-root">
        <Head onNew={() => void openFollowupForm({ data: formData, onSaved: reload })} />
        <div className="fu-kpis">
          <KpiRow>
            <Kpi label="Overdue" value={fmt.num(lists.overdue.length)} tone={lists.overdue.length ? "bad" : "good"} icon="warn" sub={lists.overdue.length ? "past their due date" : "all on schedule"} onClick={() => setTab("overdue")} />
            <Kpi label="Due today" value={fmt.num(lists.today.length)} tone={lists.today.length ? "info" : undefined} icon="clock" sub={fmt.date(today())} onClick={() => setTab("today")} />
            <Kpi label="Next 14 days" value={fmt.num(lists.fortnight.length)} icon="followup" sub={`until ${fmt.date(addDays(today(), 14))}`} onClick={() => setTab("fortnight")} />
            <Kpi label="Done this week" value={fmt.num(doneThisWeek)} tone="good" icon="check" sub="last 7 days" onClick={() => setTab("done")} />
          </KpiRow>
        </div>
        <div className="fu-tabbar">
          <Segmented ariaLabel="Which follow-ups" value={tab} onChange={setTab} options={FOLLOWUP_TABS.map(([value, label]) => ({ value, label, count: lists[value as keyof Lists].length }))} />
        </div>
        <div className="fu-filters">
          <FilterBar
            values={{ q: search, owner, issue }}
            search={{ key: "q", placeholder: "Search title, college, person, notes" }}
            filters={[
              { key: "owner", label: "Assigned to", type: "select", options: ownerOpts, allLabel: "Anyone" },
              { key: "issue", label: "Reason", type: "select", options: [{ value: "callback", label: "Call-back" }, ...Object.entries(ISSUES).map(([value, [label]]) => ({ value, label }))], allLabel: "All reasons" },
            ]}
            onChange={(v, changed) => set({ q: String(v.q ?? "").trim() || null, owner: (v.owner as string) || null, issue: (v.issue as string) || null, page: null }, changed === "q" ? "replace" : "auto")}
          />
        </div>
        {sel.length ? (
          <div className="fu-bulk" role="region" aria-label="Bulk actions">
            <strong className="fu-bulk-n">{`${fmt.num(sel.length)} selected`}</strong>
            <div className="fu-bulk-actions">
              <Button icon="check" tone="primary" size="sm" onClick={() => void bulkDone(sel)}>
                Mark done
              </Button>
              <Button icon="clock" size="sm" onClick={() => void rescheduleFollowups(sel, { onSaved: () => (clearSel(), reload()) })}>
                Reschedule…
              </Button>
              <Button tone="ghost" size="sm" onClick={clearSel}>
                Clear selection
              </Button>
            </div>
          </div>
        ) : null}
        <p className="fu-note opk-muted" aria-live="polite">
          {sorted.length ? `${fmt.plural(sorted.length, "follow-up")} · ${(FOLLOWUP_TABS.find(([k]) => k === tab)?.[1] ?? "").toLowerCase()}` : ""}
        </p>
        <DataTable<FuItem>
          clearSelectionKey={`${tab}|${selKey}`}
          caption="Follow-ups"
          columns={columns}
          rows={slice}
          rowKey={(r) => r.id}
          sort={{ key: sort, dir }}
          onSort={(key, d) => set({ sort: key === "due_date" ? null : key, dir: d === "desc" ? "desc" : null, page: null })}
          page={cur}
          pageSize={PAGE}
          total={sorted.length}
          pageLabel="follow-ups"
          onPage={(n) => set({ page: n > 1 ? n : null })}
          selectable={!done}
          onSelect={(rows) => setSel(rows.map((r) => r.id))}
          rowActions={(r) =>
            r.status === "done"
              ? [
                  { label: "Reopen", icon: "refresh", writeOnly: true, onClick: () => void reopenFollowup(r).then((ok) => ok && reload()) },
                  { label: "Edit", icon: "edit", writeOnly: true, onClick: () => edit(r) },
                ]
              : [
                  { label: "Done", icon: "check", tone: "primary", writeOnly: true, onClick: () => void markFollowupDone(r, { onSaved: reload }) },
                  { label: "Reschedule", icon: "clock", writeOnly: true, onClick: () => void rescheduleFollowup(r, { onSaved: reload }) },
                ]
          }
          // the whole row opens the edit form (title, due date, assigned to, notes, delete)
          onRowClick={edit}
          empty={
            <EmptyState
              icon={filtered ? "filter" : tab === "overdue" ? "check" : "followup"}
              title={msgs[0]}
              text={msgs[1]}
              actions={filtered ? [{ label: "Clear filters", icon: "close", tone: "secondary", onClick: () => set({ q: null, owner: null, issue: null, page: null }) }] : []}
            />
          }
          mobile="cards"
        />
        <div className="fu-unsched-host">
          <Unscheduled items={data.items} colleges={data.colleges} districtName={data.districtName} formData={formData} onSaved={reload} />
        </div>
      </div>
    </div>
  );
}

function Head({ onNew }: { onNew: (() => void) | null }) {
  return (
    <PageHeader
      title="Follow-ups"
      eyebrow="Calls & follow-ups"
      sub="Call-backs and to-dos for colleges, branches and team members. Overdue items are highlighted."
      scope
      actions={
        onNew ? (
          <WriteOnly>
            <Button icon="plus" tone="primary" onClick={onNew}>
              New follow-up
            </Button>
          </WriteOnly>
        ) : null
      }
    />
  );
}

function DueCell({ r }: { r: FuItem }) {
  if (r.status === "done") return <span>{fmt.date(r.done_at)}</span>;
  if (!r.due_date) return <span className="opk-muted">No date</span>;
  const b = r._bucket;
  return (
    <div className={`fu-due is-${b}`}>
      {b === "overdue" ? <StatusChip status="overdue" label={`Overdue ${-(daysUntil(r.due_date) ?? 0)}d`} size="sm" /> : null}
      <span className="fu-due__d">{fmt.date(r.due_date)}</span>
      {b !== "overdue" ? <small className={b === "today" ? "fu-today" : "opk-muted"}>{fmt.days(r.due_date)}</small> : null}
    </div>
  );
}

function scopeInfo(r: Followup & { college_id?: unknown; scope_label?: unknown; href?: unknown; branch_name?: unknown; branch_code?: unknown }, colMap: Map<string, CollegeRow>, peopleMap: Map<string, Person>): FuItem["_scope"] {
  const id = String(r.scope_id);
  const col = colMap.get(String(r.college_id ?? ""));
  const apiHref = typeof r.href === "string" && r.href ? toPortalHref(r.href) : null;
  const label = typeof r.scope_label === "string" && r.scope_label ? r.scope_label : null;
  if (r.scope_type === "college") {
    const c = colMap.get(id) ?? col;
    return { label: label || c?.short_name || c?.name || id, href: apiHref ?? portalPath.college(id), college: c };
  }
  if (r.scope_type === "person") {
    const p = peopleMap.get(id);
    const c = col ?? colMap.get(String(p?.college_id));
    return { label: label || p?.full_name || `Person #${id}`, href: apiHref ?? portalPath.person(id), college: c };
  }
  return {
    label: label || (r.branch_name as string) || (r.branch_code as string) || `Branch #${id}`,
    href: apiHref ?? (r.college_id ? `${portalPath.college(String(r.college_id))}?tab=branches&branch=${encodeURIComponent(id)}` : null),
    college: col,
  };
}

/** Targeted colleges (in scope) with nothing scheduled. */
function Unscheduled({
  items,
  colleges,
  districtName,
  formData,
  onSaved,
}: {
  items: FuItem[];
  colleges: CollegeRow[];
  districtName: Map<string, string>;
  formData: { colleges: CollegeRow[]; people: Person[] } | undefined;
  onSaved: () => void;
}) {
  const [all, setAll] = useState(false);
  const openFor = new Set(items.filter((r) => r.status !== "done" && r.college_id).map((r) => String(r.college_id)));
  const list = colleges
    .filter((c) => c.targeted && !openFor.has(String(c.id)) && (c.next_followup === null || c.next_followup === undefined))
    .sort((a, b) => (districtName.get(a.district_id) || "").localeCompare(districtName.get(b.district_id) || "") || String(a.name).localeCompare(String(b.name)));
  const LIMIT = 8;
  return (
    <Section title={`Targeted colleges with nothing scheduled (${list.length})`} sub="In the selected districts. Plan the next check-in so no targeted college goes quiet.">
      {list.length ? (
        <div>
          <ul className="fu-unsched">
            {(all ? list : list.slice(0, LIMIT)).map((c) => (
              <li className="fu-unsched-row" key={c.id}>
                <div className="fu-unsched-name">
                  <Link to={portalPath.college(c.id)}>{c.short_name || c.name}</Link> <span className="opk-muted">{districtName.get(c.district_id) || c.district_id || ""}</span>
                </div>
                <WriteOnly>
                  <Button
                    icon="plus"
                    size="sm"
                    onClick={() => void openFollowupForm({ data: formData, preset: { scope_type: "college", scope_id: c.id }, lockScope: true, scopeLabel: c.short_name || c.name, onSaved })}
                  >
                    Schedule
                  </Button>
                </WriteOnly>
              </li>
            ))}
          </ul>
          {!all && list.length > LIMIT ? (
            <Button tone="ghost" size="sm" onClick={() => setAll(true)}>
              {`Show all ${list.length}`}
            </Button>
          ) : null}
        </div>
      ) : (
        <EmptyState icon="check" title="Every targeted college has a follow-up" text="Targeted colleges in these districts without an open follow-up will show up here." />
      )}
    </Section>
  );
}
