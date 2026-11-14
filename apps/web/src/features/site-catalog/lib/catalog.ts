/**
 * Website course catalogue: fetch, normalise, merge with the live state and group.
 * Pure apart from the injected `fetch`, so it is unit-tested directly (site-catalog.test.tsx).
 * Every failure degrades: no catalog.json -> cards from the live state only; no live state ->
 * the catalogue's own defaults; neither -> an empty catalogue (the UI shows a link to the website).
 */
import type {
  CatalogCourse,
  CoursePublicState,
  CourseRegStatus,
  SiteCatalog,
  SiteCourse,
  SiteCourseFact,
  SiteCourseGroup,
  SiteCourseSection,
  SiteCourseTheme,
} from "./types";
import { publicRegisterHref, registerHref } from "@/features/registration/lib/registration";
import { siteBaseUrl, siteCourseUrl } from "./site-url";

type Env = Record<string, string | undefined>;
export type FetchLike = (url: string, init?: RequestInit & { next?: { revalidate?: number } }) => Promise<Response>;

export const SITE_CATALOG_REVALIDATE_SECONDS = 300;
/** The LMS registration status changes when an admin flips it: keep it fresh. */
export const COURSE_STATUS_REVALIDATE_SECONDS = 30;
export const SITE_CATALOG_TIMEOUT_MS = 4000;

export const SITE_COURSE_GROUPS: { key: SiteCourseGroup; kicker: string; title: string; lead: string; label: string }[] = [
  { key: "open", kicker: "Now enrolling", title: "Open registrations", lead: "Registrations are open. Register and pay here, and we enrol you in the LMS.", label: "Registrations open" },
  { key: "running", kicker: "In progress", title: "Running", lead: "Batches in progress right now. Join the waitlist to hear when the next batch opens.", label: "Batch in progress" },
  { key: "upcoming", kicker: "Coming soon", title: "Upcoming", lead: "Registrations open soon. Explore the syllabus and join the waitlist to hear first.", label: "Coming soon" },
  { key: "completed", kicker: "Past batches", title: "Completed", lead: "Batches that have finished. Join the waitlist for the next edition.", label: "Batch completed" },
];

const GROUP_ORDER: Record<SiteCourseGroup, number> = { open: 0, running: 1, upcoming: 2, completed: 3 };

/* ------------------------------------------------------------------ normalising */

const str = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const strOrNull = (v: unknown): string | null => str(v) || null;
const SAFE_COLOUR = /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%deg]+\))$/i;
const SAFE_SLUG = /^[a-z0-9][a-z0-9-]{0,119}$/;
export const DEFAULT_THEME: SiteCourseTheme = { accent: "#1d3a8a", accentSoft: "#e8eefc", labels: [] };

function normTheme(v: unknown): SiteCourseTheme {
  const t = (v && typeof v === "object" ? v : {}) as Record<string, unknown>;
  const accent = str(t.accent);
  const soft = str(t.accentSoft);
  return {
    accent: SAFE_COLOUR.test(accent) ? accent : DEFAULT_THEME.accent,
    accentSoft: SAFE_COLOUR.test(soft) ? soft : DEFAULT_THEME.accentSoft,
    art: str(t.art) || undefined,
    labels: Array.isArray(t.labels) ? t.labels.map(str).filter(Boolean).slice(0, 4) : [],
  };
}

function normFacts(v: unknown): SiteCourseFact[] {
  if (!Array.isArray(v)) return [];
  return v
    .map((f) => (f && typeof f === "object" ? (f as Record<string, unknown>) : {}))
    .map((f) => ({ icon: str(f.icon) || undefined, label: str(f.label), value: str(f.value), note: str(f.note) || undefined }))
    .filter((f) => f.label && f.value);
}

/** One catalog.json entry, or null when it has no usable slug/title. */
export function normaliseCatalogCourse(v: unknown): CatalogCourse | null {
  if (!v || typeof v !== "object") return null;
  const c = v as Record<string, unknown>;
  const slug = str(c.slug).toLowerCase();
  const title = str(c.title);
  if (!SAFE_SLUG.test(slug) || !title) return null;
  return {
    slug,
    title,
    kicker: str(c.kicker),
    tagline: str(c.tagline),
    edition: str(c.edition),
    icon: str(c.icon),
    family: str(c.family),
    theme: normTheme(c.theme),
    tech: Array.isArray(c.tech) ? c.tech.map(str).filter(Boolean) : [],
    facts: normFacts(c.facts),
    comingSoon: c.comingSoon === true,
    featured: c.featured === true,
    status: str(c.status) || undefined,
    image: /^\/[\w./-]+\.(webp|png|jpe?g|avif)$/i.test(str(c.image)) ? str(c.image) : undefined,
    imageSmall: /^\/[\w./-]+\.(webp|png|jpe?g|avif)$/i.test(str(c.imageSmall)) ? str(c.imageSmall) : undefined,
    scene: /^[a-z0-9-]{2,40}$/.test(str(c.id)) ? str(c.id) : undefined,
  };
}

