/**
 * Audit log (/colleges/audit) — port of js/views/admin.js `renderAudit`.
 * Every change with who / when / what / record / changed fields; filters (record type, action, changed by, one
 * record — only when a link set it —, from / to dates), Newer / Older paging (50 per page) and a "Change details"
 * drawer with before / after values in plain labels. Raw JSON only with ?dev=1.
 * URL: ?entity=&entity_id=&actor=&action=&from=&to=&page= (same keys as before; plural entity names still work).
 */
import "@/features/colleges/styles/views/admin.css";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { isPortalApiError } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt, today } from "../lib/fmt";
import { queryInt, useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import type { AuditEntry } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Badge, Button, DataTable, Drawer, EmptyState, ErrorCard, Icon, Kv, PageHeader, Skeleton, usePortalUi, type Column } from "../ui";
import { SrcLink, devMode, fieldLabel } from "./admin/shared";
import { rowsOf } from "../forms";

export const AUDIT_ENTITIES: [string, string][] = [
  ["college", "Colleges"],
  ["branch", "Branches"],
  ["person", "People"],
  ["target", "Targets"],
  ["enrollment", "Enrollments"],
  ["activity", "Activities"],
  ["followup", "Follow-ups"],
  ["contact", "Contacts"],
  ["call", "Calls"],
  ["exam", "Exams"],
  ["course", "Courses"],
  ["setting", "Settings"],
  ["district", "Districts"],
];
const PLURAL_TO_ENTITY: Record<string, string> = {
  colleges: "college", branches: "branch", people: "person", targets: "target", enrollments: "enrollment", activities: "activity", followups: "followup",
  exams: "exam", courses: "course", settings: "setting", districts: "district", contacts: "contact", calls: "call",
};
const PAGE = 50;
const FILTER_KEYS = ["entity", "entity_id", "actor", "action", "from", "to"] as const;
const ENT_LABEL = Object.fromEntries(AUDIT_ENTITIES);
const SINGULAR: Record<string, string> = { person: "Person", followup: "Follow-up", activity: "Activity", branch: "Branch" };
export const entName = (e: string): string => SINGULAR[e] || (ENT_LABEL[e] || fieldLabel(e)).replace(/ies$/, "y").replace(/s$/, "");
const TONE: Record<string, "good" | "info" | "bad"> = { create: "good", update: "info", delete: "bad" };
const ACT_LABEL: Record<string, string> = { create: "Added", update: "Changed", delete: "Deleted" };
const BOOL_KEYS = new Set(["targeted", "active", "is_relevant", "autonomous", "is_demo", "confirms_participation"]);
const HIDDEN = ["updated_at", "updated_by", "created_at", "created_by"];

type Row = AuditEntry & { before: unknown; after: unknown };
const obj = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const parse = (v: unknown) => {
  if (v === null || v === undefined || typeof v === "object") return v;
  try {
    return JSON.parse(String(v)) as unknown;
  } catch {
    return v;
  }
};

/** Changed field names of an update (timestamps / stamps left out). */
export function changedFields(r: { before: unknown; after: unknown }): string[] {
  const b = obj(r.before);
  const a = obj(r.after);
  return [...new Set([...Object.keys(b), ...Object.keys(a)])].filter((k) => !HIDDEN.includes(k) && JSON.stringify(b[k]) !== JSON.stringify(a[k]));
}
function recordName(r: Row): string {
  const o = obj(r.after ?? null);
  const src = Object.keys(o).length ? o : obj(r.before);
  return (
    (src.name as string) ||
    (src.full_name as string) ||
    (src.title as string) ||
    (src.student_name as string) ||
    (r.entity === "setting" ? fieldLabel(r.entity_id) : "") ||
    (r.entity === "target" && src.scope_type ? `${src.scope_type} ${src.scope_id}` : "") ||
    (r.entity === "exam" && src.semester ? `${src.college_id} · ${src.semester}` : "")
  );
}
function recordHref(r: Row): string | null {
  const id = r.entity_id;
  if (r.entity === "college") return portalPath.college(id);
  if (r.entity === "person") return portalPath.person(id);
  const o = { ...obj(r.before), ...obj(r.after) };
  if (r.entity === "branch" && o.college_id) return `${portalPath.college(String(o.college_id))}?tab=branches&branch=${encodeURIComponent(id)}`;
  if (o.college_id) return portalPath.college(String(o.college_id));
  return null;
}
const local = (at: string) => {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? null : d;
};
const dayOf = (at: string) => {
  const d = local(at);
  return d ? d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : fmt.date(at);
};
const timeOf = (at: string) => {
  const d = local(at);
  return d ? d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }) : "";
};

