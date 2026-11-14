import { shortRef } from "@/features/admin/lib/console";

/** True for a raw UUID, which is never shown as-is (audit 1.11). */
export function looksLikeId(v: string | null | undefined): boolean {
  return !!v && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
}

/**
 * A staff/user reference for display: names and emails pass through; raw ids become a short
 * reference ("Staff #9F3C21AB"). The security API returns only ids for reviewers and subjects.
 */
export function staffRef(v: string | null | undefined, kind = "Staff"): string {
  if (!v) return "—";
  if (v === "me") return "You";
  return looksLikeId(v) || v.length > 24 ? `${kind} ${shortRef(v)}` : v;
}
