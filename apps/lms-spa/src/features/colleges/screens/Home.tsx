/**
 * Home (/colleges) — port of js/views/dashboard.js `renderState` with the owner-reviewed wording of 2026-11-14
 * (docs/qa/college-portal/home-targets-people.md): 4 KPI tiles, Needs attention, the map, Colleges to call next and
 * Next 14 days. Every number comes from the API; the district scope applies everywhere.
 */
import "@/features/colleges/styles/views/dashboard.css";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { PortalApiError } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { daysUntil, fmt } from "../lib/fmt";
import { portalPath, toPortalHref } from "../lib/routes";
import { inScope, scopeRows, useDistrictScope } from "../lib/scope";
import type { PortalMeta } from "../lib/types";
import { CollegeMap } from "../map/CollegeMap";
import { usePortalPage } from "../shell/page-context";
import { Badge, ErrorCard, Icon, PageHeader, Provenance, Section, Skeleton, StatusBadge, usePortalUi, WriteOnly, type Tone } from "../ui";
import { CALL_STATUS, contactLabel, formatPhone, logCall } from "../forms";
import {
  AttentionList,
  ErrorNote,
  Expandable,
  daysLeftText,
  isNum,
  itemsOf,
  leadOf,
  noTargetReason,
  pctText,
  perfRows,
  programmeNA,
  rateText,
  unassignedOf,
  ROLE_TIPS,
  type AnyRow,
} from "./shared/perf";

const HOME_SUB = "Paid enrollments against the target, and what needs doing next.";
const notFound = (e: unknown) => e instanceof PortalApiError && (e.status === 404 || e.status === 405 || e.status === 501);

export function Home() {
  usePortalPage({ title: "Home", crumbs: [] });
  const scope = useDistrictScope();
  const summary = usePortalQuery<AnyRow>("summary", { scoped: true, query: { scope: "state" } });
  const road = usePortalQuery<AnyRow>("target-dashboard", { scoped: true, query: { scope: "state" } });
  const colleges = usePortalQuery<unknown>("colleges", { scoped: true });
  const attention = usePortalQuery<AnyRow[]>("attention", { scoped: true, query: { scope: "state" } });
  const followups = usePortalQuery<unknown>("followups", { scoped: true, query: { status: "open" } });
  const exams = usePortalQuery<AnyRow[]>("exams", { scoped: true });
  const queue = usePortalQuery<AnyRow>("calls/queue", { scoped: true, query: { filter: "all", sort: "priority", limit: 300 } });
  const people = usePortalQuery<unknown>("people", { scoped: true, query: { assignment: "unassigned,invalid_link", page: 1, page_size: 1 } });
  // v3 servers: the plain people list (rule R3 applied to its rows)
  const peopleAll = usePortalQuery<unknown>(people.error ? "people" : null, { scoped: true });
  const perf = usePortalQuery<AnyRow>("performance", { scoped: true, query: { level: "person", period: "programme" } });
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const [hover, setHover] = useState<string | null>(null);

  const d = useMemo(() => {
    const collegesAll = scopeRows(itemsOf<AnyRow>(colleges.data));
    const ids = new Set(collegesAll.map((c) => c.id));
    const collegeOk = (id: unknown) => scope.all || !id || ids.has(id);
    const ex = exams.data ? scopeRows(exams.data).filter((e) => collegeOk(e.college_id)) : null;
    const fu = followups.data ? itemsOf<AnyRow>(followups.data).filter((f) => collegeOk(f.college_id || (f.scope_type === "college" ? f.scope_id : null))) : null;
    const q = queue.data ? { ...queue.data, rows: scopeRows((queue.data.rows as AnyRow[]) || []).filter((r) => collegeOk(r.college_id)) } : null;
    const att = attention.data
      ? attention.data.filter((r) => r.type === "group" || (r.type === "college" ? collegeOk(r.id) : r.type === "district" ? inScope(r.id) : true))
      : null;
    const pd = people.data as AnyRow | AnyRow[] | undefined;
    const unassignedTotal =
      pd && !Array.isArray(pd) && isNum(pd.total)
        ? pd.total
        : pd
          ? unassignedOf(itemsOf<AnyRow>(pd).filter((p) => collegeOk(p.college_id)) as never[]).length
          : peopleAll.data
            ? unassignedOf(itemsOf<AnyRow>(peopleAll.data).filter((p) => collegeOk(p.college_id)) as never[]).length
            : null;
    return { collegesAll, ex, fu, q, att, unassignedTotal };
  }, [colleges.data, exams.data, followups.data, queue.data, attention.data, people.data, peopleAll.data, scope]);

  const head = <PageHeader title="Home" sub={HOME_SUB} />;
  if (summary.loading && !summary.data) {
    return (
      <div className="v-dashboard">
        <div className="vd-skel" role="status" aria-label="Loading home">
          <Skeleton lines={2} />
          <Skeleton lines={4} />
          <Skeleton lines={4} />
        </div>
      </div>
    );
  }
  const S = summary.data;
  if (!S) {
    return (
      <div className="v-dashboard">
        <ErrorCard title="Could not load the programme summary" error={summary.error} retry={() => void summary.reload()} />
      </div>
    );
  }
  const perfData = perf.error && notFound(perf.error) ? null : perf.data;
  const errors = { road: road.error, people: people.error && peopleAll.error, attention: attention.error, followups: followups.error, exams: exams.error, queue: queue.error };

  return (
    <div className="v-dashboard">
      <div className="vd-home">
        {head}
        <KpiStrip S={S} T={road.data} roadError={!!errors.road} />
        <NeedsAttention S={S} colleges={d.collegesAll} unassignedTotal={d.unassignedTotal} perf={perfData} peopleError={errors.people} attention={d.att} attentionError={errors.attention} onHover={setHover} />
        <MapPanel rows={d.collegesAll} meta={meta.data} highlight={hover} />
        <div className="vd-duo">
          <TopCalls q={d.q} error={errors.queue} />
          <Section title="Next 14 days" sub="Follow-ups due and exams coming up" actions={<Link to={portalPath.exams} className="vd-link">Exam calendar</Link>}>
            <Upcoming followups={d.fu} exams={d.ex} S={S} fuError={errors.followups} exError={errors.exams} />
          </Section>
        </div>
        <p className="vd-muted vd-small vd-home-foot">
          Charts, rankings, districts and courses are in <Link to={portalPath.analytics}>Reports</Link>.
        </p>
      </div>
    </div>
  );
}

