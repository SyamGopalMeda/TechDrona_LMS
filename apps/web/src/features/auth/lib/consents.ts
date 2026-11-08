/**
 * Consent purposes (privacy-and-data-retention §3.2). The notice version is the one the
 * signup form displays; ME-05 returns the current one for signed-in users.
 * verified: there is no public endpoint that returns the notice version before signup, so it is
 * configured (NEXT_PUBLIC_NOTICE_VERSION); the default matches NOTICE_VERSION_DEFAULT in
 * app/modules/identity/router.py.
 */
export const NOTICE_VERSION = process.env.NEXT_PUBLIC_NOTICE_VERSION ?? "2026-11-01";

export type Purpose =
  | "terms"
  | "privacy_notice"
  | "core_service"
  | "security_monitoring"
  | "analytics_personalisation"
  | "device_fingerprint"
  | "marketing_email"
  | "marketing_sms"
  | "analytics_product";

export const REQUIRED_PURPOSES: Purpose[] = ["terms", "privacy_notice", "core_service"];

/** Optional items offered at signup to adults only (none pre-ticked). */
export const SIGNUP_OPTIONAL: { purpose: Purpose; label: string; description: string }[] = [
  {
    purpose: "security_monitoring",
    label: "Account protection and single-user licence checks",
    description: "Detect account sharing using device, session-overlap and network signals. It may lead to verification or a temporary restriction, always reviewed by a person before any suspension. Needed later for paid plans.",
  },
  {
    purpose: "analytics_personalisation",
    label: "Personalised recommendations and readiness scores",
    description: "Use my learning activity to suggest what to practise next.",
  },
  {
    purpose: "marketing_email",
    label: "Product news and offers by email",
    description: "You can stop these at any time.",
  },
];

/** Purposes never available to under-18 accounts (AUTH-01, ME-06). */
export const ADULT_ONLY: Purpose[] = ["security_monitoring", "analytics_personalisation", "device_fingerprint", "marketing_email", "marketing_sms", "analytics_product"];

export const PURPOSE_LABELS: Record<string, { label: string; description: string; required?: boolean }> = {
  core_service: { label: "Account and learning service", description: "Your account, courses, tests and basic progress. Required to use Tech Drona; withdrawing it means closing your account.", required: true },
  security_monitoring: {
    label: "Account protection and single-user licence checks",
    description: "Sharing detection using device, session-overlap and network signals. If you withdraw, device and session limits still apply, and paid plans may need it.",
  },
  analytics_personalisation: { label: "Personalised recommendations and readiness scores", description: "Withdrawing stops personalisation; derived profiles are deleted within 30 days." },
  device_fingerprint: { label: "Device fingerprint for account protection", description: "Withdrawing deletes the fingerprint within 24 hours." },
  marketing_email: { label: "Product news and offers by email", description: "Stops within 24 hours." },
  marketing_sms: { label: "Product news and offers by SMS / WhatsApp", description: "Stops within 24 hours." },
  analytics_product: { label: "Product analytics", description: "Route and feature usage to improve the product." },
};
