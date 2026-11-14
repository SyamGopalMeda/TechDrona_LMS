/**
 * Student-facing copy, verbatim from account-unblock-workflow §1 / §3 and design-system §9.8.
 * `{…}` variables are filled by the components.
 */

export const WHAT_HAPPENED: { code: string; label: string }[] = [
  { code: "all_devices_mine", label: "All devices are mine" },
  { code: "family_member_used", label: "A family member used my account" },
  { code: "shared_with_friend", label: "I shared my login with a friend" },
  { code: "account_may_be_hacked", label: "My account may have been hacked" },
  { code: "shared_computer", label: "I signed in on a shared computer (office, café)" },
  { code: "travelling_or_vpn", label: "I was travelling / using VPN" },
  { code: "other", label: "Other" },
];

export const DECLARATION = "The information I've given is true. I understand one account is for one person.";
export const NO_SECRETS_HINT = "Please don't include passwords or codes.";
export const EXPLANATION_MIN = 30;
export const EXPLANATION_MAX = 2000;

/** Client-side mirror of the server DLP check (unblock §3): 6-digit code next to OTP/code, or "password:". */
export function looksLikeSecret(text: string): boolean {
  const t = text.toLowerCase();
  if (/password\s*[:=]/.test(t)) return true;
  if (/\b(otp|code|pin)\b[^\n]{0,20}\b\d{4,8}\b/.test(t)) return true;
  if (/\b\d{4,8}\b[^\n]{0,20}\b(otp|code|pin)\b/.test(t)) return true;
  if (/\b(?:\d[ -]?){13,19}\b/.test(t)) return true; // card-like
  return false;
}

export type UnblockState = "draft" | "submitted" | "under_review" | "info_requested" | "escalated" | "approved" | "rejected" | "closed";

export const STATE_BADGE: Record<UnblockState, string> = {
  draft: "Draft",
  submitted: "Submitted",
  under_review: "Under review",
  info_requested: "We need more information",
  escalated: "With senior reviewer",
  approved: "Approved",
  rejected: "Not approved",
  closed: "Closed",
};

export const CLOSURE_COPY: Record<string, string> = {
  completed: "Your access is back. Thanks for your patience.",
  rejected_final: "This case is closed.",
  withdrawn: "You withdrew this request.",
  no_response: "We closed this request because we didn't hear back in 7 days. You can open a new one.",
  moot: "The pause ended and you've confirmed your devices, so this request is closed.",
};

export const STEPPER: { key: string; label: string }[] = [
  { key: "submitted", label: "Submitted" },
  { key: "under_review", label: "Under review" },
  { key: "decision", label: "Decision" },
  { key: "closed", label: "Closed" },
];

export function stepIndex(state: string): number {
  switch (state) {
    case "draft":
      return -1;
    case "submitted":
      return 0;
    case "under_review":
    case "info_requested":
    case "escalated":
      return 1;
    case "approved":
    case "rejected":
      return 2;
    case "closed":
      return 3;
    default:
      return 0;
  }
}

export const APL_REF = /^APL-\d{4}-[0-9A-HJKMNP-TV-Z]{6}$/;
export const SEC_REF = /^SEC-\d{4}-[0-9A-Z]{6}$/;
