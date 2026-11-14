/**
 * Portal routes, navigation and the old-hash-route → new-path map.
 *
 * Rule: the old portal's canonical hash route `#/<x>` is now the path `/colleges/<x>` (`#/` → `/colleges`).
 * Query strings are unchanged (filters, `?tab=`, `?d=` scope). Old alias paths (`#/team`, `#/reports`…) still
 * work through the `[...rest]` catch-all page, which redirects with `resolveAlias()`.
 *
 * Build links with `portalPath` (never by hand) so a later move of the base path is one change.
 */
import { matchPath } from "react-router";

export const PORTAL_BASE = "/colleges";

const enc = encodeURIComponent;

/** Paths of every portal screen. */
export const portalPath = {
  home: PORTAL_BASE,
  colleges: `${PORTAL_BASE}/colleges`,
  college: (id: string) => `${PORTAL_BASE}/college/${enc(id)}`,
  district: (district: string) => `${PORTAL_BASE}/d/${enc(district)}`,
  city: (district: string, city: string) => `${PORTAL_BASE}/d/${enc(district)}/${enc(city)}`,
  people: `${PORTAL_BASE}/people`,
  person: (id: string | number) => `${PORTAL_BASE}/person/${enc(String(id))}`,
  targets: `${PORTAL_BASE}/targets`,
  plan: `${PORTAL_BASE}/plan`,
  calls: `${PORTAL_BASE}/calls`,
  followups: `${PORTAL_BASE}/followups`,
  analytics: `${PORTAL_BASE}/analytics`,
  exams: `${PORTAL_BASE}/exams`,
  notices: `${PORTAL_BASE}/notices`,
  live: `${PORTAL_BASE}/live`,
  data: `${PORTAL_BASE}/data`,
  audit: `${PORTAL_BASE}/audit`,
  settings: `${PORTAL_BASE}/settings`,
} as const;

/** Icon names of ui/Icon.tsx used by the navigation. */
export type NavIcon = "home" | "college" | "people" | "target" | "phone" | "analytics" | "exam" | "list" | "refresh" | "data" | "audit" | "settings";

export interface NavItem {
  id: string;
  /** sidebar / More sheet label (owner-reviewed wording, app.js NAV as of 2026-11-14) */
  label: string;
  /** phone tab bar label */
  short?: string;
  icon: NavIcon;
  href: string;
  /** tooltip (also the collapsed sidebar's title) */
  tip?: string;
  /** under the sidebar's "More" heading */
  more?: boolean;
}

export const NAV: readonly NavItem[] = [
  { id: "home", label: "Home", short: "Home", icon: "home", href: portalPath.home },
  { id: "colleges", label: "Colleges", short: "Colleges", icon: "college", href: portalPath.colleges },
  { id: "people", label: "Team", short: "Team", icon: "people", href: portalPath.people, tip: "Team: college leads and ambassadors" },
  {
    id: "targets",
    label: "Targets & performance",
    short: "Targets",
    icon: "target",
    href: portalPath.targets,
    tip: "Targets & performance: paid enrollments against targets, by person, college or district",
  },
  { id: "calls", label: "Calls & follow-ups", short: "Calls", icon: "phone", href: portalPath.calls },
  { id: "analytics", label: "Reports", short: "Reports", icon: "analytics", href: portalPath.analytics, tip: "Reports: trend, pace, rankings and courses" },
  { id: "exams", label: "Exams", icon: "exam", href: portalPath.exams, more: true },
  { id: "notices", label: "Official notices", icon: "list", href: portalPath.notices, more: true },
  { id: "live", label: "Official sources", icon: "refresh", href: portalPath.live, more: true, tip: "Official sources: EAPCET / ECET / JNTUK lists checked automatically" },
  { id: "data", label: "Data quality", icon: "data", href: portalPath.data, more: true },
  { id: "audit", label: "Audit log", icon: "audit", href: portalPath.audit, more: true },
  { id: "settings", label: "Settings", icon: "settings", href: portalPath.settings, more: true },
];
export const PRIMARY = NAV.filter((n) => !n.more);
export const SECONDARY = NAV.filter((n) => n.more);
/** Phone tab bar: the first TAB_COUNT primary items + "More". */
export const TAB_COUNT = 4;

export interface SectionTab {
  label: string;
  href: string;
  /** active test (pathname + query); default: the href's path equals the pathname */
  is?: (pathname: string, q: URLSearchParams) => boolean;
}

/** Route-level sub-sections the shell draws above the page (one consistent tab strip). */
export const SECTIONS: Record<"targets" | "calls", SectionTab[]> = {
  targets: [
    {
      label: "Performance",
      href: portalPath.targets,
      is: (p, q) => p === portalPath.targets && !(q.get("tab") === "places" || (!!q.get("scope") && q.get("tab") !== "perf")),
    },
    {
      label: "Targets by place",
      href: `${portalPath.targets}?tab=places`,
      is: (p, q) => p === portalPath.targets && (q.get("tab") === "places" || (!!q.get("scope") && q.get("tab") !== "perf")),
    },
    { label: "Planner", href: portalPath.plan },
  ],
  calls: [
    { label: "Call queue", href: portalPath.calls },
    { label: "Follow-ups", href: portalPath.followups },
  ],
};

export interface PortalRoute {
  /** react-router pattern under the base */
  pattern: string;
  /** old hash route (for the porting guide and legacy links) */
  legacy: string;
  /** old view module + export that rendered it (js/views/<file>.js) */
  oldView: string;
  /** nav item to highlight */
  nav: string;
  title: string;
  section?: keyof typeof SECTIONS;
}