/** Compact KPI strip: Target · Paid enrollments (with % of target) · Still needed · Needed each week. */
function KpiStrip({ S, T, roadError }: { S: AnyRow; T: AnyRow | undefined; roadError: boolean }) {
  const prog = T && T.program ? (T.program as AnyRow) : null;
  const why = noTargetReason(T, S);
  const progNA = programmeNA(T);
  const target = why ? null : progNA ? T!.target : prog && prog.target !== undefined ? prog.target : T ? T.target : S.target;
  const partialT = !!T && T.target_status === "partial_target";
  const hasTarget = target > 0;
  const confirmed = T ? T.confirmed : S.enrolled;
  const remaining = T ? T.remaining : S.remaining;
  const exceeded = partialT ? 0 : T && isNum(T.exceeded_by) ? T.exceeded_by : hasTarget && confirmed > target ? confirmed - target : 0;
  const pct = T ? T.pct : S.pct;
  const paceSt = (T && (T.pace_status || (prog && prog.pace_status))) || S.pace_status || null;
  const behind = hasTarget && T && T.required_weekly != null && (T.current_weekly ?? 0) < T.required_weekly && paceSt !== "too_early";
  const deadline = (prog && prog.deadline) || (T && T.deadline) || S.deadline || null;
  const judged = hasTarget && !partialT;
  const targetSub = !hasTarget
    ? "Set it in Targets"
    : partialT && T!.covers
      ? `only ${fmt.num(T!.covers.with_target)} of ${fmt.num(T!.covers.total)} places have a target`
      : progNA
        ? "sum of the selected districts’ targets"
        : deadline
          ? `by ${fmt.date(deadline)}`
          : null;
  const paceSub =
    T && hasTarget ? (
      <span>
        {paceSt === "too_early" ? "too early to judge · " : `current pace ${rateText(T.current_weekly)} a week · `}
        {daysLeftText(T.days_left, null)}
      </span>
    ) : roadError ? (
      "Pace unavailable"
    ) : null;
  return (
    <section className="vd-kstrip vd-kstrip--4" aria-label="Progress to the target">
      {why ? (
        <div className="vd-kt" title={why}>
          <span className="vd-kt-l">Target</span>
          <span className="vd-kt-v vd-kt-v--text">No target</span>
          <span className="vd-kt-s">for these districts</span>
        </div>
      ) : (
        <Tile label="Target" value={hasTarget ? fmt.num(target) : "Not set"} sub={targetSub} tone={partialT ? "warn" : null} to={hasTarget ? null : portalPath.targets} tip="Paid enrollments the programme aims for in the target districts" />
      )}
      <Tile
        label="Paid enrollments"
        value={fmt.num(confirmed ?? 0)}
        sub={judged ? `${pctText(pct)} of target` : "confirmed and paid"}
        tip="Students who have paid. Leads, interested and applied students do not count until they pay."
      />
      <Tile
        label={exceeded ? "Above target by" : "Still needed"}
        value={judged ? fmt.num(exceeded || remaining) : "—"}
        sub={judged ? (exceeded ? "more than the target" : "to reach the target") : null}
        tone={exceeded ? "good" : null}
      />
      <Tile
        label="Needed each week"
        value={hasTarget && T ? (T.deadline_passed ? "Deadline passed" : rateText(T.required_weekly)) : "—"}
        sub={paceSub}
        tone={behind ? "bad" : paceSt === "too_early" ? "info" : hasTarget && T ? "good" : null}
        to={portalPath.analytics}
        tip="Paid enrollments needed every week from today to reach the target by the deadline. Current pace = the last 14 days."
      />
    </section>
  );
}

