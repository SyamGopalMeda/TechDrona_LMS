/**
 * Team (/colleges/people) — port of js/views/people.js `renderList` with the owner-reviewed wording of 2026-11-14:
 * segments (All / College leads / Ambassadors / Without a lead) with counts, filters in the URL, server paging +
 * sort, bulk "assign to a lead", row actions (edit, move, deactivate / reactivate) and "people who left".
 * Assignment status, actuals, targets and status all come from GET /api/people (v4); nothing is recomputed.
 */
import "@/features/colleges/styles/views/college.css";
import "@/features/colleges/styles/views/ops.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { usePortalPage } from "../shell/page-context";
import { Badge, Button, ContactActions, DataTable, FilterBar, ListEmpty, PageHeader, ProgressBar, Segmented, StatusChip, WriteOnly, toast, usePortalUi, type FilterValues } from "../ui";
import { ROLE_LABEL, assignToLead, deactivatePerson, movePerson, peopleRows, personDialog, reactivatePerson } from "../forms";

/* eslint-disable @typescript-eslint/no-explicit-any -- API rows */
type Raw = Record<string, any>;

const SEGMENTS = [
  { value: "all", label: "All" },
  { value: "leads", label: "College leads" },
  { value: "ambassadors", label: "Ambassadors" },
  { value: "unassigned", label: "Without a lead", title: "Ambassadors who do not report to a college lead yet" },
] as const;
const SEG_PARAMS: Record<string, { role?: string; assignment?: string }> = {
  all: {},
  leads: { role: "college_lead" },
  ambassadors: { role: "ambassador_lead,ambassador" },
  unassigned: { assignment: "unassigned,invalid_link" },
};
export const ISSUE_TEXT: Record<string, string> = {
  no_lead: "No lead assigned",
  lead_missing: "Lead record no longer exists",
  lead_inactive: "Lead is inactive",
  lead_other_college: "Lead belongs to another college",
  lead_wrong_role: "Reports to someone who is not a lead",
};
const PAGE_SIZE = 50;
const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();
const tail = (phone: unknown) => {
  const d = String(phone || "").replace(/\D/g, "");
  return d.length >= 4 ? `…${d.slice(-4)}` : "";
};
export const collegeOf = (p: Raw): Raw | null => p.college || (p.college_id ? { id: p.college_id, name: p.college_name, short_name: p.college_short_name } : null);
export const isLeadRole = (r: unknown) => r === "college_lead" || r === "ambassador_lead";

export function RoleChip({ p }: { p: Raw }) {
  return <Badge tone={p.role === "ambassador" ? "neutral" : "brand"}>{ROLE_LABEL[p.role] || p.role}</Badge>;
}
export function ContactCell({ p }: { p: Raw }) {
  return <ContactActions phone={p.phone_norm || p.phone} email={p.email} compact whatsapp name={p.full_name} />;
}

function AssignmentCell({ p }: { p: Raw }) {
  if (p.role === "college_lead") return <span className="vx-muted vx-small">Leads the college</span>;
  const st = p.assignment_status || (p.reports_to ? "assigned" : "unassigned");
  const lead = p.lead || (p.reports_to ? { id: p.reports_to, name: p.reports_to_name } : null);
  return (
    <div className="v-people__lead">
      {lead && lead.id ? (
        <Link to={portalPath.person(lead.id)} onClick={stop} className={lead.status === "inactive" ? "is-inactive" : undefined}>
          {lead.name || `#${lead.id}`}
        </Link>
      ) : null}
      {st === "assigned" ? null : <StatusChip status={st} size="sm" title={ISSUE_TEXT[p.assignment_issue] || ""} />}
      {st === "invalid_link" && p.assignment_issue ? <span className="vx-small vx-muted">{ISSUE_TEXT[p.assignment_issue] || ""}</span> : null}
    </div>
  );
}

/** Target vs actual for the programme period, exactly as the server returned it. */
function PerfCell({ p }: { p: Raw }) {
  const ts = p.target_summary;
  const actual = p.actual_own ?? p.enrolled ?? 0;
  if (!ts) return <ProgressBar actual={actual} target={p.target ?? null} size="sm" unit="enrolled" />;
  return (
    <div className="v-people__perf">
      <ProgressBar actual={actual} target={ts.target} min={ts.min} max={ts.max} size="sm" unit="enrolled" status={ts.status} pct={ts.pct} />
      <div className="v-people__perfmeta">
        <StatusChip status={ts.status} size="sm" />
        {isLeadRole(p.role) && p.team_size ? <span className="vx-small vx-muted">{`team ${fmt.num(p.actual_team ?? 0)} · total ${fmt.num(p.actual_combined ?? actual)}`}</span> : null}
      </div>
    </div>
  );
}

