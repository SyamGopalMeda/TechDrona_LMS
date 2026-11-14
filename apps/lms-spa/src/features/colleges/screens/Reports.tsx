/**
 * Reports (/colleges/analytics) — port of js/views/dashboard.js `renderAnalytics`: what to report on (selected
 * districts / one district / city / college, kept in the URL), headline, "Road to N", charts, leaderboards,
 * recruitment structure, districts, key facts and courses. Numbers come from the server; nothing is estimated here.
 */
import "@/features/colleges/styles/views/dashboard.css";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { PortalApiError } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import { inScope, scopeRows, useDistrictScope, useScopeLabel } from "../lib/scope";
import type { PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import { BarChart, ColumnChart, EmptyChart, Funnel, LineChart, PaceMeter } from "../charts";
import { Badge, DataTable, EmptyState, Icon, Provenance, ScopePill, Section, Segmented, Skeleton, StatCard, StatusBadge, PageHeader, type IconName } from "../ui";
import { DIAG_INFO, DIAG_ORDER, ErrorNote, ProgressNode, StatusNode, collegesHref, daysLeftText, hrefFor, isNum, itemsOf, noTargetReason, pctText, rateText, rowId, rowLabel, type AnyRow } from "./shared/perf";

const CHILD: Record<string, string> = { state: "district", district: "city", city: "college", college: "branch" };
const LEVEL_TITLE: Record<string, string> = { district: "District performance", city: "City performance", college: "College performance", branch: "Branch performance" };
const notFound = (e: unknown) => e instanceof PortalApiError && (e.status === 404 || e.status === 405 || e.status === 501);

function scopeString(a: { level: string; district: string; city: string; college: string }): string {
  if (a.level === "district" && a.district) return `district:${a.district}`;
  if (a.level === "city" && a.city) return `city:${a.city}`;
  if (a.level === "college" && a.college) return `college:${a.college}`;
  return "state";
}

const ActionLink = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className="td-btn td-btn--secondary td-btn--sm">
    {children}
  </Link>
);

