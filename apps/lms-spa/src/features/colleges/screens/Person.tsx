/**
 * Person (/colleges/person/:id) — port of js/views/people.js `renderPerson`: where they fit, contact, targets &
 * performance (own / team / combined per period, server values only), their team tree, credited enrollments,
 * follow-ups, activities and change history, with every action of the old page.
 */
import "@/features/colleges/styles/views/college.css";
import "@/features/colleges/styles/views/ops.css";
import { useMemo, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { PortalApiError } from "../lib/api";
import { usePortalQuery } from "../lib/cache";
import { fmt } from "../lib/fmt";
import { useQueryState } from "../lib/query";
import { portalPath } from "../lib/routes";
import type { PortalMeta } from "../lib/types";
import { usePortalPage } from "../shell/page-context";
import {
  ROLE_LABEL,
  StageBadge,
  addFollowup,
  deactivatePerson,
  editEnrollment,
  formatPhone,
  logActivity,
  mondayOf,
  movePerson,
  peopleRows,
  periodLabel,
  personDialog,
  reactivatePerson,
  recordEnrollment,
  replaceLead,
} from "../forms";
import { Button, ContactActions, EmptyState, ErrorCard, Icon, Kv, LinkButton, Menu, PageHeader, ProgressBar, Section, Segmented, Skeleton, StatusChip, WriteOnly, usePortalUi, type MenuItem } from "../ui";
import { ActivityList, FollowupList } from "./college/parts";
import { ContactCell, ISSUE_TEXT, RoleChip, collegeOf, isLeadRole } from "./People";
import { targetDialog } from "./targets/TargetDialog";
import { useServerToday } from "./targets/common";

/* eslint-disable @typescript-eslint/no-explicit-any -- API rows */
type Raw = Record<string, any>;
type TreeNode = { p: Raw; children: TreeNode[] };

function treeOf(people: Raw[], rootId: unknown): TreeNode[] {
  const kids = new Map<number, Raw[]>();
  for (const p of people) {
    if (p.reports_to == null) continue;
    const k = Number(p.reports_to);
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k)!.push(p);
  }
  const seen = new Set([Number(rootId)]);
  const walk = (id: unknown): TreeNode[] =>
    (kids.get(Number(id)) || [])
      .filter((p) => !seen.has(Number(p.id)) && !!seen.add(Number(p.id)))
      .sort((a, b) => Number(a.status === "inactive") - Number(b.status === "inactive") || String(a.full_name).localeCompare(b.full_name))
      .map((p) => ({ p, children: walk(p.id) }));
  return walk(rootId);
}

function TreeList({ nodes }: { nodes: TreeNode[] }) {
  if (!nodes.length) return null;
  return (
    <ul className="v-person__tree">
      {nodes.map(({ p, children }) => (
        <li key={p.id}>
          <div className={`v-person__node${p.status === "inactive" ? " is-inactive" : ""}`}>
            <Link to={portalPath.person(p.id)}>{p.full_name}</Link>
            <RoleChip p={p} />
            {p.status !== "active" ? <StatusChip status={p.status} size="sm" /> : null}
            <span className="vx-small vx-muted td-num">{`${fmt.num(p.actual_own ?? p.enrolled ?? 0)} confirmed`}</span>
            <ContactCell p={p} />
          </div>
          <TreeList nodes={children} />
        </li>
      ))}
    </ul>
  );
}

const Fig = ({ label, v }: { label: string; v: ReactNode }) => (
  <div className="vx-fig">
    <div className="vx-fig-label">{label}</div>
    <div className="vx-fig-value td-num">{v}</div>
  </div>
);

