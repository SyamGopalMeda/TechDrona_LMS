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
import { siteHref } from "@/lib/site/website";

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
  /** Sidebar group heading. Consecutive items with the same section form one (collapsible) group. */
  section?: string;
  /** App toggle (ai module "Authorized apps"); hidden when it is turned off. UX only. */
  appKey?: "assignments" | "assessments" | "question_banks" | "engage" | "paths";
  /**
   * Open with a full document load instead of client-side routing. Needed when the page relies on
   * its own per-document CSP (the CSP of the page a soft navigation started from stays in force).
   */
  documentNav?: boolean;
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
 * Every item belongs to a section so the long list scans as groups (the sidebar collapses the
 * sections that don't hold the current page). One entry per page: the all-types Approvals queue
 * and the all-namespaces Policies page cover the security-filtered views (/security/approvals and
 * /security/policies stay reachable from the security pages that link to them).
 */
export const ADMIN_NAV: NavItem[] = [
  { href: "/admin", label: "Dashboard", screen: "ADM-001", section: "Overview" },
  { href: "/admin/approvals", label: "Approvals", screen: "ADM-010", section: "Overview" },
  { href: "/admin/users", label: "Users", screen: "ADM-004", section: "People" },
  { href: "/admin/roles", label: "Role grants", screen: "ADM-005", section: "People" },
  { href: "/admin/privacy-requests", label: "Privacy requests", screen: "ADM-009", section: "People" },
  // documentNav: the page frames /college-portal/, which only its own CSP (frame-src 'self') allows.
  { href: "/college-portal/index.html", label: "Colleges Data", screen: "ADM-015", section: "Colleges", documentNav: true },
  // Company website back office (enquiries, website content and settings): one click from the LMS admin.
  { href: siteHref("/admin"), label: "Website Admin Panel", screen: "ADM-018", section: "Website", documentNav: true },
  { href: "/admin/courses", label: "Courses", screen: "ADM-016", section: "Learning" },
  { href: "/admin/question-review", label: "Question review", screen: "CMS-007", section: "Learning" },
  { href: "/admin/batches", label: "Batches", screen: "ADM-013", section: "Learning" },
  { href: "/admin/certificates", label: "Certificates & documents", screen: "ADM-017", section: "Learning" },
  { href: "/mentor", label: "Mentor sessions", screen: "MEN-001", section: "Mentoring" },
  { href: "/mentor/students", label: "Mentees", screen: "MEN-004", section: "Mentoring" },
  { href: "/mentor/slots", label: "Mentor availability", screen: "MEN-002", section: "Mentoring" },
  { href: "/mentor/resume-reviews", label: "Résumé reviews", screen: "MEN-005", section: "Mentoring" },
  { href: "/finance", label: "Revenue", screen: "FIN-001", section: "Payments" },
  // Admissions: website course registrations, instalment fees, manual UPI payment verification.
  { href: "/finance/admissions", label: "Admissions", screen: "ADM-019", section: "Payments" },
  { href: "/finance/admissions/verify", label: "Verify payments", screen: "ADM-020", section: "Payments" },
  { href: "/finance/admissions/registrations", label: "Registrations", screen: "ADM-021", section: "Payments" },
  { href: "/finance/admissions/plans", label: "Fee plans", screen: "ADM-022", section: "Payments" },
  { href: "/finance/orders", label: "Orders", screen: "FIN-004", section: "Payments" },
  { href: "/finance/refunds", label: "Refunds", screen: "FIN-005", section: "Payments" },
  { href: "/finance/subscriptions", label: "Subscriptions", screen: "FIN-006", section: "Payments" },
  { href: "/finance/invoices", label: "Invoices", screen: "FIN-007", section: "Payments" },
  { href: "/finance/products", label: "Products & prices", screen: "FIN-002", section: "Payments" },
  { href: "/finance/coupons", label: "Coupons", screen: "FIN-003", section: "Payments" },
  { href: "/finance/reconciliation", label: "Reconciliation", screen: "FIN-009", section: "Payments" },
  { href: "/desk", label: "Ticket queue", screen: "SUP-001", section: "Support" },
  { href: "/desk/unblock-requests", label: "Unblock requests", screen: "SUP-005", section: "Support" },
  { href: "/desk/enquiries", label: "Corporate enquiries", screen: "SUP-006", section: "Support" },
  { href: "/security", label: "Security overview", screen: "SEC-001", section: "Security" },
  { href: "/security/cases", label: "Cases", screen: "SEC-002", section: "Security" },
  { href: "/security/incidents", label: "Incidents", screen: "SEC-001", section: "Security" },
  { href: "/security/restrictions", label: "Restrictions", screen: "SEC-005", section: "Security" },
  { href: "/security/unblock-requests", label: "Unblock reviews", screen: "SEC-004", section: "Security" },
  { href: "/security/rules", label: "Risk rules", screen: "SEC-006", section: "Security" },
  { href: "/security/reports", label: "Reports", screen: "SEC-001", section: "Security" },
  { href: "/admin/audit", label: "Audit log", screen: "ADM-008", section: "Settings" },
  { href: "/admin/policies", label: "Policies", screen: "ADM-006", section: "Settings" },
  { href: "/admin/ai", label: "AI & apps", screen: "ADM-003", section: "Settings" },
  { href: "/admin/feature-flags", label: "Feature flags", screen: "ADM-007", section: "Settings" },
  { href: "/admin/break-glass", label: "Break-glass", screen: "ADM-012", section: "Settings" },
];

export const PORTALS: Record<PortalKey, PortalDef> = {
  student: {
    key: "student",
    prefix: "/app",
    title: "Student",
    roles: ["student"],
    // Sections follow the learner's jobs: Learn / Practice & tests / Placement / Account.
    // "Account status" lives in the header account menu; /app/path is reached from the dashboard.
    nav: [
      { href: "/app", label: "Dashboard", screen: "STU-001" },
      { href: "/app/learning", label: "My learning", screen: "STU-004", section: "Learn" },
      { href: "/app/classes", label: "My classes", screen: "STU-040", section: "Learn" },
      { href: "/app/courses", label: "Explore courses", screen: "STU-033", section: "Learn" },
      { href: "/app/registrations", label: "My registrations", screen: "STU-041", section: "Learn" },
      { href: "/app/path/my", label: "My paths", screen: "PTH-002", section: "Learn", appKey: "paths" },
      { href: "/app/assignments", label: "Assignments", screen: "STU-007", section: "Learn", appKey: "assignments" },
      { href: "/app/engage", label: "Live activities", screen: "STU-030", section: "Learn", appKey: "engage" },
      { href: "/app/certificates", label: "Certificates", screen: "STU-012", section: "Learn" },
      { href: "/app/practice", label: "Practice", screen: "PRC-001", section: "Practice & tests" },
      { href: "/app/tests", label: "Tests", screen: "STU-009", section: "Practice & tests" },
      { href: "/app/coding", label: "Coding", screen: "COD-001", section: "Practice & tests" },
      { href: "/app/progress", label: "Progress", screen: "STU-011", section: "Practice & tests" },
      { href: "/app/diagnostic", label: "Free diagnostic", screen: "STU-010", section: "Practice & tests" },
      { href: "/app/interview-prep", label: "Interview prep", screen: "STU-015", section: "Placement" },
      { href: "/app/mentoring", label: "Mock interviews", screen: "STU-013", section: "Placement" },
      { href: "/app/resume", label: "Résumé builder", screen: "STU-014", section: "Placement" },
      { href: "/app/companies", label: "Company paths", screen: "PRC-005", section: "Placement" },
      { href: "/app/notifications", label: "Notifications", screen: "STU-024", section: "Account" },
      { href: "/app/billing", label: "Billing", screen: "STU-018", section: "Account" },
      { href: "/app/access", label: "My access", screen: "STU-019", section: "Account" },
      { href: "/app/support", label: "Support", screen: "STU-025", section: "Account" },
      { href: "/app/settings/profile", label: "Profile & settings", screen: "STU-020", section: "Account" },
    ],
  },
  trainer: {
    key: "trainer",
    prefix: "/trainer",
    title: "Trainer",
    roles: ["trainer"],
    nav: [
      { href: "/trainer", label: "Dashboard", screen: "TRN-001" },
      { href: "/trainer/courses", label: "Courses", screen: "TRN-003", section: "Teach" },
      { href: "/trainer/paths", label: "Learning paths", screen: "PTH-001", section: "Teach", appKey: "paths" },
      { href: "/trainer/paths/articles", label: "Articles", screen: "PTH-003", section: "Teach", appKey: "paths" },
      { href: "/trainer/engage", label: "Engage", screen: "TRN-020", section: "Teach", appKey: "engage" },
      { href: "/trainer/grading", label: "Grading", screen: "TRN-008", section: "Assess" },
      { href: "/trainer/assignments", label: "Assignments", screen: "TRN-012", section: "Assess", appKey: "assignments" },
      { href: "/trainer/tests", label: "Tests", screen: "TRN-005", section: "Assess" },
      { href: "/trainer/integrity", label: "Integrity flags", screen: "TRN-010", section: "Assess" },
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
      { href: "/studio/review", label: "Review queue", screen: "CMS-007", section: "Review" },
      { href: "/studio/reports/errors", label: "Reported errors", screen: "CMS-013", section: "Review" },
      { href: "/studio/courses", label: "Courses", screen: "CMS-002", section: "Content" },
      { href: "/studio/media", label: "Media", screen: "CMS-012", section: "Content" },
      { href: "/studio/taxonomy", label: "Taxonomy", screen: "CMS-008", section: "Content" },
      { href: "/studio/companies", label: "Companies", screen: "CMS-009", section: "Content" },
      { href: "/studio/questions", label: "All questions", screen: "CMS-004", section: "Questions & tests" },
      { href: "/studio/question-banks", label: "Question banks", screen: "CMS-004", section: "Questions & tests", appKey: "question_banks" },
      { href: "/studio/coding", label: "Coding problems", screen: "CMS-010", section: "Questions & tests" },
      { href: "/studio/tests", label: "Template mocks", screen: "CMS-011", section: "Questions & tests" },
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
