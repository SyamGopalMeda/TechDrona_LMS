/** Exams tab and Activity tab (follow-ups, activity log, change history) of the college page. */
import { Link } from "react-router";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import type { AuditEntry } from "../../lib/types";
import { Badge, EmptyState, Kv, LinkButton, Section, StatusBadge, WriteOnly } from "../../ui";
import { addFollowup } from "../../forms/Followup";
import { logActivity } from "../../forms/Activity";
import { EXAM_STATUS_LABEL, evidenceLabel, sourceUrls } from "../exams/labels";
import type { CollegeCtx } from "./ctx";
import { ENTITY_LABEL, SKIP_FIELDS, collegeLabel, examCountdown, fieldLabel, parseJ, shortVal, type ExamX } from "./model";
import { ActivityList, Btn, FollowupList, ISSUE_LABEL, SourceLink, Txt, branchLabel, type ActivityItem, type FollowupItem } from "./parts";

const dt = (v: string | null | undefined) => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? fmt.date(v) : v);

function ExamSource({ x }: { x: ExamX }) {
  if (!x.source_url) return <Txt v={null} />;
  const urls = sourceUrls(x.source_url);
  if (!urls.length) return <>{String(x.source_url)}</>;
  return (
    <span className="vx-row">
      {urls.map((u) => (
        <SourceLink key={u} url={u} />
      ))}
    </span>
  );
}