function NameCell({ p }: { p: Raw }) {
  const sub = [p.designation, tail(p.phone_norm || p.phone)].filter(Boolean).join(" · ");
  return (
    <div className="v-people__name">
      <Link to={portalPath.person(p.id)} onClick={stop}>
        {p.full_name || "(no name)"}
      </Link>
      {/* shown only when the Role column is hidden for width, so the role is never lost (D2) */}
      <span className="v-people__rolein">
        <RoleChip p={p} />
      </span>
      {sub ? <span className="vx-small vx-muted">{sub}</span> : null}
    </div>
  );
}
function CollegeLink({ p }: { p: Raw }) {
  const c = collegeOf(p);
  return c ? (
    <Link to={portalPath.college(String(c.id))} onClick={stop} title={c.name || ""}>
      {c.short_name || c.name || c.id}
    </Link>
  ) : (
    <>—</>
  );
}

export function People() {
  usePortalPage({ title: "Team", crumbs: [{ label: "Team" }] });
  const { canWrite } = usePortalUi();
  const [q, setQuery] = useQueryState();
  const f = {
    seg: SEG_PARAMS[q.seg || ""] ? q.seg! : q.view === "amb_no_lead" ? "unassigned" : "all",
    q: q.q || "",
    role: q.role || "",
    college: q.college || "",
    lead: q.lead || "",
    assignment: q.assignment || "",
    status: q.status || "",
    sort: q.sort || "name",
    page: Math.max(1, Number(q.page) || 1),
  };
  // `view=amb_no_lead` (old Home link) becomes seg=unassigned
  useEffect(() => {
    if (q.view) setQuery({ view: null, seg: q.view === "amb_no_lead" ? "unassigned" : q.seg || null }, { history: "replace" });
  }, [q.view, q.seg, setQuery]);

  // query params of the list (F4/D9: without a status filter the directory lists people still on the team)
  const seg = SEG_PARAMS[f.seg] || {};
  const segRoles = seg.role ? seg.role.split(",") : null;
  const role = f.role ? (segRoles && !segRoles.includes(f.role) ? "__none__" : f.role) : seg.role;
  let assignment = f.assignment || seg.assignment;
  if (f.seg === "unassigned" && f.assignment === "assigned") assignment = "__none__";
  const impossible = role === "__none__" || assignment === "__none__";
  const base = { q: f.q, college_id: f.college, reports_to: f.lead, status: f.status || "active,onboarding" };
  const list = usePortalQuery<Raw | Raw[]>(impossible ? null : "people", {
    scoped: true,
    keepPrevious: true,
    query: { ...base, role: role ?? "", assignment: assignment ?? "", sort: f.sort, page: f.page, page_size: PAGE_SIZE },
  });
  const cnt = usePortalQuery<Raw | Raw[]>("people", { scoped: true, keepPrevious: true, query: { ...base, page: 1, page_size: 1 } });
  const left = usePortalQuery<Raw | Raw[]>(f.status ? null : "people", { scoped: true, keepPrevious: true, query: { ...base, status: "inactive", page: 1, page_size: 1 } });
  // filter option sources (scoped to the district picker)
  const collegesQ = usePortalQuery<unknown>("colleges", { scoped: true });
  const leadsQ = usePortalQuery<unknown>("people", { scoped: true, query: { role: "college_lead,ambassador_lead", status: "active,onboarding", page: 1, page_size: 200 } });
  const colleges = useMemo(() => peopleRows(collegesQ.data), [collegesQ.data]);
  const leads = useMemo(() => peopleRows(leadsQ.data), [leadsQ.data]);

  const legacy = Array.isArray(list.data);
  const view = useMemo(() => {
    if (impossible) return { rows: [] as Raw[], total: 0, counts: null as Raw | null };
    const d = list.data;
    if (!d) return { rows: undefined, total: 0, counts: null };
    if (Array.isArray(d)) {
      // servers before v4 return a plain array: filter / sort / page here from the same live rows
      const segRows = (s: string) =>
        d.filter((p) => (s === "leads" ? p.role === "college_lead" : s === "ambassadors" ? p.role !== "college_lead" : s === "unassigned" ? p.role !== "college_lead" && p.status !== "inactive" && !p.reports_to : true));
      let rows = segRows(f.seg);
      if (f.role) rows = rows.filter((p) => p.role === f.role);
      if (f.lead) rows = rows.filter((p) => (f.lead === "none" ? !p.reports_to : String(p.reports_to) === f.lead));
      if (f.assignment) rows = rows.filter((p) => (f.assignment === "assigned" ? !!p.reports_to : f.assignment === "unassigned" ? !p.reports_to : false));
      const dir = f.sort.startsWith("-") ? -1 : 1;
      const key = f.sort.replace(/^-/, "");
      const val = (p: Raw) => ({ name: p.full_name, college: p.college_name, role: p.role, status: p.status, actual: p.enrolled, pct: p.pct, assignment: p.reports_to ? 1 : 0 })[key] ?? p.full_name;
      rows = rows.slice().sort((a, b) => {
        const x = val(a);
        const y = val(b);
        return (typeof x === "number" && typeof y === "number" ? x - y : String(x ?? "").localeCompare(String(y ?? ""))) * dir;
      });
      return {
        rows: rows.slice((f.page - 1) * PAGE_SIZE, f.page * PAGE_SIZE),
        total: rows.length,
        counts: { total: d.length, counts: { college_lead: segRows("leads").length, ambassador: segRows("ambassadors").length, unassigned: segRows("unassigned").length } },
      };
    }
    return { rows: (d.items || []) as Raw[], total: Number(d.total || 0), counts: cnt.data && !Array.isArray(cnt.data) ? cnt.data : null };
  }, [list.data, cnt.data, impossible, f.seg, f.role, f.lead, f.assignment, f.sort, f.page]);

  // a page past the end (rows removed): go to the last page
  useEffect(() => {
    if (legacy || !list.data || Array.isArray(list.data)) return;
    const pages = Math.max(1, Math.ceil(view.total / PAGE_SIZE));
    if (f.page > pages) setQuery({ page: pages > 1 ? pages : null }, { history: "replace" });
  }, [legacy, list.data, view.total, f.page, setQuery]);

  const segCounts = (() => {
    const c = view.counts;
    if (!c) return {} as Record<string, number | undefined>;
    const k: Raw = c.counts || {};
    return { all: c.total, leads: k.college_lead, ambassadors: (k.ambassador || 0) + (legacy ? 0 : k.ambassador_lead || 0), unassigned: (k.unassigned || 0) + (k.invalid_link || 0) } as Record<string, number | undefined>;
  })();
  const segRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    segRef.current?.querySelector('[data-value="unassigned"]')?.classList.toggle("v-people__seg--alert", !!segCounts.unassigned);
  });

  const push = (patch: Record<string, string | number | null>) => setQuery({ view: null, ...patch }, { history: "auto" });
  const isFiltered = f.seg !== "all" || [f.q, f.role, f.college, f.lead, f.assignment, f.status].some(Boolean);
  const clearFilters = () => push({ seg: null, q: null, role: null, college: null, lead: null, assignment: null, status: null, page: null });

  const cname = (c: Raw) => (c.short_name && !String(c.name).includes(c.short_name) ? `${c.name} (${c.short_name})` : c.name);
  const collegeOpts = colleges
    .slice()
    .sort((a, b) => String(a.name).localeCompare(String(b.name)))
    .map((c) => ({ value: String(c.id), label: String(cname(c)) }));
  const leadOpts = [
    { value: "none", label: "No lead (unassigned)" },
    ...leads
      .filter((p) => !f.college || p.college_id === f.college)
      .sort((a, b) => String(a.full_name).localeCompare(String(b.full_name)))
      .map((p) => ({ value: String(p.id), label: `${p.full_name} — ${p.college?.short_name || p.college_short_name || p.college_id}` })),
  ];

  const onFilters = (v: FilterValues, k: string | null) => {
    const next: Record<string, string | number | null> = {};
    for (const key of ["q", "role", "college", "lead", "assignment", "status"]) next[key] = String(v[key] ?? "") || null;
    // a "reports to" lead of another college is dropped when the college changes
    if (k === "college" && next.lead && next.lead !== "none" && !leads.some((p) => String(p.id) === next.lead && (!next.college || p.college_id === next.college))) next.lead = null;
    setQuery({ view: null, ...next, page: null }, { history: k === "q" ? "replace" : "auto" });
  };

  // bulk selection (cleared on every reload: the table is keyed on the request)
  const [selected, setSelected] = useState<Raw[]>([]);
  const tableKey = JSON.stringify([f, list.data ? "1" : "0", cnt.data ? (cnt.data as Raw).total : 0]);
  useEffect(() => setSelected([]), [tableKey]);
  const [clearN, setClearN] = useState(0);

  const nLeft = left.data && !Array.isArray(left.data) && Number.isFinite(left.data.total) ? Number(left.data.total) : 0;
  const sortState = { key: f.sort.replace(/^-/, ""), dir: (f.sort.startsWith("-") ? "desc" : "asc") as "asc" | "desc" };

  return (
    <div className="v-people v-people--dir">
      <PageHeader
        title="Team"
        scope
        sub="The student team: a college lead runs outreach at one college, and ambassadors (some of them ambassador leads) bring in enrollments. See who reports to whom and how each person is doing against their target."
        actions={
          <WriteOnly>
            <Button icon="plus" tone="primary" onClick={() => void personDialog({})}>
              Add person
            </Button>
          </WriteOnly>
        }
      />
      <div className="v-people__segs" ref={segRef}>
        <Segmented
          ariaLabel="Show"
          value={f.seg}
          options={SEGMENTS.map((s) => ({ value: s.value as string, label: <span title={"title" in s ? s.title : undefined}>{s.label}</span>, count: segCounts[s.value] }))}
          onChange={(v) => push({ seg: v === "all" ? null : v, page: null })}
        />
      </div>
      <div className="v-people__filters">
        <FilterBar
          values={{ q: f.q, role: f.role, college: f.college, lead: f.lead, assignment: f.assignment, status: f.status }}
          onChange={onFilters}
          search={{ key: "q", placeholder: "Search name, phone, email or college", debounce: 300 }}
          filters={[
            { key: "role", label: "Role", options: [["college_lead", "College lead"], ["ambassador_lead", "Ambassador lead"], ["ambassador", "Ambassador"]] },
            { key: "college", label: "College", options: collegeOpts },
            { key: "lead", label: "Reports to", options: leadOpts },
            { key: "assignment", label: "Link to a lead", options: [["assigned", "Has a lead"], ["unassigned", "No lead"], ["invalid_link", "Lead link broken"]] },
            { key: "status", label: "Status", options: [["active", "Active"], ["onboarding", "Onboarding"], ["inactive", "Inactive"]] },
          ]}
        />
      </div>
      {selected.length ? <BulkBar selected={selected} leads={leads} onClear={() => {
            setClearN((n) => n + 1);
            setSelected([]);
          }} /> : null}
      <div className="v-people__table">
        <DataTable<Raw>
          key={`${tableKey}:${clearN}`}
          caption="Team members"
          rows={view.rows}
          loading={!view.rows && !list.error}
          error={list.error}
          onRetry={() => void list.reload()}
          pageSize={PAGE_SIZE}
          page={f.page}
          total={view.total}
          pageLabel="people"
          sort={sortState}
          onSort={(key, dir) => {
            const sort = `${dir === "desc" ? "-" : ""}${key}`;
            push({ sort: sort === "name" ? null : sort, page: null });
          }}
          onPage={(n) => push({ page: n > 1 ? n : null })}
          rowHref={(p) => portalPath.person(p.id)}
          selectable={canWrite}
          onSelect={setSelected}
          columns={[
            { key: "name", label: "Name", primary: true, priority: 1, minWidth: 200, render: (p) => <NameCell p={p} /> },
            { key: "role", label: "Role", priority: 3, minWidth: 130, cardHidden: true, render: (p) => <RoleChip p={p} /> },
            { key: "college", label: "College", priority: 2, minWidth: 100, cardHidden: true, render: (p) => <CollegeLink p={p} /> },
            { key: "assignment", label: "Reports to", priority: 2, minWidth: 140, render: (p) => <AssignmentCell p={p} /> },
            { key: "contact", label: "Contact", sortable: false, priority: 3, minWidth: 150, render: (p) => <ContactCell p={p} /> },
            { key: "actual", label: "Paid enrollments vs target", phoneLabel: "Paid vs target", priority: 2, minWidth: 190, render: (p) => <PerfCell p={p} /> },
            { key: "status", label: "Status", priority: 1, minWidth: 100, cardHidden: true, render: (p) => <StatusChip status={p.status || "active"} size="sm" /> },
          ]}
          cardTitle={(p) => (
            <Link to={portalPath.person(p.id)} onClick={stop}>
              {p.full_name || "(no name)"}
            </Link>
          )}
          cardSubtitle={(p) => {
            const c = collegeOf(p);
            return [ROLE_LABEL[p.role] || p.role, c ? c.short_name || c.name : null, p.designation].filter(Boolean).join(" · ");
          }}
          cardMeta={(p) => [p.status && p.status !== "active" ? <StatusChip key="st" status={p.status} size="sm" /> : null]}
          rowActions={(p) => [
            { label: "Edit", icon: "edit", writeOnly: true, onClick: () => void personDialog({ id: p.id }) },
            { label: "Move to another college", icon: "college", writeOnly: true, onClick: () => void movePerson(p as { id: number }) },
            p.status === "inactive"
              ? { label: "Reactivate", icon: "check", writeOnly: true, onClick: () => void reactivatePerson(p as never) }
              : { label: "Deactivate…", icon: "close", tone: "danger", writeOnly: true, onClick: () => void deactivatePerson(p as { id: number }) },
          ]}
          empty={
            <ListEmpty
              filtered={isFiltered}
              noun="people"
              addLabel="Add College Lead"
              onAdd={() => void personDialog({ role: "college_lead" })}
              onClear={clearFilters}
              text={isFiltered ? undefined : "Add the first College Lead, then their ambassadors. Everyone you add appears here with their targets."}
            />
          }
        />
      </div>
      {nLeft ? (
        <p className="vx-small vx-muted v-people__left">
          {`${fmt.plural(nLeft, "person", "people")} who left ${nLeft === 1 ? "is" : "are"} not listed. `}
          <Link to={`${portalPath.people}?status=inactive`} onClick={(e) => (e.preventDefault(), push({ status: "inactive", page: null }))}>
            Show them
          </Link>
        </p>
      ) : null}
      <p className="v-people__links vx-small">
        Colleges: <Link to={`${portalPath.colleges}?team=no_lead`}>without a college lead</Link> · <Link to={`${portalPath.colleges}?team=no_ambassadors`}>without ambassadors</Link> ·{" "}
        <Link to={`${portalPath.colleges}?team=has_unassigned`}>with unassigned ambassadors</Link>
      </p>
    </div>
  );
}

