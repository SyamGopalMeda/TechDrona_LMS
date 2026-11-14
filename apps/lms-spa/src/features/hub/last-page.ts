import { safeNextPath } from "@/features/auth/lib/validation";
import { PORTALS } from "@/lib/nav/portals";
import { homePortal, isSharedAccountPath } from "@/features/staff-portal/access";

/**
 * "Last page" memory (per browser): the last portal page the user had open, so that coming back
 * from the company website (or the module hub) resumes where they left off instead of always
 * landing on a dashboard. Navigation convenience only: nothing secret is stored (a same-origin
 * path and a timestamp), every page still checks the session and the api authorises every request.
 * Cleared on sign-out (SignOutButton → clearLocal).
 */
export interface LastPage {
  /** pathname + search, same-origin */
  path: string;
  /** epoch ms */
  at: number;
}

export type ContinueArea = "lms" | "colleges";

export const LAST_PAGE_KEY = "td.last_page";
/** Older records are ignored (a stale page from weeks ago is no longer "where I was"). */
export const LAST_PAGE_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

/** Signed-in areas worth resuming: every portal (incl. the Admin sections) and the reader. */
const TRACKED_PREFIXES: readonly string[] = [...Object.values(PORTALS).map((p) => p.prefix), "/read"];
const COLLEGES_PREFIXES: readonly string[] = ["/admin/college-data", "/college-portal"];

function under(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function pathnameOf(path: string): string {
  const i = path.search(/[?#]/);
  return i === -1 ? path : path.slice(0, i);
}

/** True for paths that are recorded (portal pages); never /login*, /modules, /sso*, /continue or public pages. */
export function isTrackablePath(path: string): boolean {
  const pathname = pathnameOf(path);
  return TRACKED_PREFIXES.some((p) => under(pathname, p));
}

/** Which module a portal path belongs to. */
export function areaOf(path: string): ContinueArea {
  const pathname = pathnameOf(path);
  return COLLEGES_PREFIXES.some((p) => under(pathname, p)) ? "colleges" : "lms";
}

/**
 * Whether a user whose RBAC grants open `portals` (GET /me/grants → `portals`) can open `path`.
 * Guards against resuming another account's page on a shared browser whose session expired
 * without a sign-out. The Admin sections (finance, desk, security, mentor) belong to /admin.
 */
export function allowedFor(path: string, portals: readonly string[]): boolean {
  const pathname = pathnameOf(path);
  // SPA override (role/portal navigation fix): a student page is resumed only for an account that
  // opens the Student portal; the shared account pages (settings, account status) open for all.
  if (under(pathname, "/read") || isSharedAccountPath(pathname)) return true;
  if (under(pathname, "/app")) return portals.includes("/app");
  const def = Object.values(PORTALS).find((p) => under(pathname, p.prefix));
  if (!def) return false;
  if (portals.includes(def.prefix)) return true;
  return def.parent === "admin" && portals.includes("/admin");
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function recordLastPage(path: string, now: number = Date.now()): void {
  if (!isTrackablePath(path)) return;
  const safe = safeNextPath(path, "");
  if (!safe) return;
  try {
    storage()?.setItem(LAST_PAGE_KEY, JSON.stringify({ path: safe, at: now } satisfies LastPage));
  } catch {
    /* private mode / quota: resuming is a convenience */
  }
}

export function readLastPage(): LastPage | null {
  try {
    const raw = storage()?.getItem(LAST_PAGE_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<LastPage> | null;
    if (!v || typeof v.path !== "string" || typeof v.at !== "number") return null;
    return { path: v.path, at: v.at };
  } catch {
    return null;
  }
}

export function clearLastPage(): void {
  try {
    storage()?.removeItem(LAST_PAGE_KEY);
  } catch {
    /* best effort */
  }
}

/**
 * Where /continue should go: the remembered page when it is safe, recent, in the requested area
 * and open to this user; otherwise `fallback`.
 */
export function pickContinueTarget(opts: {
  record: LastPage | null;
  area?: ContinueArea;
  /** RBAC portal prefixes; null = unknown (then the remembered page is not used). */
  portals: readonly string[] | null;
  fallback: string;
  now?: number;
}): string {
  const { record, area, portals, now = Date.now() } = opts;
  // A portal fallback this account cannot open (e.g. `fallback=/admin` for a student) becomes
  // their own home portal, so nobody is sent to a portal they would only be bounced out of.
  const fallback = portals && isTrackablePath(opts.fallback) && !allowedFor(opts.fallback, portals) ? (homePortal(portals) ?? "/modules") : opts.fallback;
  if (!record || !portals) return fallback;
  if (now - record.at > LAST_PAGE_MAX_AGE_MS || record.at > now + 60_000) return fallback;
  const path = safeNextPath(record.path, "");
  if (!path || !isTrackablePath(path)) return fallback;
  if (area && areaOf(path) !== area) return fallback;
  if (!allowedFor(path, portals)) return fallback;
  return path;
}

/** Fallback for /continue when nothing is remembered: the module's normal landing page or the hub. */
export function continueFallback(area: ContinueArea | undefined, requested: string | null | undefined): string {
  const safe = safeNextPath(requested, "");
  if (safe && (isTrackablePath(safe) || pathnameOf(safe) === "/modules")) return safe;
  return area === "colleges" ? "/college-portal/index.html" : "/modules";
}

/** Build a /continue link. */
export function continueHref(area?: ContinueArea, fallback?: string): string {
  const qs = new URLSearchParams();
  if (area) qs.set("area", area);
  if (fallback) qs.set("fallback", fallback);
  const s = qs.toString();
  return `/continue${s ? `?${s}` : ""}`;
}

/** Pages that rely on their own per-document CSP must be opened with a full page load. */
export function needsDocumentLoad(path: string): boolean {
  return under(pathnameOf(path), "/admin/college-data") || under(pathnameOf(path), "/college-portal");
}
