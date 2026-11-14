/** Targets & performance tab (old college.js performanceTab / collegePerfCard / peopleTable / fallbackPerf). */
import { Link } from "react-router";
import { isPortalApiError } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import { Badge, DataTable, EmptyState, ErrorCard, Icon, ProgressBar, Section, Segmented, Skeleton, StatusBadge, WriteOnly } from "../../ui";
import { recordEnrollment } from "../../forms/Enrollment";
import { ROLE_LABEL, StageBadge } from "../../forms/labels";
import { targetDialog } from "../targets/TargetDialog";
import { PerfChip, Progress, pctNumText, pctText } from "../shared/dashboard";
import { setCollegeTarget, type CollegeCtx } from "./ctx";
import { collegeLabel, perfPeriod, perfRows, personPerf, type BranchX, type PerfPeriod, type PerfRes, type PerfRow, type Shaped } from "./model";
import { Btn, EnrollmentList, ProgressCell, type EnrollmentItem } from "./parts";

const ROLE_RANK = ["college_lead", "ambassador_lead", "ambassador"];
const noPerf = (e: unknown) => isPortalApiError(e) && (e.status === 404 || e.status === 405 || e.status === 501);

export function PerformanceTab({ c: cx, period, periods, onPeriod }: { c: CollegeCtx; period: string; periods: [string, string][]; onPeriod: (p: string) => void }) {
  const { d, s, meta } = cx;
  const c = d.college;
  const r = d.rollup;
  const col = usePortalQuery<PerfRes>("performance", { query: { level: "college", college_id: c.id, period }, keepPrevious: true });
  const ppl = usePortalQuery<PerfRes>("performance", { query: { level: "person", college_id: c.id, period, include_inactive: 1 }, keepPrevious: true });
  const err = (col.error && !noPerf(col.error) ? col.error : null) ?? (ppl.error && !noPerf(ppl.error) ? ppl.error : null);
  const v3 = noPerf(col.error) && noPerf(ppl.error);

  let host;
  if (err) host = <ErrorCard title="Could not load performance" error={err} retry={() => void Promise.all([col.reload(), ppl.reload()])} />;
  else if (v3) host = <FallbackPerf cx={cx} />;
  else if (col.loading || ppl.loading) host = <Skeleton lines={3} card={false} />;
  else {
    const rows = perfRows(col.data);
    const row = rows.find((x) => String(x.id) === String(c.id)) ?? rows[0] ?? null;
    host = (
      <>
        <CollegePerfCard row={row} period={perfPeriod(col.data)} />
        <PeopleTable rows={perfRows(ppl.data)} period={perfPeriod(ppl.data)} periodKey={period} />
      </>
    );
  }

  const branchRows = s.branches.filter((b) => b.is_relevant || b.rollup.enrolled || b.rollup.target);
  const byCourse = r.by_course ?? [];
  const fn = d.funnel;
  return (
    <div className="vc-tab vc-perf">
      <div className="vc-perf-bar">
        <Segmented options={periods.map(([value, label]) => ({ value, label }))} value={period} ariaLabel="Period" onChange={onPeriod} />
        <span className="vx-grow" />
        <WriteOnly>
          <Btn small icon="plus" tone="primary" onClick={() => void recordEnrollment({ college_id: c.id })}>
            Record enrollment
          </Btn>
          <Btn small icon="target" onClick={() => setCollegeTarget(cx)}>
            Set college target
          </Btn>
        </WriteOnly>
      </div>
      <div className="vc-perf-host">{host}</div>
      {fn && fn.total ? (
        <Section title="Student pipeline" sub={fn.note ?? undefined}>
          <div className="vcc-summary">
            {fn.stages.map((x) => (
              <span key={x.stage} className="vx-small">
                <StageBadge stage={x.stage} /> <strong className="td-num">{fmt.num(x.count)}</strong>
              </span>
            ))}
          </div>
        </Section>
      ) : null}
      <Section title="By branch">
        {branchRows.length ? (
          <DataTable<BranchX>
            rows={branchRows}
            rowKey={(b) => b.id}
            caption="Targets and confirmed enrollments by branch"
            onRowClick={(b) => cx.showBranch(b.id)}
            columns={[
              { key: "code", label: "Branch", primary: true, render: (b) => `${b.code || ""} ${b.name ? `— ${b.name}` : ""}`, sortValue: (b) => b.code || b.name },
              { key: "r_target", label: "Target", align: "right", render: (b) => (b.rollup.target != null ? fmt.num(b.rollup.target) : "—"), sortValue: (b) => b.rollup.target ?? -1 },
              { key: "r_enrolled", label: "Confirmed", align: "right", render: (b) => fmt.num(b.rollup.enrolled || 0), sortValue: (b) => b.rollup.enrolled ?? 0 },
              {
                key: "r_remaining",
                label: "Remaining",
                align: "right",
                render: (b) => (b.rollup.target ? ((b.rollup.exceeded_by ?? 0) > 0 ? `+${fmt.num(b.rollup.exceeded_by)}` : fmt.num(b.rollup.remaining)) : "—"),
                sortValue: (b) => b.rollup.remaining ?? -1,
              },
              { key: "r_pct", label: "Progress", sortable: false, render: (b) => <ProgressCell target={b.rollup.target} done={b.rollup.enrolled} /> },
            ]}
            rowActions={(b) => [
              { label: "Set target", icon: "target", writeOnly: true, onClick: () => void targetDialog({ scope_type: "branch", scope_id: String(b.id), label: `${collegeLabel(c)} · ${b.code || b.name}` }) },
            ]}
          />
        ) : (
          <EmptyState title="No target branches to track" icon="branch" text="Add this college’s branches to split targets and track branch-wise enrollment." />
        )}
      </Section>
      {byCourse.length ? (
        <Section title="By course">
          <DataTable
            rows={byCourse}
            rowKey={(x) => x.name}
            caption="Enrollments by course"
            columns={[
              { key: "name", label: "Course", primary: true, render: (x) => x.name },
              { key: "price_inr", label: "Price", align: "right", render: (x) => fmt.inr(x.price_inr) },
              { key: "target", label: "Target", align: "right", render: (x) => (x.target ? fmt.num(x.target) : "—") },
              { key: "enrolled", label: "Confirmed", align: "right", render: (x) => fmt.num(x.enrolled || 0) },
              { key: "revenue_inr", label: "Revenue", align: "right", render: (x) => fmt.inr(x.revenue_inr || 0) },
            ]}
          />
        </Section>
      ) : null}
      <Section title="Recent enrollments">
        <EnrollmentList
          list={(d.recent_enrollments ?? []) as EnrollmentItem[]}
          courses={meta?.courses ?? []}
          people={s.people}
          branches={s.branches}
          emptyText="Use “Record enrollment” when a student from this college signs up. Credit the ambassador so their progress updates."
        />
      </Section>
    </div>
  );
}