/** One "Own / Team / Combined" block from a /api/performance row (values as returned). */
function PerfBlock({ title, b, note }: { title: string; b: Raw | null | undefined; note?: string }) {
  if (!b) return null;
  const actual = b.actual ?? 0;
  const rng = fmt.range(b.min, b.max);
  return (
    <div className="v-person__perf">
      <div className="v-person__perfhead">
        <strong>{title}</strong>
        <StatusChip status={b.status} size="sm" />
        {note ? <span className="vx-small vx-muted">{note}</span> : null}
      </div>
      <ProgressBar actual={actual} target={b.target} min={b.min} max={b.max} size="md" unit="enrolled" status={b.status} pct={b.pct} />
      {b.covers && Number(b.covers.total) > 0 && Number(b.covers.with_target) < Number(b.covers.total) ? (
        <p className="vx-small vx-muted">{`${fmt.num(b.covers.with_target)} of ${fmt.plural(b.covers.total, "member")} have a target for this period — the team is judged only when everyone has one.`}</p>
      ) : null}
      <div className="vx-figs v-person__figs">
        <Fig label="Target" v={b.target == null ? "—" : `${fmt.num(b.target)}${rng ? ` (${rng})` : ""}`} />
        <Fig label="Actual" v={fmt.num(actual)} />
        <Fig label="Remaining" v={b.remaining == null ? "—" : fmt.num(b.remaining)} />
        <Fig label="Exceeded by" v={b.exceeded_by ? fmt.num(b.exceeded_by) : "—"} />
        <Fig label="Achieved" v={fmt.pctPts(b.pct)} />
      </div>
    </div>
  );
}