export function Reports() {
  usePortalPage({ title: "Reports", crumbs: [{ label: "Reports", to: portalPath.analytics }] });
  const [q, setQuery] = useQueryState();
  const scope = useDistrictScope();
  const scopeLabel5 = useScopeLabel(5);
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 }).data;

  // "Report on" lives in the URL; a district outside the scope falls back to the selected districts
  let a = { level: q.level || "state", district: q.district || "", city: q.city || "", college: q.college || "" };
  if (a.district && !inScope(a.district)) a = { level: "state", district: "", city: "", college: "" };
  const sc = scopeString(a);
  const level = sc.split(":")[0]!;
  const child = CHILD[level]!;
  const isState = level === "state";
  const persist = (n: typeof a) => setQuery(n.level === "state" ? { level: null, district: null, city: null, college: null } : { level: n.level, district: n.district, city: n.city, college: n.college }, { history: "auto" });

  const collegeParams: Record<string, string> = level === "district" ? { district: sc.slice(9) } : level === "city" ? { city: sc.slice(5) } : {};
  const summary = useReportQuery<AnyRow>(isState, "summary", { scope: sc });
  const road = useReportQuery<AnyRow>(isState, "target-dashboard", { scope: sc });
  const geo = useReportQuery<AnyRow[]>(isState, "leaderboard", { level: child, scope: sc, limit: 200 });
  const cities = useReportQuery<AnyRow[]>(isState, isState || level === "district" ? "leaderboard" : null, { level: "city", scope: sc, limit: 200 });
  const collegesLb = useReportQuery<AnyRow[]>(isState, level !== "college" ? "leaderboard" : null, { level: "college", scope: sc, limit: 500 });
  const branches = useReportQuery<AnyRow[]>(isState, "leaderboard", { level: "branch", scope: sc, limit: 500 });
  const persons = useReportQuery<AnyRow[]>(isState, "leaderboard", { level: "person", scope: sc, limit: 500 });
  const ts = useReportQuery<AnyRow[]>(isState, "timeseries", { scope: sc, days: 60 });
  const collegeRowsQ = useReportQuery<unknown>(isState, level !== "college" ? "colleges" : null, collegeParams);
  const plan = usePortalQuery<AnyRow>(isState ? "plan" : null, { scoped: true });
  const perfQ = usePortalQuery<AnyRow>(isState ? "performance" : null, { scoped: true, query: { level: "college", period: "programme" } });
  const collegeOptsQ = usePortalQuery<unknown>(a.level === "college" && a.district ? "colleges" : null, { query: { district: a.district } });

  const S = summary.data;
  const geoRows = useMemo(() => (geo.data && isState ? geo.data.filter((r) => inScope(rowId(r))) : geo.data), [geo.data, isState, scope]); // eslint-disable-line react-hooks/exhaustive-deps
  const collegeRows = useMemo(() => (level === "college" ? (S ? [S] : []) : scopeRows(itemsOf<AnyRow>(collegeRowsQ.data))), [level, S, collegeRowsQ.data, scope]); // eslint-disable-line react-hooks/exhaustive-deps

  const inScopeDistricts = (meta?.districts || []).filter((d) => inScope(d.id)).sort((x, y) => String(x.name).localeCompare(String(y.name)));
  const cityOpts = (meta?.cities || []).filter((c) => c.district_id === a.district).sort((x, y) => String(x.name).localeCompare(String(y.name)));
  const collegeOpts = itemsOf<AnyRow>(collegeOptsQ.data);

  const scopeBar = (
    <div className="vd-scopebar" role="group" aria-label="Choose what to report on">
      <Sel
        label="Report on"
        value={a.level}
        options={[
          ["state", scope.all ? "All districts" : "Selected districts"],
          ["district", "One district"],
          ["city", "One city or town"],
          ["college", "One college"],
        ]}
        onChange={(v) => persist({ ...a, level: v })}
      />
      {a.level !== "state" ? (
        <Sel label="District" value={a.district} options={[["", "Choose a district"], ...inScopeDistricts.map((d) => [d.id, d.name] as [string, string])]} onChange={(v) => persist({ ...a, district: v, city: "", college: "" })} />
      ) : null}
      {a.level === "city" ? (
        <Sel label="City" value={a.city} disabled={!a.district} options={[["", "Choose a city"], ...cityOpts.map((c) => [c.id, c.name] as [string, string])]} onChange={(v) => persist({ ...a, city: v })} />
      ) : null}
      {a.level === "college" ? (
        <Sel
          label="College"
          value={a.college}
          disabled={!a.district}
          options={[["", "Choose a college"], ...collegeOpts.map((c) => [String(c.id), String(c.short_name || c.name)] as [string, string])]}
          onChange={(v) => persist({ ...a, college: v })}
        />
      ) : null}
      <span className="vd-grow" />
      <ScopePill />
    </div>
  );

  let body: ReactNode;
  if (!S) {
    body = summary.error ? (
      <ErrorNote error={summary.error} what="reports for this selection" />
    ) : (
      <div className="vd-skel" role="status" aria-label="Loading reports">
        <Skeleton lines={2} />
        <div className="va-grid">
          <Skeleton lines={5} />
          <Skeleton lines={5} />
        </div>
      </div>
    );
  } else {
    const T = road.data;
    const nothingYet = !(S.target > 0) && !(S.enrolled > 0) && !(S.reached > 0) && !(persons.data || []).length;
    const funnelSec = (
      <Section title="Likely prospects → reached → paid" sub="How many likely prospects the team has reached and enrolled">
        <Funnel
          label="Conversion funnel"
          steps={[
            { label: "Likely prospects (est.)", value: S.eligible ? S.eligible.value : null, basis: S.eligible ? S.eligible.basis : "pending", hint: "Final-year students in relevant branches" },
            { label: "Students reached", value: S.reached ?? null, basis: "verified", hint: S.reached > 0 ? undefined : "Log visits and sessions from a college page to count students reached" },
            { label: "Confirmed", value: S.enrolled ?? null, basis: "verified", hint: S.enrolled > 0 ? undefined : "Record enrollments from a college page" },
          ]}
        />
      </Section>
    );
    const perfData = perfQ.error && notFound(perfQ.error) ? null : perfQ.data;
    body = (
      <>
        <div className="va-headline td-card">
          <h2>{isState ? (scope.all ? "All districts" : scopeLabel5) : S.label || "Selection"}</h2>
          <div className="vd-kpis vd-kpis-tight">
            <KpiCard
              label="Target"
              value={S.target > 0 ? S.target : null}
              notSet={noTargetReason(T, S) ? "No target for this selection" : "Not set yet"}
              icon="target"
              sub={S.target > 0 ? targetSourceText(S) : null}
              to={S.target > 0 ? undefined : portalPath.targets}
            />
            <KpiCard label="Paid enrollments" value={S.enrolled} icon="check" />
            <KpiCard
              label={S.target > 0 && S.enrolled > S.target ? "Above target by" : "Still needed"}
              value={S.target > 0 ? (S.enrolled > S.target ? S.enrolled - S.target : S.remaining) : null}
              notSet="Needs a target"
              icon="clock"
            />
            <KpiCard
              label="% of target"
              value={S.target > 0 ? S.pct : null}
              notSet="Needs a target"
              format={pctText}
              tone={S.target > 0 ? (S.on_track === true ? "good" : S.on_track === false ? "warn" : undefined) : undefined}
              sub={S.target > 0 ? daysLeftText(T && T.days_left, S.deadline) : null}
            />
            <KpiCard label="Students reached" value={S.reached} icon="people" />
            <KpiCard label="Likely prospects (est.)" value={S.eligible ? S.eligible.value : null} basis={S.eligible ? S.eligible.basis : "pending"} icon="people" />
          </div>
          <CoverageNote S={S} geo={geoRows} collegeRows={collegeRows} perf={perfData} child={child} />
          {S.target > 0 ? (
            <div className="va-pace">
              <PaceMeter done={S.enrolled ?? 0} target={S.target} expected={S.expected_now} label={`${S.label || "Selection"} progress to target`} />
              <div className="va-pace-meta">
                <StatusNode r={S} />
                {S.on_track === false && S.diagnosis ? <StatusBadge kind="diagnosis" value={S.diagnosis} /> : null}
                {S.on_track === false && S.diagnosis && DIAG_INFO[S.diagnosis] ? <span className="vd-muted vd-small">{DIAG_INFO[S.diagnosis]!.text}</span> : null}
              </div>
            </div>
          ) : null}
        </div>
        {T ? <RoadBlock T={T} /> : null}
        {nothingYet ? (
          <div className="va-grid">
            <Section title="Nothing to report yet">
              <div className="va-start">
                <p>No targets, outreach or enrollments are recorded for {S.label || "this selection"} yet. Charts and rankings appear as soon as the team adds real records.</p>
                <ol className="va-start-steps">
                  <li>
                    <Link to={portalPath.targets}>Set a target</Link> to compare progress across districts, cities and colleges.
                  </li>
                  <li>
                    <Link to={`${portalPath.colleges}?team=no_lead&targeted=1`}>Appoint leads and ambassadors</Link> from a college page to rank the team.
                  </li>
                  <li>
                    <Link to={portalPath.colleges}>Log outreach and enrollments</Link> to see the trend and conversion.
                  </li>
                </ol>
              </div>
            </Section>
            {funnelSec}
          </div>
        ) : (
          <div className="va-grid">
            <Section title={LEVEL_TITLE[child] || "Performance"} sub="Confirmed against target; click a bar to open it">
              <GeoChart level={child} rows={geoRows} error={geo.error} />
            </Section>
            <Section title="Trend (last 60 days)">
              <TrendBlock rows={ts.data} error={ts.error} S={S} />
            </Section>
            {funnelSec}
            <Section title="Why colleges are behind" sub="Main reason for each college that is behind pace">
              <DiagnosisBlock rows={collegeRows} error={collegeRowsQ.error} />
            </Section>
            {cities.data ? (
              <Section title="City leaderboard">
                <LeaderTable level="city" rows={isState ? cities.data.filter((r) => inScope(String(r.district_id || rowId(r).split("--")[0]))) : cities.data} limit={10} />
              </Section>
            ) : null}
            {collegesLb.data ? (
              <Section title="College leaderboard">
                <TopBottom rows={isState ? collegesLb.data.filter((r) => !r.district_id || inScope(String(r.district_id))) : collegesLb.data} />
              </Section>
            ) : null}
            <Section title="Branch leaderboard">{branches.data ? <LeaderTable level="branch" rows={branches.data} limit={10} /> : branches.error ? <ErrorNote error={branches.error} what="branches" /> : <Skeleton lines={3} card={false} />}</Section>
            <Section title="Team leaderboards">
              <PeopleBoards rows={persons.data} error={persons.error} />
            </Section>
          </div>
        )}
        {isState ? (
          <div className="va-grid">
            <RecruitCard plan={plan.data} S={S} error={plan.error} />
            <Section
              title="Districts"
              sub="Selected districts; open one for its summary and colleges"
              actions={
                <button type="button" className="vd-linkbtn vd-scope-change" onClick={() => window.dispatchEvent(new CustomEvent("td:open-scope"))}>
                  Change districts
                </button>
              }
            >
              <DistrictList districts={(meta?.districts || []).filter((d) => inScope(d.id))} colleges={collegeRows} lb={geoRows || []} />
            </Section>
          </div>
        ) : null}
        <KeyFacts S={S} />
        <Section title="Courses">
          <CourseBreakdown rows={S.by_course} />
        </Section>
      </>
    );
  }

  return (
    <div className="v-analytics">
      <PageHeader title="Reports" sub="Progress, pace, trend, conversion and rankings for the selected districts. Numbers come from the server; nothing is estimated here." />
      {scopeBar}
      <div className="va-body">{body}</div>
    </div>
  );
}