function Tile({ label, value, sub, tone, to, tip }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string | null; to?: string | null; tip?: string }) {
  const cls = `vd-kt${tone ? ` is-${tone}` : ""}`;
  const body = (
    <>
      <span className="vd-kt-l">{label}</span>
      <span className="vd-kt-v td-num">{value}</span>
      {sub ? <span className="vd-kt-s">{sub}</span> : null}
    </>
  );
  return to ? (
    <Link to={to} className={cls} title={tip}>
      {body}
    </Link>
  ) : (
    <div className={cls} title={tip}>
      {body}
    </div>
  );
}

/** "Needs attention": overdue follow-ups and colleges without a lead always; the two people cards only when above 0. */
function NeedsAttention({
  S,
  colleges,
  unassignedTotal,
  perf,
  peopleError,
  attention,
  attentionError,
  onHover,
}: {
  S: AnyRow;
  colleges: AnyRow[];
  unassignedTotal: number | null;
  perf: AnyRow | null | undefined;
  peopleError: unknown;
  attention: AnyRow[] | null;
  attentionError: unknown;
  onHover: (id: string | null) => void;
}) {
  const targetedOps = colleges.filter((c) => c.targeted && (c.op_status || "pending") === "operational");
  const noLead = targetedOps.filter((c) => !leadOf(c));
  const pRows = perfRows(perf);
  const behind = perf ? pRows.filter((r) => r.status === "behind") : null;
  const withTarget = pRows.filter((r) => r.target > 0).length;
  const cards: ReactNode[] = [
    <NeedCard
      key="fu"
      n={isNum(S.followups_overdue) ? S.followups_overdue : null}
      title="Overdue follow-ups"
      text={isNum(S.followups_open) ? `${fmt.num(S.followups_open)} open in total` : ""}
      to={`${portalPath.followups}?tab=overdue`}
      tone="bad"
      icon="followup"
      tip="Planned calls or visits whose due date has passed"
    />,
    <NeedCard
      key="lead"
      n={noLead.length}
      title="Colleges without a college lead"
      text={`of ${fmt.plural(targetedOps.length, "college")} we are targeting`}
      to={`${portalPath.colleges}?team=no_lead&targeted=1`}
      tone="bad"
      icon="lead"
      tip={`${ROLE_TIPS.college_lead} Counts open colleges in the target districts only.`}
    />,
    unassignedTotal && unassignedTotal > 0 ? (
      <NeedCard
        key="amb"
        n={unassignedTotal}
        title="Ambassadors without a lead"
        text="not linked to a college lead yet"
        to={`${portalPath.people}?seg=unassigned`}
        tone="warn"
        icon="ambassador"
        tip="Active ambassadors who do not report to a college lead of their own college"
      />
    ) : null,
    behind && behind.length > 0 ? (
      <NeedCard
        key="behind"
        n={behind.length}
        title="Team members behind their target"
        text={`of ${fmt.plural(withTarget, "person", "people")} with a target`}
        to={`${portalPath.targets}?level=person&status=behind`}
        tone="bad"
        icon="target"
        tip="Their paid enrollments are below the pace needed to reach their own target"
      />
    ) : null,
  ].filter(Boolean);
  const all = attention || [];
  return (
    <section className="vd-needs" aria-labelledby="vd-needs-t">
      <div className="vd-needs-head">
        <h2 id="vd-needs-t" className="vd-h2">
          Needs attention
        </h2>
        <span className="vd-muted vd-small">Click a card to see the list</span>
      </div>
      <div className={`vd-needs-grid vd-needs-grid--${cards.length}`}>{cards}</div>
      {peopleError && unassignedTotal === null ? <ErrorNote error={peopleError} what="the team" /> : null}
      {all.length ? (
        <details className="vd-needs-more">
          <summary>Show every issue, college by college ({fmt.num(all.length)})</summary>
          <AttentionList rows={all as never[]} limit={8} onHover={onHover} />
        </details>
      ) : attentionError ? (
        <ErrorNote error={attentionError} what="the issue list" />
      ) : null}
    </section>
  );
}