/** Every screen, in the old router's order (app.js ROUTES). */
export const ROUTES: readonly PortalRoute[] = [
  { pattern: portalPath.home, legacy: "#/", oldView: "dashboard.js renderState", nav: "home", title: "Home" },
  { pattern: `${PORTAL_BASE}/d/:district`, legacy: "#/d/:district", oldView: "geo.js renderDistrict", nav: "colleges", title: "District" },
  { pattern: `${PORTAL_BASE}/d/:district/:city`, legacy: "#/d/:district/:city", oldView: "geo.js renderCity", nav: "colleges", title: "Town" },
  { pattern: `${PORTAL_BASE}/college/:id`, legacy: "#/college/:id", oldView: "college.js render (+ college-form.js, branch.js, forms.js)", nav: "colleges", title: "College" },
  { pattern: portalPath.colleges, legacy: "#/colleges", oldView: "dashboard.js renderCollegeList", nav: "colleges", title: "Colleges" },
  { pattern: portalPath.calls, legacy: "#/calls", oldView: "calls.js render", nav: "calls", section: "calls", title: "Calls & follow-ups" },
  { pattern: portalPath.followups, legacy: "#/followups", oldView: "followups.js render", nav: "calls", section: "calls", title: "Follow-ups" },
  { pattern: portalPath.analytics, legacy: "#/analytics", oldView: "dashboard.js renderAnalytics", nav: "analytics", title: "Reports" },
  { pattern: portalPath.people, legacy: "#/people", oldView: "people.js renderList", nav: "people", title: "Team" },
  { pattern: `${PORTAL_BASE}/person/:id`, legacy: "#/person/:id", oldView: "people.js renderPerson", nav: "people", title: "Person" },
  { pattern: portalPath.exams, legacy: "#/exams", oldView: "exams.js render", nav: "exams", title: "Exams" },
  { pattern: portalPath.targets, legacy: "#/targets", oldView: "targets.js render", nav: "targets", section: "targets", title: "Targets & performance" },
  { pattern: portalPath.plan, legacy: "#/plan", oldView: "plan.js render (+ plan/model.js)", nav: "targets", section: "targets", title: "Target planner" },
  { pattern: portalPath.live, legacy: "#/live", oldView: "live.js renderSources", nav: "live", title: "Official sources" },
  { pattern: portalPath.notices, legacy: "#/notices", oldView: "live.js renderNotices", nav: "notices", title: "Official notices" },
  { pattern: portalPath.data, legacy: "#/data", oldView: "admin.js renderData", nav: "data", title: "Data quality" },
  { pattern: portalPath.audit, legacy: "#/audit", oldView: "admin.js renderAudit", nav: "audit", title: "Audit log" },
  { pattern: portalPath.settings, legacy: "#/settings", oldView: "admin.js renderSettings", nav: "settings", title: "Settings" },
];

/** Friendly / legacy paths (old app.js ALIASES, relative to the base) → canonical. */
export const ALIASES: Readonly<Record<string, string>> = {
  "/home": "/",
  "/overview": "/",
  "/map": "/",
  "/team": "/people",
  "/people/list": "/people",
  "/reports": "/analytics",
  "/planner": "/plan",
  "/targets/plan": "/plan",
  "/performance": "/targets",
  "/calling": "/calls",
  "/follow-ups": "/followups",
  "/calls/followups": "/followups",
  "/sources": "/live",
  "/official": "/live",
  "/announcements": "/notices",
  "/quality": "/data",
  "/data-quality": "/data",
  "/verification": "/data",
  "/log": "/audit",
};

export interface RouteMatch {
  route: PortalRoute;
  params: Record<string, string>;
}

/** The portal route for a pathname (null = not a portal screen). */
export function matchPortalRoute(pathname: string): RouteMatch | null {
  const p = pathname.replace(/\/+$/, "") || "/";
  for (const route of ROUTES) {
    const m = matchPath({ path: route.pattern, end: true }, p);
    if (m) {
      const params: Record<string, string> = {};
      for (const [k, v] of Object.entries(m.params)) if (typeof v === "string") params[k] = v;
      return { route, params };
    }
  }
  return null;
}

/** `/colleges/team` → `/colleges/people` (null when `pathname` is not an alias). */
export function resolveAlias(pathname: string): string | null {
  if (!pathname.startsWith(PORTAL_BASE)) return null;
  const rest = pathname.slice(PORTAL_BASE.length).replace(/\/+$/, "") || "/";
  const to = ALIASES[rest];
  if (to === undefined) return null;
  return to === "/" ? PORTAL_BASE : `${PORTAL_BASE}${to}`;
}

/**
 * Map an old portal link to the new path: '#/college/c9?x=1' → '/colleges/college/c9?x=1', '#/' → '/colleges'.
 * The API still returns old-style hrefs (search hits, attention items, performance rows); pass them through this.
 * Anything else (already a path, an external URL) is returned unchanged.
 */
export function toPortalHref(href: string | null | undefined): string {
  if (!href) return PORTAL_BASE;
  if (!href.startsWith("#")) return href;
  let h = href.replace(/^#/, "") || "/";
  if (!h.startsWith("/")) h = `/${h}`;
  const i = h.indexOf("?");
  let path = (i < 0 ? h : h.slice(0, i)).replace(/\/+$/, "") || "/";
  const qs = i < 0 ? "" : h.slice(i);
  path = ALIASES[path] ?? path;
  return `${path === "/" ? PORTAL_BASE : `${PORTAL_BASE}${path}`}${qs}`;
}

/** Link of a search hit (API `href` when present, else built from type + id). */
export function searchHitHref(hit: { type: string; id: string; href?: string | null }): string {
  if (hit.href) return toPortalHref(hit.href);
  if (hit.type === "district") return portalPath.district(hit.id);
  if (hit.type === "college") return portalPath.college(hit.id);
  if (hit.type === "person") return portalPath.person(hit.id);
  return portalPath.home;
}