function CollegePerfCard({ row, period }: { row: PerfRow | null; period: PerfPeriod | null }) {
  if (!row) return <EmptyState title="No figures for this period" text="Nothing recorded yet." />;
  const hasT = row.target != null;
  const exceeded = (row.exceeded_by ?? 0) > 0;
  const stat = (lbl: string, val: string, sub?: string | null) => (
    <div className="vc-pstat" key={lbl}>
      <span className="vx-small vx-muted">{lbl}</span>
      <strong className="td-num">{val}</strong>
      {sub ? <span className="vx-small vx-muted">{sub}</span> : null}
    </div>
  );
  return (
    <section className="vc-pcol td-card">
      <div className="vc-pcol-head">
        <div>
          <h2 className="vc-card-title">College</h2>
          <span className="vx-small vx-muted">{period ? `${period.label || ""}${period.days_total ? ` · day ${fmt.num(period.days_elapsed)} of ${fmt.num(period.days_total)}` : ""}` : ""}</span>
        </div>
        <PerfChip status={row.status} />
      </div>
      {hasT && (row.target ?? 0) > 0 ? <ProgressBar actual={row.actual ?? 0} target={row.target} min={row.min} max={row.max} status={row.status} unit="confirmed" pct={row.pct} /> : null}
      <div className="vc-pstats">
        {stat(
          "Target",
          hasT ? fmt.num(row.target) : "Not set",
          [row.min != null ? `min ${fmt.num(row.min)}` : null, row.max != null ? `max ${fmt.num(row.max)}` : null, row.target_source === "sum_of_children" ? "sum of branch targets" : null]
            .filter(Boolean)
            .join(" · ") || null,
        )}
        {stat("Confirmed", fmt.num(row.actual ?? 0), row.not_credited ? `${fmt.num(row.not_credited)} not credited to anyone` : null)}
        {stat(exceeded ? "Exceeded by" : "Remaining", hasT ? fmt.num(exceeded ? row.exceeded_by : row.remaining) : "—")}
        {stat("Achieved", pctNumText(row.pct))}
        {row.expected != null ? stat("Expected by now", fmt.num(Math.round(row.expected * 10) / 10)) : null}
      </div>
      {row.covers && Number(row.covers.total) > 0 && row.target_source === "sum_of_children" ? (
        <p className="vx-small vx-muted">{`Target covers ${fmt.num(row.covers.with_target)} of ${fmt.num(row.covers.total)} branches; only their confirmed enrollments are compared with it.`}</p>
      ) : null}
      {row.below_min ? <p className="vx-small vx-warn-text">Below the minimum.</p> : null}
      {row.above_max ? <p className="vx-small">Above the maximum.</p> : null}
    </section>
  );
}