/** Human-readable value for the diff. */
export function ShowValue({ k, v }: { k: string; v: unknown }): ReactNode {
  if (v === undefined) return <span className="adm-muted">—</span>;
  if (v === null || v === "") return <span className="adm-muted">empty</span>;
  if (BOOL_KEYS.has(k) || typeof v === "boolean") return v === true || v === 1 || v === "1" ? "Yes" : "No";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) return fmt.date(v);
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return `${dayOf(v)} ${timeOf(v)}`;
  if (typeof v === "number") return Number.isInteger(v) ? fmt.num(v) : String(v);
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : <span className="adm-muted">none</span>;
  if (typeof v === "object") {
    const e = Object.entries(v as Record<string, unknown>);
    if (!e.length) return <span className="adm-muted">none</span>;
    return (
      <ul className="ad-diff__obj">
        {e.map(([kk, vv]) => (
          <li key={kk}>
            <span className="adm-muted">{`${fieldLabel(kk)}: `}</span>
            {vv && typeof vv === "object" && !Array.isArray(vv)
              ? Object.entries(vv as Record<string, unknown>)
                  .map(([a, b]) => `${fieldLabel(a)} ${b ?? "—"}`)
                  .join(" · ")
              : Array.isArray(vv)
                ? vv.join(", ")
                : String(vv ?? "—")}
          </li>
        ))}
      </ul>
    );
  }
  const s = String(v);
  if (/^https?:\/\//.test(s)) return <SrcLink src={s} label={s.length > 60 ? `${s.slice(0, 57)}…` : s} />;
  return s.length > 400 ? <span title={s}>{`${s.slice(0, 400)}…`}</span> : s;
}

