/** Team helpers shared by the person and enrollment dialogs (old forms.js plumbing). */
import { confirm } from "../ui/Overlay";
import { ROLE_LABEL } from "./labels";

export interface TeamPerson {
  id: number;
  full_name: string;
  role: string;
  status?: string | null;
  branch_ids?: unknown;
  branches?: unknown;
  [k: string]: unknown;
}

/** Branch ids a person covers (branch_ids, branches[], or the branches' people lists). */
export function personBranchIds(p: TeamPerson, branches?: readonly { id: number | string; people?: readonly { id: number | string }[] }[]): number[] {
  const ids: unknown[] = Array.isArray(p.branch_ids)
    ? p.branch_ids
    : Array.isArray(p.branches)
      ? (p.branches as unknown[]).map((b) => (b && typeof b === "object" ? ((b as { id?: unknown; branch_id?: unknown }).id ?? (b as { branch_id?: unknown }).branch_id) : b))
      : [];
  const out = ids.map(Number).filter((x) => !Number.isNaN(x));
  if (!out.length && branches) for (const b of branches) if ((b.people || []).some((q) => Number(q.id) === Number(p.id))) out.push(Number(b.id));
  return out;
}

/** "Name (Ambassador, inactive)". */
export function personOptLabel(p: TeamPerson): string {
  return `${p.full_name} (${ROLE_LABEL[p.role] || p.role}${p.status === "inactive" ? ", inactive" : ""})`;
}

/** D10: crediting an enrollment to someone who is no longer active needs a deliberate yes. true = go ahead. */
export async function confirmInactiveCredit(person: TeamPerson | null | undefined): Promise<boolean> {
  if (!person || person.status !== "inactive") return true;
  return confirm({
    title: `${person.full_name} is inactive`,
    text: `${person.full_name} has left the team. Credit this enrollment to them anyway? It will count toward their (and their lead's) figures. Choose "No one credited" or an active person instead if they did not bring this student.`,
    confirmLabel: "Credit anyway",
    cancelLabel: "Go back",
    danger: false,
  });
}
