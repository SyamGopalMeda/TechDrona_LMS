/**
 * Data quality (/colleges/data) — port of js/views/admin.js `renderData`.
 * Tabs: To verify (college details / contact numbers, not verified yet / verified, "Mark verified" with a source),
 * Missing or doubtful (reliability bars, map locations, still-operating review, missing details) and Download
 * (CSVs, full JSON backup, demo-data card). URL: ?tab=verify|gaps|export&kind=colleges|contacts&show=pending|verified&page=
 * Respects the district scope.
 */
import "@/features/colleges/styles/views/admin.css";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { CONTACT_ROLE_LABEL, DialogForm, openDialog as openDialogSafe, TextAreaField, TextField, rowsOf, safeUrl, validationError } from "../forms";
import { portalApi } from "../lib/api";
import { fetchCached, usePortalQuery } from "../lib/cache";
import { downloadCsv } from "../lib/csv";
import { fmt, today } from "../lib/fmt";
import { queryInt, useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { scopeRows } from "../lib/scope";
import { usePortalSession } from "../lib/session";
import type { College, CollegeDetail, CollegeRow, Contact, PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { Button, ContactActions, DataTable, EmptyState, ErrorCard, Icon, Kpi, KpiRow, PageHeader, Section, Segmented, Skeleton, StatusBadge, StatusChip, Tabs, VerifiedBadge, toast, usePortalUi, type Column } from "../ui";
import { SrcLink, downloadText, fieldLabel, pool } from "./admin/shared";

/** College fields the verification queue tracks (R13 field_status keys). */
const VERIFY_FIELDS = ["name", "district_id", "city_id", "phone", "email", "website", "ownership", "affiliation", "op_status"];
const EXPORTS: [string, string][] = [
  ["branches", "Branches"],
  ["people", "Team (leads & ambassadors)"],
  ["targets", "Targets"],
  ["enrollments", "Enrollments"],
  ["activities", "Outreach activities"],
  ["followups", "Follow-ups"],
  ["contacts", "College contacts"],
  ["courses", "Courses"],
];
const PAGE_V = 15;

interface Quality {
  missing?: { field: string; label?: string; count: number; college_ids?: string[] }[];
  basis_counts?: { verified?: number; estimated?: number; pending?: number };
  [k: string]: unknown;
}
type Detail = (College & { field_status?: Record<string, string>; op_2025_26?: string | null; op_2026_27?: string | null; op_status_source?: string | null }) | null;
type ContactRow = Contact & { college_label?: string; district_id?: string; source_url?: string | null; notes?: string | null };

interface Ctx {
  colleges: CollegeRow[];
  meta: PortalMeta | undefined;
  dName: Map<string, string>;
  cMap: Map<string, CollegeRow>;
  quality: Quality;
  v4: boolean;
  canWrite: boolean;
  reload: () => void;
}

export function DataQuality() {
  const [q, setQuery] = useQueryState();
  usePortalPage({ title: "Data quality", crumbs: [{ label: "Data quality" }] });
  const tab = ["verify", "gaps", "export"].includes(q.tab ?? "") ? q.tab! : "verify";
  const kind = q.kind === "contacts" ? "contacts" : "colleges";
  const show = q.show === "verified" ? "verified" : "pending";
  const page = queryInt(q.page);
  const { canWrite } = usePortalUi();

  const qual = usePortalQuery<Quality>("quality", { scoped: true });
  const cols = usePortalQuery<unknown>("colleges", { scoped: true });
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });

  const ctx = useMemo((): Ctx | null => {
    if (!qual.data || cols.data === undefined || !meta.data) return null;
    const colleges = scopeRows(rowsOf<CollegeRow>(cols.data) as unknown as Record<string, unknown>[]) as unknown as CollegeRow[];
    const inScope = new Set(colleges.map((c) => String(c.id)));
    // /quality on older servers ignores districts=: keep only colleges in scope
    const quality: Quality = {
      ...qual.data,
      missing: (qual.data.missing ?? []).map((m) => {
        const ids = (m.college_ids ?? []).map(String).filter((id) => inScope.has(id));
        return { ...m, college_ids: ids, count: ids.length };
      }),
    };
    return {
      colleges,
      meta: meta.data,
      dName: new Map((meta.data.districts ?? []).map((d) => [d.id, d.name])),
      cMap: new Map(colleges.map((c) => [String(c.id), c])),
      quality,
      v4: colleges.some((c) => "data_status" in c),
      canWrite,
      reload: () => {
        void qual.reload();
        void cols.reload();
      },
    };
  }, [qual.data, cols.data, meta.data, canWrite]); // eslint-disable-line react-hooks/exhaustive-deps

  const head = <PageHeader title="Data quality" sub="Check college details and contact numbers against a source, fill in what is missing, and download the data." scope />;
  const err = qual.error ?? cols.error ?? meta.error;
  if (!ctx) {
    return (
      <div className="v-adm v-adm-data">
        {head}
        {err ? <ErrorCard title="Could not load data quality" error={err} retry={() => (void qual.reload(), void cols.reload(), void meta.reload())} /> : <Skeleton lines={4} />}
      </div>
    );
  }

  const sync = (patch: { tab?: string; kind?: string; show?: string; page?: number }) => {
    const n = { tab, kind, show, page, ...patch };
    setQuery(
      {
        tab: n.tab === "verify" ? null : n.tab,
        kind: n.tab === "verify" && n.kind !== "colleges" ? n.kind : null,
        show: n.tab === "verify" && n.show !== "pending" ? n.show : null,
        page: n.tab === "verify" && n.page > 1 ? n.page : null,
      },
      { history: "auto" },
    );
  };
  const unver = ctx.colleges.filter((c) => c.data_status && c.data_status !== "verified").length;

  return (
    <div className="v-adm v-adm-data">
      {head}
      <KpiRow>
        {dataKpis(ctx).map((k) => (
          <Kpi key={String(k.label)} {...k} />
        ))}
      </KpiRow>
      <Tabs
        active={tab}
        onChange={(id) => sync({ tab: id, page: 1 })}
        tabs={[
          { id: "verify", label: "To verify", count: ctx.v4 ? unver : undefined, render: () => <VerifyPanel ctx={ctx} kind={kind} show={show} page={page} sync={sync} /> },
          { id: "gaps", label: "Missing or doubtful", count: (ctx.quality.missing ?? []).reduce((s, m) => s + (m.count ? 1 : 0), 0), render: () => <GapsPanel ctx={ctx} /> },
          { id: "export", label: "Download", render: () => <ExportPanel ctx={ctx} /> },
        ]}
      />
    </div>
  );
}