export function Person() {
  const { id = "" } = useParams();
  const { canWrite } = usePortalUi();
  const detail = usePortalQuery<Raw>(`people/${encodeURIComponent(id)}`);
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const p: Raw = detail.data?.person || {};
  const collegeId = p.college_id ? String(p.college_id) : null;
  const colRes = usePortalQuery<unknown>(collegeId ? "people" : null, { query: { college_id: collegeId ?? "", page: 1, page_size: 200 } });
  const auditRes = usePortalQuery<unknown>(p.id != null ? "audit" : null, { query: { entity: "person", entity_id: String(p.id ?? ""), limit: 15 } });
  const tgtRes = usePortalQuery<unknown>(p.id != null ? "targets" : null, { query: { scope: `person:${p.id}` } });
  const serverToday = useServerToday();
  const [q, setQuery] = useQueryState();

  const d = detail.data;
  const c: Raw = d?.college || (d ? collegeOf(p) : null) || {};
  usePortalPage({
    title: d ? p.full_name || "Person" : "Person",
    crumbs: d
      ? [{ label: "Team", to: portalPath.people }, ...(c.id ? [{ label: String(c.short_name || c.name), to: `${portalPath.college(String(c.id))}?tab=team` }] : []), { label: String(p.full_name || "(no name)") }]
      : [{ label: "Team", to: portalPath.people }, { label: detail.error ? "Not found" : "…" }],
  });

  // periods: programme, this month, this week (server TODAY) + any period that has a stored target
  const td = /^\d{4}-\d{2}-\d{2}$/.test(String(serverToday || "")) ? serverToday! : new Date().toISOString().slice(0, 10);
  const periods = useMemo(() => {
    const list = [
      { value: "programme", label: "Programme" },
      { value: `month:${td.slice(0, 7)}`, label: "This month" },
      { value: `week:${mondayOf(td)}`, label: "This week" },
    ];
    for (const r of Array.isArray(tgtRes.data) ? (tgtRes.data as Raw[]) : []) {
      const k = r.period_key || "programme";
      if (!list.some((x) => x.value === k)) list.push({ value: k, label: periodLabel(k) });
    }
    return list;
  }, [td, tgtRes.data]);
  const period = q.period && periods.some((x) => x.value === q.period) ? q.period : "programme";
  const perfQ = usePortalQuery<Raw>(collegeId ? "performance" : null, { keepPrevious: true, query: { level: "person", period, college_id: collegeId ?? "", include_inactive: 1 } });

  if (detail.loading && !d)
    return (
      <div className="v-people v-person">
        <Skeleton lines={6} />
      </div>
    );
  if (!d) {
    const e = detail.error as PortalApiError | undefined;
    return (
      <div className="v-people v-person">
        <EmptyState
          icon="people"
          title={e?.status === 404 ? "Person not found" : "Could not load this person"}
          text={e?.status === 404 ? "They may have been removed. Go back to the team directory to find someone else." : e?.message}
          actions={[
            <LinkButton key="back" to={portalPath.people}>
              Back to team
            </LinkButton>,
          ]}
        />
      </div>
    );
  }

  const colPeople = peopleRows(colRes.data) as Raw[];
  const lead = p.lead || (p.reports_to ? colPeople.find((x) => Number(x.id) === Number(p.reports_to)) : null);
  const leadRow: Raw | null = lead ? colPeople.find((x) => Number(x.id) === Number(lead.id)) || lead : null;
  const collegeLead = colPeople.find((x) => x.role === "college_lead" && x.status !== "inactive");
  const chain: Raw[] = [];
  {
    let cur: Raw | undefined = p;
    const seen = new Set([Number(p.id)]);
    while (cur && cur.reports_to && !seen.has(Number(cur.reports_to))) {
      seen.add(Number(cur.reports_to));
      const b = colPeople.find((x) => Number(x.id) === Number(cur!.reports_to));
      if (!b) break;
      chain.unshift(b);
      cur = b;
    }
  }
  const tree = treeOf(colPeople, p.id);
  const isLead = isLeadRole(p.role);
  const edit = () => void personDialog({ id: p.id });
  const setTarget = () => void targetDialog({ scope_type: "person", scope_id: String(p.id), label: p.full_name, period });
  const moreItems: MenuItem[] = [
    { label: "Record enrollment", icon: "plus", writeOnly: true, onClick: () => void recordEnrollment({ college_id: p.college_id, person_id: p.id }) },
    { label: "Log activity", icon: "clock", writeOnly: true, onClick: () => void logActivity({ college_id: p.college_id, person_id: p.id }) },
    { label: "Add follow-up", icon: "followup", writeOnly: true, onClick: () => void addFollowup({ scope_type: "person", scope_id: String(p.id), college_id: p.college_id, label: p.full_name }) },
    { label: "Move to another college…", icon: "college", writeOnly: true, onClick: () => void movePerson(p as { id: number }) },
    { label: "Replace as college lead…", icon: "lead", writeOnly: true, hidden: !(p.role === "college_lead" && p.status !== "inactive"), onClick: () => void replaceLead(p as { id: number }) },
    p.status === "inactive"
      ? { label: "Reactivate", icon: "check", writeOnly: true, onClick: () => void reactivatePerson(p as never) }
      : { label: "Deactivate…", icon: "close", tone: "danger", writeOnly: true, onClick: () => void deactivatePerson(p as { id: number }) },
  ];
  const cName = c.short_name || c.name;

  // performance block (server values only)
  let perfBody: ReactNode;
  const perr = perfQ.error as PortalApiError | undefined;
  if (perr && (perr.status === 404 || perr.status === 400)) {
    const rr: Raw = d.rollup || {};
    perfBody = (
      <p className="vx-muted">
        {period === "programme"
          ? `Confirmed: ${fmt.num(rr.enrolled ?? 0)}${rr.target != null ? ` of ${fmt.num(rr.target)} target` : " · no target"}. Monthly and weekly figures need the updated server.`
          : "Monthly and weekly performance needs the updated server."}
      </p>
    );
  } else if (perr && !perfQ.data) {
    perfBody = <ErrorCard title="Could not load performance" error={perr} retry={() => void perfQ.reload()} />;
  } else if (!perfQ.data) {
    perfBody = <Skeleton lines={2} card={false} />;
  } else {
    const per: Raw | undefined = perfQ.data.period;
    const row: Raw | undefined = (perfQ.data.rows || []).find((x: Raw) => Number(x.id) === Number(p.id));
    if (!row) perfBody = <p className="vx-muted">No performance row for this period.</p>;
    else {
      const own = { min: row.min, target: row.target, max: row.max, actual: row.actual_own ?? row.actual, remaining: row.remaining, exceeded_by: row.exceeded_by, pct: row.pct, status: row.status };
      perfBody = (
        <>
          {per ? (
            <p className="vx-small vx-muted">
              {`${per.label || periodLabel(period)}${per.start && !/\d{4}\s*[–-]/.test(per.label || "") ? ` · ${fmt.date(per.start)} – ${fmt.date(per.end)}` : ""}${per.days_total ? ` · day ${fmt.num(per.days_elapsed)} of ${fmt.num(per.days_total)}` : ""}. Confirmed enrollments only.`}
            </p>
          ) : null}
          <div className="v-person__perfgrid">
            <PerfBlock title="Own" b={own} note="credited to them" />
            {row.team ? <PerfBlock title="Team" b={row.team} note={`${fmt.num(row.team.size ?? 0)} ${row.team.size === 1 ? "person" : "people"} below them · against the team's targets`} /> : null}
            {row.combined ? <PerfBlock title="Combined" b={row.combined} note="own + team, against own + team targets" /> : null}
          </div>
          {row.below_min ? <p className="vf-note vf-note--warn">Below the minimum for this period.</p> : null}
          {row.above_max ? <p className="vf-note">Above the stretch maximum for this period.</p> : null}
        </>
      );
    }
  }

  const enr: Raw[] = d.enrollments || [];
  const conf = enr.filter((e) => e.stage === "confirmed" || !e.stage).length;
  const dropped = enr.filter((e) => e.stage === "dropped").length;
  const courses = meta.data?.courses || [];
  const fu: Raw[] = d.followups || [];
  const audit: Raw[] = Array.isArray(auditRes.data) ? (auditRes.data as Raw[]) : ((auditRes.data as Raw)?.items ?? (auditRes.data as Raw)?.rows ?? []);
  const teamN = tree.length ? (p.team_size ?? tree.length) : 0;

  return (
    <div className="v-people v-person">
      <PageHeader
        back={{ to: portalPath.people, label: "Team" }}
        eyebrow={
          <span className="v-person__kicker">
            <RoleChip p={p} />
            <StatusChip status={p.status || "active"} size="sm" />
            {p.role !== "college_lead" && p.assignment_status && p.assignment_status !== "assigned" ? <StatusChip status={p.assignment_status} size="sm" /> : null}
          </span>
        }
        title={p.full_name || "(no name)"}
        sub={
          <span>
            {c.id ? <Link to={portalPath.college(String(c.id))}>{c.name || c.short_name}</Link> : "No college"}
            {p.designation ? ` · ${p.designation}` : ""}
          </span>
        }
        actions={
          <>
            <WriteOnly>
              <Button icon="edit" tone="primary" onClick={edit}>
                Edit
              </Button>
              <Button icon="target" onClick={setTarget}>
                Set target
              </Button>
            </WriteOnly>
            <Menu ariaLabel="More actions" items={moreItems} />
          </>
        }
      />

      {p.role !== "college_lead" && p.status !== "inactive" && p.assignment_status && p.assignment_status !== "assigned" ? (
        <div className="vx-callout vx-callout-warn" role="status">
          <span className="vx-callout-ic">
            <Icon name="warn" />
          </span>
          <div className="vx-callout-body">
            <strong>{ISSUE_TEXT[p.assignment_issue] || "No lead assigned"}</strong>
            <div className="vx-callout-text">
              {collegeLead ? `Assign ${p.full_name} to a lead of ${cName}.` : `${cName || "This college"} has no active college lead yet — appoint one, then assign ${p.full_name}.`}
            </div>
          </div>
          {canWrite ? (
            <Button size="sm" onClick={() => (collegeLead ? edit() : void personDialog({ college_id: p.college_id, role: "college_lead" }))}>
              {collegeLead ? "Assign lead" : "Appoint college lead"}
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="v-person__grid">
        <Section title="Where they fit">
          <div className="v-person__fit">
            <Kv
              pairs={[
                ["College", c.id ? <Link to={portalPath.college(String(c.id))}>{c.name || c.short_name}</Link> : "—"],
                [
                  "College lead",
                  p.role === "college_lead" ? "This person" : collegeLead ? <Link to={portalPath.person(collegeLead.id)}>{collegeLead.full_name}</Link> : <span className="vx-warn-text">None appointed</span>,
                ],
                p.role === "college_lead"
                  ? ["Reports to", "Tech Drona"]
                  : [
                      "Managed by",
                      leadRow ? (
                        <span className="v-person__mgr">
                          <Link to={portalPath.person(leadRow.id)} className={leadRow.status === "inactive" ? "is-inactive" : undefined}>
                            {leadRow.name || leadRow.full_name}
                          </Link>
                          {leadRow.role ? ` · ${ROLE_LABEL[leadRow.role] || leadRow.role}` : ""}
                          {leadRow.phone || leadRow.email ? <ContactCell p={leadRow} /> : null}
                        </span>
                      ) : (
                        <span className="vx-warn-text">Nobody (unassigned)</span>
                      ),
                    ],
                chain.length > 1
                  ? [
                      "Reporting line",
                      <span key="line">
                        {chain.map((x, i) => (
                          <span key={x.id}>
                            {i ? " → " : ""}
                            <Link to={portalPath.person(x.id)}>{x.full_name}</Link>
                          </span>
                        ))}
                        {" → "}
                        <strong>{p.full_name}</strong>
                      </span>,
                    ]
                  : null,
                isLead || tree.length ? ["Reports to them", tree.length ? `${fmt.num(teamN)} ${teamN === 1 ? "person" : "people"} (below)` : "Nobody yet"] : null,
                ["Branches", (d.branches || []).length ? (d.branches as Raw[]).map((b) => b.code || b.name).join(", ") : p.role === "college_lead" ? "Whole college" : "—"],
                ["Joined", p.joined_on ? fmt.date(p.joined_on) : "—"],
                p.notes ? ["Notes", <span key="n" className="v-person__notes">{p.notes}</span>] : null,
              ]}
            />
          </div>
        </Section>
        <Section title="Contact">
          <div className="v-person__contact">
            <div className="v-person__contactlines">
              <div>
                <Icon name="phone" /> {p.phone_norm || p.phone ? formatPhone(p.phone_norm || p.phone) : <span className="vx-muted">No phone recorded</span>}
              </div>
              <div>
                <Icon name="mail" /> {p.email || <span className="vx-muted">No email recorded</span>}
              </div>
            </div>
            <ContactActions phone={p.phone_norm || p.phone} email={p.email} whatsapp name={p.full_name} />
          </div>
        </Section>
      </div>

      <Section
        title="Targets & performance"
        actions={
          <WriteOnly>
            <Button icon="target" size="sm" onClick={setTarget}>
              Set target
            </Button>
          </WriteOnly>
        }
      >
        <div>
          <Segmented ariaLabel="Period" value={period} options={periods} onChange={(v) => setQuery({ period: v === "programme" ? null : v }, { history: "push" })} />
          <div className="v-person__perfbody">{perfBody}</div>
        </div>
      </Section>

      {isLead || tree.length ? (
        <Section
          title={`Team (${fmt.num(teamN)})`}
          sub="Everyone who reports to them, directly or through an ambassador lead."
          actions={
            <WriteOnly>
              <Button icon="plus" size="sm" onClick={() => void personDialog({ college_id: p.college_id, role: "ambassador", reports_to: p.id })}>
                Add ambassador
              </Button>
            </WriteOnly>
          }
        >
          {tree.length ? <TreeList nodes={tree} /> : <p className="vx-muted">Nobody reports to them yet.</p>}
        </Section>
      ) : null}

      <Section
        title="Enrollments credited"
        sub={enr.length ? `${fmt.num(conf)} confirmed · ${fmt.num(enr.length - conf - dropped)} in progress · ${fmt.num(dropped)} dropped` : null}
        actions={
          <WriteOnly>
            <Button icon="plus" size="sm" onClick={() => void recordEnrollment({ college_id: p.college_id, person_id: p.id })}>
              Record
            </Button>
          </WriteOnly>
        }
      >
        {enr.length ? (
          <ul className="vx-list">
            {enr.map((e) => (
              <li key={e.id} className="vx-li">
                <div className="vx-li-main">
                  <div className="vx-li-title">
                    {e.student_name || "Student (name not recorded)"} <StageBadge stage={e.stage} />
                  </div>
                  <div className="vx-li-sub">
                    {[e.course_name || courses.find((x) => Number(x.id) === Number(e.course_id))?.name || "Course not set", e.amount_inr != null ? fmt.inr(e.amount_inr) : null, e.branch_code].filter(Boolean).join(" · ")}
                  </div>
                  <div className="vx-li-sub vx-muted">{[`recorded ${fmt.date(e.enrolled_on)}`, e.confirmed_on ? `confirmed ${fmt.date(e.confirmed_on)}` : null].filter(Boolean).join(" · ")}</div>
                </div>
                <WriteOnly>
                  <Button icon="edit" tone="ghost" size="sm" ariaLabel={`Edit enrollment of ${e.student_name || "student"}`} onClick={() => void editEnrollment(e as never)}>
                    Edit
                  </Button>
                </WriteOnly>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon="target" title="No enrollments credited yet" text="Enrollments recorded with this person as “Credit to” appear here." />
        )}
      </Section>

      <div className="v-person__grid">
        <Section
          title={`Follow-ups (${fmt.num(fu.filter((x) => x.status === "open").length)} open)`}
          actions={
            <WriteOnly>
              <Button icon="plus" size="sm" onClick={() => void addFollowup({ scope_type: "person", scope_id: String(p.id), college_id: p.college_id, label: p.full_name })}>
                Add
              </Button>
            </WriteOnly>
          }
        >
          <FollowupList list={fu as never} emptyText="Nothing scheduled for this person." />
        </Section>
        <Section
          title="Activities"
          actions={
            <WriteOnly>
              <Button icon="plus" size="sm" onClick={() => void logActivity({ college_id: p.college_id, person_id: p.id })}>
                Log
              </Button>
            </WriteOnly>
          }
        >
          <ActivityList list={((d.activities || []) as Raw[]).map((a) => ({ ...a, person_name: null })) as never} />
        </Section>
      </div>

      <Section
        title="Change history"
        sub={p.updated_at ? `Last updated ${fmt.date(p.updated_at)}${p.updated_by ? ` by ${p.updated_by}` : ""}` : null}
        actions={
          <Link className="vx-link vx-small" to={`${portalPath.audit}?entity=person&entity_id=${encodeURIComponent(String(p.id))}`}>
            Full history
          </Link>
        }
      >
        {audit.length ? (
          <ul className="vx-list">
            {audit.map((a, i) => (
              <li key={a.id ?? i} className="vx-li">
                <div className="vx-li-main">
                  <div className="vx-li-title">
                    {a.action === "create" ? "Added" : a.action === "delete" ? "Deleted" : "Updated"}
                    {a.fields ? <span className="vx-small vx-muted">{` · ${([] as unknown[]).concat(a.fields).join(", ")}`}</span> : null}
                  </div>
                  <div className="vx-li-sub vx-muted">{`${a.at || a.created_at ? fmt.date(a.at || a.created_at) : ""}${a.actor ? ` · by ${a.actor}` : ""}`}</div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="vx-muted">No recorded changes.</p>
        )}
      </Section>
    </div>
  );
}