/** State level = the selected districts (districts=); a district / city / college is already inside the selection. */
function useReportQuery<T>(isState: boolean, path: string | null, query: Record<string, string | number>) {
  return usePortalQuery<T>(path, { scoped: isState, query, keepPrevious: true });
}

function Sel({ label, value, options, onChange, disabled }: { label: string; value: string; options: [string, string][]; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="vd-field">
      <span>{label}</span>
      <select className="td-input td-select td-input--sm" disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, t]) => (
          <option key={v} value={v}>
            {t}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Stat card that never shows 0 for an unknown: null → "—" with a Pending basis (old kpi()). */
function KpiCard({
  label,
  value,
  basis,
  sub,
  tone,
  icon,
  to,
  format = fmt.num,
  notSet,
}: {
  label: string;
  value: unknown;
  basis?: string | null;
  sub?: ReactNode;
  tone?: string;
  icon?: IconName;
  to?: string;
  format?: (n: number) => string;
  notSet?: string;
}) {
  const navigate = useNavigate();
  const unknown = value === null || value === undefined || (typeof value === "number" && Number.isNaN(value));
  return (
    <StatCard
      label={label}
      icon={icon}
      tone={tone}
      sub={unknown && notSet ? notSet : sub}
      value={unknown ? "—" : format(Number(value))}
      basis={(unknown ? (notSet ? undefined : "pending") : basis || undefined) as never}
      onClick={to ? () => void navigate(to) : undefined}
    />
  );
}

function targetSourceText(S: AnyRow): string | null {
  if (S.target_source === "sum_of_children") return "sum of lower-level targets";
  if (S.target_source === "explicit" || S.target_source === "program") return "set directly";
  return null;
}

/** A rolled-up target only covers places that have a target; say how many, and how much came from the rest. */
function CoverageNote({ S, geo, collegeRows, perf, child }: { S: AnyRow; geo: AnyRow[] | undefined; collegeRows: AnyRow[]; perf: AnyRow | null | undefined; child: string }) {
  if (!(S.target > 0) || S.target_source !== "sum_of_children") return null;
  const totals = perf && perf.totals && perf.totals.covers ? perf.totals.covers : null;
  let withT: number;
  let total: number;
  let label: string;
  if (totals) {
    withT = totals.with_target;
    total = totals.total;
    label = "colleges";
  } else if (Array.isArray(geo) && geo.length) {
    withT = geo.filter((r) => r.target > 0).length;
    total = geo.length;
    label = child === "city" ? "cities" : child === "college" ? "colleges" : child === "branch" ? "branches" : "districts";
  } else {
    withT = collegeRows.filter((r) => r.target > 0).length;
    total = collegeRows.length;
    label = "colleges";
  }
  const outside = Array.isArray(geo) ? geo.filter((r) => !(r.target > 0)).reduce((s, r) => s + (r.enrolled || 0), 0) : 0;
  return (
    <p className="va-cover" role="note">
      <Icon name="info" size={16} />
      <span>
        This target is the sum of lower-level targets and covers {fmt.num(withT)} of {fmt.num(total)} {label}.
        {outside > 0 ? ` ${fmt.plural(outside, "confirmed enrollment")} came from ${label} without a target, so the % may overstate progress.` : ""}
      </span>
    </p>
  );
}

/* "Road to {target}": confirmed vs target, required vs current pace, projection, funnel, calling and people. */
const ROLE_SHORT: Record<string, string> = { college_lead: "College lead", ambassador_lead: "Amb. lead", ambassador: "Ambassador" };
const Num = ({ label, value, note }: { label: string; value: ReactNode; note?: string | null }) => (
  <div className="vdr-num">
    <dt>{label}</dt>
    <dd>{value}</dd>
    {note ? <small>{note}</small> : null}
  </div>
);

const Facts = ({ items }: { items: [unknown, string, string?][] }) => (
  <ul className="vdr-facts">
    {items.map(([v, l, to]) => (
      <li key={l}>
        {to ? (
          <Link to={to} className="vd-link">
            <b>{fmt.num(v as number)}</b>
          </Link>
        ) : (
          <b>{fmt.num(v as number)}</b>
        )}
        <span>{l}</span>
      </li>
    ))}
  </ul>
);

export function RoadBlock({ T }: { T: AnyRow }) {
  const hasTarget = T.target > 0;
  const P: AnyRow = T.projection || {};
  const projTone = P.status === "after_deadline" ? "is-bad" : P.status === "on_or_before_deadline" || P.status === "achieved" ? "is-good" : undefined;
  const behind = hasTarget && T.required_weekly != null && T.current_weekly < T.required_weekly;
  const f: AnyRow = T.funnel || { stages: [] };
  const stages: AnyRow[] = (f.stages || []).filter((s: AnyRow) => s.stage !== "dropped");
  const max = Math.max(1, ...stages.map((s) => s.count));
  const dropped = (f.stages || []).find((s: AnyRow) => s.stage === "dropped")?.count || 0;
  const k: AnyRow = T.contacts || {};
  const c: AnyRow = T.calls || {};
  const p: AnyRow = T.pending_calls || {};
  const exceeded = hasTarget && T.confirmed > T.target ? T.confirmed - T.target : 0;
  const why = noTargetReason(T);
  return (
    <section className="vdr td-card" aria-labelledby="vdr-title">
      <div className="vdr-head">
        <div>
          <h2 id="vdr-title" className="vdr-title">
            {hasTarget ? `Road to ${fmt.num(T.target)}` : "Road to the target"}
          </h2>
          <p className="vdr-sub">Only paid (confirmed) enrollments count toward the target. Interested, registered and applied students are shown separately.</p>
        </div>
        <Link to={portalPath.calls} className="td-btn td-btn--secondary td-btn--sm">
          <Icon name="phone" size={16} />
          <span>Open calling</span>
        </Link>
      </div>
      <dl className="vdr-nums">
        <Num label="Target" value={hasTarget ? fmt.num(T.target) : "Not set"} note={hasTarget && T.deadline ? `deadline ${fmt.date(T.deadline)}` : null} />
        <Num label="Paid enrollments" value={fmt.num(T.confirmed)} />
        <Num label={exceeded ? "Above target by" : "Still needed"} value={hasTarget ? fmt.num(exceeded || T.remaining) : "—"} />
        <Num label="% of target" value={hasTarget ? pctText(T.pct) : "—"} />
      </dl>
      {hasTarget ? (
        <div className="vdr-pace">
          <div className={behind ? "is-bad" : undefined}>
            <span>Needed each week from today</span>
            <strong>{T.deadline_passed ? "Deadline passed" : `${rateText(T.required_weekly)} / week`}</strong>
            <span>{T.deadline_passed ? daysLeftText(T.days_left, T.deadline) : `${rateText(T.required_daily)} a day · ${daysLeftText(T.days_left, null)}`}</span>
          </div>
          <div className={behind ? "is-bad" : T.current_weekly > 0 ? "is-good" : undefined}>
            <span>Current pace (last 14 days)</span>
            <strong>{`${rateText(T.current_weekly)} / week`}</strong>
            <span>{fmt.plural(T.confirmed_last_14d, "confirmed enrollment")} in 14 days</span>
          </div>
          <div className={projTone}>
            <span>Projected completion</span>
            <strong>{P.date ? fmt.date(P.date) : P.status === "achieved" ? "Reached" : "Not enough data"}</strong>
            <span>{P.explanation || ""}</span>
          </div>
        </div>
      ) : why ? (
        <p className="vdr-empty">No target for this selection. {why}</p>
      ) : (
        <p className="vdr-empty">
          No target is set yet, so pace and projection cannot be shown. <Link to={portalPath.targets}>Set the programme target</Link>.
        </p>
      )}
      <div className="vdr-grid">
        <div>
          <h3 className="vdr-h3">Student pipeline</h3>
          {f.total ? (
            <ol className="vdr-bars" aria-label="Students by current stage">
              {stages.map((s) => (
                <li key={s.stage} className={`vdr-bar${s.counts_toward_target ? " is-target" : ""}`}>
                  <span className="vdr-bar-l">
                    {s.label}
                    {s.counts_toward_target ? <small> · counts toward target</small> : null}
                  </span>
                  <span className="vdr-bar-v td-num">{fmt.num(s.count)}</span>
                  <span className="vdr-bar-t" aria-hidden="true">
                    {s.count > 0 ? <span style={{ width: `${Math.max(2, (s.count / max) * 100)}%` }} /> : null}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="vdr-empty">No student records yet. Open a college and use “Record enrollment”: save a lead as soon as a student shows interest, then move the same record forward.</p>
          )}
          {f.total ? <p className="vdr-note">Each student is counted once, at their current stage.{dropped ? ` ${fmt.plural(dropped, "student")} dropped or refunded (not counted).` : ""}</p> : null}
        </div>
        <div>
          <h3 className="vdr-h3">Calling</h3>
          {k.total ? (
            <Facts
              items={[
                [k.working, "working numbers", `${portalPath.calls}?filter=working`],
                [(k.non_working || 0) + (k.invalid || 0), "not working / invalid", `${portalPath.calls}?filter=invalid`],
                [k.untested, "not called yet"],
                [k.colleges_without_contact, "colleges with no contact"],
              ]}
            />
          ) : (
            <p className="vdr-empty">No contacts recorded yet. Add numbers on a college page (Contacts & calls).</p>
          )}
          <Facts
            items={[
              [c.today, "calls today"],
              [c.last_7d, "calls in 7 days"],
              [p.callbacks_due, "call-backs due", `${portalPath.calls}?filter=pending`],
              [T.followups_due, "follow-ups due", portalPath.followups],
            ]}
          />
        </div>
      </div>
      <div>
        <h3 className="vdr-h3">Leads & ambassadors by confirmed enrollments</h3>
        {(T.people || []).length ? (
          <ol className="vdr-people">
            {(T.people as AnyRow[]).slice(0, 5).map((x) => (
              <li key={x.id}>
                <span>
                  <Link to={hrefFor("person", x) ?? portalPath.person(x.id)}>{x.full_name}</Link>
                  <span className="vd-muted">
                    {" "}
                    · {ROLE_SHORT[x.role] || x.role}
                    {x.college_label ? `, ${x.college_label}` : ""}
                  </span>
                </span>
                <span className="td-num">
                  <b>{fmt.num(x.confirmed)}</b>
                  {x.target != null ? ` / ${fmt.num(x.target)}` : ""}
                  {x.in_pipeline ? <span className="vd-muted"> · {fmt.num(x.in_pipeline)} in pipeline</span> : null}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="vdr-empty">
            No college leads or ambassadors yet. <Link to={`${portalPath.colleges}?team=no_lead&targeted=1`}>Open a college</Link> to appoint them; credit each enrollment to the person who brought it.
          </p>
        )}
      </div>
    </section>
  );
}

const Row = ({ label, need, have, hint }: { label: string; need: unknown; have: number | null; hint: string }) => (
  <div className="vdq-row">
    <div className="vdq-row-head">
      <strong>{label}</strong>
      <span className="vdq-nums td-num">
        <b>{have === null ? "—" : fmt.num(have)}</b> recruited{isNum(need) ? ` of ${fmt.num(need)} needed` : ""}
      </span>
    </div>
    {isNum(need) && need > 0 ? (
      <span className="vdq-bar" role="progressbar" aria-label={`${label} recruited`} aria-valuemin={0} aria-valuemax={need} aria-valuenow={have || 0}>
        <span style={{ width: `${Math.min(100, ((have || 0) / need) * 100)}%` }} />
      </span>
    ) : null}
    <span className="vd-muted vd-small vdq-hint">
      {hint}
      {isNum(need) ? <Provenance basis="estimated" /> : null}
    </span>
  </div>
);

/* Recruitment structure: College Leads / Ambassadors required (research model) vs recruited (people records). */
function RecruitCard({ plan, S, error }: { plan: AnyRow | undefined; S: AnyRow; error: unknown }) {
  const T = plan && plan.totals_research;
  const A = plan && plan.totals_actual;
  const leadsHave = A ? A.college_leads : (S.college_leads ?? null);
  const ambHave = A ? (A.ambassadors ?? 0) + (A.ambassador_leads ?? 0) : (S.ambassadors ?? 0) + (S.ambassador_leads ?? 0);
  return (
    <Section
      title="Recruitment structure"
      sub="Each college has one student College Lead, with Student Ambassadors reporting to the lead."
      actions={
        <Link to={portalPath.plan} className="vd-link">
          Target planner
        </Link>
      }
    >
      <div className="vdq">
        {!T ? <p className="vd-muted vd-small">{error ? `Could not load the planner numbers (${(error as Error).message || "error"}).` : plan ? "No planner numbers for these districts yet." : "Loading the planner numbers…"}</p> : null}
        <Row label="College Leads" need={T ? T.college_leads : null} have={leadsHave} hint={T ? "Needed (research model) " : "Recruited so far"} />
        <Row label="Student Ambassadors" need={T ? T.ambassadors : null} have={ambHave} hint={T ? "Needed (research model, incl. ambassador leads) " : "Including ambassador leads"} />
        {T && isNum(T.avg) ? (
          <p className="vdq-est">
            Research estimate for these colleges: <b className="td-num">{`${fmt.num(T.min)}–${fmt.num(T.max)}`}</b> paid enrollments (average <b className="td-num">{fmt.num(T.avg)}</b>) <Provenance basis="estimated" />
          </p>
        ) : null}
      </div>
    </Section>
  );
}

function Fact({ label, value, sub, basis, tone, to, format = fmt.num }: { label: string; value: unknown; sub?: string | null; basis?: string | null; tone?: string; to?: string; format?: (n: number) => string }) {
  const unknown = value === null || value === undefined || (typeof value === "number" && Number.isNaN(value));
  const cls = `vd-fact${tone ? ` is-${tone}` : ""}${to ? " is-link" : ""}`;
  const inner = (
    <>
      <span className="vd-fact-label">{label}</span>
      <span className="vd-fact-value">
        {unknown ? "—" : format(Number(value))}
        {to ? <Icon name="chevron" size={14} className="vd-fact-go" /> : null}
      </span>
      {sub || basis || unknown ? (
        <span className="vd-fact-sub">
          {sub ? <span>{sub}</span> : null}
          {basis || unknown ? <Provenance basis={unknown ? "pending" : basis} /> : null}
        </span>
      ) : null}
    </>
  );
  return (
    <li>
      {to ? (
        <Link to={to} className={cls}>
          {inner}
        </Link>
      ) : (
        <div className={cls}>{inner}</div>
      )}
    </li>
  );
}

const Group = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="vd-factgroup td-card" aria-label={title}>
    <h2 className="vd-h2">{title}</h2>
    <ul className="vd-facts">{children}</ul>
  </section>
);

function KeyFacts({ S }: { S: AnyRow }) {
  const ex: AnyRow = S.exams || {};
  const of = (n: unknown, what: string) => (isNum(n) ? `of ${fmt.num(n)} ${what}` : null);
  return (
    <div className="vd-factgrid">
      <Group title="Colleges & students">
        <Fact label="Operational colleges" value={S.operational_colleges} sub={of(S.colleges, "listed")} to={portalPath.colleges} />
        <Fact label="Targeted colleges" value={S.targeted_colleges} sub="chosen for outreach" to={`${portalPath.colleges}?targeted=1`} />
        <Fact label="Relevant branches" value={S.branches_relevant} sub={of(S.branches, "branches")} />
        <Fact label="Relevant students" value={S.relevant_students?.value ?? null} basis={S.relevant_students?.basis} sub="IT, allied & circuit branches" />
        <Fact label="Likely prospects (est.)" value={S.eligible?.value ?? null} basis={S.eligible?.basis} sub="final-year, likely to enrol" />
      </Group>
      <Group title="Team">
        <Fact label="Colleges with a lead" value={S.colleges_with_lead} sub={of(S.targeted_colleges, "targeted")} to={`${portalPath.colleges}?team=has_lead`} />
        <Fact label="Ambassador leads" value={S.ambassador_leads} to={`${portalPath.people}?role=ambassador_lead`} />
        <Fact label="Ambassadors" value={S.ambassadors} to={`${portalPath.people}?role=ambassador`} />
        <Fact label="Branches covered" value={S.branches_with_ambassadors} sub={of(S.branches_relevant, "relevant")} />
        <Fact
          label="Branches needing ambassadors"
          value={S.branches_needing_ambassadors}
          tone={S.branches_needing_ambassadors > 0 ? "warn" : undefined}
          sub={S.branches_needing_ambassadors > 0 ? "Show colleges with gaps" : "All covered"}
          to={`${portalPath.colleges}?amb=gap`}
        />
      </Group>
      <Group title="Follow-ups & exams">
        <Fact label="Open follow-ups" value={S.followups_open} to={portalPath.followups} />
        <Fact label="Overdue follow-ups" value={S.followups_overdue} tone={S.followups_overdue > 0 ? "bad" : undefined} to={`${portalPath.followups}?tab=overdue`} />
        <Fact label="Colleges in exams now" value={ex.in_exams ?? null} sub="avoid visits" to={collegesHref("exam", "in_exams")} />
        <Fact label="Exams within 14 days" value={ex.exams_soon ?? null} to={collegesHref("exam", "exams_soon")} />
        <Fact label="Exam dates unknown" value={ex.unknown ?? null} sub="need checking" to={portalPath.exams} />
      </Group>
    </div>
  );
}

function DistrictList({ districts, colleges, lb }: { districts: { id: string; name: string }[]; colleges: AnyRow[]; lb: AnyRow[] }) {
  const counts = new Map<string, { total: number; targeted: number }>();
  for (const c of colleges) {
    const k = c.district_id;
    if (!k) continue;
    const o = counts.get(k) || { total: 0, targeted: 0 };
    o.total++;
    if (c.targeted) o.targeted++;
    counts.set(k, o);
  }
  const lbMap = new Map(lb.map((r) => [rowId(r), r]));
  const rows = districts
    .map((d) => ({ ...d, ...(counts.get(d.id) || { total: 0, targeted: 0 }), lb: lbMap.get(d.id) || null }))
    .sort((x, y) => {
      const at = !!(x.lb && x.lb.target > 0);
      const bt = !!(y.lb && y.lb.target > 0);
      if (at !== bt) return at ? -1 : 1;
      if (at) return (y.lb!.pct ?? 0) - (x.lb!.pct ?? 0);
      return y.targeted - x.targeted || String(x.name).localeCompare(String(y.name));
    });
  if (!rows.length) return <EmptyState title="No districts selected" text="Pick districts in the header to see them here." />;
  return (
    <ul className="vd-dlist">
      {rows.map((d) => (
        <li key={d.id}>
          <Link to={portalPath.district(d.id)} className={`vd-drow${d.targeted ? "" : " is-dim"}`}>
            <div className="vd-drow-name">
              <strong>{d.name}</strong>
              <span className="vd-muted vd-small">{d.targeted ? fmt.plural(d.targeted, "targeted college") : d.total ? `${fmt.plural(d.total, "college")}, none targeted` : "No operational colleges listed"}</span>
            </div>
            <div className="vd-drow-prog">
              {d.lb && d.lb.target > 0 ? <ProgressNode r={d.lb} /> : <span className="vd-muted vd-small">{d.lb && d.lb.enrolled > 0 ? `${fmt.num(d.lb.enrolled)} confirmed · no target` : "No target yet"}</span>}
            </div>
            <div className="vd-drow-status">{d.lb && d.lb.target > 0 ? <StatusNode r={d.lb} /> : null}</div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function CourseBreakdown({ rows: rows0 }: { rows: AnyRow[] | undefined }) {
  const rows = rows0 || [];
  if (!rows.length)
    return (
      <EmptyState
        icon="target"
        title="No courses yet"
        text="Add your courses and prices in Settings to see enrollments and revenue by course."
        actions={[
          <Link key="s" to={portalPath.settings} className="td-btn td-btn--secondary">
            Add courses
          </Link>,
        ]}
      />
    );
  const total = rows.reduce((s, r) => s + (r.revenue_inr || 0), 0);
  return (
    <div className="vd-course">
      <DataTable<AnyRow>
        caption="Courses"
        rows={rows}
        rowKey={(r) => String(r.course_id ?? r.id ?? r.name)}
        mobile="scroll"
        cardSort={false}
        empty="No courses yet"
        columns={[
          { key: "name", label: "Course", primary: true },
          { key: "price_inr", label: "Price", align: "right", render: (r) => fmt.inr(r.price_inr) },
          { key: "target", label: "Target", align: "right", render: (r) => (r.target > 0 ? fmt.num(r.target) : "—") },
          { key: "enrolled", label: "Confirmed", align: "right", render: (r) => fmt.num(r.enrolled ?? 0) },
          { key: "revenue_inr", label: "Revenue", align: "right", render: (r) => fmt.inr(r.revenue_inr) },
        ]}
      />
      <p className="vd-total">
        Total revenue recorded: <strong>{fmt.inr(total)}</strong>
      </p>
    </div>
  );
}

function sortLb(rows: AnyRow[] | undefined): AnyRow[] {
  return [...(rows || [])].sort((x, y) => {
    const at = x.target > 0;
    const bt = y.target > 0;
    if (at !== bt) return at ? -1 : 1;
    if (at) return (y.pct ?? 0) - (x.pct ?? 0) || (y.enrolled ?? 0) - (x.enrolled ?? 0);
    return (y.enrolled ?? 0) - (x.enrolled ?? 0);
  });
}

function GeoChart({ level, rows, error }: { level: string; rows: AnyRow[] | undefined; error: unknown }) {
  const navigate = useNavigate();
  if (error) return <ErrorNote error={error} what="performance" />;
  if (!rows) return <Skeleton lines={4} card={false} />;
  const list = sortLb(rows)
    .filter((r) => r.target > 0 || r.enrolled > 0)
    .slice(0, 30);
  const chart = (
    <BarChart
      label={LEVEL_TITLE[level] || "Performance"}
      valueLabel="Confirmed"
      secondaryLabel="Target"
      data={list.map((r) => ({ label: rowLabel(r), value: r.enrolled ?? 0, secondary: r.target > 0 ? r.target : null, href: hrefFor(level, r) }))}
      onClick={(d) => (d.href ? void navigate(String(d.href)) : undefined)}
      empty="No targets or enrollments here yet. Set targets to compare performance."
    />
  );
  return list.length && list.length < rows.length ? (
    <div>
      {chart}
      <p className="vd-muted vd-small">
        Showing {list.length} with a target or enrollments, of {rows.length}.
      </p>
    </div>
  ) : (
    chart
  );
}

function TrendBlock({ rows: rows0, error, S }: { rows: AnyRow[] | undefined; error: unknown; S: AnyRow }) {
  const rows = rows0 || [];
  const hasCum = rows.some((r) => "cum_enrolled" in r);
  const [metric, setMetric] = useState<"enrolled" | "reached">("enrolled");
  const [trend0, setTrend] = useState<"cumulative" | "weekly" | "daily">("cumulative");
  const trend = !hasCum && trend0 === "cumulative" ? "weekly" : trend0;
  if (error) return <ErrorNote error={error} what="the trend" />;
  if (!rows0) return <Skeleton lines={4} card={false} />;
  const lastCum = hasCum && rows.length ? rows[rows.length - 1]!.cum_enrolled : null;
  const gap = isNum(lastCum) && isNum(S && S.enrolled) && lastCum !== S.enrolled ? S.enrolled - lastCum : 0;
  const name = metric === "enrolled" ? "Confirmed enrollments" : "Students reached";
  let chart: ReactNode;
  if (!rows.some((r) => (r[metric] ?? 0) > 0)) {
    chart = <EmptyChart text={`No ${metric === "enrolled" ? "enrollments" : "outreach"} recorded in the last 60 days.`} action={<ActionLink to={portalPath.colleges}>{metric === "enrolled" ? "Record an enrollment" : "Log outreach"}</ActionLink>} />;
  } else if (trend === "cumulative") {
    const key = metric === "enrolled" ? "cum_enrolled" : "cum_reached";
    chart = <LineChart label={`${name}, running total`} series={[{ name: `${name} so far`, points: rows.map((r) => ({ x: String(r.date), y: r[key] ?? null })) }]} />;
  } else {
    let points = rows.map((r) => ({ x: String(r.date), y: (r[metric] ?? 0) as number }));
    if (trend === "weekly") {
      const wk = new Map<string, number>();
      for (const pt of points) {
        const dd = new Date(`${pt.x.slice(0, 10)}T00:00:00Z`);
        if (Number.isNaN(dd.getTime())) continue;
        dd.setUTCDate(dd.getUTCDate() - ((dd.getUTCDay() + 6) % 7)); // Monday
        const k = dd.toISOString().slice(0, 10);
        wk.set(k, (wk.get(k) || 0) + (pt.y || 0));
      }
      points = [...wk.entries()].sort().map(([x, y]) => ({ x, y }));
    }
    chart = <ColumnChart label={`${name} per ${trend === "weekly" ? "week" : "day"}`} name={name} points={points} xLabel={trend === "weekly" ? (x) => `Week of ${fmt.date(x)}` : undefined} />;
  }
  return (
    <div>
      <div className="va-toggles">
        <Segmented
          ariaLabel="Measure"
          size="sm"
          value={metric}
          onChange={setMetric}
          options={[
            { value: "enrolled", label: "Confirmed" },
            { value: "reached", label: "Reached" },
          ]}
        />
        <Segmented
          ariaLabel="View"
          size="sm"
          value={trend}
          onChange={setTrend}
          options={[...(hasCum ? [{ value: "cumulative" as const, label: "Total" }] : []), { value: "weekly" as const, label: "Per week" }, { value: "daily" as const, label: "Per day" }]}
        />
      </div>
      <div className="va-chart" aria-live="polite">
        {chart}
      </div>
      {gap ? (
        <p className="vd-muted vd-small va-cover">
          <Icon name="info" size={14} /> The running total ends at {fmt.num(lastCum)} while the headline shows {fmt.num(S.enrolled)}: the trend counts records dated up to today, the headline counts every confirmed record
          {gap > 0 ? " (including any dated after today)" : ""}.
        </p>
      ) : null}
    </div>
  );
}

function DiagnosisBlock({ rows, error }: { rows: AnyRow[]; error: unknown }) {
  const navigate = useNavigate();
  if (error) return <ErrorNote error={error} what="diagnosis" />;
  const withTarget = rows.filter((r) => r.target > 0);
  const behind = withTarget.filter((r) => r.on_track === false);
  const counts = new Map<string, number>();
  behind.forEach((r) => {
    const k = DIAG_INFO[r.diagnosis] ? String(r.diagnosis) : "behind_pace";
    counts.set(k, (counts.get(k) || 0) + 1);
  });
  if (!withTarget.length) return <EmptyChart text="No colleges have targets yet, so there is nothing to diagnose." action={<ActionLink to={portalPath.targets}>Set targets</ActionLink>} />;
  if (!behind.length)
    return (
      <div className="vd-allgood">
        <Badge tone="good">All on track</Badge>
        <p className="vd-muted">All {fmt.plural(withTarget.length, "college")} with targets are on pace.</p>
      </div>
    );
  const data = DIAG_ORDER.filter((k) => counts.get(k))
    .map((k) => ({ key: k, label: DIAG_INFO[k]!.title, value: counts.get(k)!, sub: DIAG_INFO[k]!.text }))
    .sort((x, y) => y.value - x.value);
  return (
    <div>
      <BarChart label="Why colleges are behind" valueLabel="Colleges" data={data} max={Math.max(...data.map((x) => x.value))} onClick={(x) => void navigate(collegesHref("diagnosis", String(x.key)))} />
      <p className="vd-muted vd-small">
        {fmt.num(behind.length)} of {fmt.plural(withTarget.length, "college")} with targets are behind pace.{" "}
        <Link className="vd-link" to={`${portalPath.colleges}?progress=behind`}>
          Show them
        </Link>
      </p>
    </div>
  );
}

function LeaderTable({ level, rows, limit = 10, reverse = false }: { level: string; rows: AnyRow[] | undefined; limit?: number; reverse?: boolean }) {
  if (!(rows || []).some((r) => r.target > 0 || r.enrolled > 0)) return <EmptyChart text="Nothing to rank yet. Rankings appear once targets or enrollments exist here." action={<ActionLink to={portalPath.targets}>Set targets</ActionLink>} />;
  let list = sortLb(rows);
  if (reverse) list = list.filter((r) => r.target > 0).reverse();
  list = list.slice(0, limit);
  return (
    <ol className="va-rank">
      {list.map((r, i) => {
        const to = hrefFor(level, r);
        const sub = r.sub || r.college_name || null;
        const inner = (
          <>
            <span className="va-rank-n" aria-label={`Rank ${i + 1}`}>
              {String(i + 1)}
            </span>
            <span className="va-rank-name">
              <strong>{rowLabel(r)}</strong>
              {sub ? <span className="vd-muted vd-small">{sub}</span> : null}
            </span>
            <span className="va-rank-prog">
              <ProgressNode r={r} />
            </span>
          </>
        );
        return (
          <li key={`${rowId(r)}:${i}`}>
            {to ? (
              <Link to={to} className="va-rank-row">
                {inner}
              </Link>
            ) : (
              <div className="va-rank-row">{inner}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function TopBottom({ rows }: { rows: AnyRow[] }) {
  const ranked = rows.filter((r) => r.target > 0);
  if (!ranked.length) return <EmptyChart text="No colleges have targets yet." action={<ActionLink to={portalPath.targets}>Set targets</ActionLink>} />;
  return (
    <div className="va-pair">
      <div>
        <h3 className="vd-h3">Top 10</h3>
        <LeaderTable level="college" rows={rows} limit={10} />
      </div>
      {ranked.length > 10 ? (
        <div>
          <h3 className="vd-h3">Bottom 10</h3>
          <LeaderTable level="college" rows={rows} limit={10} reverse />
        </div>
      ) : null}
    </div>
  );
}

function PeopleBoards({ rows, error }: { rows: AnyRow[] | undefined; error: unknown }) {
  if (error) return <ErrorNote error={error} what="the team leaderboard" />;
  if (!rows) return <Skeleton lines={3} card={false} />;
  if (!rows.length) return <EmptyState title="No team yet" text="Appoint college leads and ambassadors from a college page to rank them here." />;
  if (!rows.some((r) => r.role)) return <LeaderTable level="person" rows={rows} limit={15} />;
  const leads = rows.filter((r) => r.role === "college_lead" || r.role === "ambassador_lead");
  const ambs = rows.filter((r) => r.role === "ambassador");
  return (
    <div className="va-pair">
      <div>
        <h3 className="vd-h3">Leads</h3>
        {leads.length ? <LeaderTable level="person" rows={leads} limit={10} /> : <EmptyChart text="No leads yet" />}
      </div>
      <div>
        <h3 className="vd-h3">Ambassadors</h3>
        {ambs.length ? <LeaderTable level="person" rows={ambs} limit={10} /> : <EmptyChart text="No ambassadors yet" />}
      </div>
    </div>
  );
}
