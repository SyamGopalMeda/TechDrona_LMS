/**
 * The Tech Drona website course catalogue as seen from the LMS.
 *
 * Source of truth: the website. Its build writes `/catalog.json` (tech drona/scripts/
 * build-catalog-json.mjs: slug, title, kicker, tagline, theme, tech, facts, comingSoon, featured)
 * and the website admin keeps the live state of each course in the public Firestore collection
 * `web_course_public/{slug}` (status, registrations_open, start_date, end_date).
 */

/** The four groups the LMS shows, in display order (website admin: running / coming soon / completed). */
export type SiteCourseGroup = "open" | "running" | "upcoming" | "completed";

export interface SiteCourseTheme {
  accent: string;
  accentSoft: string;
  art?: string;
  labels?: string[];
}

export interface SiteCourseFact {
  icon?: string;
  label: string;
  value: string;
  note?: string;
}

/** One course from catalog.json, normalised (missing arrays become empty, unsafe colours dropped). */
export interface CatalogCourse {
  slug: string;
  title: string;
  kicker: string;
  tagline: string;
  edition: string;
  icon: string;
  family: string;
  theme: SiteCourseTheme;
  tech: string[];
  facts: SiteCourseFact[];
  comingSoon: boolean;
  featured: boolean;
  /** Poster path on the website ("/media/x.webp"), featured programs only. */
  image?: string;
  /** Smaller poster (480w) for cards. */
  imageSmall?: string;
  /** Website course id, used to pick the animated course artwork (CourseScene). */
  scene?: string;
  /** Marketing status text of featured programs ("Registrations open"). */
  status?: string;
  /** Built only from the live state (catalog.json missing or not listing the course yet). */
  minimal?: boolean;
}

export type CoursePublicStatus = "draft" | "coming_soon" | "running" | "completed";

/** `web_course_public/{slug}` (public read). Dates are YYYY-MM-DD or ISO strings. */
export interface CoursePublicState {
  title: string | null;
  status: CoursePublicStatus | string | null;
  registrations_open: boolean;
  start_date: string | null;
  end_date: string | null;
}

/** LMS course registration status (admin: Open for registration / Coming soon / Closed). */
export type CourseRegStatus = "open" | "coming_soon" | "closed";

/** Who is looking at a card: signed-in students register in the app, visitors on /register. */
export type SiteAudience = "student" | "public";

export interface SiteCourse extends CatalogCourse {
  group: SiteCourseGroup;
  live: CoursePublicState | null;
  /** True only when `regStatus` is "open". */
  registrationOpen: boolean;
  /** From the LMS (`GET public/courses/status`) when it lists the course, else derived from the live state. */
  regStatus: CourseRegStatus;
  /** Where `regStatus` came from. */
  regStatusSource: "lms" | "derived";
  /** Badge text: "Registrations open" / "Batch in progress" / "Coming soon" / "Batch completed". */
  statusLabel: string;
  /** YYYY-MM-DD, or null. */
  startDate: string | null;
  endDate: string | null;
  courseUrl: string;
  /** Absolute poster URLs on the website (featured programs). */
  imageUrl?: string;
  imageSmallUrl?: string;
  /** Signed-in registration page (/app/courses/<slug>/register). */
  registerUrl: string;
  /** Public registration page, no account needed (/register/<slug>). */
  publicRegisterUrl: string;
}

export interface SiteCourseSection {
  key: SiteCourseGroup;
  courses: SiteCourse[];
}

export interface SiteCatalog {
  siteUrl: string;
  /** Website courses page (fallback link). */
  coursesUrl: string;
  /** Website admin (course marketing and registrations are managed there). */
  adminUrl: string;
  generatedAt: string | null;
  courses: SiteCourse[];
  /** Non-empty groups only, in display order. */
  sections: SiteCourseSection[];
  source: { catalog: "ok" | "unavailable"; live: "ok" | "unavailable"; status?: "ok" | "unavailable" };
}
