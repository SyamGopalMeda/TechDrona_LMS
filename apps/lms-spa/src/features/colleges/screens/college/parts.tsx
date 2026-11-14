/**
 * Shared pieces of the college page and the branch drawer (port of the helper exports of js/views/branch.js):
 * branch wording, value-with-basis, callouts, source links, and the follow-up / activity / enrollment lists.
 */
import type { MouseEvent, ReactNode } from "react";
import { portalApi } from "../../lib/api";
import { fmt, today } from "../../lib/fmt";
import type { Basis } from "../../lib/types";
import { Badge, Button, EmptyState, Icon, Provenance, StatusBadge, ValueWithBasis, WriteOnly, cx, toast, type IconName } from "../../ui";
import { CATEGORY_LABEL as FORM_CATEGORY_LABEL, StageBadge } from "../../forms/labels";
import { openFollowupForm, type FollowupRow } from "../../forms/Followup";
import { editEnrollment } from "../../forms/Enrollment";
import { Progress } from "../shared/dashboard";

export const ACT_LABEL: Record<string, string> = { visit: "Visit", call: "Call", session: "Session", whatsapp: "WhatsApp", followup: "Follow-up", other: "Other" };
export const ISSUE_LABEL: Record<string, string> = {
  ambassador_gap: "Ambassador gap",
  low_outreach: "Low outreach",
  low_conversion: "Low conversion",
  unrealistic_target: "Unrealistic target",
  exams: "Exams",
  data: "Data check",
  other: "Other",
};
/** Branch groups in plain words (it_core, it_allied and circuit count toward the target by default). */
export const CATEGORY_LABEL: Record<string, string> = {
  it_core: "Computer science",
  it_allied: "CS-related (AI, data, IoT…)",
  circuit: "Electronics / electrical",
  core: "Other engineering",
  other: "Other",
  ...FORM_CATEGORY_LABEL,
};
export const TARGET_BRANCH_HELP = "Computer science, CS-related and electronics branches count toward the enrollment target.";
/** Plain labels for the branch numbers (same words in cards, tables, the drawer and the change history). */
export const BRANCH_FIG = {
  intake: "Seats / year",
  strength: "Students, all 4 years (est.)",
  final_year: "Final-year students",
  eligible: "Likely prospects (est.)",
} as const;
export const BRANCH_FIG_HELP = {
  intake: "Seats the branch admits each year (mostly from the AP EAPCET 2026 counselling list).",
  strength: "Seats per year × 4. An estimate, not a head count.",
  final_year: "Students now in the final year (joined in 2023). Estimated from the seats unless verified.",
  eligible: "Final-year students × how relevant the branch is to our courses (computer branches count fully, electronics 60%, others 15%).",
} as const;

/** Value with its basis pill; unknown → "—" + Pending. */
export function Vb({ value, basis }: { value: number | null | undefined; basis: Basis | string | null | undefined }) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return (
      <span className="vx-vb">
        <span className="vx-dash">—</span>
        <Provenance basis="pending" />
      </span>
    );
  }
  return <ValueWithBasis value={{ value, basis: (basis || "pending") as Basis }} />;
}

/** Plain text or "—" + Pending pill. */
export function Txt({ v }: { v: unknown }) {
  if (v === null || v === undefined || v === "" || v === "—") {
    return (
      <span className="vx-vb">
        <span className="vx-dash">—</span>
        <Provenance basis="pending" />
      </span>
    );
  }
  return <>{String(v)}</>;
}

export function branchLabel(b: { code?: string | null; name?: string | null; id?: number | string } | null | undefined): string {
  if (!b) return "—";
  return b.code ? String(b.code) : b.name || `Branch ${b.id}`;
}

/** Small "done / target" progress, or "N confirmed · no target". */
export function ProgressCell({ target, done }: { target: number | null | undefined; done: number | null | undefined }) {
  if (!target) return <span className="vx-muted">{done ? `${fmt.num(done)} confirmed · no target` : "No target"}</span>;
  return (
    <div className="vx-prog">
      <Progress target={target} done={done || 0} size="sm" />
      <span className="vx-prog-num">{`${fmt.num(done || 0)} / ${fmt.num(target)}`}</span>
    </div>
  );
}

/** Small button that never lets the click reach a clickable card / row underneath. */
export function Btn({
  children,
  onClick,
  icon,
  tone = "secondary",
  small,
  aria,
  title,
  className,
}: {
  children?: ReactNode;
  onClick: () => void;
  icon?: IconName;
  tone?: "primary" | "secondary" | "ghost" | "danger" | "accent";
  small?: boolean;
  aria?: string;
  title?: string;
  className?: string;
}) {
  return (
    <Button
      tone={tone}
      size={small ? "sm" : undefined}
      icon={icon}
      ariaLabel={aria}
      title={title}
      className={className}
      onClick={(e: MouseEvent) => {
        e.stopPropagation();
        onClick();
      }}
    >
      {children}
    </Button>
  );
}