export function ExamsTab({ c: cx }: { c: CollegeCtx }) {
  const { d, ex } = cx;
  const lines = examCountdown(ex);
  const rows = (d.exams ?? []).slice().sort((a, b) => String(a.semester).localeCompare(String(b.semester)));
  return (
    <div className="vc-tab vc-exams-tab">
      <div className="vc-exam-now td-card">
        <StatusBadge kind="exam_state" value={ex.state || "unknown"} />
        <div className="vc-countdown">
          {lines.length ? (
            lines.map((l, i) => (
              <div key={i} className={i === 0 ? "vc-cd-main" : "vc-cd-sub"}>
                {l}
              </div>
            ))
          ) : (
            <div className="vc-cd-sub">{ex.state === "unknown" ? "Dates not published yet. Confirm with the college before planning a visit." : "No upcoming exams known."}</div>
          )}
        </div>
      </div>
      <Section
        title="Exam windows"
        sub="Avoid outreach while students write 3-1 / 4-1 exams."
        actions={
          <Link to={portalPath.exams} className="vx-link vx-small">
            All exams
          </Link>
        }
      >
        {rows.length ? (
          <div className="vc-exam-grid">
            {rows.map((x) => (
              <article key={x.id} className="vc-exam-card">
                <h3 className="vc-exam-title">
                  {`${x.semester === "4-1" ? "Final year" : "Third year"} (${x.semester})`}
                  {x.exam_body ? <span className="vx-muted vx-small">{` · exams set by ${x.exam_body}`}</span> : null}
                </h3>
                <div className="vx-row">
                  <Badge tone={/no current|unverified/i.test(x.status || "") ? "neutral" : "info"}>{(x.status && EXAM_STATUS_LABEL[x.status]) || x.status || "Not known"}</Badge>
                  {x.evidence ? (
                    <span title={`${x.evidence}${x.confidence ? ` · ${x.confidence} confidence` : ""}`}>
                      <Badge tone={/unverified|conflict/i.test(x.evidence) ? "warn" : "good"}>{evidenceLabel(x.evidence, x.confidence)}</Badge>
                    </span>
                  ) : null}
                </div>
                <Kv
                  pairs={[
                    ["End-semester exams", x.endsem_start || x.endsem_end ? `${dt(x.endsem_start) || "start not known"} → ${dt(x.endsem_end) || "end not known"}` : <Txt v={null} />],
                    x.mid_window ? ["Mid exams", x.mid_window] : null,
                    x.lab_window ? ["Labs / practicals", x.lab_window] : null,
                    x.notice_date ? ["Notice published", dt(x.notice_date)] : null,
                    ["Source", <ExamSource x={x} />],
                    x.verified_on ? ["Last checked", dt(x.verified_on)] : null,
                  ]}
                />
                {x.notes ? <p className="vx-small vx-muted">{x.notes}</p> : null}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No exam information yet"
            icon="exam"
            text="Exam dates for this college have not been researched. Add them on the Exams page once the college publishes a notice."
            actions={[
              <LinkButton key="open" to={portalPath.exams} size="sm">
                Open Exams
              </LinkButton>,
            ]}
          />
        )}
      </Section>
    </div>
  );
}

export function ActivityTab({ c: cx }: { c: CollegeCtx }) {
  const { d, s } = cx;
  const c = d.college;
  const fu = d.followups ?? [];
  const bmap = new Map(s.branches.map((b) => [String(b.id), b]));
  const pmap = new Map(s.people.map((p) => [String(p.id), p]));
  const labelled: FollowupItem[] = fu.map((f) => {
    const br = f.scope_type === "branch" ? bmap.get(String(f.scope_id)) : undefined;
    const pe = f.scope_type === "person" ? pmap.get(String(f.scope_id)) : undefined;
    return { ...f, _orig: f, title: `${f.title || (f.issue ? ISSUE_LABEL[f.issue] : null) || "Follow-up"}${br ? ` · ${branchLabel(br)}` : pe ? ` · ${pe.full_name}` : ""}` };
  });
  const acts: ActivityItem[] = (d.recent_activities ?? []).map((a) => {
    const x = a as typeof a & { person_name?: string | null; branch_code?: string | null; created_by?: string | null };
    return {
      ...x,
      person_name: x.person_name || pmap.get(String(a.person_id))?.full_name,
      branch_code: x.branch_code || (a.branch_id ? branchLabel(bmap.get(String(a.branch_id))) : null),
    };
  });
  const done = labelled.filter((f) => f.status === "done");
  const label = collegeLabel(c);
  return (
    <div className="vc-tab vc-fu">
      <WriteOnly>
        <div className="vx-actions vc-act-bar">
          <Btn small icon="followup" tone="primary" onClick={() => void addFollowup({ scope_type: "college", scope_id: c.id, college_id: c.id, label })}>
            Add follow-up
          </Btn>
          <Btn small icon="clock" onClick={() => void logActivity({ college_id: c.id })}>
            Log activity
          </Btn>
        </div>
      </WriteOnly>
      <Section title={`Open follow-ups (${fu.filter((f) => f.status === "open").length})`}>
        <FollowupList list={labelled.filter((f) => f.status === "open")} emptyText="Nothing planned. Add a follow-up so the next call or visit is not forgotten." />
      </Section>
      <Section title="Activity log" sub={acts.length ? `${fmt.plural(acts.length, "recent activity", "recent activities")} · ${fmt.num(d.rollup?.reached || 0)} students reached in total` : undefined}>
        <ActivityList list={acts} />
      </Section>
      {done.length ? (
        <details className="vc-done">
          <summary>{`Completed follow-ups (${done.length})`}</summary>
          <FollowupList list={done} />
        </details>
      ) : null}
      <Section
        title="Change history"
        actions={
          <Link to={`${portalPath.audit}?entity=college&entity_id=${encodeURIComponent(c.id)}`} className="vx-link vx-small">
            Full audit log
          </Link>
        }
      >
        <AuditList entries={d.audit ?? []} />
      </Section>
    </div>
  );
}

export function AuditList({ entries }: { entries: AuditEntry[] }) {
  if (!entries.length) return <EmptyState title="No changes recorded yet" icon="audit" text="Every edit made in the portal — by whom and when — shows up here." />;
  return (
    <ol className="vc-audit">
      {entries.map((a) => {
        const before = parseJ(a.before) ?? {};
        const after = parseJ(a.after) ?? {};
        const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => !SKIP_FIELDS.has(k) && JSON.stringify(before[k]) !== JSON.stringify(after[k]));
        const pick = (k: string) => after[k] || before[k];
        const lbl = String(pick("full_name") || pick("title") || pick("code") || pick("name") || "");
        return (
          <li key={a.id} className="vc-audit-item">
            <div className="vc-audit-head">
              <Badge tone={a.action === "create" ? "good" : a.action === "delete" ? "bad" : "info"}>{a.action}</Badge>
              <span className="vc-audit-what">
                <strong>{ENTITY_LABEL[a.entity] || a.entity}</strong>
                {lbl ? ` · ${lbl}` : ""}
              </span>
              <span className="vx-muted vx-small vc-audit-when">{`${a.actor || "unknown"} · ${a.at ? `${fmt.date(a.at)}, ${String(a.at).slice(11, 16)}` : ""}`}</span>
            </div>
            {a.action === "update" && keys.length ? (
              <ul className="vc-diff">
                {keys.slice(0, 12).map((k) => (
                  <li key={k}>
                    <span className="vc-diff-key">{fieldLabel(k)}</span> <span className="vc-diff-old">{shortVal(before[k])}</span>
                    {" → "}
                    <span className="vc-diff-new">{shortVal(after[k])}</span>
                  </li>
                ))}
              </ul>
            ) : a.action === "create" && keys.length ? (
              <div className="vx-small vx-muted">
                {keys
                  .filter((k) => after[k] != null && after[k] !== "" && !/^(id|is_demo|college_id)$/.test(k))
                  .slice(0, 8)
                  .map((k) => `${fieldLabel(k)}: ${shortVal(after[k])}`)
                  .join(" · ")}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