function PeopleTable({ rows, period, periodKey }: { rows: PerfRow[]; period: PerfPeriod | null; periodKey: string }) {
  const list = rows.slice().sort((a, b) => ROLE_RANK.indexOf(String(a.role)) - ROLE_RANK.indexOf(String(b.role)) || String(a.name).localeCompare(String(b.name)));
  const role = (p: PerfRow) => `${ROLE_LABEL[String(p.role)] || p.role || ""}${p.person_status === "inactive" ? " · inactive" : ""}`;
  return (
    <Section title="People" sub={`Own figures are compared with own targets; the team below a lead is shown separately${period?.label ? ` · ${period.label}` : ""}.`}>
      {list.length ? (
        <DataTable<PerfRow>
          rows={list}
          rowKey={(p) => p.id}
          caption="People of this college: own and team performance"
          columns={[
            {
              key: "name",
              label: "Person",
              primary: true,
              priority: 1,
              minWidth: 200,
              render: (p) => (
                <div>
                  <Link to={portalPath.person(p.id)}>{p.name}</Link>
                  <div className="vx-small vx-muted">{role(p)}</div>
                </div>
              ),
              sortValue: (p) => p.name,
            },
            {
              key: "actual",
              label: "Own: confirmed vs target",
              priority: 1,
              minWidth: 200,
              sortValue: (p) => p.actual ?? 0,
              render: (p) =>
                (p.target ?? 0) > 0 ? (
                  <ProgressBar actual={p.actual ?? 0} target={p.target} min={p.min} max={p.max} size="sm" status={p.status} pct={p.pct} />
                ) : (
                  <span>
                    {fmt.num(p.actual ?? 0)}
                    <span className="vx-muted">{p.target === 0 ? " · target 0" : " · no target"}</span>
                  </span>
                ),
            },
            { key: "status", label: "Status", priority: 2, minWidth: 120, cardHidden: true, render: (p) => <PerfChip status={p.status} />, sortValue: (p) => p.status },
            {
              key: "team",
              label: "Team below",
              sortable: false,
              priority: 2,
              minWidth: 180,
              render: (p) =>
                p.team && p.team.size ? (
                  <span className="vx-small">
                    {`${fmt.num(p.team.actual ?? 0)}${p.team.target != null ? ` / ${fmt.num(p.team.target)}` : ""} · ${fmt.plural(p.team.size, "person", "people")}`}
                    {p.team.status ? (
                      <span>
                        {" "}
                        <PerfChip status={p.team.status} />
                      </span>
                    ) : null}
                  </span>
                ) : (
                  <span className="vx-muted">—</span>
                ),
            },
            {
              key: "combined",
              label: "Own + team",
              sortable: false,
              priority: 3,
              minWidth: 120,
              render: (p) =>
                p.combined && p.team && p.team.size ? (
                  <span className="td-num">{`${fmt.num(p.combined.actual ?? 0)}${p.combined.target != null ? ` / ${fmt.num(p.combined.target)}` : ""}`}</span>
                ) : (
                  <span className="vx-muted">—</span>
                ),
            },
          ]}
          rowActions={(p) => [{ label: "Set target", icon: "target", writeOnly: true, onClick: () => void targetDialog({ scope_type: "person", scope_id: String(p.id), label: String(p.name ?? ""), period: periodKey }) }]}
          cardTitle={(p) => <Link to={portalPath.person(p.id)}>{p.name}</Link>}
          cardSubtitle={(p) => role(p)}
          cardMeta={(p) => [<PerfChip key="s" status={p.status} />]}
        />
      ) : (
        <EmptyState title="No team yet" icon="people" text="Targets per person appear once the college lead and ambassadors are added in the Team tab." />
      )}
    </Section>
  );
}