function BulkBar({ selected, leads, onClear }: { selected: Raw[]; leads: Raw[]; onClear: () => void }) {
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const cols = [...new Set(selected.map((p) => collegeOf(p)?.id))];
  const n = selected.length;
  const label = <strong>{`${fmt.num(n)} selected`}</strong>;
  const clear = (
    <Button tone="ghost" size="sm" onClick={onClear}>
      Clear
    </Button>
  );
  if (cols.length > 1)
    return (
      <div className="v-people__bulk" role="region" aria-label="Bulk actions">
        {label}
        <span className="vx-small">People from different colleges are selected. A lead can only manage people of their own college — pick people of one college.</span>
        {clear}
      </div>
    );
  const hasAmbLead = selected.some((p) => p.role === "ambassador_lead");
  const cand = leads.filter((p) => p.college_id === cols[0] && !selected.some((s) => Number(s.id) === Number(p.id)) && (!hasAmbLead || p.role === "college_lead"));
  const go = async () => {
    if (!to) return;
    if (selected.some((p) => p.role === "college_lead")) return toast("College leads do not report to anyone — unselect them first.", "warn");
    setBusy(true);
    const leadId = to === "none" ? null : Number(to);
    const r = await assignToLead(
      selected.map((p) => p.id),
      leadId,
    );
    setBusy(false);
    if (r.failed.length) toast(`${r.ok.length} updated, ${r.failed.length} not: ${r.failed[0]!.message}`, "bad");
    else toast(`${r.ok.length} ${r.ok.length === 1 ? "person" : "people"} ${leadId ? `now report to ${cand.find((c) => Number(c.id) === leadId)?.full_name}` : "unassigned"}`, "good");
    onClear();
  };
  const c0 = collegeOf(selected[0]!);
  return (
    <div className="v-people__bulk" role="region" aria-label="Bulk actions">
      {label}
      <span className="vx-small vx-muted">{`at ${c0?.short_name || c0?.name || ""}`}</span>
      <select className="td-input td-select td-input--sm" aria-label="Assign to lead" value={to} onChange={(e) => setTo(e.target.value)}>
        <option value="">{cand.length ? "Choose a lead…" : "No active lead at this college"}</option>
        {cand.map((p) => (
          <option key={p.id} value={String(p.id)}>
            {`${p.full_name} (${ROLE_LABEL[p.role]})`}
          </option>
        ))}
        <option value="none">— Remove lead (unassign) —</option>
      </select>
      <Button tone="primary" size="sm" busy={busy} disabled={busy} onClick={() => void go()}>
        Assign
      </Button>
      {clear}
    </div>
  );
}
