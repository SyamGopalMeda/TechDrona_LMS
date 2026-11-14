/**
 * Branch detail drawer (port of js/views/branch.js openBranch / renderBranchPage). The college page opens it
 * from `?branch=<id>` so it is deep-linkable and Back closes it; elsewhere it can be mounted with any id.
 *
 *   <BranchDrawer branchId="12" inCollege onClose={…} />
 */
import { useEffect } from "react";
import { Link, useNavigate } from "react-router";
import { isPortalApiError } from "../../lib/api";
import { usePortalQuery } from "../../lib/cache";
import { fmt } from "../../lib/fmt";
import { portalPath } from "../../lib/routes";
import type { Branch, Followup, Person, PortalMeta, Summary } from "../../lib/types";
import { Badge, ContactActions, DataTable, Drawer, EmptyState, Icon, Section, Skeleton, StatusBadge, WriteOnly } from "../../ui";
import { addPerson } from "../../forms/People";
import { recordEnrollment } from "../../forms/Enrollment";
import { logActivity } from "../../forms/Activity";
import { addFollowup } from "../../forms/Followup";
import { editBranch } from "../../forms/Branch";
import { ROLE_LABEL } from "../../forms/labels";
import { targetDialog } from "../targets/TargetDialog";
import { Progress } from "../shared/dashboard";
import {
  ActivityList,
  BranchFigures,
  Btn,
  CATEGORY_LABEL,
  Callout,
  EnrollmentList,
  Fig,
  FollowupList,
  SourceLink,
  TARGET_BRANCH_HELP,
  type ActivityItem,
  type EnrollmentItem,
} from "./parts";
import type { Roll } from "./model";

type BranchPerson = Person & { reports_to_name?: string | null; reached?: number | null; enrolled?: number | null; target?: number | null };
export interface BranchDetail {
  branch: Branch & { college_name?: string | null; college_short_name?: string | null; intake_source?: string | null; intake_year?: string | null; is_demo?: number | null };
  rollup?: Roll;
  people?: BranchPerson[];
  followups?: Followup[];
  activities?: ActivityItem[];
  enrollments?: EnrollmentItem[];
  college_name?: string | null;
}

export function BranchDrawer({ branchId, inCollege, onClose }: { branchId: string; inCollege?: boolean; onClose: () => void }) {
  const q = usePortalQuery<BranchDetail>(`branches/${encodeURIComponent(branchId)}`);
  const b = q.data?.branch;
  const collegeName = b ? b.college_short_name || b.college_name || q.data?.college_name || "" : "";
  const title = b ? [b.code || b.name || "Branch", collegeName].filter(Boolean).join(" · ") : "Branch";
  const gone = isPortalApiError(q.error) && q.error.status === 404;
  // e.g. the branch was just deleted from its own edit form
  useEffect(() => {
    if (gone && !q.data) onClose();
  }, [gone, q.data, onClose]);
  return (
    <Drawer open title={title} wide onClose={onClose}>
      {q.data ? (
        <BranchBody d={q.data} inCollege={inCollege} />
      ) : q.error && !gone ? (
        <div className="v-branch is-drawer">
          <EmptyState
            title="Could not load this branch"
            text={q.error instanceof Error ? q.error.message : String(q.error)}
            icon="warn"
            actions={[{ label: "Try again", icon: "refresh", onClick: () => void q.reload() }]}
          />
        </div>
      ) : (
        <div className="v-branch is-drawer" aria-busy="true">
          <div className="vb-skel">
            <div className="td-skel td-skel--title" />
            <div className="td-skel" style={{ width: "40%" }} />
          </div>
          <Skeleton lines={3} />
          <Skeleton lines={4} />
        </div>
      )}
    </Drawer>
  );
}