/** v3 server: no /api/performance — the programme figures the server already has, and what is missing. */
function FallbackPerf({ cx }: { cx: CollegeCtx }) {
  const r = cx.d.rollup;
  const s: Shaped = cx.s;
  const hasT = (r.target ?? 0) > 0;
  return (
    <div>
      <p className="vx-small vx-muted vc-note">
        <Icon name="info" size={14} /> Week and month views appear once the server provides performance by period. Showing programme-to-date figures.
      </p>
      <section className="vc-pcol td-card">
        <div className="vc-pcol-head">
          <h2 className="vc-card-title">College</h2>
          {hasT ? <StatusBadge kind="on_track" value={r.on_track ?? null} /> : <Badge tone="neutral">No target</Badge>}
        </div>
        {hasT ? <Progress target={r.target} done={r.enrolled ?? 0} /> : null}
        <div className="vc-pstats">
          <div className="vc-pstat">
            <span className="vx-small vx-muted">Target</span>
            <strong>{r.target != null ? fmt.num(r.target) : "Not set"}</strong>
          </div>
          <div className="vc-pstat">
            <span className="vx-small vx-muted">Confirmed</span>
            <strong>{fmt.num(r.enrolled ?? 0)}</strong>
          </div>
          <div className="vc-pstat">
            <span className="vx-small vx-muted">Remaining</span>
            <strong>{r.target ? fmt.num(r.remaining) : "—"}</strong>
          </div>
          <div className="vc-pstat">
            <span className="vx-small vx-muted">Achieved</span>
            <strong>{r.target ? pctText(r.pct) : "—"}</strong>
          </div>
        </div>
      </section>
      <Section title="People">
        {s.people.length ? (
          <DataTable
            rows={s.people}
            rowKey={(p) => p.id}
            caption="People of this college"
            columns={[
              { key: "full_name", label: "Person", primary: true, render: (p) => <Link to={portalPath.person(p.id)}>{p.full_name}</Link>, sortValue: (p) => p.full_name },
              { key: "role", label: "Role", render: (p) => ROLE_LABEL[p.role] || p.role },
              { key: "target", label: "Target", align: "right", render: (p) => (personPerf(p).target != null ? fmt.num(personPerf(p).target) : "—") },
              { key: "enrolled", label: "Confirmed", align: "right", render: (p) => fmt.num(personPerf(p).actual ?? 0) },
            ]}
          />
        ) : (
          <EmptyState title="No team yet" icon="people" text="Add people in the Team tab." />
        )}
      </Section>
    </div>
  );
}