function NeedCard({ n, title, text, to, tone, icon, tip }: { n: number | null; title: string; text?: string; to: string; tone: string; icon: string; tip?: string }) {
  return (
    <Link to={to} className={`vd-need is-${n !== null && n > 0 ? tone : "ok"}`} title={tip}>
      <span className="vd-need-icon">
        <Icon name={n !== null && n > 0 ? icon : "check"} size={20} />
      </span>
      <span className="vd-need-body">
        <span className="vd-need-n td-num">{n === null ? "—" : fmt.num(n)}</span>
        <strong>{title}</strong>
        {text ? <span className="vd-muted vd-small">{text}</span> : null}
      </span>
      <Icon name="chevron" size={16} className="vd-need-go" />
    </Link>
  );
}

const MAP_KEY = "td.home.map";
function readMapOpen(phone: boolean): boolean {
  try {
    const v = localStorage.getItem(MAP_KEY);
    if (v === "1" || v === "0") return v === "1";
  } catch {
    /* ignore */
  }
  return !phone; // visible by default on tablet / desktop; one tap away on phones
}

/** The map as a panel: open by default on tablet / desktop, remembered per browser. */
function MapPanel({ rows, meta, highlight }: { rows: AnyRow[]; meta: PortalMeta | undefined; highlight: string | null }) {
  const { form } = usePortalUi();
  const [open, setOpen] = useState(() => readMapOpen(form === "phone"));
  const toggle = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(MAP_KEY, o ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !o;
    });
  };
  const closedN = rows.filter((r) => r.op_status === "possibly_closed" || r.op_status === "closed").length;
  const mapSub = `${fmt.plural(rows.length - closedN, "college")} in the selected districts${closedN ? ` · ${fmt.num(closedN)} more may have shut down (hidden by default)` : ""}`;
  return (
    <section className="vd-mapsec td-card" aria-labelledby="vd-map-t">
      <div className="vd-mapsec-head">
        <div>
          <h2 className="vd-h2" id="vd-map-t">
            Map
          </h2>
          <span className="vd-muted vd-small" title='A college is marked "may have shut down" when research found signs it stopped admitting students. Use the button on the map to show them.'>
            {mapSub}
          </span>
        </div>
        <button type="button" className="td-btn td-btn--secondary td-btn--sm" aria-expanded={open} onClick={toggle}>
          <Icon name="map" size={16} />
          <span>{open ? "Hide map" : "Show map"}</span>
        </button>
      </div>
      {open ? (
        <CollegeMap
          className="vd-mapbox td-mapcard"
          colleges={rows as never}
          places={meta ? { districts: meta.districts || [], cities: meta.cities || [] } : null}
          focus={{ kind: "state" }}
          highlight={highlight}
        />
      ) : null}
    </section>
  );
}