function BranchBody({ d, inCollege }: { d: BranchDetail; inCollege?: boolean }) {
  const navigate = useNavigate();
  const b = d.branch;
  const r: Roll = d.rollup ?? {};
  const meta = usePortalQuery<PortalMeta>("meta", { ttl: 300_000 });
  const college = usePortalQuery<Summary>(b.college_id ? "summary" : null, { query: { scope: `college:${b.college_id}` } });
  const people = d.people ?? [];
  const ambs = people.filter((p) => p.role === "ambassador");
  const leads = people.filter((p) => p.role !== "ambassador" && p.status !== "inactive");
  const activeAmbs = ambs.filter((p) => p.status !== "inactive");
  const ctxB = { college_id: b.college_id, branch_id: b.id };
  const collegeName = b.college_short_name || b.college_name || d.college_name || "";
  const gap = !!b.is_relevant && !activeAmbs.length;
  const recruit = () => void addPerson({ college_id: b.college_id, role: "ambassador", branch_ids: [b.id] });
  const setT = () => void targetDialog({ scope_type: "branch", scope_id: String(b.id), label: [collegeName, b.code || b.name].filter(Boolean).join(" · ") });

  const ct = college.data?.target ?? null;
  const share = r.target && ct ? r.target / ct : null;
  const fu = d.followups ?? [];
  const openFu = fu.filter((f) => f.status === "open").length;
  const responsibleNames = [...new Set(ambs.map((a) => a.reports_to_name).filter(Boolean))].join(", ");

  return (
    <div className="v-branch is-drawer">
      <header className="vb-head">
        <div className="vb-title">
          <div className="vb-titlerow">
            <h2>{b.name || b.code || "Branch"}</h2>
            <WriteOnly>
              <Btn small icon="edit" tone="ghost" aria="Edit branch details or delete branch" title="Edit branch details" onClick={() => void editBranch(b)}>
                Edit
              </Btn>
            </WriteOnly>
          </div>
          <div className="vx-row">
            {b.code ? <span className="vx-code">{b.code}</span> : null}
            <Badge tone={b.is_relevant ? "brand" : "neutral"}>{CATEGORY_LABEL[b.category] || b.category || "Uncategorised"}</Badge>
            <span title={TARGET_BRANCH_HELP}>{b.is_relevant ? <Badge tone="info">Target branch</Badge> : <Badge tone="neutral">Not a target branch</Badge>}</span>
            {gap ? <Badge tone="bad">No ambassador</Badge> : null}
            {r.target && r.on_track != null ? <StatusBadge kind="on_track" value={r.on_track} /> : null}
            {r.target && r.on_track === false && r.diagnosis ? <StatusBadge kind="diagnosis" value={r.diagnosis} /> : null}
            {b.is_demo ? <Badge tone="bad">DEMO</Badge> : null}
          </div>
          {!inCollege && b.college_id ? (
            <Link to={`${portalPath.college(b.college_id)}?tab=branches&branch=${encodeURIComponent(String(b.id))}`} className="vx-link vx-small">
              <Icon name="college" size={16} />
              {collegeName ? `Open ${collegeName}` : "Open college"}
            </Link>
          ) : null}
        </div>
      </header>

      <WriteOnly>
        <div className="vx-actions vb-actions" role="toolbar" aria-label="Branch actions">
          <Btn icon="plus" tone="primary" onClick={() => void recordEnrollment(ctxB)}>
            Record enrollment
          </Btn>
          <Btn icon="ambassador" onClick={recruit}>
            Add ambassador
          </Btn>
          <Btn icon="clock" onClick={() => void logActivity(ctxB)}>
            Log activity
          </Btn>
          <Btn icon="followup" onClick={() => void addFollowup({ scope_type: "branch", scope_id: String(b.id), college_id: b.college_id })}>
            Add follow-up
          </Btn>
        </div>
      </WriteOnly>

      <Section title="Students" sub="Each number shows whether it is verified, estimated or still pending. Hover a number for how it is worked out.">
        <div className="vb-students">
          <BranchFigures b={b} all />
          {b.intake_source || b.intake_year ? (
            <p className="vx-small vx-muted vb-source">
              {"Seats from: "}
              {b.intake_source ? <SourceLink url={b.intake_source} /> : "source not recorded"}
              {b.intake_year && b.intake_year !== "unspecified" ? ` (${b.intake_year})` : ""}
            </p>
          ) : null}
        </div>
      </Section>

      <Section
        title="Target and progress"
        actions={
          <WriteOnly>
            <Btn small icon="target" tone={r.target ? "secondary" : "primary"} onClick={setT}>
              {r.target ? "Change target" : "Set target"}
            </Btn>
          </WriteOnly>
        }
      >
        <div className="vb-target">
          <div className="vx-figs vx-figs-4">
            <Fig label="Target">{r.target ? fmt.num(r.target) : <span className="vx-muted">Not set</span>}</Fig>
            <Fig label="Confirmed">{fmt.num(r.enrolled ?? 0)}</Fig>
            <Fig label={r.target && (r.exceeded_by ?? 0) > 0 ? "Exceeded by" : "Remaining"}>{r.target ? fmt.num((r.exceeded_by ?? 0) > 0 ? r.exceeded_by : r.remaining) : "—"}</Fig>
            <Fig label="Students reached">{fmt.num(r.reached ?? 0)}</Fig>
          </div>
          {r.target ? <Progress target={r.target} done={r.enrolled || 0} size="md" /> : null}
          <p className="vx-small vx-muted">
            {r.target
              ? `${r.target_source === "sum_of_children" ? "Target is the sum of this branch’s ambassador targets." : "Target set for this branch."}${share != null && ct ? ` It is ${fmt.pctOf(share)} of the college target (${fmt.num(r.target)} of ${fmt.num(ct)}).` : ""}${r.deadline ? ` Deadline ${fmt.date(r.deadline)}.` : ""}`
              : ct
                ? `The college target is ${fmt.num(ct)}. Set a branch target to split it across branches.`
                : "Neither this branch nor the college has a target yet."}
          </p>
        </div>
      </Section>

      <Section title={`Ambassadors (${fmt.num(activeAmbs.length)} active)`}>
        <div className="vb-people">
          <p className="vx-small">
            <span className="vx-muted">Responsible lead: </span>
            {leads.length ? (
              <span className="vx-contacts">
                {leads.map((p) => (
                  <Link key={p.id} to={portalPath.person(p.id)} className="vx-link">
                    {`${p.full_name} (${ROLE_LABEL[p.role] ?? p.role})`}
                  </Link>
                ))}
              </span>
            ) : responsibleNames ? (
              responsibleNames
            ) : (
              <span className="vx-warn-text">none appointed yet</span>
            )}
          </p>
          {ambs.length ? (
            <DataTable<BranchPerson>
              rows={ambs.slice().sort((x, y) => Number(x.status === "inactive") - Number(y.status === "inactive"))}
              rowKey={(p) => p.id}
              caption="Ambassadors of this branch"
              onRowClick={(p) => void navigate(portalPath.person(p.id))}
              columns={[
                {
                  key: "full_name",
                  label: "Name",
                  primary: true,
                  render: (p) => (
                    <Link to={portalPath.person(p.id)} className={p.status === "inactive" ? "is-inactive" : undefined} onClick={(e) => e.stopPropagation()}>
                      {p.full_name}
                    </Link>
                  ),
                },
                { key: "contact", label: "Contact", sortable: false, render: (p) => <ContactActions phone={p.phone} email={p.email} compact whatsapp name={p.full_name} /> },
                {
                  key: "target",
                  label: "Target",
                  align: "right",
                  render: (p) => {
                    const t = p.target_summary ? p.target_summary.target : p.target;
                    return t == null ? "—" : fmt.num(t);
                  },
                },
                { key: "reached", label: "Reached", align: "right", render: (p) => fmt.num(p.reached ?? 0) },
                { key: "enrolled", label: "Confirmed", align: "right", render: (p) => fmt.num(p.actual_own ?? p.enrolled ?? 0) },
                { key: "status", label: "Status", render: (p) => <StatusBadge kind="person_status" value={p.status || "active"} /> },
              ]}
            />
          ) : (
            <Callout
              tone={b.is_relevant ? "bad" : "info"}
              title="No ambassador for this branch"
              action={
                <WriteOnly>
                  <Btn small tone={b.is_relevant ? "primary" : "secondary"} onClick={recruit}>
                    Recruit ambassador
                  </Btn>
                </WriteOnly>
              }
            >
              {b.is_relevant ? "This branch counts toward the target. Recruit at least one student ambassador to start outreach." : "This branch does not count toward the target, so an ambassador is optional."}
            </Callout>
          )}
        </div>
      </Section>

      <Section title={`Follow-ups (${fmt.num(openFu)} open)`}>
        <FollowupList list={fu} emptyText="Plan the next call or visit for this branch so it does not slip." />
      </Section>
      <Section title="Recent activity">
        <ActivityList list={(d.activities ?? []).slice(0, 15)} emptyText="Log a visit, call or session after you reach students in this branch." />
      </Section>
      <Section title="Recent enrollments">
        <EnrollmentList
          list={(d.enrollments ?? []).slice(0, 15)}
          courses={meta.data?.courses ?? []}
          people={people}
          branches={[b]}
          emptyText="When a student from this branch enrolls, record it here so progress updates."
        />
      </Section>
      {b.notes ? (
        <Section title="Research notes">
          <p className="vb-notes">{b.notes}</p>
        </Section>
      ) : null}
    </div>
  );
}

