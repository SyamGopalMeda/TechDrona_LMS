import type { InboxItem } from "./types";

/**
 * Human copy for in-app notification templates. The api stores only `template_key` + `data`
 * (no rendered text), so the inbox renders from this table. Titles mirror the email subjects
 * the backend sends for the same events (security/engine.py, unblock.py, cases.py, …).
 */
export interface RenderedNotification {
  title: string;
  body?: string;
  href?: string;
  linkLabel?: string;
}

const str = (v: unknown): string | undefined => (typeof v === "string" && v.trim() ? v : undefined);

/**
 * Only same-origin app paths are followed (never `//host`, `/api/…` or absolute URLs): links in
 * notification data come from the server, but a link is a navigation target, not an API call.
 */
export function safeAppPath(v: unknown): string | undefined {
  const s = str(v);
  if (!s || !s.startsWith("/") || s.startsWith("//") || s.startsWith("/\\") || s.startsWith("/api/")) return undefined;
  if (/[\u0000-\u001F\u007F\s\\]/.test(s)) return undefined;
  return s;
}

const enc = encodeURIComponent;

const STATUS = { href: "/app/account-status", linkLabel: "See account status" };
const SECURITY = { href: "/app/settings/security", linkLabel: "Security settings" };

function notMe(data: Record<string, unknown>) {
  const ref = str(data.event_ref);
  return ref ? { href: `/app/settings/security/not-me/${enc(ref)}`, linkLabel: "This wasn't me" } : SECURITY;
}

function unblockLink(data: Record<string, unknown>) {
  const ref = str(data.reference);
  return ref ? { href: `/unblock-request?reference=${enc(ref)}#status`, linkLabel: "View request" } : STATUS;
}

const TEMPLATES: Record<string, (data: Record<string, unknown>) => RenderedNotification> = {
  "batch.announcement": (d) => ({ title: str(d.title) ?? "Announcement from your batch", body: str(d.body) }),
  "assessment.attempt_invalidated": (d) => ({
    title: "A test attempt was invalidated",
    body: "You can ask for a review of this decision.",
    href: safeAppPath(d.appeal_url),
    linkLabel: "Appeal",
  }),
  "placement.question_report_resolved": (d) => ({
    title: "Your question report was reviewed",
    body: str(d.note) ?? (str(d.resolution) ? `Outcome: ${String(d.resolution).replace(/_/g, " ")}` : undefined),
  }),
  "session.revoked": () => ({ title: "One of your sessions was signed out", href: "/app/settings/devices", linkLabel: "Devices & sessions" }),
  "security.password_changed": () => ({ title: "Your password was changed", body: "If this wasn't you, contact support immediately.", ...SECURITY }),
  "security.mfa_added": () => ({ title: "Two-step verification added", body: "An authenticator app was added to your account.", ...SECURITY }),
  "security.l1_notice": () => ({ title: "New activity on your account", ...STATUS }),
  "security.l2_verify": () => ({ title: "Confirm it's you", ...STATUS }),
  "security.l3_restricted": () => ({ title: "Learning access paused", ...STATUS }),
  "security.l3_expired": () => ({ title: "You can restore your learning access", ...STATUS }),
  "security.takeover_protect": (d) => ({ title: "We've secured your account", ...notMe(d) }),
  "security.step_up": (d) => ({ title: "Was this you?", ...notMe(d) }),
  "security.session_replay": (d) => ({ title: "We signed out a session that looked unusual", ...notMe(d) }),
  "security.review_approved": () => ({ title: "Your review was approved — finish these steps to get back in", ...STATUS }),
  "security.review_rejected": () => ({ title: "Decision on your review request", ...STATUS }),
  "security.bulk_false_positive": () => ({ title: "We made a mistake — your access is back", ...STATUS }),
  "security.access_restored": () => ({ title: "Access restored", ...STATUS }),
  "security.unblock_received": (d) => ({ title: `We've received your request${str(d.reference) ? ` ${String(d.reference)}` : ""}`, ...unblockLink(d) }),
  "security.unblock_under_review": (d) => ({ title: "A reviewer is looking at your case", ...unblockLink(d) }),
  "security.unblock_info_requested": (d) => ({ title: "We need a little more information", ...unblockLink(d) }),
};

const CATEGORY_FALLBACK: Record<string, string> = {
  security: "Account security update",
  learning: "Learning update",
  billing: "Billing update",
};

export function renderNotification(n: Pick<InboxItem, "template_key" | "category" | "data">): RenderedNotification {
  const data = n.data && typeof n.data === "object" ? n.data : {};
  const t = TEMPLATES[n.template_key];
  if (t) return t(data);
  return { title: CATEGORY_FALLBACK[n.category] ?? "Notification", body: str(data.title) };
}