/** Colleges to call next: the internal priority queue for the selected districts. */
function TopCalls({ q, error }: { q: AnyRow | null; error: unknown }) {
  const head = (
    <div className="vdq-head">
      <h2 className="vd-h2">Colleges to call next</h2>
      <Link to={portalPath.calls} className="vd-link">
        Open the call list
      </Link>
    </div>
  );
  if (!q)
    return (
      <section className="vdc vd-lite td-card">
        {head}
        {error ? <ErrorNote error={error} what="the calling queue" /> : <Skeleton lines={3} card={false} />}
      </section>
    );
  const all: AnyRow[] = q.rows || [];
  const rows = all.slice(0, 5);
  return (
    <section className="vdc vd-lite td-card" aria-label="Colleges to call next">
      {head}
      <p className="vd-muted vd-small vdq-sub">
        Highest priority first: {fmt.num(rows.length)} of {fmt.plural(all.length, "college")} on the call list. “Call” only dials checked numbers.
      </p>
      {rows.length ? (
        <ol className="vdc-list">
          {rows.map((r) => {
            const k = r.best_contact as AnyRow | null;
            const verified = !!(k && k.phone && k.basis === "verified" && k.status !== "invalid" && k.status !== "non_working");
            const cs = CALL_STATUS[r.call_status as string] ?? [r.call_status, "neutral"];
            return (
              <li key={r.college_id} className="vdc-item">
                <div className="vdc-main">
                  <Link to={portalPath.college(String(r.college_id))} className="vdc-name">
                    {r.short_name || r.name}
                  </Link>
                  <span className="vd-muted vd-small" title={r.priority ? "Priority score out of 100: student numbers, a working phone number, the exam calendar, college tier and past responses" : undefined}>
                    {[r.city_name, r.district_name].filter(Boolean).join(", ")}
                    {r.priority ? ` · priority ${r.priority.score}/100` : ""}
                  </span>
                  <span className="vdc-badges">
                    {r.call_status ? <Badge tone={cs[1] as Tone}>{cs[0]}</Badge> : null}
                    <span className="vd-small vd-muted">{verified ? contactLabel(k) || "Verified number" : k && k.phone ? "Number not verified" : "No number yet"}</span>
                    {verified ? <Provenance basis="verified" /> : null}
                  </span>
                </div>
                <div className="vdc-act">
                  {verified ? (
                    <a href={`tel:${k!.phone}`} className="vx-tel td-btn td-btn--primary td-btn--sm vdc-call" aria-label={`Call ${formatPhone(k!.phone)}`}>
                      <Icon name="phone" size={16} />
                      <span>Call</span>
                    </a>
                  ) : null}
                  <WriteOnly>
                    <button type="button" className="td-btn td-btn--secondary td-btn--sm" onClick={() => void logCall({ college_id: String(r.college_id), college_label: r.short_name || r.name })}>
                      <Icon name="phone" size={14} />
                      <span>Log call</span>
                    </button>
                  </WriteOnly>
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="vd-muted vd-small">No operational colleges in the selected districts.</p>
      )}
    </section>
  );
}

const examRange = (ne: AnyRow | null | undefined) => {
  if (!ne || !ne.start) return "";
  const what = [ne.semester, ne.kind].filter(Boolean).join(" ");
  return `${what ? `${what}: ` : ""}${fmt.date(ne.start)}${ne.end && ne.end !== ne.start ? ` – ${fmt.date(ne.end)}` : ""}`;
};
const noYear = (s: string) => s.replace(/ \d{4}$/, "");

function Upcoming({ followups, exams, S, fuError, exError }: { followups: AnyRow[] | null; exams: AnyRow[] | null; S: AnyRow; fuError: unknown; exError: unknown }) {
  const fuItems: { date: string; node: ReactNode }[] = [];
  for (const f of followups || []) {
    const fd = daysUntil(f.due_date);
    if (fd === null || fd < 0 || fd > 14) continue; // overdue ones are counted in "Needs attention"
    const to = f.href
      ? toPortalHref(String(f.href))
      : f.scope_type === "college"
        ? portalPath.college(String(f.scope_id))
        : f.scope_type === "person"
          ? portalPath.person(String(f.scope_id))
          : f.college_id
            ? portalPath.college(String(f.college_id))
            : portalPath.followups;
    fuItems.push({
      date: String(f.due_date),
      node: (
        <li key={`f${f.id}`}>
          <Link to={to} className="vd-up">
            <span className="vd-up-date">
              <strong>{noYear(fmt.date(f.due_date))}</strong>
              <small>{fmt.days(f.due_date)}</small>
            </span>
            <span className="vd-up-main">
              <strong>{f.title || "Follow-up"}</strong>
              <span className="vd-muted vd-small">{[f.scope_label || f.college_name || f.label, f.owner_name ? `owner ${f.owner_name}` : null].filter(Boolean).join(" · ")}</span>
            </span>
          </Link>
        </li>
      ),
    });
  }
  fuItems.sort((a, b) => a.date.localeCompare(b.date));
  const exItems: { key: string; node: ReactNode }[] = [];
  for (const e of exams || []) {
    const ne = e.next_exam as AnyRow | null;
    const inNow = e.exam_state === "in_exams";
    const dd = ne && ne.start ? daysUntil(ne.start) : null;
    if (!inNow && !(dd !== null && dd >= 0 && dd <= 14)) continue;
    exItems.push({
      key: inNow ? `0-${ne && ne.end ? ne.end : ""}` : `1-${ne!.start}`,
      node: (
        <li key={`e${e.college_id}`}>
          <Link to={`${portalPath.college(String(e.college_id))}?tab=exams`} className="vd-up">
            <span className="vd-up-date">
              <strong>{inNow ? "Now" : noYear(fmt.date(ne!.start))}</strong>
              <small>{inNow ? (ne && ne.end ? `ends ${fmt.days(ne.end)}` : "running") : fmt.days(ne!.start)}</small>
            </span>
            <span className="vd-up-main">
              <strong>{e.name || e.college_id}</strong>
              <span className="vd-muted vd-small">{examRange(ne)}</span>
            </span>
            <StatusBadge kind="exam_state" value={e.exam_state} />
          </Link>
        </li>
      ),
    });
  }
  exItems.sort((a, b) => a.key.localeCompare(b.key));
  return (
    <div className="vd-up-grid">
      <div className="vd-up-block">
        <h3 className="vd-h3">
          <Icon name="followup" size={16} />
          Follow-ups due<span className="vd-count">{fmt.num(fuItems.length)}</span>
        </h3>
        {fuError ? <ErrorNote error={fuError} what="follow-ups" /> : null}
        {fuItems.length ? (
          <Expandable items={fuItems.map((x) => x.node)} limit={3} className="vd-uplist" />
        ) : (
          <p className="vd-muted vd-small vd-up-empty">{S.followups_open > 0 ? "No open follow-up is due in the next 14 days." : "No follow-ups yet. Add one from a college page when you plan a call or visit."}</p>
        )}
      </div>
      <div className="vd-up-block">
        <h3 className="vd-h3">
          <Icon name="exam" size={16} />
          Exams<span className="vd-count">{fmt.num(exItems.length)}</span>
        </h3>
        {exError ? <ErrorNote error={exError} what="exams" /> : null}
        {exItems.length ? <Expandable items={exItems.map((x) => x.node)} limit={3} className="vd-uplist" /> : <p className="vd-muted vd-small vd-up-empty">No exams running or starting in the next 14 days.</p>}
      </div>
    </div>
  );
}
