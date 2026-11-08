/**
 * Portal registry: route prefixes and navigation per role (PRD §6 screen inventory).
 * Navigation visibility is a UX convenience only — the api is authoritative for access
 * (every request is authorised server-side; a hidden link is not a control).
 *
 * Portal agents: add nav entries here and create pages under src/app/<prefix>/...
 * Screens that are not built yet (ADM-011 notification templates) are
 * kept out of the navigation until their APIs exist.
 */

import { safeNextPath as hardenedSafeNextPath } from "@/features/auth/lib/validation";

export type PortalKey =
  | "student"
  | "trainer"
  | "evaluator"
  | "mentor"
  | "studio"
  | "support"
  | "finance"
  | "security"
  | "admin";

export interface NavItem {
  href: string;
  label: string;
  /** PRD screen id(s) */
  screen: string;
  /** Sidebar group heading (the Admin portal groups its finance / support / security / mentoring sections). */
  section?: string;
  /** App toggle (ai module "Authorized apps"); hidden when it is turned off. UX only. */
  appKey?: "assignments" | "assessments" | "question_banks" | "engage" | "paths";
}

export interface PortalDef {
  key: PortalKey;
  prefix: string;
  title: string;
  /** role key(s) that normally use this portal (single-company roles: plan §8 D2) */
  roles: string[];
  nav: NavItem[];
  /**
   * Set for the finance / support / security / mentoring sections, which are part of the Admin
   * portal since the single-company conversion (D2): they keep their URLs but share the Admin nav
   * and are not listed separately in the portal switcher.
   */
  parent?: "admin";
}

/**
 * Admin portal navigation (D2: Finance admin, Support agent, Security reviewer and Placement
 * mentor are folded into Admin). Shared by /admin, /finance, /desk, /security and /mentor.
 */
export const ADMIN_NAV: NavItem[] = [
  { href: "/admin", label: "Dashboard", screen: "ADM-001" },
  { href: "/admin/users", label: "Users", screen: "ADM-004" },
  { href: "/admin/batches", label: "Batches", screen: "ADM-013" },
  { href: "/admin/roles", label: "Role grants", screen: "ADM-005" },
  { href: "/admin/policies", label: "Policies", screen: "ADM-006" },
  { href: "/admin/ai", label: "AI & apps", screen: "ADM-003" },
  { href: "/admin/feature-flags", label: "Feature flags", screen: "ADM-007" },
  { href: "/admin/audit", label: "Audit log", screen: "ADM-008" },
  { href: "/admin/privacy-requests", label: "Privacy requests", screen: "ADM-009" },
  { href: "/admin/approvals", label: "Approvals", screen: "ADM-010" },
  { href: "/admin/break-glass", label: "Break-glass", screen: "ADM-012" },
  { href: "/finance", label: "Revenue", screen: "FIN-001", section: "Finance" },
  { href: "/finance/products", label: "Products & prices", screen: "FIN-002", section: "Finance" },
  { href: "/finance/coupons", label: "Coupons", screen: "FIN-003", section: "Finance" },
  { href: "/finance/orders", label: "Orders", screen: "FIN-004", section: "Finance" },
  { href: "/finance/refunds", label: "Refunds", screen: "FIN-005", section: "Finance" },
  { href: "/finance/subscriptions", label: "Subscriptions", screen: "FIN-006", section: "Finance" },
  { href: "/finance/invoices", label: "Invoices", screen: "FIN-007", section: "Finance" },
  { href: "/finance/reconciliation", label: "Reconciliation", screen: "FIN-009", section: "Finance" },
  { href: "/desk", label: "Ticket queue", screen: "SUP-001", section: "Support" },
  { href: "/desk/unblock-requests", label: "Unblock requests", screen: "SUP-005", section: "Support" },
  { href: "/desk/enquiries", label: "Corporate enquiries", screen: "SUP-006", section: "Support" },
  { href: "/security", label: "Security dashboard", screen: "SEC-001", section: "Account security" },
  { href: "/security/cases", label: "Cases", screen: "SEC-002", section: "Account security" },
  { href: "/security/unblock-requests", label: "Unblock reviews", screen: "SEC-004", section: "Account security" },
  { href: "/security/restrictions", label: "Restrictions", screen: "SEC-005", section: "Account security" },
  { href: "/security/incidents", label: "Incidents", screen: "SEC-001", section: "Account security" },
  { href: "/security/rules", label: "Risk rules", screen: "SEC-006", section: "Account security" },
  { href: "/security/reports", label: "Reports (H1–H12)", screen: "SEC-001", section: "Account security" },
  { href: "/security/approvals", label: "Security approvals", screen: "SEC-005", section: "Account security" },
  { href: "/security/policies", label: "Security policy", screen: "ADM-006", section: "Account security" },
  { href: "/mentor", label: "Sessions", screen: "MEN-001", section: "Mentoring" },
  { href: "/mentor/students", label: "Mentees", screen: "MEN-004", section: "Mentoring" },
  { href: "/mentor/slots", label: "Availability", screen: "MEN-002", section: "Mentoring" },
  { href: "/mentor/resume-reviews", label: "Resume reviews", screen: "MEN-005", section: "Mentoring" },
];