export function Callout({ tone, title, children, action }: { tone: "bad" | "warn" | "info" | "good"; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={cx("vx-callout", `vx-callout-${tone}`)} role={tone === "bad" || tone === "warn" ? "status" : undefined}>
      <div className="vx-callout-ic">
        <Icon name={tone === "good" ? "check" : tone === "info" ? "clock" : "warn"} />
      </div>
      <div className="vx-callout-body">
        <strong>{title}</strong>
        {children ? <div className="vx-callout-text">{children}</div> : null}
      </div>
      {action ?? null}
    </div>
  );
}

/** Short, readable label for a source link ("kluniversity.in · PDF"). */
export function sourceLabel(url: string | null | undefined): string {
  if (!url) return "";
  if (!/^https?:\/\//i.test(url)) return String(url);
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./i, "").toLowerCase();
    return /\.pdf($|\?)/i.test(u.pathname) ? `${host} · PDF` : host;
  } catch {
    return String(url).slice(0, 48);
  }
}
export function SourceLink({ url, label }: { url: string | null | undefined; label?: string }) {
  if (!url) return null;
  if (!/^https?:\/\//i.test(url)) return <span>{url}</span>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="vx-link" title={url}>
      {label || sourceLabel(url)}
      <Icon name="external" size={14} />
    </a>
  );
}

export function Fig({ label, help, children }: { label: ReactNode; help?: string; children: ReactNode }) {
  return (
    <div className="vx-fig" title={help}>
      <div className="vx-fig-label">{label}</div>
      <div className="vx-fig-value">{children}</div>
    </div>
  );
}