/** `{ courses: [...] }` from catalog.json -> normalised courses (duplicates by slug dropped). */
export function parseCatalogJson(json: unknown): { courses: CatalogCourse[]; generatedAt: string | null } {
  const root = (json && typeof json === "object" ? json : {}) as Record<string, unknown>;
  if (!Array.isArray(root.courses)) throw new Error("catalog.json has no courses array");
  const seen = new Set<string>();
  const courses: CatalogCourse[] = [];
  for (const raw of root.courses) {
    const c = normaliseCatalogCourse(raw);
    if (c && !seen.has(c.slug)) {
      seen.add(c.slug);
      courses.push(c);
    }
  }
  return { courses, generatedAt: strOrNull(root.generated_at) };
}

/* ------------------------------------------------------------------ Firestore REST */

type FsValue = Record<string, unknown>;

/** A Firestore REST typed value (`{ stringValue: "x" }`, `{ booleanValue: true }`, ...) as plain JS. */
export function firestoreValue(v: unknown): unknown {
  if (!v || typeof v !== "object") return null;
  const f = v as FsValue;
  if ("stringValue" in f) return f.stringValue;
  if ("booleanValue" in f) return f.booleanValue === true;
  if ("integerValue" in f) return Number(f.integerValue);
  if ("doubleValue" in f) return Number(f.doubleValue);
  if ("timestampValue" in f) return f.timestampValue;
  if ("nullValue" in f) return null;
  if ("mapValue" in f) {
    const fields = ((f.mapValue as FsValue | undefined)?.fields ?? {}) as Record<string, unknown>;
    return Object.fromEntries(Object.entries(fields).map(([k, x]) => [k, firestoreValue(x)]));
  }
  if ("arrayValue" in f) {
    const values = ((f.arrayValue as FsValue | undefined)?.values ?? []) as unknown[];
    return values.map(firestoreValue);
  }
  return null;
}

/** `web_course_public` list response -> state per slug. */
export function parseCoursePublic(json: unknown): Record<string, CoursePublicState> {
  const docs = (json && typeof json === "object" ? (json as Record<string, unknown>).documents : undefined) ?? [];
  const out: Record<string, CoursePublicState> = {};
  if (!Array.isArray(docs)) return out;
  for (const d of docs) {
    if (!d || typeof d !== "object") continue;
    const doc = d as Record<string, unknown>;
    const slug = str(doc.name).split("/").pop()?.toLowerCase() ?? "";
    if (!SAFE_SLUG.test(slug)) continue;
    const fields = (doc.fields ?? {}) as Record<string, unknown>;
    const get = (k: string) => firestoreValue(fields[k]);
    out[slug] = {
      title: strOrNull(get("title")),
      status: strOrNull(get("status")),
      registrations_open: get("registrations_open") === true,
      start_date: strOrNull(get("start_date")),
      end_date: strOrNull(get("end_date")),
    };
  }
  return out;
}

/* ------------------------------------------------------------------ LMS registration status */

const REG_STATUSES = new Set<CourseRegStatus>(["open", "coming_soon", "closed"]);

/** Badge text per registration status (LMS admin setting). */
export const REG_STATUS_LABEL: Record<CourseRegStatus, string> = { open: "Registration open", coming_soon: "Coming soon", closed: "Closed" };

/** `GET public/courses/status` (`{data: {slug: status}, updated_at}`) -> status per slug (unknown values dropped). */
export function parseCourseStatus(json: unknown): Record<string, CourseRegStatus> {
  const root = (json && typeof json === "object" ? json : {}) as Record<string, unknown>;
  const data = root.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("course status has no data map");
  const out: Record<string, CourseRegStatus> = {};
  for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
    const slug = k.trim().toLowerCase();
    if (SAFE_SLUG.test(slug) && typeof v === "string" && REG_STATUSES.has(v as CourseRegStatus)) out[slug] = v as CourseRegStatus;
  }
  return out;
}