function dataKpis(ctx: Ctx) {
  const n = ctx.colleges.length;
  const by: Record<string, number> = { verified: 0, partly: 0, unverified: 0 };
  for (const c of ctx.colleges) if (c.data_status) by[c.data_status] = (by[c.data_status] ?? 0) + 1;
  const bc = ctx.quality.basis_counts ?? {};
  const tot = (bc.verified || 0) + (bc.estimated || 0) + (bc.pending || 0);
  const k: { label: string; value: string; sub: string; icon: string; tone?: "good" | "warn" }[] = [{ label: "Colleges in view", value: fmt.num(n), sub: "in the selected districts", icon: "college" }];
  if (ctx.v4) k.push({ label: "Colleges fully verified", value: fmt.num(by.verified), sub: `${fmt.num(by.partly)} partly · ${fmt.num(by.unverified)} not yet`, tone: by.verified ? "good" : undefined, icon: "check" });
  // "numbers" here are branch seat / student figures, not phone numbers
  k.push({ label: "Verified student figures", value: tot ? fmt.pct((bc.verified || 0) / tot) : "—", sub: `${fmt.num(bc.verified || 0)} of ${fmt.num(tot)} branch figures`, icon: "data" });
  const op = (ctx.quality.missing ?? []).find((m) => m.field === "op_status");
  k.push({ label: "Still open? To confirm", value: fmt.num(op?.count || 0), sub: "possibly closed or not known", tone: op?.count ? "warn" : "good", icon: "warn" });
  return k;
}

/* ------------------------------------------------------------------ to verify */

function VerifyPanel({ ctx, kind, show, page, sync }: { ctx: Ctx; kind: string; show: string; page: number; sync: (p: { kind?: string; show?: string; page?: number }) => void }) {
  return (
    <div className="ad-verify">
      <div className="ad-verify__bar">
        <Segmented
          ariaLabel="What to verify"
          value={kind}
          onChange={(v) => sync({ kind: v, page: 1 })}
          options={[
            { value: "colleges", label: "College details" },
            { value: "contacts", label: "Contact numbers" },
          ]}
        />
        <Segmented
          ariaLabel="Which records"
          value={show}
          onChange={(v) => sync({ show: v, page: 1 })}
          options={[
            { value: "pending", label: "Not verified yet" },
            { value: "verified", label: "Verified" },
          ]}
        />
      </div>
      <p className="adm-muted ad-verify__help">
        {kind === "colleges"
          ? "A college detail counts as verified only when someone checked it against a source (official website, AICTE/university listing, a call to the office). Typing a value without a source leaves it unverified."
          : "A contact is verified when its number or email was confirmed from an official page or by the college itself."}
      </p>
      {kind === "colleges" ? <CollegeQueue ctx={ctx} show={show} page={page} onPage={(p) => sync({ page: p })} /> : <ContactQueue ctx={ctx} show={show} page={page} onPage={(p) => sync({ page: p })} />}
    </div>
  );
}

function parseVF(v: unknown): Record<string, { verified_on?: string; verified_by?: string; source?: string } | undefined> {
  if (!v) return {};
  if (typeof v === "object") return v as Record<string, never>;
  try {
    return (JSON.parse(String(v)) as Record<string, never>) || {};
  } catch {
    return {};
  }
}