interface BranchNums {
  intake_per_year?: number | null;
  intake_basis?: Basis | null;
  final_year?: number | null;
  final_year_basis?: Basis | null;
  eligible_estimate?: number | null;
  eligible_basis?: Basis | null;
  strength_total?: number | null;
  strength_basis?: Basis | null;
}
/** Seats / final-years / prospects (+ students, all 4 years in the drawer). */
export function BranchFigures({ b, all }: { b: BranchNums; all?: boolean }) {
  return (
    <div className={cx("vx-figs", all ? "vx-figs-4" : "vx-figs-3")}>
      <Fig label={BRANCH_FIG.intake} help={BRANCH_FIG_HELP.intake}>
        <Vb value={b.intake_per_year} basis={b.intake_basis} />
      </Fig>
      <Fig label={BRANCH_FIG.final_year} help={BRANCH_FIG_HELP.final_year}>
        <Vb value={b.final_year} basis={b.final_year_basis} />
      </Fig>
      <Fig label={BRANCH_FIG.eligible} help={BRANCH_FIG_HELP.eligible}>
        <Vb value={b.eligible_estimate} basis={b.eligible_basis} />
      </Fig>
      {all ? (
        <Fig label={BRANCH_FIG.strength} help={BRANCH_FIG_HELP.strength}>
          <Vb value={b.strength_total} basis={b.strength_basis} />
        </Fig>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ lists */

export type FollowupItem = FollowupRow & { _orig?: FollowupRow };

async function markDone(f: FollowupItem): Promise<void> {
  try {
    await portalApi.patch(`followups/${f.id}`, { status: "done" });
    toast("Follow-up marked done", "good");
  } catch (e) {
    toast(e instanceof Error && e.message ? e.message : "Could not update follow-up", "bad");
  }
}

/** Follow-ups, open first (old branch.js followupList). */
export function FollowupList({ list, emptyText }: { list: FollowupItem[]; emptyText?: string }) {
  const rows = list.slice().sort((a, b) => (a.status === b.status ? String(a.due_date || "9").localeCompare(String(b.due_date || "9")) : a.status === "open" ? -1 : 1));
  if (!rows.length) return <EmptyState title="No follow-ups" text={emptyText || "Nothing scheduled yet."} />;
  const t = today();
  return (
    <ul className="vx-list">
      {rows.map((f) => {
        const overdue = f.status === "open" && !!f.due_date && f.due_date < t;
        const issueLabel = f.issue ? (ISSUE_LABEL[f.issue] ?? f.issue) : null;
        return (
          <li key={f.id} className={cx("vx-li", f.status === "done" && "is-done", overdue && "is-overdue")}>
            <div className="vx-li-main">
              <div className="vx-li-title">{f.title || (f.issue ? ISSUE_LABEL[f.issue] : null) || "Follow-up"}</div>
              <div className="vx-li-sub vx-row">
                <StatusBadge kind="followup" value={overdue ? "overdue" : f.status} />
                {f.issue && f.title && f.title !== issueLabel ? <Badge tone="neutral">{issueLabel}</Badge> : null}
                <span>
                  {[
                    f.status === "done" && f.done_at ? `Done ${fmt.date(f.done_at)}` : f.due_date ? `Due ${fmt.date(f.due_date)} (${fmt.days(f.due_date)})` : "No due date",
                    f.owner_name ? `owner ${f.owner_name}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              {f.notes ? <div className="vx-li-sub vx-muted">{f.notes}</div> : null}
            </div>
            <WriteOnly>
              <span className="vx-rowactions">
                <Btn small icon="edit" aria={`Edit or reschedule follow-up "${f.title || "Follow-up"}"`} title="Edit or reschedule" onClick={() => void openFollowupForm({ row: f._orig ?? f })} />
                {f.status === "open" ? (
                  <Btn small icon="check" onClick={() => void markDone(f)}>
                    Mark done
                  </Btn>
                ) : null}
              </span>
            </WriteOnly>
          </li>
        );
      })}
    </ul>
  );
}

export interface ActivityItem {
  id: number | string;
  type?: string | null;
  on_date?: string | null;
  students_reached?: number | null;
  person_name?: string | null;
  branch_code?: string | null;
  created_by?: string | null;
  notes?: string | null;
}
export function ActivityList({ list, emptyText }: { list: ActivityItem[]; emptyText?: string }) {
  if (!list.length) return <EmptyState title="No activity yet" text={emptyText || "Log visits, calls and sessions here."} />;
  return (
    <ul className="vx-list">
      {list.map((a) => (
        <li key={a.id} className="vx-li">
          <div className="vx-li-main">
            <div className="vx-li-title">
              {(a.type && ACT_LABEL[a.type]) || a.type || "Activity"}
              {a.students_reached ? <span className="vx-muted">{` · ${fmt.num(a.students_reached)} students reached`}</span> : null}
            </div>
            <div className="vx-li-sub">
              {[fmt.date(a.on_date), a.person_name, a.branch_code && a.branch_code !== "—" ? a.branch_code : null, a.created_by ? `logged by ${a.created_by}` : null].filter(Boolean).join(" · ")}
              {a.notes ? <div className="vx-muted">{a.notes}</div> : null}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export interface EnrollmentItem {
  id: number;
  student_name?: string | null;
  stage?: string | null;
  enrolled_on?: string | null;
  course_id?: number | null;
  course_name?: string | null;
  amount_inr?: number | null;
  branch_id?: number | null;
  branch_code?: string | null;
  person_id?: number | null;
  person_name?: string | null;
  is_demo?: number | boolean | null;
  [k: string]: unknown;
}
export function EnrollmentList({
  list,
  courses = [],
  people = [],
  branches = [],
  emptyText,
}: {
  list: EnrollmentItem[];
  courses?: { id: number; name: string }[];
  people?: { id: number; full_name: string }[];
  branches?: { id: number; code?: string | null; name?: string | null }[];
  emptyText?: string;
}) {
  if (!list.length) return <EmptyState title="No enrollments yet" text={emptyText || "Recorded enrollments appear here."} />;
  return (
    <ul className="vx-list">
      {list.map((e) => {
        const br = e.branch_code || (e.branch_id ? branchLabel(branches.find((b) => Number(b.id) === Number(e.branch_id))) : null);
        const who = e.person_name || people.find((p) => Number(p.id) === Number(e.person_id))?.full_name;
        const meta = [fmt.date(e.enrolled_on), br && br !== "—" ? br : null, who ? `credited to ${who}` : "not credited to anyone"].filter(Boolean).join(" · ");
        const course = e.course_name || courses.find((c) => Number(c.id) === Number(e.course_id))?.name || "Course not set";
        return (
          <li key={e.id} className="vx-li vx-li--enr">
            <div className="vx-li-main">
              <div className="vx-li-title">
                {e.student_name || "Student (name not recorded)"} <StageBadge stage={e.stage || "confirmed"} />
                {e.is_demo ? <span className="td-badge td-badge--bad vx-demo">DEMO</span> : null}
              </div>
              <div className="vx-li-sub">{[course, e.amount_inr != null ? fmt.inr(e.amount_inr) : null].filter(Boolean).join(" · ")}</div>
              <div className="vx-li-sub vx-muted">{meta}</div>
            </div>
            <WriteOnly>
              <Btn small tone="ghost" icon="edit" aria={`Update stage of ${e.student_name || "this enrollment"}`} onClick={() => void editEnrollment(e as Parameters<typeof editEnrollment>[0])}>
                Update stage
              </Btn>
            </WriteOnly>
          </li>
        );
      })}
    </ul>
  );
}