export function AuditLog() {
  const [q, setQuery] = useQueryState();
  usePortalPage({ title: "Audit log", crumbs: [{ label: "Audit log" }] });
  const { form } = usePortalUi();
  const f: Record<(typeof FILTER_KEYS)[number], string> = {
    entity: PLURAL_TO_ENTITY[q.entity ?? ""] || q.entity || "",
    entity_id: q.entity_id ?? "",
    actor: q.actor ?? "",
    action: q.action ?? "",
    from: q.from ?? "",
    to: q.to ?? "",
  };
  const page = queryInt(q.page);
  const badRange = !!(f.from && f.to && f.from > f.to);
  const query = useMemo(() => {
    const x: Record<string, string | number> = { limit: PAGE + 1, offset: (page - 1) * PAGE };
    for (const k of FILTER_KEYS) if (f[k]) x[k] = f[k];
    return x;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, f.entity, f.entity_id, f.actor, f.action, f.from, f.to]);
  const { data, error, loading, reload } = usePortalQuery<unknown>(badRange ? null : "audit", { query, keepPrevious: true });
  const actorsQ = usePortalQuery<unknown>("audit/actors", { ttl: 120_000 });
  const fallbackActors = usePortalQuery<unknown>(actorsQ.error ? "audit" : null, { query: { limit: 1000 } });
  const [open, setOpen] = useState<Row | null>(null);

  // a date the server refuses (400 on from / to): drop the dates, like before
  useEffect(() => {
    if (isPortalApiError(error) && error.status === 400 && (error.fields.from || error.fields.to)) setQuery({ from: null, to: null, page: null });
  }, [error, setQuery]);

  const rows = useMemo(() => rowsOf<Row>(data).map((r) => ({ ...r, before: parse(r.before), after: parse(r.after) })), [data]);
  const more = rows.length > PAGE;
  const shown = rows.slice(0, PAGE);
  const actors = useMemo(() => {
    const a = actorsQ.data;
    if (Array.isArray(a)) return [...new Set(a.map((x) => (typeof x === "string" ? x : (x as { actor?: string })?.actor)).filter((x): x is string => !!x))].sort();
    return [...new Set(rowsOf<Row>(fallbackActors.data).map((r) => r.actor).filter(Boolean))].sort();
  }, [actorsQ.data, fallbackActors.data]);

  const activeFilters = FILTER_KEYS.some((k) => !!f[k]);
  const everEmpty = !!data && !shown.length && page === 1 && !activeFilters;
  const set = (patch: Record<string, string | null>) => setQuery({ ...patch, page: null }, { history: "auto" });
  const clear = () => setQuery({ entity: null, entity_id: null, actor: null, action: null, from: null, to: null, page: null }, { history: "auto" });

  const head = <PageHeader title="Audit log" sub="Every change is recorded with who made it and when. Open any row to see exactly what changed, before and after." />;
  if (!data && !badRange) {
    return (
      <div className="v-adm v-adm-audit">
        {head}
        {error && !loading ? <ErrorCard title="Could not load the audit log" error={error} retry={() => void reload()} /> : <Skeleton lines={5} />}
      </div>
    );
  }

  const sel = (label: string, key: (typeof FILTER_KEYS)[number], opts: [string, string][]) => (
    <label className="adm-inline">
      <span>{label}</span>
      <select className="td-input td-select" aria-label={label} value={f[key]} onChange={(e) => set({ [key]: e.target.value || null })}>
        {opts.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
  const dateIn = (label: string, key: "from" | "to") => (
    <label className="adm-inline">
      <span>{label}</span>
      <input type="date" className="td-input td-num" value={f[key]} max={today()} onChange={(e) => set({ [key]: e.target.value || null })} />
    </label>
  );
  const toolbar = (
    <div className="adm-toolbar ad-audit-filters">
      <div className="adm-toolbar__filters">
        {sel("Record type", "entity", [["", "All record types"], ...AUDIT_ENTITIES])}
        {sel("Action", "action", [
          ["", "Any action"],
          ["create", "Added"],
          ["update", "Changed"],
          ["delete", "Deleted"],
        ])}
        {sel("Changed by", "actor", [["", "Anyone"], ...actors.map((x): [string, string] => [x, x]), ...(f.actor && !actors.includes(f.actor) ? [[f.actor, f.actor] as [string, string]] : [])])}
        {/* record ids (c6, 12) mean nothing to people: the box only shows when a link opened the log for one record */}
        {f.entity_id ? <RecordIdInput value={f.entity_id} onChange={(v) => setQuery({ entity_id: v || null, page: null })} /> : null}
        {dateIn("From", "from")}
        {dateIn("To", "to")}
        <div className="td-field__error" aria-live="polite">
          {badRange ? "“From” is after “To”." : ""}
        </div>
      </div>
      {activeFilters ? (
        <div className="adm-toolbar__end">
          <Button icon="close" tone="ghost" size="sm" onClick={clear}>
            Clear filters
          </Button>
        </div>
      ) : null}
    </div>
  );

  const columns: Column<Row>[] = [
    {
      key: "at",
      label: "When",
      sortable: false,
      priority: 1,
      minWidth: 170,
      cardHidden: true,
      render: (r) => (
        <span className="ad-when" title={r.at}>
          {dayOf(r.at)}
          <small className="adm-muted">{` ${timeOf(r.at)}`}</small>
        </span>
      ),
    },
    { key: "actor", label: "Who", sortable: false, priority: 2, minWidth: 140, cardHidden: true, render: (r) => r.actor || "—" },
    { key: "action", label: "What", sortable: false, priority: 1, minWidth: 110, cardHidden: true, render: (r) => <Badge tone={TONE[r.action] ?? "neutral"}>{ACT_LABEL[r.action] ?? r.action}</Badge> },
    {
      key: "entity",
      label: "Record",
      primary: true,
      sortable: false,
      priority: 1,
      minWidth: 260,
      render: (r) => {
        const href = recordHref(r);
        const nm = recordName(r);
        return (
          <span className="ad-rec">
            <span className="adm-muted">{entName(r.entity)}</span>{" "}
            {href ? (
              <Link to={href} onClick={(e) => e.stopPropagation()}>
                {nm || `#${r.entity_id}`}
              </Link>
            ) : (
              <strong>{nm || `#${r.entity_id ?? ""}`}</strong>
            )}
          </span>
        );
      },
    },
    {
      key: "fields",
      label: "Changed",
      sortable: false,
      priority: 3,
      minWidth: 200,
      render: (r) => {
        if (r.action !== "update") return <span className="adm-muted">{r.action === "create" ? "new record" : "record removed"}</span>;
        const c = changedFields(r);
        return c.length ? (
          <span className="ad-fields">
            {c.slice(0, 3).map(fieldLabel).join(", ")}
            {c.length > 3 ? <span className="adm-muted">{` +${c.length - 3} more`}</span> : null}
          </span>
        ) : (
          <span className="adm-muted">no visible change</span>
        );
      },
    },
  ];

  return (
    <div className="v-adm v-adm-audit">
      {head}
      {everEmpty ? null : form === "phone" ? (
        <details className="ad-filt" open={activeFilters || undefined}>
          <summary>
            <Icon name="filter" size={16} />
            {activeFilters ? "Filters (on)" : "Filter changes"}
          </summary>
          {toolbar}
        </details>
      ) : (
        toolbar
      )}
      <div className="ad-audit-host" aria-live="polite" aria-busy={loading || undefined}>
        {everEmpty ? (
          <EmptyState title="No changes recorded yet" icon="audit" text="Whenever someone adds, edits or deletes anything — a target, an exam date, a team member — it appears here with their name and exactly what changed." />
        ) : error && data ? (
          <ErrorCard title="Could not load changes" error={error} retry={() => void reload()} />
        ) : shown.length ? (
          <DataTable<Row>
            caption="Changes, newest first"
            rowKey={(r) => r.id ?? `${r.at}|${r.entity}|${r.entity_id}`}
            cardSubtitle={(r) => `${r.actor || "unknown"} · ${dayOf(r.at)} ${timeOf(r.at)}`}
            cardMeta={(r) => [
              <Badge key="a" tone={TONE[r.action] ?? "neutral"}>
                {ACT_LABEL[r.action] ?? r.action}
              </Badge>,
            ]}
            columns={columns}
            rows={shown}
            onRowClick={setOpen}
            mobile="cards"
          />
        ) : (
          <EmptyState
            title={page > 1 ? "No more changes" : "No changes match these filters"}
            icon="filter"
            text="Clear a filter or pick a wider date range."
            actions={[{ label: "Clear filters", icon: "close", onClick: clear }]}
          />
        )}
        {page > 1 || more ? (
          <nav className="opk-pager ad-pager" aria-label="Pages">
            <span className="adm-muted">{`Changes ${fmt.num((page - 1) * PAGE + 1)}–${fmt.num((page - 1) * PAGE + shown.length)} (newest first)`}</span>
            <Button size="sm" disabled={page <= 1} onClick={() => setQuery({ page: page - 1 > 1 ? page - 1 : null }, { history: "auto" })}>
              Newer
            </Button>
            <span className="adm-muted">{`Page ${page}`}</span>
            <Button size="sm" disabled={!more} onClick={() => setQuery({ page: page + 1 }, { history: "auto" })}>
              Older
            </Button>
          </nav>
        ) : null}
      </div>
      {open ? <DiffDrawer r={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

function RecordIdInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  useEffect(() => {
    if (text.trim() === value) return;
    const t = setTimeout(() => onChange(text.trim()), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return (
    <label className="adm-inline">
      <span>One record</span>
      <input type="search" className="td-input" placeholder="e.g. c6 or 12" aria-label="Record reference" value={text} onChange={(e) => setText(e.target.value)} />
    </label>
  );
}

function DiffDrawer({ r, onClose }: { r: Row; onClose: () => void }) {
  const b = obj(r.before);
  const a = obj(r.after);
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])];
  const ch = new Set(changedFields(r));
  const [onlyChanged, setOnlyChanged] = useState(r.action === "update");
  const [raw, setRaw] = useState(false);
  const dev = devMode();
  const href = recordHref(r);
  const ks = keys.filter((k) => !onlyChanged || ch.has(k));
  return (
    <Drawer open title="Change details" onClose={onClose}>
      <div className="v-adm ad-diffwrap">
        <Kv
          pairs={[
            ["Who", r.actor || "unknown"],
            ["When", `${dayOf(r.at)} at ${timeOf(r.at)}`],
            ["What", `${ACT_LABEL[r.action] ?? r.action} ${entName(r.entity).toLowerCase()}`],
            ["Record", href ? <Link to={href}>{recordName(r) || `#${r.entity_id}`}</Link> : recordName(r) || `#${r.entity_id ?? ""}`],
          ]}
        />
        <div className="ad-diff__opts">
          {r.action === "update" ? (
            <label className="adm-toggle">
              <input type="checkbox" className="td-check" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
              <span>{`Only the ${ch.size} changed field${ch.size === 1 ? "" : "s"}`}</span>
            </label>
          ) : null}
          {/* the raw JSON is for developers only (?dev=1, same switch as the style guide) */}
          {dev ? (
            <label className="adm-toggle">
              <input type="checkbox" className="td-check" checked={raw} onChange={(e) => setRaw(e.target.checked)} />
              <span>Show raw data</span>
            </label>
          ) : null}
        </div>
        {raw && dev ? (
          <pre className="ad-raw">{JSON.stringify({ before: r.before, after: r.after }, null, 2)}</pre>
        ) : (
          <div className="ad-diff">
            {ks.map((k) => (
              <div key={k} className={ch.has(k) ? "ad-diff__row is-changed" : "ad-diff__row"}>
                <div className="ad-diff__key" title={k}>
                  {fieldLabel(k)}
                </div>
                {r.action !== "create" ? (
                  <div className="ad-diff__before">
                    <span className="ad-diff__tag">Before</span>
                    <ShowValue k={k} v={b[k]} />
                  </div>
                ) : null}
                {r.action !== "delete" ? (
                  <div className="ad-diff__after">
                    <span className="ad-diff__tag">After</span>
                    <ShowValue k={k} v={a[k]} />
                  </div>
                ) : null}
              </div>
            ))}
            {!ks.length ? <p className="adm-muted">No fields to show.</p> : null}
          </div>
        )}
      </div>
    </Drawer>
  );
}
