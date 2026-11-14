/**
 * Helpers shared by the Data quality, Audit log and Settings screens (old js/views/admin.js top section).
 */
import { safeUrl } from "../../forms";

export { safeUrl };

/** Field names → plain labels (audit log "Changed", diffs, verification queue). Owner-reviewed wording. */
export const FIELD_LABEL: Record<string, string> = {
  lat: "Map location", lng: "Map location", website: "Website", phone: "Phone", email: "Email", naac: "NAAC grade", nirf: "NIRF rank",
  address: "Address", city_id: "Town", intake_per_year: "Seats / year", tier: "Tier", ownership: "Ownership", affiliation: "Affiliation",
  op_status: "Operating status", branches: "Branch list", exams: "Exam dates", name: "Name", district_id: "District", short_name: "Short name",
  full_name: "Name", reports_to: "Reports to", college_id: "College", role: "Role", status: "Status", joined_on: "Joined on", notes: "Notes",
  op_status_note: "Status evidence", op_status_source: "Status source", due_date: "Due date", owner_name: "Assigned to", owner_person_id: "Assigned to (team member)",
  scope_type: "About (type)", scope_id: "About", target: "Target", target_min: "Minimum", target_max: "Maximum", period: "Period", period_start: "Period starts",
  stage: "Stage", enrolled_on: "Enrolled on", confirmed_on: "Confirmed on", student_name: "Student", student_contact: "Student contact",
  basis: "Verification", source_url: "Source link", verified_fields: "Verified fields", verified_by: "Verified by", verified_on: "Verified on",
  title: "Title", issue: "Reason", last_contact: "Last spoke to them", done_at: "Done on", program_target: "Programme target", program_deadline: "Programme deadline",
  program_start: "Programme start", target_district_groups: "Target districts", deadline: "Deadline", course_id: "Course", person_id: "Person",
  branch_id: "Branch", price_inr: "Price (₹)", active: "Offered", outcome: "What happened", called_at: "Called on", caller: "Called by", next_action_at: "Call back on",
  contact_id: "Contact", semester: "Semester", endsem_start: "End-sem starts", endsem_end: "End-sem ends", evidence: "Evidence", confidence: "Confidence",
  aliases: "Other names", targeted: "Targeted", designation: "Designation", responsibility: "Responsibility", relevance_factors: "Branch relevance",
  min_conversion: "Low-conversion alert", org_name: "Organisation name", state_target_deadline: "Fallback deadline",
  // calling system and other fields that showed up as raw names in the audit log
  followup_id: "Call-back", confirms_participation: "College agreed to take part", participation_confirmed_on: "College agreed on",
  participation_note: "Agreement note", status_source: "Number status set by", unreachable_after_attempts: 'Unanswered calls before "Not working"',
  op_2025_26: "Admitted students 2025-26", op_2026_27: "Admitted students 2026-27", contact_source: "Contact details source", is_demo: "Demo record",
  students_reached: "Students reached", on_date: "Date", type: "Type", amount_inr: "Amount paid (₹)", interested_on: "Interested on",
  registered_on: "Registered on", applied_on: "Applied on", dropped_on: "Dropped on", research_id: "Research reference", sno: "Serial no.",
  is_relevant: "Target branch", category: "Category", intake_basis: "Seats basis", intake_source: "Seats source", intake_year: "Seats year",
  strength_total: "Total students", final_year: "Final-year students",
};

/** Plain label of a field name ("some_field" → "Some field" when unknown). */
export const fieldLabel = (k: string): string => FIELD_LABEL[k] ?? String(k).replace(/_/g, " ").replace(/^\w/, (m) => m.toUpperCase());

/** Hostname of a URL without "www.". */
export const hostOf = (u: string): string => {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
};

/** A safe external link (http/https only); "source noted" text for anything else; nothing when empty. */
export function SrcLink({ src, label = "Open source" }: { src: string | null | undefined; label?: string | null }) {
  const href = safeUrl(src);
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" title={href}>
        {label === null ? hostOf(href) : label}
      </a>
    );
  }
  return src ? (
    <span className="adm-muted" title={String(src)}>
      source noted
    </span>
  ) : null;
}

/** Developer extras (raw JSON) only with ?dev=1 — the old shell kept that switch in sessionStorage 'td.dev'. */
export function devMode(): boolean {
  try {
    if (/[?&]dev=1\b/.test(window.location.search) || /[?&]dev=1\b/.test(window.location.hash)) {
      try {
        sessionStorage.setItem("td.dev", "1");
      } catch {
        /* ignore */
      }
      return true;
    }
    return sessionStorage.getItem("td.dev") === "1";
  } catch {
    return false;
  }
}

/** Run fn over items, n at a time; failures become null. */
export async function pool<T, R>(items: readonly T[], n: number, fn: (x: T) => Promise<R>): Promise<(R | null)[]> {
  const out: (R | null)[] = new Array(items.length).fill(null);
  let i = 0;
  await Promise.all(
    Array.from({ length: Math.min(n, items.length) }, async () => {
      while (i < items.length) {
        const k = i++;
        try {
          out[k] = await fn(items[k]!);
        } catch {
          out[k] = null;
        }
      }
    }),
  );
  return out;
}

/** Save a text file (JSON backup). */
export function downloadText(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
