/** What every college-page tab gets from the page (the old view's module-level `current`). */
import type { PortalMeta } from "../../lib/types";
import { addPerson as addPersonForm } from "../../forms/People";
import { targetDialog } from "../targets/TargetDialog";
import type { PlanCollege } from "../shared/dashboard";
import { collegeLabel, type CollegeData, type ExamInfo, type Shaped, type TabId } from "./model";

export interface CollegeCtx {
  d: CollegeData;
  s: Shaped;
  ex: ExamInfo;
  meta: PortalMeta | null;
  research: PlanCollege | null;
  /** switch tab (pushes a history entry) */
  go: (tab: TabId) => void;
  /** open the branch drawer (`?branch=`) */
  showBranch: (id: number | string) => void;
}

/** Add a person to this college; non-leads report to the college lead by default. */
export function addPerson(c: CollegeCtx, role: "college_lead" | "ambassador_lead" | "ambassador", extra: { branch_ids?: (number | string)[]; reports_to?: number | string } = {}): void {
  const reports_to = role === "college_lead" ? undefined : (extra.reports_to ?? c.s.lead?.id);
  void addPersonForm({ college_id: c.d.college.id, role, ...extra, reports_to });
}

export function setCollegeTarget(c: CollegeCtx): void {
  const col = c.d.college;
  void targetDialog({ scope_type: "college", scope_id: col.id, label: collegeLabel(col) });
}