export const PORTALS: Record<PortalKey, PortalDef> = {
  student: {
    key: "student",
    prefix: "/app",
    title: "Student",
    roles: ["student"],
    nav: [
      { href: "/app", label: "Dashboard", screen: "STU-001" },
      { href: "/app/learning", label: "My learning", screen: "STU-004" },
      { href: "/app/path", label: "Learning path", screen: "STU-006" },
      { href: "/app/path/my", label: "My paths", screen: "PTH-002", appKey: "paths" },
      { href: "/app/practice", label: "Practice", screen: "PRC-001" },
      { href: "/app/tests", label: "Tests", screen: "STU-009" },
      { href: "/app/coding", label: "Coding", screen: "COD-001" },
      { href: "/app/companies", label: "Company paths", screen: "PRC-005" },
      { href: "/app/progress", label: "Progress", screen: "STU-011" },
      { href: "/app/assignments", label: "Assignments", screen: "STU-007", appKey: "assignments" },
      { href: "/app/engage", label: "Live activities", screen: "STU-030", appKey: "engage" },
      { href: "/app/certificates", label: "Certificates", screen: "STU-012" },
      { href: "/app/mentoring", label: "Mentoring", screen: "STU-013" },
      { href: "/app/notifications", label: "Notifications", screen: "STU-024" },
      { href: "/app/billing", label: "Billing", screen: "STU-018" },
      { href: "/app/access", label: "My access", screen: "STU-019" },
      { href: "/app/support", label: "Support", screen: "STU-025" },
      { href: "/app/account-status", label: "Account status", screen: "STU-026" },
      { href: "/app/settings/profile", label: "Settings", screen: "STU-020" },
    ],
  },
  trainer: {
    key: "trainer",
    prefix: "/trainer",
    title: "Trainer",
    roles: ["trainer"],
    nav: [
      { href: "/trainer", label: "Dashboard", screen: "TRN-001" },
      { href: "/trainer/courses", label: "Courses", screen: "TRN-003" },
      { href: "/trainer/tests", label: "Tests", screen: "TRN-005" },
      { href: "/trainer/assignments", label: "Assignments", screen: "TRN-012", appKey: "assignments" },
      { href: "/trainer/grading", label: "Grading", screen: "TRN-008" },
      { href: "/trainer/integrity", label: "Integrity flags", screen: "TRN-010" },
      { href: "/trainer/engage", label: "Engage", screen: "TRN-020", appKey: "engage" },
      { href: "/trainer/paths", label: "Learning paths", screen: "PTH-001", appKey: "paths" },
      { href: "/trainer/paths/articles", label: "Articles", screen: "PTH-003", appKey: "paths" },
    ],
  },
  evaluator: {
    key: "evaluator",
    prefix: "/evaluator",
    title: "Evaluator",
    roles: ["evaluator"],
    // Reuses the trainer grading screens with authoring hidden (plan §4.2, D3: grade + publish).
    nav: [
      { href: "/evaluator", label: "Grading", screen: "TRN-008" },
      { href: "/evaluator/tests", label: "Tests", screen: "TRN-005" },
      { href: "/evaluator/integrity", label: "Integrity flags", screen: "TRN-010" },
    ],
  },
  mentor: {
    key: "mentor",
    prefix: "/mentor",
    title: "Admin · Mentoring",
    roles: ["super_admin"],
    nav: ADMIN_NAV,
    parent: "admin",
  },
  studio: {
    key: "studio",
    prefix: "/studio",
    title: "Content studio",
    roles: ["content_manager"],
    nav: [
      { href: "/studio", label: "Dashboard", screen: "CMS-001" },
      { href: "/studio/courses", label: "Courses", screen: "CMS-002" },
      { href: "/studio/question-banks", label: "Question banks", screen: "CMS-004", appKey: "question_banks" },
      { href: "/studio/questions", label: "Question bank", screen: "CMS-004" },
      { href: "/studio/review", label: "Review queue", screen: "CMS-007" },
      { href: "/studio/coding", label: "Coding problems", screen: "CMS-010" },
      { href: "/studio/taxonomy", label: "Taxonomy", screen: "CMS-008" },
      { href: "/studio/companies", label: "Companies", screen: "CMS-009" },
      { href: "/studio/tests", label: "Template mocks", screen: "CMS-011" },
      { href: "/studio/media", label: "Media", screen: "CMS-012" },
      { href: "/studio/reports/errors", label: "Reported errors", screen: "CMS-013" },
    ],
  },
  support: {
    key: "support",
    prefix: "/desk",
    title: "Admin · Support",
    roles: ["super_admin"],
    nav: ADMIN_NAV,
    parent: "admin",
  },
  finance: {
    key: "finance",
    prefix: "/finance",
    title: "Admin · Finance",
    roles: ["super_admin"],
    nav: ADMIN_NAV,
    parent: "admin",
  },
  security: {
    key: "security",
    prefix: "/security",
    title: "Admin · Account security",
    roles: ["super_admin"],
    nav: ADMIN_NAV,
    parent: "admin",
  },
  admin: {
    key: "admin",
    prefix: "/admin",
    title: "Admin",
    roles: ["super_admin"],
    nav: ADMIN_NAV,
  },
};

export const PORTAL_PREFIXES: readonly string[] = Object.values(PORTALS).map((p) => p.prefix);

/** True for any path that belongs to an authenticated portal. */
export function isPortalPath(pathname: string): boolean {
  return PORTAL_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

/**
 * Only same-origin relative paths are allowed as post-login redirect targets. Delegates to the
 * hardened guard in features/auth (SEC-04: control characters, whitespace, backslashes, `/api`).
 */
export function safeNextPath(next: string | null | undefined): string | null {
  return hardenedSafeNextPath(next, "") || null;
}

/**
 * Deep link for the sign-in redirect: the path the middleware saw (`x-td-request-path`), when
 * it is a safe same-origin path inside this portal; otherwise the portal root.
 */
export function signInNext(requestPath: string | null, prefix: string): string {
  const path = safeNextPath(requestPath);
  if (path && (path === prefix || path.startsWith(`${prefix}/`) || path.startsWith(`${prefix}?`))) return path;
  return prefix;
}