/** Status without an LMS setting: open group -> open, upcoming -> coming soon, running/completed -> closed. */
export function derivedRegStatus(group: SiteCourseGroup): CourseRegStatus {
  return group === "open" ? "open" : group === "upcoming" ? "coming_soon" : "closed";
}

/* ------------------------------------------------------------------ grouping */

/** Today's date (YYYY-MM-DD) in India time, the zone course dates are planned in. */
export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

/** "2026-12-01" or an ISO timestamp -> YYYY-MM-DD (IST); anything else -> null. */
export function dateKey(v: string | null | undefined): string | null {
  if (!v) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return v;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : todayIST(d);
}

/**
 * Which group a course belongs in, or null to hide it (draft on the website).
 * - Open registrations: the live state says registrations_open (without live state: the catalogue
 *   default, i.e. not `comingSoon` — the website's own fallback).
 * - Completed: status completed, or the end date has passed.
 * - Running: status running (and the start date is not in the future).
 * - Upcoming: everything else (coming_soon, comingSoon, a future start date, no state at all).
 */
export function siteCourseGroup(c: Pick<CatalogCourse, "comingSoon">, live: CoursePublicState | null, today: string): SiteCourseGroup | null {
  if (live?.status === "draft") return null;
  const open = live ? live.registrations_open : !c.comingSoon;
  if (open) return "open";
  const start = dateKey(live?.start_date);
  const end = dateKey(live?.end_date);
  if (live?.status === "completed" || (end && end < today)) return "completed";
  if (live?.status === "running") return start && start > today ? "upcoming" : "running";
  return "upcoming";
}

export const groupMeta = (key: SiteCourseGroup) => SITE_COURSE_GROUPS.find((g) => g.key === key)!;

/** A card for a course the website admin manages but catalog.json does not list (yet). */
function minimalCourse(slug: string, live: CoursePublicState): CatalogCourse {
  return {
    slug,
    title: live.title || slug.replace(/-/g, " ").replace(/^\w/, (m) => m.toUpperCase()),
    kicker: "",
    tagline: "",
    edition: "",
    icon: "",
    family: "",
    theme: DEFAULT_THEME,
    tech: [],
    facts: [],
    comingSoon: live.status === "coming_soon",
    featured: false,
    minimal: true,
  };
}

/** Merge the catalogue with the live state and group it. Courses only in the live state are added. */
export function buildSiteCatalog(input: {
  courses: CatalogCourse[];
  live: Record<string, CoursePublicState>;
  /** LMS registration status per slug (source of truth when it lists the course). */
  status?: Record<string, CourseRegStatus>;
  siteUrl: string;
  generatedAt?: string | null;
  today: string;
  source: SiteCatalog["source"];
}): SiteCatalog {
  const { live, siteUrl, today } = input;
  const all = [...input.courses];
  for (const [slug, state] of Object.entries(live)) if (!all.some((c) => c.slug === slug)) all.push(minimalCourse(slug, state));

  const merged: (SiteCourse & { _i: number })[] = [];
  all.forEach((c, i) => {
    const state = live[c.slug] ?? null;
    const derived = siteCourseGroup(c, state, today);
    if (!derived) return;
    const lms = input.status?.[c.slug];
    // The LMS status decides the group: open -> Open registrations, coming soon -> Upcoming,
    // closed -> Running / Completed by the live state (never Open).
    let group: SiteCourseGroup = derived;
    if (lms === "open") group = "open";
    else if (lms === "coming_soon") group = "upcoming";
    else if (lms === "closed") group = siteCourseGroup(c, state ? { ...state, registrations_open: false } : null, today) === "running" ? "running" : "completed";
    const regStatus = lms ?? derivedRegStatus(group);
    const courseUrl = siteCourseUrl(siteUrl, c.slug);
    merged.push({
      ...c,
      group,
      live: state,
      registrationOpen: regStatus === "open",
      regStatus,
      regStatusSource: lms ? "lms" : "derived",
      statusLabel: lms ? REG_STATUS_LABEL[lms] : group === "open" ? "Registrations open" : groupMeta(group).label,
      startDate: dateKey(state?.start_date),
      endDate: dateKey(state?.end_date),
      courseUrl,
      // Registration happens inside the LMS: signed-in students in the app, visitors on /register.
      registerUrl: registerHref(c.slug),
      publicRegisterUrl: publicRegisterHref(c.slug),
      imageUrl: c.image ? `${siteUrl}${c.image}` : undefined,
      imageSmallUrl: c.imageSmall ? `${siteUrl}${c.imageSmall}` : c.image ? `${siteUrl}${c.image}` : undefined,
      _i: i,
    });
  });

  merged.sort(
    (a, b) =>
      GROUP_ORDER[a.group] - GROUP_ORDER[b.group] ||
      Number(b.featured) - Number(a.featured) ||
      (a.startDate ?? "9999").localeCompare(b.startDate ?? "9999") ||
      a._i - b._i,
  );
  const courses: SiteCourse[] = merged.map(({ _i, ...c }) => c);
  const sections: SiteCourseSection[] = SITE_COURSE_GROUPS.map((g) => ({ key: g.key, courses: courses.filter((c) => c.group === g.key) })).filter(
    (s) => s.courses.length > 0,
  );
  return {
    siteUrl,
    coursesUrl: `${siteUrl}/courses`,
    adminUrl: `${siteUrl}/admin`,
    generatedAt: input.generatedAt ?? null,
    courses,
    sections,
    source: input.source,
  };
}