function CollegeQueue({ ctx, show, page, onPage }: { ctx: Ctx; show: string; page: number; onPage: (p: number) => void }) {
  const list = useMemo(
    () =>
      ctx.colleges
        .filter(show === "verified" ? (c) => c.data_status === "verified" || c.data_status === "partly" : (c) => c.data_status !== "verified")
        .sort((a, b) => (b.targeted ? 1 : 0) - (a.targeted ? 1 : 0) || (a.sno ?? 0) - (b.sno ?? 0)),
    [ctx.colleges, show],
  );
  const pages = Math.max(1, Math.ceil(list.length / PAGE_V));
  const cur = Math.min(page, pages);
  const rows = list.slice((cur - 1) * PAGE_V, cur * PAGE_V);
  const [details, setDetails] = useState<Map<string, Detail>>(() => new Map());
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [bump, setBump] = useState(0);

  useEffect(() => {
    const need = rows.filter((c) => !details.has(String(c.id)));
    if (!need.length) return;
    let live = true;
    setLoadingDetails(true);
    void pool(need, 6, (c) => fetchCached<CollegeDetail & { field_status?: Record<string, string> }>(`colleges/${encodeURIComponent(c.id)}`)).then((got) => {
      if (!live) return;
      setDetails((m) => {
        const n = new Map(m);
        need.forEach((c, i) => {
          const g = got[i];
          n.set(String(c.id), g?.college ? ({ ...g.college, field_status: (g.college.field_status as Record<string, string> | undefined) || g.field_status } as Detail) : null);
        });
        return n;
      });
      setLoadingDetails(false);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows.map((r) => r.id).join(","), bump]);

  if (!ctx.v4) {
    return <EmptyState icon="warn" title="College details cannot be verified here yet" text="This server is out of date. Contact numbers can still be verified: choose “Contact numbers” above." />;
  }
  const columns: Column<CollegeRow>[] = [
    {
      key: "name",
      label: "College",
      primary: true,
      sortable: false,
      priority: 1,
      minWidth: 220,
      render: (c) => (
        <div className="ad-vq-name">
          <Link to={portalPath.college(c.id)}>{c.short_name || c.name}</Link>
          <span className="adm-muted">{[ctx.dName.get(c.district_id), c.targeted ? "targeted" : null].filter(Boolean).join(" · ")}</span>
        </div>
      ),
    },
    {
      key: "data_status",
      label: "Status",
      sortable: false,
      priority: 1,
      minWidth: 140,
      render: (c) => <StatusChip status={c.data_status === "partly" ? "unverified" : c.data_status} label={({ verified: "Verified", partly: "Partly verified", unverified: "Not verified" } as Record<string, string>)[c.data_status ?? ""]} />,
    },
    { key: "fields", label: "Details checked", sortable: false, priority: 2, minWidth: 280, render: (c) => <FieldChips d={details.get(String(c.id))} loaded={details.has(String(c.id))} /> },
    { key: "last", label: "Last verified", sortable: false, priority: 3, minWidth: 160, hideOnPhone: true, render: (c) => <LastVerified d={details.get(String(c.id))} /> },
  ];
  const refresh = (id: string) => {
    setDetails((m) => {
      const n = new Map(m);
      n.delete(id);
      return n;
    });
    setBump((b) => b + 1);
    ctx.reload();
  };
  return (
    <DataTable<CollegeRow>
      columns={columns}
      rows={rows}
      rowKey={(c) => c.id}
      loading={loadingDetails && rows.some((c) => !details.has(String(c.id)))}
      page={cur}
      pageSize={PAGE_V}
      total={list.length}
      pageLabel="colleges"
      onPage={onPage}
      rowActions={(c) => [
        {
          label: show === "verified" ? "Verify more" : "Mark verified",
          icon: "check",
          tone: "primary",
          writeOnly: true,
          hidden: !ctx.canWrite,
          onClick: () => markCollegeVerified(ctx, c, details.get(String(c.id)) ?? null, () => refresh(String(c.id))),
        },
      ]}
      empty={
        show === "verified" ? (
          <EmptyState icon="check" title="Nothing verified yet" text="Colleges appear here once someone marks at least one detail verified with a source." />
        ) : (
          <EmptyState icon="check" title="Every college in view is verified" text="Nice. Widen the district selection to check more colleges." />
        )
      }
    />
  );
}

function FieldChips({ d, loaded }: { d: Detail | undefined; loaded: boolean }) {
  if (!d) return <span className="adm-muted">{loaded ? "Could not load" : "…"}</span>;
  const fs = d.field_status ?? {};
  const vf = parseVF(d.verified_fields);
  return (
    <div className="ad-vq-fields">
      {VERIFY_FIELDS.filter((f) => f in fs || vf[f]).map((f) => {
        const st = fs[f] || (vf[f] ? "verified" : "unverified");
        const v = vf[f];
        return (
          <span
            key={f}
            className={`ad-vq-f is-${st}`}
            title={st === "verified" && v ? `Verified ${v.verified_on || ""} by ${v.verified_by || "unknown"}${v.source ? ` · ${v.source}` : ""}` : st === "missing" ? "No value recorded" : "Has a value but no source yet"}
          >
            <span className="ad-vq-f__k">{fieldLabel(f)}</span>
            <span className="ad-vq-f__v">{st === "verified" ? "✓" : st === "missing" ? "missing" : "not verified"}</span>
          </span>
        );
      })}
    </div>
  );
}

function LastVerified({ d }: { d: Detail | undefined }) {
  const vf = Object.entries(parseVF(d?.verified_fields));
  if (!vf.length) return <span className="adm-muted">Never</span>;
  const last = vf.sort((a, b) => String(b[1]?.verified_on || "").localeCompare(String(a[1]?.verified_on || "")))[0]![1];
  return (
    <div className="ad-vq-last">
      <span>{fmt.date(last?.verified_on)}</span>
      <small className="adm-muted">{`by ${last?.verified_by || "unknown"}`}</small>
      {last?.source ? <SrcLink src={last.source} label={null} /> : null}
    </div>
  );
}

/** Source link + checked-on date + note; onSave gets {source, date, note}. */
function VerifyDialog({
  title,
  intro,
  source = "",
  extraFields,
  onSave,
  onDone,
}: {
  title: string;
  intro?: ReactNode;
  source?: string | null;
  extraFields?: (err: Record<string, string>) => ReactNode;
  onSave: (v: { source: string; date: string; note?: string }) => Promise<void>;
  onDone: (r: boolean | null) => void;
}) {
  const [src, setSrc] = useState(safeUrl(source) ?? "");
  const [date, setDate] = useState(today());
  const [note, setNote] = useState("");
  return (
    <DialogForm<boolean>
      title={title}
      submitLabel="Mark verified"
      className="v-adm ad-vdlg"
      intro={intro ? <p>{intro}</p> : null}
      onDone={onDone}
      onSubmit={async () => {
        const s = src.trim();
        const errs: Record<string, string> = {};
        if (!s) errs.source = "Paste the link where you checked this.";
        else if (!safeUrl(s)) errs.source = "Use a full link starting with https://";
        if (!date) errs.date = "Pick the date.";
        else if (date > today()) errs.date = "Cannot be in the future.";
        if (Object.keys(errs).length) throw validationError(errs);
        const n = [note.trim(), date !== today() ? `checked on ${date}` : ""].filter(Boolean).join(" · ");
        await onSave({ source: s, date, note: n || undefined });
        return true;
      }}
    >
      {(err) => (
        <>
          {extraFields?.(err)}
          <TextField name="source" label="Source link" type="url" required full value={src} onChange={setSrc} placeholder="https://… (official page, notice or listing)" help="Where you checked it. Must start with http:// or https://." error={err.source} />
          <TextField name="date" label="Checked on" type="date" required value={date} onChange={setDate} max={today()} help="The day you looked at the source." error={err.date} />
          <TextField name="note" label="Note" value={note} onChange={setNote} maxLength={300} placeholder="e.g. Confirmed by phone with the office on 6 Nov" help="Optional." />
        </>
      )}
    </DialogForm>
  );
}

function fieldValue(ctx: Ctx, d: Detail, f: string): string {
  const v = (d as Record<string, unknown> | null)?.[f];
  if (f === "district_id") return ctx.dName.get(String(v)) || (v ? String(v) : "—");
  if (f === "city_id") return (ctx.meta?.cities ?? []).find((x) => x.id === v)?.name || (v ? String(v) : "—");
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

function CollegeVerifyFields({ ctx, d, can, picked, setPicked, err }: { ctx: Ctx; d: Detail; can: string[]; picked: Set<string>; setPicked: (s: Set<string>) => void; err?: string }) {
  const fs = d?.field_status ?? {};
  return (
    <fieldset className="ad-vdlg__fs td-field--full" data-field="fields">
      <legend>Details checked</legend>
      {can.map((f) => (
        <label key={f} className="adm-toggle ad-vdlg__f">
          <input
            type="checkbox"
            className="td-check"
            checked={picked.has(f)}
            onChange={(e) => {
              const n = new Set(picked);
              if (e.target.checked) n.add(f);
              else n.delete(f);
              setPicked(n);
            }}
          />
          <span>
            {fieldLabel(f)}: <strong>{fieldValue(ctx, d, f)}</strong>
            {fs[f] === "verified" ? <small className="adm-muted"> (already verified)</small> : null}
          </span>
        </label>
      ))}
      <div className="td-field__error" aria-live="polite">
        {err ?? ""}
      </div>
    </fieldset>
  );
}

function markCollegeVerified(ctx: Ctx, c: CollegeRow, d: Detail, done: () => void): void {
  const fs = d?.field_status ?? {};
  const can = VERIFY_FIELDS.filter((f) => fs[f] && fs[f] !== "missing");
  if (!can.length) {
    toast("This college has no recorded details to verify yet. Open the college and fill them in first.", "warn");
    return;
  }
  void openDialogSafe<boolean>((close) => <CollegeVerify ctx={ctx} c={c} d={d} can={can} onDone={(r) => (close(r), r && done())} />);
}

function CollegeVerify({ ctx, c, d, can, onDone }: { ctx: Ctx; c: CollegeRow; d: Detail; can: string[]; onDone: (r: boolean | null) => void }) {
  const fs = d?.field_status ?? {};
  const [picked, setPicked] = useState(() => new Set(can.filter((f) => fs[f] !== "verified")));
  return (
    <VerifyDialog
      title={`Verify details — ${c.short_name || c.name}`}
      intro="Tick the details you checked against the source. Each ticked detail is stamped with your name, the date and the link."
      source={d?.website}
      extraFields={(err) => <CollegeVerifyFields ctx={ctx} d={d} can={can} picked={picked} setPicked={setPicked} err={err.fields} />}
      onDone={onDone}
      onSave={async ({ source, note }) => {
        const fields = can.filter((f) => picked.has(f));
        if (!fields.length) throw validationError({ fields: "Tick at least one detail." });
        await portalApi.post(`colleges/${encodeURIComponent(c.id)}/verify`, { fields, source, note, verified: true });
        toast(`${fields.length} detail${fields.length === 1 ? "" : "s"} of ${c.short_name || c.name} marked verified`, "good");
      }}
    />
  );
}

function ContactQueue({ ctx, show, page, onPage }: { ctx: Ctx; show: string; page: number; onPage: (p: number) => void }) {
  const { data, error, loading, reload } = usePortalQuery<unknown>("contacts", { scoped: true, query: { basis: show === "verified" ? "verified" : "pending" } });
  const list = useMemo(
    () =>
      (scopeRows(rowsOf<ContactRow>(data) as unknown as Record<string, unknown>[]) as unknown as ContactRow[]).sort(
        (a, b) => String(b.verified_on || "").localeCompare(String(a.verified_on || "")) || String(a.college_label).localeCompare(String(b.college_label)),
      ),
    [data],
  );
  const pages = Math.max(1, Math.ceil(list.length / PAGE_V));
  const cur = Math.min(page, pages);
  const columns: Column<ContactRow>[] = [
    {
      key: "name",
      label: "Contact",
      primary: true,
      sortable: false,
      priority: 1,
      minWidth: 200,
      render: (k) => (
        <div className="ad-vq-name">
          <strong>{k.name || "No name recorded"}</strong>
          <span className="adm-muted">{CONTACT_ROLE_LABEL[k.role] || String(k.role || "").replace(/_/g, " ")}</span>
        </div>
      ),
    },
    {
      key: "college",
      label: "College",
      sortable: false,
      priority: 2,
      minWidth: 180,
      render: (k) => (
        <div className="ad-vq-name">
          <Link to={`${portalPath.college(k.college_id)}?tab=contacts`}>{k.college_label || k.college_id}</Link>
          <span className="adm-muted">{ctx.dName.get(k.district_id ?? "") || ""}</span>
        </div>
      ),
    },
    { key: "reach", label: "Phone / email", sortable: false, priority: 1, minWidth: 200, render: (k) => <ContactActions phone={k.phone} email={k.email} name={k.name} compact /> },
    {
      key: "basis",
      label: "Verified?",
      sortable: false,
      priority: 2,
      minWidth: 130,
      render: (k) => <VerifiedBadge state={k.basis === "verified" ? "verified" : "unverified"} source={k.source_url} date={k.verified_on} by={k.verified_by} />,
    },
    {
      key: "src",
      label: show === "verified" ? "Verified by" : "Found at",
      sortable: false,
      priority: 3,
      minWidth: 180,
      hideOnPhone: true,
      render: (k) => (
        <div className="ad-vq-last">
          {show === "verified" ? <span>{k.verified_by ? `${k.verified_by}${k.verified_on ? `, ${fmt.date(k.verified_on)}` : ""}` : "Not recorded"}</span> : null}
          {safeUrl(k.source_url) || k.source_url ? <SrcLink src={k.source_url} label={null} /> : <span className="adm-muted">no link</span>}
        </div>
      ),
    },
  ];
  const verify = (k: ContactRow) =>
    void openDialogSafe<boolean>((close) => (
      <VerifyDialog
        title={`Verify contact — ${k.name || k.college_label}`}
        intro={
          <span>
            <strong>{[k.name, k.phone, k.email].filter(Boolean).join(" · ")}</strong>
            {` at ${k.college_label}. Confirm the number or email against an official page, or by calling the college.`}
          </span>
        }
        source={k.source_url}
        onDone={close}
        onSave={async ({ source, note }) => {
          const notes = note ? [k.notes, `[${today()}] Verified: ${note}`].filter(Boolean).join("\n") : undefined;
          await portalApi.patch(`contacts/${k.id}`, { basis: "verified", source_url: source, ...(notes ? { notes } : {}) });
          toast(`${k.name || "Contact"} marked verified`, "good");
          void reload();
        }}
      />
    ));
  return (
    <DataTable<ContactRow>
      columns={columns}
      rows={data === undefined ? undefined : list.slice((cur - 1) * PAGE_V, cur * PAGE_V)}
      rowKey={(k) => k.id}
      loading={loading && data === undefined}
      error={data === undefined ? error : null}
      onRetry={() => void reload()}
      page={cur}
      pageSize={PAGE_V}
      total={list.length}
      pageLabel="contacts"
      onPage={onPage}
      rowActions={(k) => (k.basis === "verified" ? [] : [{ label: "Mark verified", icon: "check", tone: "primary", writeOnly: true, hidden: !ctx.canWrite, onClick: () => verify(k) }])}
      empty={
        show === "verified" ? (
          <EmptyState icon="phone" title="No verified contacts in view" text="Contacts marked verified appear here with who checked them and when." />
        ) : (
          <EmptyState icon="check" title="Every contact in view is verified" text="Widen the district selection to check more." />
        )
      }
    />
  );
}

/* ------------------------------------------------------------------ missing or doubtful */

function CollegeLinks({ ids, cMap, max = 12 }: { ids: string[]; cMap: Map<string, CollegeRow>; max?: number }) {
  const [n, setN] = useState(max);
  return (
    <div className="adm-chips">
      {ids.slice(0, n).map((id) => (
        <Link key={id} className="adm-chip" to={portalPath.college(id)} title={cMap.get(id)?.name || id}>
          {cMap.get(id)?.short_name || cMap.get(id)?.name || id}
        </Link>
      ))}
      {ids.length > n ? (
        <button type="button" className="adm-chip adm-chip--more" onClick={() => setN(ids.length)}>
          {`+${ids.length - n} more`}
        </button>
      ) : null}
    </div>
  );
}

function GapsPanel({ ctx }: { ctx: Ctx }) {
  const { colleges, quality, cMap } = ctx;
  const bc = quality.basis_counts ?? {};
  const total = (bc.verified || 0) + (bc.estimated || 0) + (bc.pending || 0);
  const missing = [...(quality.missing ?? [])].filter((m) => m.count).sort((a, b) => b.count - a.count);
  const pendingGeo = colleges.filter((c) => c.geo_precision === "pending" || c.lat === null || c.lat === undefined || c.lng === null || c.lng === undefined);
  const approxGeo = colleges.filter((c) => c.geo_precision === "town" || c.geo_precision === "district");
  const review = colleges.filter((c) => c.op_status === "possibly_closed" || c.op_status === "pending");
  const BARS: [keyof typeof bc, string, string][] = [
    ["verified", "Verified", "from an official or first-hand source"],
    ["estimated", "Estimated", "worked out from other numbers, e.g. strength = intake × 4"],
    ["pending", "Pending", "not known yet"],
  ];
  return (
    <div className="ad-gaps">
      <div className="ad-grid">
        <Section title="How reliable are our numbers?" sub={`${fmt.num(total)} branch figures (intake, strength, final year, eligible)`}>
          <div className="ad-bars">
            {BARS.map(([k, l, help]) => (
              <div className="ad-bar-row" key={k}>
                <div className="ad-bar-row__label">
                  <strong>{l}</strong>
                  <span className="adm-muted">{help}</span>
                </div>
                <div className="ad-bar" role="img" aria-label={`${l}: ${fmt.num(bc[k] || 0)} values (${total ? fmt.pct((bc[k] || 0) / total) : "0%"})`}>
                  <i className={`t-${k}`} style={{ width: total ? `${((bc[k] || 0) / total) * 100}%` : "0" }} />
                </div>
                <span className="ad-bar-row__n td-num">
                  {fmt.num(bc[k] || 0)}
                  <small className="adm-muted">{total ? ` ${fmt.pct((bc[k] || 0) / total)}` : ""}</small>
                </span>
              </div>
            ))}
          </div>
        </Section>
        <Section title="Map locations">
          <div className="ad-geo">
            <div className="ad-geo__n">
              <strong className="td-num">{fmt.num(colleges.length - pendingGeo.length)}</strong>
              <span className="adm-muted">{` of ${fmt.num(colleges.length)} colleges are on the map`}</span>
            </div>
            {approxGeo.length ? <p className="adm-muted">{`${fmt.num(approxGeo.length)} are placed at town or district level (approximate pins).`}</p> : null}
            {pendingGeo.length ? (
              <div>
                <p className="adm-muted">Missing a location:</p>
                <CollegeLinks ids={pendingGeo.map((c) => String(c.id))} cMap={cMap} max={20} />
              </div>
            ) : (
              <p className="ad-ok">
                <Icon name="check" size={16} />
                Every college in view has a map location.
              </p>
            )}
          </div>
        </Section>
      </div>
      <Section title={`Is the college still operating? (${review.length})`} sub="Colleges marked “possibly closed” or “pending”. Check the evidence and confirm.">
        <OpReview ctx={ctx} review={review} />
      </Section>
      <Section title="Missing details" sub="Sorted by how many colleges are affected. Open a college to fix it.">
        {missing.length ? (
          <DataTable
            columns={[
              { key: "label", label: "What is missing", render: (r) => <strong>{r.label || fieldLabel(r.field)}</strong>, sortValue: (r) => r.label || fieldLabel(r.field) },
              { key: "count", label: "Colleges", align: "right" },
              { key: "college_ids", label: "Open a college to fix it", sortable: false, render: (r) => <CollegeLinks ids={(r.college_ids ?? []).map(String)} cMap={cMap} max={10} /> },
            ]}
            rows={missing}
            rowKey={(r) => r.field}
            mobile="cards"
          />
        ) : (
          <EmptyState title="Nothing is missing" icon="check" text="Every tracked field has a value for the colleges in view." />
        )}
      </Section>
    </div>
  );
}

function OpReview({ ctx, review }: { ctx: Ctx; review: CollegeRow[] }) {
  const [details, setDetails] = useState<(CollegeDetail | null)[] | null>(null);
  const [shown, setShown] = useState(10);
  const ids = review.map((c) => c.id).join(",");
  useEffect(() => {
    let live = true;
    setDetails(null);
    void pool(review, 6, (c) => fetchCached<CollegeDetail>(`colleges/${encodeURIComponent(c.id)}`)).then((d) => live && setDetails(d));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids]);
  if (!review.length) return <EmptyState title="Nothing to review" icon="check" text="No college in view is marked “possibly closed” or “pending”." />;
  if (!details) return <Skeleton lines={2} card={false} />;
  return (
    <div className="ad-review">
      <ul className="adm-list">
        {review.slice(0, shown).map((c, i) => {
          const d = (details[i]?.college ?? {}) as Partial<College> & { op_2025_26?: string; op_2026_27?: string; op_status_source?: string };
          return (
            <li className="adm-list__row ad-review-row" key={c.id}>
              <div className="ad-review-main">
                <div className="ad-review-title">
                  <Link to={portalPath.college(c.id)}>{c.name}</Link> <StatusBadge kind="op_status" value={c.op_status} /> <span className="adm-muted">{ctx.dName.get(c.district_id) || ""}</span>
                </div>
                <p className="ad-evidence">{d.op_status_note || "No evidence recorded yet."}</p>
                <div className="ad-review-meta">
                  <SrcLink src={d.op_status_source} />
                  {d.op_2025_26 || d.op_2026_27 ? <span className="adm-muted">{`Admissions 2025-26: ${d.op_2025_26 || "unknown"} · 2026-27: ${d.op_2026_27 || "unknown"}`}</span> : null}
                </div>
              </div>
              {ctx.canWrite ? (
                <div className="ad-review-actions">
                  <Button icon="check" size="sm" onClick={() => setOp(ctx, c, "operational")}>
                    Still operating
                  </Button>
                  <Button tone="danger" size="sm" onClick={() => setOp(ctx, c, "closed")}>
                    Closed
                  </Button>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {review.length > shown ? (
        <div className="ad-more">
          <Button onClick={() => setShown(review.length)}>{`Show all ${review.length}`}</Button>
        </div>
      ) : null}
    </div>
  );
}

function setOp(ctx: Ctx, c: CollegeRow, status: "operational" | "closed"): void {
  void openDialogSafe<boolean>((close) => <OpDialog c={c} status={status} onDone={(r) => (close(r), r && ctx.reload())} />);
}

function OpDialog({ c, status, onDone }: { c: CollegeRow; status: "operational" | "closed"; onDone: (r: boolean | null) => void }) {
  const [note, setNote] = useState("");
  const [src, setSrc] = useState("");
  return (
    <DialogForm<boolean>
      title="Update operating status"
      className="v-adm"
      submitLabel={status === "closed" ? "Mark closed" : "Save"}
      danger={status === "closed"}
      intro={
        <>
          <p>
            Mark <strong>{c.name}</strong> as <strong>{status === "closed" ? "closed" : "operational"}</strong>?
          </p>
          {status === "closed" ? <p className="ad-warnline">Closed colleges drop out of the call queue and the planner.</p> : null}
        </>
      }
      onDone={onDone}
      onSubmit={async (key) => {
        const errs: Record<string, string> = {};
        if (!note.trim()) errs.note = "Add a short note so others can see why this changed.";
        const s = src.trim();
        if (s && !safeUrl(s)) errs.src = "Use a full link starting with https://, or leave it empty.";
        if (Object.keys(errs).length) throw validationError(errs);
        await portalApi.patch(
          `colleges/${encodeURIComponent(c.id)}`,
          { op_status: status, op_status_note: `${note.trim()} [${today()}]`, ...(s ? { op_status_source: s, sources: { op_status: s } } : {}) },
          { idempotencyKey: key },
        );
        toast(`${c.name} marked ${status === "closed" ? "closed" : "operational"}`, "good");
        return true;
      }}
    >
      {(err) => (
        <>
          <TextAreaField name="note" label="Evidence" required value={note} onChange={setNote} placeholder='How do you know? e.g. "Called the office on 3 Nov; admissions open for 2026-27"' error={err.note} />
          <TextField name="src" label="Source link" type="url" full value={src} onChange={setSrc} placeholder="https://… (optional)" help="With a link, the status is stamped verified." error={err.src} />
        </>
      )}
    </DialogForm>
  );
}

/* ------------------------------------------------------------------ download */

const colsOf = (rows: Record<string, unknown>[]) => [...new Set(rows.flatMap((r) => Object.keys(r)))];
function csvOf(name: string, rows: Record<string, unknown>[], cols: string[]): void {
  downloadCsv(name, [cols, ...rows.map((r) => cols.map((k) => r[k] as never))]);
}

/** Colleges CSV (same columns as before). */
export function collegesCsvRows(colleges: CollegeRow[], dName: Map<string, string>): { cols: string[]; rows: Record<string, unknown>[] } {
  const rows = colleges.map((c) => {
    const x = c as CollegeRow & Record<string, unknown>;
    const cl = x.college_lead as { full_name?: string; name?: string } | string | null | undefined;
    const nf = x.next_followup as { due_date?: string } | string | null | undefined;
    const ne = c.next_exam;
    return {
      ...x,
      district: dName.get(c.district_id) || c.district_id,
      strength: c.strength?.value,
      strength_basis: c.strength?.basis,
      eligible: c.eligible?.value,
      eligible_basis: c.eligible?.basis,
      college_lead: c.lead?.name || (cl && typeof cl === "object" ? cl.full_name || cl.name : cl),
      ambassador_leads: Array.isArray(x.ambassador_leads) ? (x.ambassador_leads as unknown[]).length : x.ambassador_leads,
      ambassadors: c.ambassador_count ?? (Array.isArray(x.ambassadors) ? (x.ambassadors as unknown[]).length : x.ambassadors),
      branches: Array.isArray(x.branches) ? (x.branches as unknown[]).length : x.branches,
      next_exam: ne ? `${ne.semester} ${ne.kind} ${ne.start}–${ne.end}` : "",
      next_followup: nf && typeof nf === "object" ? nf.due_date : nf,
    };
  });
  const cols = ["id", "sno", "name", "short_name", "district", "city_id", "lat", "lng", "geo_precision", "op_status", "targeted", "data_status", "tier", "autonomous",
    "branches", "strength", "strength_basis", "eligible", "eligible_basis", "college_lead", "ambassador_leads", "ambassadors", "unassigned_count", "branches_needing_ambassadors",
    "target", "enrolled", "remaining", "pct", "on_track", "diagnosis", "exam_state", "next_exam", "followups_open", "next_followup"];
  return { cols, rows };
}

async function getAll(res: string): Promise<Record<string, unknown>[]> {
  const p = res === "people" ? { page_size: 200 } : { limit: 5000 };
  const first = await portalApi.get<unknown>(res, { query: p });
  const o = first as { items?: Record<string, unknown>[]; total?: number };
  if (o && !Array.isArray(o) && Array.isArray(o.items) && Number(o.total) > o.items.length) {
    const out = [...o.items];
    for (let pg = 2; out.length < Number(o.total) && pg < 200; pg++) out.push(...rowsOf<Record<string, unknown>>(await portalApi.get(res, { query: { page: pg, page_size: 200 } })));
    return out;
  }
  return rowsOf<Record<string, unknown>>(first);
}

function ExportBtn({ label, tone, run }: { label: string; tone?: "primary"; run: () => Promise<void> | void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      icon="data"
      size="sm"
      tone={tone ?? "secondary"}
      busy={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await run();
        } catch (e) {
          toast(`Download failed: ${e instanceof Error ? e.message : "error"}`, "bad");
        } finally {
          setBusy(false);
        }
      }}
    >
      {label}
    </Button>
  );
}

function ExportPanel({ ctx }: { ctx: Ctx }) {
  const { colleges, dName, meta } = ctx;
  const { user } = usePortalSession();
  const backup = async () => {
    const names = ["branches", "people", "targets", "enrollments", "activities", "followups", "exams", "contacts"];
    const parts = await Promise.all(names.map((n) => (n === "followups" || n === "exams" ? portalApi.get<unknown>(n).then((r) => rowsOf(r)) : getAll(n))));
    const audit = rowsOf(await portalApi.get("audit", { query: { limit: 1000 } }));
    const allColleges = rowsOf(await portalApi.get("colleges"));
    const m = (meta ?? {}) as PortalMeta & { today?: string };
    const data = {
      exported_at: new Date().toISOString(),
      exported_by: user || null,
      today: m.today,
      demo_data_present: !!m.demo,
      settings: m.settings,
      courses: m.courses,
      districts: m.districts,
      cities: m.cities,
      colleges: allColleges,
      ...Object.fromEntries(names.map((n, i) => [n, parts[i]])),
      audit_latest_1000: audit,
    };
    downloadText(`techdrona-backup-${today()}.json`, JSON.stringify(data, null, 1), "application/json");
    toast("Backup downloaded", "good");
  };
  return (
    <div className="ad-tools">
      <div className="ad-tool">
        <h2>Spreadsheets (CSV)</h2>
        <p className="adm-muted">
          Open in Excel or Google Sheets. Numbers are exactly what the portal shows, with whether each is verified, estimated or not known yet. The colleges file covers the selected districts; the others cover everything.
        </p>
        <div className="ad-tool__btns">
          <ExportBtn
            label={`Colleges in view (${colleges.length})`}
            tone="primary"
            run={() => {
              const { cols, rows } = collegesCsvRows(colleges, dName);
              csvOf(`techdrona-colleges-${today()}.csv`, rows, cols);
            }}
          />
          {EXPORTS.map(([res, lbl]) => (
            <ExportBtn
              key={res}
              label={lbl}
              run={async () => {
                const rows = res === "courses" ? ((meta?.courses ?? []) as unknown as Record<string, unknown>[]) : await getAll(res);
                if (!rows.length) {
                  toast(`No ${lbl.toLowerCase()} recorded yet`, "info");
                  return;
                }
                csvOf(`techdrona-${res}-${today()}.csv`, rows, colsOf(rows));
              }}
            />
          ))}
        </div>
      </div>
      <div className="ad-tool">
        <h2>Full backup (JSON)</h2>
        <p className="adm-muted">Everything in one file: colleges, team, targets, enrollments, follow-ups, contacts, exams and the latest 1,000 audit entries. Keep it somewhere safe; it contains phone numbers.</p>
        <div className="ad-tool__btns">
          <ExportBtn label="Download backup" run={backup} />
        </div>
      </div>
      {/* (the old "Research data" card only said "ask an admin to re-import on the server": no action here, so it is gone) */}
      <div className={meta?.demo ? "ad-tool is-warn" : "ad-tool"}>
        <h2>Demo data</h2>
        {meta?.demo ? (
          <p>
            <strong>Demo records are present. </strong>They are marked “DEMO” and are not real. Ask an admin to remove them before trusting any totals.
          </p>
        ) : (
          <p className="adm-muted">No demo records. Every number comes from real entries.</p>
        )}
      </div>
    </div>
  );
}
