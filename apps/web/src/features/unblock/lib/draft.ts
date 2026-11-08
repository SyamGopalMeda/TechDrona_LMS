/**
 * Local draft autosave for the unblock request form (account-unblock-workflow §3 "Draft",
 * autosaved for 7 days). Kept on this device only, keyed by case reference, and removed as soon
 * as the request is sent or discarded. Never stores the declaration tick (it must be given
 * fresh) and never anything the form does not collect (no secrets: the DLP hint still applies).
 */
export const DRAFT_TTL_MS = 7 * 24 * 3600 * 1000;
const PREFIX = "td.unblock.draft.";

export interface UnblockDraft {
  what_happened: string[];
  explanation: string;
  recognised: string[];
  none_recognised: boolean;
  contact: "in_app" | "email" | "sms";
}

interface Stored extends UnblockDraft {
  saved_at: number;
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function loadDraft(caseRef: string, now: number = Date.now()): (UnblockDraft & { saved_at: number }) | null {
  const s = storage();
  if (!s) return null;
  try {
    const raw = s.getItem(PREFIX + caseRef);
    if (!raw) return null;
    const d = JSON.parse(raw) as Partial<Stored>;
    if (typeof d.saved_at !== "number" || now - d.saved_at > DRAFT_TTL_MS) {
      s.removeItem(PREFIX + caseRef);
      return null;
    }
    return {
      what_happened: Array.isArray(d.what_happened) ? d.what_happened.filter((x): x is string => typeof x === "string") : [],
      explanation: typeof d.explanation === "string" ? d.explanation : "",
      recognised: Array.isArray(d.recognised) ? d.recognised.filter((x): x is string => typeof x === "string") : [],
      none_recognised: d.none_recognised === true,
      contact: d.contact === "email" || d.contact === "sms" ? d.contact : "in_app",
      saved_at: d.saved_at,
    };
  } catch {
    return null;
  }
}

export function isEmptyDraft(d: UnblockDraft): boolean {
  return !d.what_happened.length && !d.explanation.trim() && !d.recognised.length && !d.none_recognised;
}

export function saveDraft(caseRef: string, d: UnblockDraft, now: number = Date.now()): boolean {
  const s = storage();
  if (!s) return false;
  try {
    if (isEmptyDraft(d)) s.removeItem(PREFIX + caseRef);
    else s.setItem(PREFIX + caseRef, JSON.stringify({ ...d, saved_at: now } satisfies Stored));
    return true;
  } catch {
    return false;
  }
}

export function clearDraft(caseRef: string): void {
  try {
    storage()?.removeItem(PREFIX + caseRef);
  } catch {
    /* storage unavailable */
  }
}
