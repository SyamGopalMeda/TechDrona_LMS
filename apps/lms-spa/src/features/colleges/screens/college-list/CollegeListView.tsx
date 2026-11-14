/**
 * Colleges list (port of the old dashboard.js `collegeList()`), used by /colleges/colleges and embedded in the
 * district and town pages (`fixed`). The list state (search, filters, sort, page) lives in the page URL, as before.
 *
 * Server filters (re-fetch): q, op_status, diagnosis, call_status, contact, amb, progress, exam_state, team.
 * Client filters (on the fetched rows): priority (research plan), verification, targeted, follow-ups, and the team
 * filter on servers that do not support `team=` yet. Sorting and paging (25 per page) run on the client. Rollups are
 * never recomputed: every number shown is a field of the /api/colleges row.
 */
import { useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import { usePortalQuery } from "../../lib/cache";
import { downloadCsv } from "../../lib/csv";
import { fmt, today } from "../../lib/fmt";
import { queryInt, useQueryState } from "../../lib/query";
import { portalPath } from "../../lib/routes";
import { scopeRows } from "../../lib/scope";
import type { CollegeRow, Page, PortalMeta, Person } from "../../lib/types";
import { Badge, Button, Chip, ContactActions, DataTable, FilterBar, ListEmpty, StatusBadge, toast, usePortalUi, type Column, type FilterDef } from "../../ui";
import {
  CALL_STATUS,
  CallStatusBadge,
  DIAG_INFO,
  DIAG_ORDER,
  NextFollowupNode,
  P_LEVELS,
  PriorityBadge,
  ProgressNode,
  StatusNode,
  ambCount,
  isNum,
  itemsOf,
  leadOf,
  nextFollowupDate,
  pLevelOf,
  unassignedOf,
  usePlanIndex,
  verifiedStateOf,
} from "../shared/dashboard";
import { useAddCollege } from "./AddCollege";

type Opt = [string, string];
const CALL_STATUS_OPTS: Opt[] = Object.entries(CALL_STATUS).map(([k, [label]]) => [k, label]);
const CONTACT_OPTS: Opt[] = [["working", "Has a working number"], ["untested", "Has an untested number"], ["non_working", "Has a non-working / invalid number"], ["none", "No contact yet"]];
const TEAM_OPTS: Opt[] = [["no_lead", "No college lead"], ["has_lead", "Has a college lead"], ["no_ambassadors", "No ambassadors"], ["has_team", "Lead and ambassadors"], ["has_unassigned", "Has unassigned people"]];
const OP_OPTS: Opt[] = [["operational", "Operational"], ["all", "Any status"], ["possibly_closed", "Possibly closed"], ["closed", "Closed"], ["pending", "Status pending"]];
const VERIFIED_OPTS: Opt[] = [["verified", "Verified"], ["partly", "Partly verified"], ["unverified", "Unverified"]];
const AMB_OPTS: Opt[] = [["gap", "Some target branch has no ambassador"], ["ok", "Every target branch covered"]];
const PROGRESS_OPTS: Opt[] = [["behind", "Behind"], ["on_track", "On track"], ["no_target", "No target"]];
const EXAM_OPTS: Opt[] = [["in_exams", "In exams now"], ["exams_soon", "Exams within 14 days"], ["clear", "Clear"], ["unknown", "Dates unknown"]];
const FU_OPTS: Opt[] = [["overdue", "Overdue follow-up"], ["open", "Has open follow-ups"], ["none", "No follow-ups"]];
const P_OPTS: Opt[] = [...P_LEVELS.map((x): Opt => [x, x === "Hold" ? "On hold" : `Priority ${x}`]), ["none", "Not in research plan"]];
const DIAG_OPTS: Opt[] = DIAG_ORDER.map((k): Opt => [k, DIAG_INFO[k]!.title]);
export const SORTS: Opt[] = [
  ["priority", "Priority (P1 first, then name)"],
  ["name", "Name"],
  ["sno", "List number"],
  ["district", "District"],
  ["lead", "Lead missing first"],
  ["ambassadors", "Ambassadors"],
  ["unassigned", "Unassigned ambassadors"],
  ["target", "Target"],
  ["actual", "Confirmed"],
  ["pct", "Progress %"],
  ["remaining", "Remaining"],
  ["eligible", "Likely prospects (est.)"],
  ["next_followup", "Next follow-up"],
];
export const PAGE_SIZE = 25;
/** URL keys of the list state */
export const LIST_KEYS = ["q", "team", "p", "op", "verified", "targeted", "diagnosis", "call_status", "contact", "amb", "progress", "exam", "followup", "sort", "dir", "page"] as const;
const MORE_KEYS = ["targeted", "diagnosis", "call_status", "contact", "amb", "progress", "exam", "followup"] as const;
const LABELS: Record<string, [string, Opt[]]> = {
  team: ["Team", TEAM_OPTS],
  p: ["Priority", P_OPTS],
  op: ["Status", OP_OPTS],
  verified: ["Verification", VERIFIED_OPTS],
  diagnosis: ["Main reason", DIAG_OPTS],
  call_status: ["Calling", CALL_STATUS_OPTS],
  contact: ["Contacts", CONTACT_OPTS],
  amb: ["Ambassadors", AMB_OPTS],
  progress: ["Progress", PROGRESS_OPTS],
  exam: ["Exams", EXAM_OPTS],
  followup: ["Follow-ups", FU_OPTS],
  targeted: ["Targeted", [["1", "Targeted only"]]],
};
const DESC_FIRST = ["ambassadors", "unassigned", "actual", "pct", "eligible", "target", "remaining"];

type Row = CollegeRow;
type ListState = Record<(typeof LIST_KEYS)[number], string | undefined> & { sortKey: string; dirN: 1 | -1; pageN: number; opV: string };

export interface CollegeListProps {
  /** district / town pages: the list is fixed to this place (not scoped by the global district selection) */
  fixed?: { district?: string; city?: string } | null;
  /** hides the "Calling · next follow-up" column */
  compact?: boolean;
  /** status filter when the URL has none (town pages show any status) */
  defaultOp?: "operational" | "all";
  /** layout: receive the export button and the list (default: just the list) */
  children?: (parts: { exportButton: ReactNode; list: ReactNode }) => ReactNode;
}

const str = (v: unknown) => (v === undefined || v === null || v === "" ? undefined : String(v));

/** Read the list state from the URL query (old `collegeList` param handling, incl. legacy exam_state / op_status). */
export function readListState(q: Record<string, string>, defaultOp: string): ListState {
  const s = {} as ListState;
  for (const k of LIST_KEYS) s[k] = str(q[k]);
  if (q.exam_state && !s.exam) s.exam = q.exam_state;
  if (q.op_status && !q.op) s.op = q.op_status;
  s.sortKey = s.sort || "priority";
  s.dirN = Number(s.dir) === -1 ? -1 : 1;
  s.pageN = queryInt(s.page, 1);
  s.opV = s.op || defaultOp;
  return s;
}

export function CollegeListView({ fixed = null, compact = false, defaultOp = "operational", children }: CollegeListProps) {
  const [q, setQuery] = useQueryState();
  const { form } = usePortalUi();
  const phone = form === "phone";
  const v = useMemo(() => readListState(q, defaultOp), [q, defaultOp]);
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 }).data;
  const plan = usePlanIndex();
  const [openAdd, addDialog] = useAddCollege();

  const dName = useMemo(() => new Map((meta?.districts ?? []).map((d) => [d.id, d.name])), [meta]);
  const cName = useMemo(() => new Map((meta?.cities ?? []).map((c) => [c.id, c.name])), [meta]);

  /* ---------- data ---------- */
  const apiQuery = useMemo(() => {
    const p: Record<string, string | undefined> = {
      q: v.q,
      diagnosis: v.diagnosis,
      call_status: v.call_status,
      contact: v.contact,
      amb: v.amb,
      progress: v.progress,
      exam_state: v.exam,
      op_status: v.opV !== "all" ? v.opV : undefined,
      district: fixed?.district,
      city: fixed?.city,
      // v4 servers filter by team (caps.team then skips the client filter); older ones ignore it
      team: v.team,
    };
    return Object.fromEntries(Object.entries(p).filter(([, x]) => x !== undefined)) as Record<string, string>;
  }, [v, fixed?.district, fixed?.city]);
  const scoped = !fixed;
  const first = usePortalQuery<Row[] | Page<Row>>("colleges", { scoped, query: apiQuery, keepPrevious: true });
  const fd = first.data;
  const total0 = fd && !Array.isArray(fd) && isNum(fd.total) && fd.total > itemsOf(fd).length ? fd.total : null;
  const second = usePortalQuery<Row[] | Page<Row>>(total0 ? "colleges" : null, { scoped, query: { ...apiQuery, page: 1, page_size: total0 ?? 0 }, keepPrevious: true });
  const rows = useMemo(() => {
    const list = itemsOf(total0 ? second.data : fd);
    return fixed ? list : scopeRows(list);
  }, [fd, second.data, total0, fixed]);
  const loading = (first.loading && !fd) || (!!total0 && !second.data && second.loading);
  const error = first.error || second.error;

  const caps = useMemo(
    () => ({
      team: rows.some((r) => "ambassador_count" in r || ("lead" in r && !("college_lead" in r))),
      verified: rows.some((r) => "data_status" in r || "verified_fields" in r),
      unassigned: rows.some((r) => "unassigned_count" in r),
    }),
    [rows],
  );
  // v3 servers have no unassigned_count per college: count from /api/people rows with the same rule (R3)
  const needPeople = rows.length > 0 && !caps.unassigned;
  const peopleQ = usePortalQuery<Person[] | Page<Person>>(needPeople ? "people" : null, fixed ? { query: fixed.district ? { district: fixed.district } : {} } : { scoped: true });
  const unassignedBy = useMemo(() => {
    if (!peopleQ.data) return null;
    const m = new Map<string, number>();
    for (const x of unassignedOf(itemsOf(peopleQ.data))) m.set(x.college_id, (m.get(x.college_id) ?? 0) + 1);
    return m;
  }, [peopleQ.data]);
  const unassignedN = (r: Row): number | null => (isNum(r.unassigned_count) ? r.unassigned_count : unassignedBy ? (unassignedBy.get(r.id) ?? 0) : null);

  /* ---------- filter + sort (client) ---------- */
  const sortVal = (r: Row, k: string): string | number | null => {
    switch (k) {
      case "priority": {
        const i = (P_LEVELS as readonly string[]).indexOf(pLevelOf(r, plan) ?? "");
        return `${i < 0 ? 9 : i}-${String(r.short_name || r.name).toLowerCase()}`;
      }
      case "name":
        return String(r.short_name || r.name || "").toLowerCase();
      case "district":
        return `${dName.get(r.district_id) || r.district_id || ""}-${r.short_name || r.name}`;
      case "lead":
        return leadOf(r) ? 1 : 0;
      case "ambassadors":
        return ambCount(r);
      case "unassigned":
        return unassignedN(r);
      case "actual":
        return (r.actual as number | undefined) ?? r.enrolled ?? null;
      case "eligible":
        return r.eligible ? r.eligible.value : null;
      case "next_followup":
        return nextFollowupDate(r);
      case "target":
        return Number(r.target) > 0 ? r.target : null;
      case "pct":
        return isNum(r.pct) && Number(r.target) > 0 ? r.pct : null;
      case "remaining":
        return Number(r.target) > 0 ? r.remaining : null;
      default: {
        const x = r[k];
        return typeof x === "number" || typeof x === "string" ? x : null;
      }
    }
  };
  const matches = (r: Row): boolean => {
    if (v.team && !caps.team) {
      const lead = !!leadOf(r);
      const amb = ambCount(r) + (Number(r.ambassador_leads) || 0);
      if (v.team === "no_lead" && lead) return false;
      if (v.team === "has_lead" && !lead) return false;
      if (v.team === "no_ambassadors" && amb > 0) return false;
      if (v.team === "has_team" && !(lead && amb > 0)) return false;
    }
    if (v.team === "has_unassigned" && !caps.team && !((unassignedN(r) ?? 0) > 0)) return false;
    if (v.p) {
      const p = pLevelOf(r, plan);
      if (v.p === "none" ? !!p : p !== v.p) return false;
    }
    if (v.verified && caps.verified && verifiedStateOf(r) !== v.verified) return false;
    if (v.targeted === "1" && !r.targeted) return false;
    if (v.followup) {
      const d = nextFollowupDate(r);
      if (v.followup === "overdue" && !(d && d < today())) return false;
      if (v.followup === "none" && r.followups_open) return false;
      if (v.followup === "open" && !(Number(r.followups_open) > 0)) return false;
    }
    return true;
  };
  const visible = rows.filter(matches).sort((a, b) => {
    const x = sortVal(a, v.sortKey);
    const y = sortVal(b, v.sortKey);
    if ((x === null || x === undefined) && (y === null || y === undefined)) return 0;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "en-IN", { numeric: true })) * v.dirN;
  });
  const total = visible.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(v.pageN, pages);
  const pageRows = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  /* ---------- state changes (URL) ---------- */
  const setV = (key: string, val: string | undefined | null) => {
    let x: string | null = val || null;
    if (key === "op" && (x === null || x === defaultOp)) x = null;
    setQuery({ [key]: x, page: null, ...(key === "exam" ? { exam_state: null } : key === "op" ? { op_status: null } : {}) }, { history: key === "q" ? "replace" : "auto" });
  };
  const setSort = (key: string, dir?: "asc" | "desc") => {
    const d = dir ? (dir === "desc" ? -1 : 1) : DESC_FIRST.includes(key) ? -1 : 1;
    setQuery({ sort: key === "priority" ? null : key, dir: d === -1 ? -1 : null, page: null }, { history: "auto" });
  };
  const clearAll = () => {
    const patch: Record<string, null> = { exam_state: null, op_status: null };
    for (const k of LIST_KEYS) if (k !== "sort" && k !== "dir") patch[k] = null;
    setQuery(patch, { history: "auto" });
  };
  const filtersActive = LIST_KEYS.some((k) => !["sort", "dir", "page", "op"].includes(k) && v[k]) || v.opV !== defaultOp;

  /* ---------- rendering ---------- */
  const placeOf = (r: Row) =>
    [cName.get(r.city_id ?? "") || (r.city_id ? cityShort(r.district_id, r.city_id) : null), fixed?.district ? null : dName.get(r.district_id) || r.district_id].filter(Boolean).join(", ");
  const badges = (r: Row): ReactNode[] =>
    [
      pLevelOf(r, plan) ? <PriorityBadge key="p" level={pLevelOf(r, plan)} /> : null,
      r.op_status && r.op_status !== "operational" ? <StatusBadge key="op" kind="op_status" value={r.op_status} /> : null,
      r.targeted ? null : (
        <Badge key="nt" tone="neutral">
          Not targeted
        </Badge>
      ),
      r.exam_state === "in_exams" || r.exam_state === "exams_soon" ? <StatusBadge key="ex" kind="exam_state" value={r.exam_state} /> : null,
    ].filter(Boolean);

  const columns: Column<Row>[] = [
    {
      key: "name",
      label: "College",
      primary: true,
      priority: 1,
      minWidth: 230,
      render: (r) => (
        <div className="vd-cc-name">
          <Link to={portalPath.college(r.id)} className="vd-cname">
            {r.short_name || r.name}
          </Link>
          <span className="vd-muted vd-small vd-cplace">{placeOf(r)}</span>
          <span className="vd-badges">{badges(r)}</span>
        </div>
      ),
    },
    {
      key: "lead",
      label: "College lead",
      priority: 2,
      minWidth: 170,
      render: (r) => {
        const lead = leadOf(r);
        if (!lead) return <Badge tone="warn">No lead</Badge>;
        return (
          <span className="vd-cc-lead">
            {lead.id ? <Link to={portalPath.person(lead.id)}>{lead.name}</Link> : <span>{lead.name}</span>}
            {lead.phone ? <ContactActions phone={lead.phone} compact whatsapp name={lead.name} /> : null}
          </span>
        );
      },
    },
    {
      key: "ambassadors",
      label: "Ambassadors",
      priority: 3,
      minWidth: 130,
      render: (r) => {
        const un = unassignedN(r);
        const al = Number(r.ambassador_leads) || 0;
        const need = Number(r.branches_needing_ambassadors) || 0;
        return (
          <span className="vd-cc-amb">
            <strong className="td-num">{fmt.num(ambCount(r))}</strong>
            {!caps.team && al ? <span className="vd-muted vd-small">{` + ${fmt.num(al)} lead${al === 1 ? "" : "s"}`}</span> : null}
            {un !== null && un > 0 ? (
              <span className="vd-cc-un">
                <Badge tone="warn">{`${fmt.num(un)} unassigned`}</Badge>
              </span>
            ) : null}
            {need > 0 ? <span className="vd-muted vd-small vd-block">{`${fmt.plural(need, "target branch", "target branches")} without an ambassador`}</span> : null}
          </span>
        );
      },
    },
    {
      key: "pct",
      label: "Target vs actual",
      priority: 1,
      minWidth: 180,
      render: (r) => (
        <div className="vd-tp">
          <ProgressNode r={r} />
          {Number(r.target) > 0 || r.status ? <StatusNode r={r} /> : null}
        </div>
      ),
    },
    ...(compact
      ? []
      : [
          {
            key: "next_followup",
            label: "Calling · next follow-up",
            priority: 3,
            minWidth: 170,
            render: (r: Row) => (
              <div className="vd-cc-call">
                {r.call_status ? <CallStatusBadge status={String(r.call_status)} /> : null}
                <span className="vd-small">
                  <NextFollowupNode r={r} />
                </span>
              </div>
            ),
          } satisfies Column<Row>,
        ]),
  ];

  /* ---------- filters ---------- */
  const opFilter: FilterDef =
    defaultOp === "operational"
      ? { key: "op", label: "Status", allLabel: "Status: operational", options: [["all", "Any status"], ...OP_OPTS.filter(([k]) => k !== "operational" && k !== "all")] }
      : { key: "op", label: "Status", allLabel: "Status: any", options: OP_OPTS.filter(([k]) => k !== "all") };
  const barKeys = new Set<string>(["team", "p", "op", "verified", ...(phone ? MORE_KEYS : [])]);
  const barValues: Record<string, string> = {
    q: v.q ?? "",
    team: v.team ?? "",
    p: v.p ?? "",
    op: v.opV === defaultOp ? "" : v.opV,
    verified: v.verified ?? "",
    sort: v.sortKey === "priority" ? "" : v.sortKey,
    ...(phone ? Object.fromEntries(MORE_KEYS.map((k) => [k, v[k] ?? ""])) : {}),
  };
  const filters: (FilterDef | null)[] = [
    { key: "team", label: "Team", options: TEAM_OPTS },
    { key: "p", label: "Priority", options: P_OPTS },
    opFilter,
    caps.verified ? { key: "verified", label: "Verification", options: VERIFIED_OPTS } : null,
    { key: "sort", label: "Sort", allLabel: "Sort: priority", options: SORTS.filter(([k]) => k !== "priority") },
    ...(phone
      ? [
          { key: "targeted", label: "Targeted", allLabel: "All colleges", options: [["1", "Targeted only"]] as Opt[] },
          { key: "diagnosis", label: "Main reason", options: DIAG_OPTS },
          { key: "call_status", label: "Calling", options: CALL_STATUS_OPTS },
          { key: "contact", label: "Contacts", options: CONTACT_OPTS },
          { key: "amb", label: "Coverage", options: AMB_OPTS },
          { key: "progress", label: "Progress", options: PROGRESS_OPTS },
          { key: "exam", label: "Exams", options: EXAM_OPTS },
          { key: "followup", label: "Follow-ups", options: FU_OPTS },
        ]
      : []),
  ];

  const select = (key: string, label: string, opts: Opt[], any = "Any") => (
    <label className="vd-field" key={key}>
      <span>{label}</span>
      <select className="td-input td-select td-input--sm" value={String((v as Record<string, unknown>)[key] ?? "")} onChange={(e) => setV(key, e.target.value)}>
        <option value="">{any}</option>
        {opts.map(([val, t]) => (
          <option key={val} value={val}>
            {t}
          </option>
        ))}
      </select>
    </label>
  );
  const moreN = MORE_KEYS.filter((k) => v[k]).length;

  const chips: ReactNode[] = [];
  for (const [k, [label, opts]] of Object.entries(LABELS)) {
    const val = k === "op" ? v.opV : ((v as Record<string, unknown>)[k] as string | undefined);
    if (!val || (k === "op" && val === defaultOp) || barKeys.has(k)) continue;
    const o = opts.find(([x]) => String(x) === String(val));
    chips.push(<Chip key={k} tone="brand" label={`${label}: ${o ? o[1] : val}`} onRemove={() => setV(k, "")} />);
  }

  const exportCsv = () => {
    const head = [
      "S.No", "College", "Short name", "District", "City", "Priority", "Status", "Targeted", "Verification", "College lead", "Ambassador leads", "Ambassadors",
      "Unassigned ambassadors", "Target branches without ambassador", "Target", "Confirmed", "Remaining", "Progress %", "Status vs target", "Likely prospects (est.)",
      "Likely prospects basis", "Exam state", "Calling status", "Open follow-ups", "Next follow-up",
    ];
    const val = <T,>(x: T) => (x === null || x === undefined ? "" : x);
    const lines = visible.map((r) => [
      r.sno, r.name, r.short_name, dName.get(r.district_id) || r.district_id, cName.get(r.city_id ?? "") || r.city_id, pLevelOf(r, plan) || "",
      r.op_status, r.targeted ? "yes" : "no", verifiedStateOf(r) || "", leadOf(r)?.name || "", val(r.ambassador_leads), ambCount(r), val(unassignedN(r)), val(r.branches_needing_ambassadors),
      Number(r.target) > 0 ? r.target : "", val((r.actual as number | undefined) ?? r.enrolled), Number(r.target) > 0 ? val(r.remaining) : "",
      isNum(r.pct) && Number(r.target) > 0 ? Math.round(r.pct * 1000) / 10 : "",
      (r.status as string | undefined) || (Number(r.target) > 0 ? (r.on_track ? "on track" : "behind") : "no target"),
      val(r.eligible?.value), r.eligible?.basis || "pending", val(r.exam_state), val(r.call_status as string | undefined), val(r.followups_open), nextFollowupDate(r) ?? "",
    ]);
    downloadCsv(`techdrona-colleges-${today()}.csv`, [head, ...lines]);
    toast(`Exported ${fmt.plural(visible.length, "college")}`, "good");
  };
  const exportButton = (
    <Button icon="data" tone="secondary" onClick={exportCsv} disabled={loading}>
      Export CSV
    </Button>
  );

  const countText = `${fmt.plural(total, "college")}${v.opV === "operational" ? " · operational" : v.opV && v.opV !== "all" ? "" : " · any status"}`;
  const addFirst = !fixed && !filtersActive ? () => openAdd() : undefined;
  const emptyText = filtersActive
    ? "Clear a filter or the search to see more."
    : fixed
      ? "No colleges from the master list are in this place yet."
      : "No colleges in the selected districts yet. Add the first one, or pick other districts in the header.";

  const list = (
    <div className="vd-clist">
      <div className="vd-filterbar">
        <FilterBar
          values={barValues}
          search={{ key: "q", placeholder: "Search name, short name, town…", debounce: 300 }}
          filters={filters}
          onChange={(vals, k) => {
            if (k === null) return clearAll();
            if (k === "sort") return setSort(String(vals.sort || "priority"));
            setV(k, String(vals[k] ?? ""));
          }}
        />
      </div>
      {phone ? null : (
        <div className="vd-filters-more">
          <details className="vd-more-filters" open={moreN ? true : undefined}>
            <summary>{moreN ? `More filters (${moreN})` : "More filters"}</summary>
            <div className="vd-filterbar">
              {select("targeted", "Targeted", [["1", "Targeted only"]], "All")}
              {select("diagnosis", "Main reason behind", DIAG_OPTS)}
              {select("call_status", "Calling status", CALL_STATUS_OPTS)}
              {select("contact", "Contact numbers", CONTACT_OPTS)}
              {select("amb", "Branch coverage", AMB_OPTS)}
              {select("progress", "Progress", PROGRESS_OPTS)}
              {select("exam", "Exams", EXAM_OPTS)}
              {select("followup", "Follow-ups", FU_OPTS)}
            </div>
          </details>
        </div>
      )}
      <div className="vd-clist-bar">
        <span className="vd-muted vd-small" aria-live="polite">
          {loading ? "" : countText}
        </span>
        {chips.length ? (
          <div className="vd-chips">
            {chips}
            <button type="button" className="vd-linkbtn" onClick={clearAll}>
              Clear all
            </button>
          </div>
        ) : null}
      </div>
      <div className="vd-ctable-host">
        <DataTable<Row>
          caption="Colleges"
          columns={columns}
          rows={loading ? undefined : pageRows}
          rowKey={(r) => r.id}
          loading={loading}
          error={error && !fd ? error : null}
          onRetry={() => void first.reload()}
          sort={columns.some((c) => c.key === v.sortKey) ? { key: v.sortKey, dir: v.dirN > 0 ? "asc" : "desc" } : null}
          onSort={(k, d) => setSort(k, d)}
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPage={(p) => setQuery({ page: p > 1 ? p : null }, { history: "auto" })}
          pageLabel="colleges"
          rowHref={(r) => portalPath.college(r.id)}
          mobile="cards"
          cardSort={false}
          cardTitle={(r) => (
            <Link to={portalPath.college(r.id)} className="vd-cname">
              {r.short_name || r.name}
            </Link>
          )}
          cardSubtitle={(r) => placeOf(r) || null}
          cardMeta={(r) => {
            const b = badges(r);
            return b.length ? [<span key="b" className="vd-badges">{b}</span>] : [];
          }}
          empty={
            <ListEmpty filtered={filtersActive} noun="colleges" icon={filtersActive ? "search" : "college"} addLabel={addFirst ? "Add college" : undefined} onAdd={addFirst} onClear={clearAll} text={emptyText} />
          }
        />
      </div>
      {addDialog}
    </div>
  );
  return <>{children ? children({ exportButton, list }) : list}</>;
}

/** "tenali" from "guntur--tenali" (city ids are "<district>--<town>"). */
export function cityShort(districtId: string, cityId: string): string {
  const p = `${districtId}--`;
  return String(cityId).startsWith(p) ? String(cityId).slice(p.length) : String(cityId);
}