/** Courses for a compact strip: open first, then running; upcoming only when nothing is live. */
export function stripCourses(catalog: SiteCatalog, limit = 3): SiteCourse[] {
  const live = catalog.courses.filter((c) => c.group === "open" || c.group === "running");
  return (live.length ? live : catalog.courses.filter((c) => c.group === "upcoming")).slice(0, limit);
}

/* ------------------------------------------------------------------ fetching */

async function fetchJson(fetchImpl: FetchLike, url: string, timeoutMs: number, revalidate = SITE_CATALOG_REVALIDATE_SECONDS): Promise<unknown> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetchImpl(url, {
      headers: { accept: "application/json" },
      signal: ctrl.signal,
      next: { revalidate },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // The website is an SPA: a missing catalog.json is served as index.html with 200, so parse
    // the text and let the HTML fail here.
    return JSON.parse(await res.text());
  } finally {
    clearTimeout(timer);
  }
}

export function firestoreCoursePublicUrl(env: Env): string | null {
  const projectId = (env["NEXT_PUBLIC_FIREBASE_PROJECT_ID"] ?? "").trim();
  const apiKey = (env["NEXT_PUBLIC_FIREBASE_API_KEY"] ?? "").trim();
  if (!projectId || !apiKey || projectId.startsWith("demo-")) return null;
  return `https://firestore.googleapis.com/v1/projects/${encodeURIComponent(projectId)}/databases/(default)/documents/web_course_public?pageSize=300&key=${encodeURIComponent(apiKey)}`;
}

/** The api's public course status endpoint (server-side, internal URL), or null when not configured. */
export function courseStatusUrl(env: Env): string | null {
  const base = (env["TD_API_INTERNAL_URL"] ?? env["API_INTERNAL_URL"] ?? "").trim().replace(/\/+$/, "");
  return /^https?:\/\//.test(base) ? `${base}/api/v1/public/courses/status` : null;
}

/** Fetch the sources in parallel and build the catalogue. Never throws. */
export async function fetchSiteCatalog(
  opts: { fetchImpl?: FetchLike; env?: Env; now?: Date; timeoutMs?: number } = {},
): Promise<SiteCatalog> {
  const env = opts.env ?? process.env;
  const fetchImpl: FetchLike = opts.fetchImpl ?? ((url, init) => fetch(url, init));
  const timeoutMs = opts.timeoutMs ?? SITE_CATALOG_TIMEOUT_MS;
  const siteUrl = siteBaseUrl(env);
  const liveUrl = firestoreCoursePublicUrl(env);
  const statusUrl = courseStatusUrl(env);

  const [cat, live, status] = await Promise.all([
    fetchJson(fetchImpl, `${siteUrl}/catalog.json`, timeoutMs)
      .then(parseCatalogJson)
      .catch(() => null),
    liveUrl
      ? fetchJson(fetchImpl, liveUrl, timeoutMs)
          .then(parseCoursePublic)
          .catch(() => null)
      : Promise.resolve(null),
    statusUrl
      ? fetchJson(fetchImpl, statusUrl, timeoutMs, COURSE_STATUS_REVALIDATE_SECONDS)
          .then(parseCourseStatus)
          .catch(() => null)
      : Promise.resolve(null),
  ]);

  return buildSiteCatalog({
    courses: cat?.courses ?? [],
    live: live ?? {},
    status: status ?? undefined,
    siteUrl,
    generatedAt: cat?.generatedAt ?? null,
    today: todayIST(opts.now),
    source: { catalog: cat ? "ok" : "unavailable", live: live ? "ok" : "unavailable", ...(statusUrl ? { status: status ? "ok" : "unavailable" } : {}) },
  });
}
