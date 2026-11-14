/**
 * The Tech Drona company website (the brand's source of truth) as seen from the LMS.
 *
 * The LMS public/auth chrome mirrors the website header and footer (`tech drona/src/components/
 * Layout.jsx`: MENU, FOOTER_COLS, SITE in src/data/content.js). Marketing pages live on the website
 * only, so every link here is absolute to `NEXT_PUBLIC_SITE_URL`; only the legal/support pages and
 * sign-in stay inside the LMS.
 */

const DEFAULT_SITE_URL = "https://35-244-50-26.sslip.io";

/** Website origin, no trailing slash (NEXT_PUBLIC_*: inlined at build time). */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || DEFAULT_SITE_URL).replace(/\/+$/, "");

/** Absolute website URL for a path such as "/courses" or "/training#labs". */
export function siteHref(path = "/"): string {
  return `${SITE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/** `SITE` in tech drona/src/data/content.js. */
export const SITE_INFO = {
  name: "Tech Drona",
  tagline: "Debug your career. Deploy your dreams.",
  email: "info@techdrona.com",
  location: "Vijayawada, Andhra Pradesh, India",
  about:
    "One technology partner for colleges, students and businesses: software, AI and cloud, practical training and internships, recruitment and IT procurement.",
} as const;

export interface SiteMenuLink {
  href: string;
  label: string;
  desc?: string;
}

export interface SiteMenuItem {
  label: string;
  href: string;
  /** Dropdown entries (Solutions); `groups` for the two-column Training & Careers menu. */
  items?: SiteMenuLink[];
  groups?: { title: string; items: SiteMenuLink[] }[];
  allLabel?: string;
  allHref?: string;
}

/** Website header MENU (Layout.jsx), plus Home first as the owner asked. Absolute URLs. */
export const SITE_MENU: SiteMenuItem[] = [
  { label: "Home", href: siteHref("/") },
  {
    label: "Solutions",
    href: siteHref("/solutions"),
    items: [
      { href: siteHref("/solutions#software"), label: "What we build", desc: "Products, CRMs, web apps and websites" },
      { href: siteHref("/solutions#products"), label: "Dental Clinic CRM", desc: "Our clinic management product" },
      { href: siteHref("/solutions#ai"), label: "Applied AI", desc: "Vision, emotion analysis, conversational AI" },
      { href: siteHref("/solutions#cloud"), label: "Launch & support", desc: "Deployment, domains and updates" },
      { href: siteHref("/procurement"), label: "IT Procurement", desc: "Hardware, networking and software licensing" },
      { href: siteHref("/recruitment"), label: "Recruitment Services", desc: "Campus hiring and talent acquisition" },
    ],
  },
  {
    label: "Training & Careers",
    href: siteHref("/training"),
    allLabel: "All programs at a glance",
    allHref: siteHref("/training#programs"),
    groups: [
      {
        title: "For students & graduates",
        items: [
          { href: siteHref("/courses/nextgen-career-accelerator-2026"), label: "NextGen Career Accelerator 2026", desc: "Four months, registrations open" },
          { href: siteHref("/courses#career-courses"), label: "Career courses", desc: "Python, Java, MERN, MEAN, AI, AWS" },
          { href: siteHref("/training#cloud-program"), label: "Cloud & Career program", desc: "78 hours, virtual" },
          { href: siteHref("/training#internships"), label: "Internships", desc: "Mentored, work-integrated learning" },
          { href: siteHref("/apply/internship"), label: "Apply for an internship", desc: "Choose a track and apply online" },
        ],
      },
      {
        title: "For colleges & institutions",
        items: [
          { href: siteHref("/training#formats"), label: "Program formats", desc: "1-day workshops to semester training" },
          { href: siteHref("/training#college"), label: "College training & partnerships", desc: "Designed with your institution" },
          { href: siteHref("/training#workshops"), label: "Workshops & faculty development", desc: "Short, hands-on formats" },
          { href: siteHref("/training#crt"), label: "Campus recruitment training", desc: "Placement preparation" },
          { href: siteHref("/training#corporate"), label: "Corporate upskilling", desc: "Training for company teams" },
        ],
      },
    ],
  },
  { label: "Courses", href: siteHref("/courses") },
  { label: "Projects", href: siteHref("/projects") },
  { label: "About", href: siteHref("/about") },
];

export const SITE_CONTACT_HREF = siteHref("/contact");

/**
 * Where "See plans" goes. The LMS `/pricing`, `/courses`, `/status`… paths are redirected to the
 * website (marketing pages live there), so in-app links point at the website directly with a
 * plain <a> (a Next <Link> would prefetch the redirect and trip the CSP connect-src).
 */
export const PLANS_HREF = siteHref("/courses");

/**
 * The LMS's own catalogue for signed-in learners (Explore courses, STU-033). In-app "get access"
 * prompts point here so the learner stays in the LMS instead of being sent to the website.
 */
export const LMS_COURSES_HREF = "/app/courses";

/** The LMS help centre's contact section: "Contact" in the LMS chrome stays in the LMS. */
export const LMS_CONTACT_HREF = "/help#help-contact";

/** Website FOOTER_COLS (Layout.jsx), absolute. */
export const SITE_FOOTER_COLS: { title: string; links: SiteMenuLink[] }[] = [
  {
    title: "Solutions",
    links: [
      { href: siteHref("/solutions#software"), label: "What we build" },
      { href: siteHref("/solutions#ai"), label: "Applied AI" },
      { href: siteHref("/solutions#cloud"), label: "Launch & support" },
      { href: siteHref("/projects"), label: "Projects & clients" },
      { href: siteHref("/procurement"), label: "IT procurement" },
    ],
  },
  {
    title: "Training & Careers",
    links: [
      { href: siteHref("/courses/nextgen-career-accelerator-2026"), label: "NextGen Career Accelerator" },
      { href: siteHref("/courses"), label: "All courses" },
      { href: siteHref("/training"), label: "College programs" },
      { href: siteHref("/apply/internship"), label: "Apply for an internship" },
      { href: siteHref("/recruitment"), label: "Hire our talent" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: siteHref("/about"), label: "About us" },
      { href: siteHref("/contact"), label: "Contact" },
    ],
  },
];

/** LMS-owned pages that stay in the LMS footer (relative links). */
export const LMS_SUPPORT_LINKS: SiteMenuLink[] = [
  { href: "/help", label: "Help" },
  { href: "/help/grievance", label: "Grievance officer" },
  { href: "/verify", label: "Certificate verification" },
];

export const LMS_LEGAL_LINKS: SiteMenuLink[] = [
  { href: "/legal/terms", label: "Terms" },
  { href: "/legal/privacy", label: "Privacy" },
  { href: "/legal/refund-policy", label: "Refund policy" },
  { href: "/legal/device-policy", label: "Device policy" },
];
