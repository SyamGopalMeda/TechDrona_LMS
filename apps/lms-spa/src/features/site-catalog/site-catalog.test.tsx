import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildSiteCatalog, courseStatusUrl, dateKey, fetchSiteCatalog, parseCatalogJson, parseCoursePublic, parseCourseStatus, siteCourseGroup, stripCourses, type FetchLike } from "./lib/catalog";
import { siteBaseUrl } from "./lib/site-url";
import type { CatalogCourse, CoursePublicState } from "./lib/types";
import { SiteCourseCard } from "./components/SiteCourseCard";
import { SiteCourseSections } from "./components/SiteCourseSections";
import { SiteCourseStripView } from "./components/SiteCourseStrip";

vi.mock("server-only", () => ({}));
vi.mock("./lib/server", () => ({ loadSiteCatalog: vi.fn() }));

const SITE = "https://site.example";
const TODAY = "2026-11-11";
const ENV = { NEXT_PUBLIC_SITE_URL: SITE, NEXT_PUBLIC_FIREBASE_PROJECT_ID: "billing-f4fe3", NEXT_PUBLIC_FIREBASE_API_KEY: "k" };

const CATALOG_JSON = {
  generated_at: "2026-11-11T09:44:52.286Z",
  courses: [
    {
      slug: "nextgen-career-accelerator-2026",
      title: "NextGen Career Accelerator 2026",
      kicker: "Four-month training roadmap",
      tagline: "Build skills. Create projects. Grow with confidence.",
      status: "Registrations open",
      facts: [
        { icon: "calendar", label: "Program length", value: "4 months", note: "16 weeks" },
        { icon: "clock", label: "Class schedule", value: "2 hours / weekday" },
        { icon: "layers", label: "Major projects", value: "2 projects" },
        { icon: "laptop", label: "Mode", value: "Online / hybrid" },
      ],
      tech: ["Python", "FastAPI", "React"],
      featured: true,
      comingSoon: false,
    },
    {
      slug: "python-full-stack-development",
      title: "Python Full Stack Development",
      kicker: "Full-stack development course",
      tagline: "Build and deploy web applications.",
      edition: "Coming soon · 2026",
      icon: "code",
      family: "Full stack",
      theme: { accent: "#0d7a4f", accentSoft: "#e4f5ec", labels: ["Frontend"] },
      tech: ["Python", "Django"],
      facts: [{ icon: "clock", label: "Duration", value: "50 hours" }],
      featured: false,
      comingSoon: true,
    },
    { slug: "generative-ai", title: "Generative AI", theme: { accent: "url(https://evil)", accentSoft: "#efe9fd" }, comingSoon: true },
    { slug: "aws-and-devops", title: "AWS and DevOps", comingSoon: true },
    { slug: "mern-stack-development", title: "MERN Stack", comingSoon: true },
    { slug: "BAD SLUG!", title: "dropped" },
  ],
};

const fs = (slug: string, f: Record<string, unknown>) => ({ name: `projects/p/databases/(default)/documents/web_course_public/${slug}`, fields: f });
const FIRESTORE_JSON = {
  documents: [
    fs("python-full-stack-development", { status: { stringValue: "running" }, registrations_open: { booleanValue: false }, start_date: { stringValue: "2026-10-01" }, end_date: { stringValue: "2027-01-31" } }),
    fs("generative-ai", { status: { stringValue: "coming_soon" }, registrations_open: { booleanValue: false }, start_date: { nullValue: null } }),
    fs("aws-and-devops", { status: { stringValue: "completed" }, registrations_open: { booleanValue: false }, end_date: { timestampValue: "2026-09-30T10:00:00Z" } }),
    fs("mern-stack-development", { status: { stringValue: "draft" }, registrations_open: { booleanValue: false } }),
    fs("cloud-bootcamp", { title: { stringValue: "Cloud Bootcamp" }, status: { stringValue: "coming_soon" }, registrations_open: { booleanValue: true } }),
  ],
};

const jsonResponse = (body: unknown, status = 200) => new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
function fakeFetch(routes: { catalog?: unknown | Error; live?: unknown | Error; status?: unknown | Error }): FetchLike & { calls: string[] } {
  const calls: string[] = [];
  const fn = (async (url: string) => {
    calls.push(url);
    const r = url.includes("catalog.json") ? routes.catalog : url.includes("/public/courses/status") ? routes.status : routes.live;
    if (r instanceof Error) throw r;
    if (r === undefined) return jsonResponse("not found", 404);
    return jsonResponse(r);
  }) as FetchLike & { calls: string[] };
  fn.calls = calls;
  return fn;
}

const live = (p: Partial<CoursePublicState>): CoursePublicState => ({ title: null, status: null, registrations_open: false, start_date: null, end_date: null, ...p });
const soon = { comingSoon: true } as Pick<CatalogCourse, "comingSoon">;

describe("site catalogue: grouping rules", () => {
  it("registrations_open wins, else completed > running > upcoming; drafts are hidden", () => {
    expect(siteCourseGroup(soon, live({ status: "coming_soon", registrations_open: true }), TODAY)).toBe("open");
    expect(siteCourseGroup(soon, live({ status: "running" }), TODAY)).toBe("running");
    expect(siteCourseGroup(soon, live({ status: "running", start_date: "2026-12-01" }), TODAY)).toBe("upcoming");
    expect(siteCourseGroup(soon, live({ status: "coming_soon" }), TODAY)).toBe("upcoming");
    expect(siteCourseGroup(soon, live({ status: "completed" }), TODAY)).toBe("completed");
    expect(siteCourseGroup(soon, live({ status: "running", end_date: "2026-11-10" }), TODAY)).toBe("completed");
    expect(siteCourseGroup(soon, live({ status: "draft", registrations_open: true }), TODAY)).toBeNull();
  });

  it("without live state falls back to the catalogue's comingSoon flag (website default)", () => {
    expect(siteCourseGroup({ comingSoon: false }, null, TODAY)).toBe("open");
    expect(siteCourseGroup({ comingSoon: true }, null, TODAY)).toBe("upcoming");
    // live state says closed even though the catalogue says open
    expect(siteCourseGroup({ comingSoon: false }, live({ status: "coming_soon" }), TODAY)).toBe("upcoming");
  });

  it("normalises dates and Firestore typed values", () => {
    expect(dateKey("2026-12-01")).toBe("2026-12-01");
    expect(dateKey("2026-09-30T20:00:00Z")).toBe("2026-10-01"); // IST
    expect(dateKey("nope")).toBeNull();
    const parsed = parseCoursePublic(FIRESTORE_JSON);
    expect(parsed["aws-and-devops"]).toEqual({ title: null, status: "completed", registrations_open: false, start_date: null, end_date: "2026-09-30T10:00:00Z" });
    expect(parsed["cloud-bootcamp"]?.title).toBe("Cloud Bootcamp");
  });

  it("parses catalog.json defensively (bad slugs, unsafe colours, missing arrays)", () => {
    const { courses, generatedAt } = parseCatalogJson(CATALOG_JSON);
    expect(generatedAt).toBe("2026-11-11T09:44:52.286Z");
    expect(courses.map((c) => c.slug)).not.toContain("bad slug!");
    expect(courses.find((c) => c.slug === "generative-ai")?.theme.accent).toBe("#1d3a8a");
    expect(courses.find((c) => c.slug === "aws-and-devops")?.tech).toEqual([]);
    expect(() => parseCatalogJson({ nope: 1 })).toThrow();
  });
});

describe("site catalogue: fetch + merge", () => {
  it("merges catalog.json with the live state into Open / Running / Upcoming / Completed", async () => {
    const f = fakeFetch({ catalog: CATALOG_JSON, live: FIRESTORE_JSON });
    const cat = await fetchSiteCatalog({ fetchImpl: f, env: ENV, now: new Date("2026-11-11T06:00:00Z") });
    expect(f.calls[0]).toBe(`${SITE}/catalog.json`);
    expect(f.calls[1]).toContain("/projects/billing-f4fe3/databases/(default)/documents/web_course_public?pageSize=300&key=k");
    expect(cat.source).toEqual({ catalog: "ok", live: "ok" });
    const bySection = Object.fromEntries(cat.sections.map((s) => [s.key, s.courses.map((c) => c.slug)]));
    expect(bySection).toEqual({
      open: ["nextgen-career-accelerator-2026", "cloud-bootcamp"],
      running: ["python-full-stack-development"],
      upcoming: ["generative-ai"],
      completed: ["aws-and-devops"],
    });
    expect(cat.courses.map((c) => c.slug)).not.toContain("mern-stack-development"); // draft
    const py = cat.courses.find((c) => c.slug === "python-full-stack-development")!;
    expect(py).toMatchObject({ statusLabel: "Batch in progress", startDate: "2026-10-01", courseUrl: `${SITE}/courses/python-full-stack-development`, registerUrl: "/app/courses/python-full-stack-development/register" });
    expect(cat.courses.find((c) => c.slug === "cloud-bootcamp")).toMatchObject({ minimal: true, title: "Cloud Bootcamp" });
    expect(cat.adminUrl).toBe(`${SITE}/admin`);
  });

  it("missing live state (no Firebase env or Firestore down) keeps the catalogue defaults", async () => {
    const noEnv = await fetchSiteCatalog({ fetchImpl: fakeFetch({ catalog: CATALOG_JSON }), env: { NEXT_PUBLIC_SITE_URL: SITE }, now: new Date("2026-11-11T06:00:00Z") });
    expect(noEnv.source.live).toBe("unavailable");
    expect(noEnv.sections.map((s) => [s.key, s.courses.length])).toEqual([
      ["open", 1],
      ["upcoming", 4],
    ]);
    const down = await fetchSiteCatalog({ fetchImpl: fakeFetch({ catalog: CATALOG_JSON, live: new Error("ECONNRESET") }), env: ENV });
    expect(down.source).toEqual({ catalog: "ok", live: "unavailable" });
    expect(down.courses).toHaveLength(5);
  });

  it("fetch failures never throw: SPA HTML instead of catalog.json, network errors, timeouts", async () => {
    const html = await fetchSiteCatalog({ fetchImpl: fakeFetch({ catalog: "<!doctype html><html></html>", live: FIRESTORE_JSON }), env: ENV });
    expect(html.source).toEqual({ catalog: "unavailable", live: "ok" });
    expect(html.courses.every((c) => c.minimal)).toBe(true); // cards from the live state only
    const none = await fetchSiteCatalog({ fetchImpl: fakeFetch({ catalog: new Error("down"), live: new Error("down") }), env: ENV });
    expect(none.courses).toEqual([]);
    expect(none.sections).toEqual([]);
    expect(none.coursesUrl).toBe(`${SITE}/courses`);
    const hang: FetchLike = (_u, init) => new Promise((_r, reject) => init?.signal?.addEventListener("abort", () => reject(new Error("aborted"))));
    const slow = await fetchSiteCatalog({ fetchImpl: hang, env: ENV, timeoutMs: 20 });
    expect(slow.courses).toEqual([]);
  });

  it("reads NEXT_PUBLIC_SITE_URL at request time, ignoring non-http values", () => {
    expect(siteBaseUrl({ NEXT_PUBLIC_SITE_URL: "https://x.example/" })).toBe("https://x.example");
    expect(siteBaseUrl({ NEXT_PUBLIC_SITE_URL: "javascript:alert(1)" })).toMatch(/^https?:\/\//);
    expect(siteBaseUrl({})).toMatch(/^https?:\/\//);
  });
});

const sample = () =>
  buildSiteCatalog({
    courses: parseCatalogJson(CATALOG_JSON).courses,
    live: parseCoursePublic(FIRESTORE_JSON),
    siteUrl: SITE,
    today: TODAY,
    source: { catalog: "ok", live: "ok" },
  });

describe("site catalogue: components", () => {
  it("SiteCourseCard: open course links to the course page and the in-LMS registration", () => {
    const c = sample().courses.find((x) => x.slug === "nextgen-career-accelerator-2026")!;
    render(<SiteCourseCard course={c} />);
    const card = screen.getByRole("article", { name: "NextGen Career Accelerator 2026" });
    expect(within(card).getByText("Registrations open")).toBeInTheDocument();
    expect(within(card).getByText("Four-month training roadmap")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Register: NextGen Career Accelerator 2026" })).toHaveAttribute("href", "/app/courses/nextgen-career-accelerator-2026/register");
    const details = within(card).getByRole("link", { name: "Course details on the Tech Drona website (opens in a new tab): NextGen Career Accelerator 2026" });
    expect(details).toHaveAttribute("href", `${SITE}/courses/nextgen-career-accelerator-2026`);
    expect(details).toHaveAttribute("target", "_blank");
    expect(within(card).getByText("4 months")).toBeInTheDocument();
    expect(within(card).queryByText("Online / hybrid")).not.toBeInTheDocument(); // 3 facts max
    expect(within(card).getByText("FastAPI")).toBeInTheDocument();
  });

  it("SiteCourseCard: a course that isn't open shows its state and dates, without Register", () => {
    const py = sample().courses.find((x) => x.slug === "python-full-stack-development")!;
    render(<SiteCourseCard course={py} />);
    expect(screen.getByText("Batch in progress")).toBeInTheDocument();
    expect(screen.getByText(/1 Oct 2026 – 31 Jan 2027/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Register/ })).not.toBeInTheDocument();
    expect(screen.getByText("Closed")).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("link", { name: /^Join waitlist/ })).not.toBeInTheDocument();
  });

  it("SiteCourseSections: four groups with counts, empty-group notes, and a fallback when nothing loads", () => {
    const cat = sample();
    const { unmount } = render(<SiteCourseSections catalog={cat} />);
    for (const [h, n] of [["Open registrations", "2"], ["Running", "1"], ["Upcoming", "1"], ["Completed", "1"]]) {
      const heading = screen.getByRole("heading", { level: 2, name: new RegExp(`^${h}\\s*${n}$`) });
      expect(heading).toBeInTheDocument();
    }
    expect(screen.getByText("Batch completed")).toBeInTheDocument();
    unmount();

    const onlyUpcoming = { ...cat, courses: cat.courses.filter((c) => c.group === "upcoming"), sections: cat.sections.filter((s) => s.key === "upcoming") };
    const r2 = render(<SiteCourseSections catalog={onlyUpcoming} />);
    expect(screen.getByText("No batch is running right now.")).toBeInTheDocument();
    r2.unmount();

    render(<SiteCourseSections catalog={{ ...cat, courses: [], sections: [] }} />);
    expect(screen.getByText("Courses are on the Tech Drona website")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse courses on the website" })).toHaveAttribute("href", `${SITE}/courses`);
  });

  it("compact variant drops empty groups (admin)", () => {
    const cat = sample();
    const onlyOpen = { ...cat, courses: cat.courses.filter((c) => c.group === "open"), sections: cat.sections.filter((s) => s.key === "open") };
    render(<SiteCourseSections catalog={onlyOpen} variant="compact" headingLevel="h3" />);
    expect(screen.getByRole("heading", { level: 3, name: /^Open registrations\s*2$/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^Running/ })).not.toBeInTheDocument();
  });

  it("SiteCourseStripView: open/running first, links to All courses", () => {
    const cat = sample();
    expect(stripCourses(cat, 3).map((c) => c.group)).toEqual(["open", "open", "running"]);
    render(<SiteCourseStripView catalog={cat} limit={2} />);
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /All courses/ })).toHaveAttribute("href", "/app/courses");
    expect(screen.getAllByRole("link", { name: /Register/ })[0]).toHaveAttribute("href", "/app/courses/nextgen-career-accelerator-2026/register");
  });
});

describe("site catalogue: cards after the live audit (F-4, CORS fallback)", () => {
  it("the whole card is one link (stretched title) that says when it opens the website", () => {
    const py = sample().courses.find((x) => x.slug === "python-full-stack-development")!; // running: links to the website
    render(<SiteCourseCard course={py} />);
    const card = screen.getByRole("article", { name: "Python Full Stack Development" });
    const title = within(card).getByRole("link", { name: "Python Full Stack Development (opens the Tech Drona website in a new tab)" });
    expect(title).toHaveAttribute("href", `${SITE}/courses/python-full-stack-development`);
    expect(title).toHaveAttribute("target", "_blank");
    expect(title.className).toMatch(/after:absolute/);
    expect(title.className).toMatch(/after:inset-0/);
    // the banner is no longer a second (hidden) link to the same place
    expect(within(card).getAllByRole("link").filter((a) => a.getAttribute("href") === py.courseUrl)).toHaveLength(2); // title + Course details
    expect(within(card).getByRole("link", { name: /^Course details on the Tech Drona website/ })).toHaveTextContent("Course details on our website");
  });

  it("the family label is at least 0.75rem (was 10.9px)", () => {
    const c = sample().courses.find((x) => x.slug === "generative-ai")!;
    render(<SiteCourseCard course={c} />);
    const label = screen.getByText("Course");
    expect(label.parentElement!.className).toMatch(/(^|\s)text-xs(\s|$)/);
    expect(label.parentElement!.className).not.toMatch(/0\.68rem/);
  });

  it("the fact labels are at least 0.75rem (live re-check: 10.88px)", () => {
    const c = sample().courses.find((x) => x.facts.some((f) => f.label === "Program length"))!;
    render(<SiteCourseCard course={c} />);
    const label = screen.getByText("Program length");
    expect(label.className).toMatch(/(^|\s)text-xs(\s|$)/);
    expect(label.className).not.toMatch(/0\.68rem/);
  });

  it("cards built without catalog.json (CORS-blocked) still say where the details are", () => {
    const cat = buildSiteCatalog({ courses: [], live: parseCoursePublic(FIRESTORE_JSON), siteUrl: SITE, today: TODAY, source: { catalog: "unavailable", live: "ok" } });
    const c = cat.courses.find((x) => x.slug === "generative-ai")!;
    expect(c.minimal).toBe(true);
    render(<SiteCourseCard course={c} />);
    expect(screen.getByText("Syllabus, fees and batch dates are on the Tech Drona website.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Join the waitlist on our website/ })).toHaveAttribute("href", `${SITE}/courses/generative-ai#register`);
  });

  it("strip: no waitlist promise unless a course has one; one Coming soon per card; big tap target", () => {
    const upcomingOnly = withStatusAll({ "generative-ai": "coming_soon" });
    const r1 = render(<SiteCourseStripView catalog={upcomingOnly} limit={3} />);
    expect(screen.getByText("Registrations open soon. Join the waitlist on our website to hear first.")).toBeInTheDocument();
    const card = screen.getByRole("article", { name: "Generative AI" });
    expect(within(card).getAllByText("Coming soon")).toHaveLength(1);
    expect(within(card).getByRole("link", { name: /^Join the waitlist on our website/ })).toHaveAttribute("target", "_blank");
    expect(within(card).getByRole("link", { name: /^Generative AI \(opens the Tech Drona website/ }).className).toMatch(/after:inset-0/);
    r1.unmount();

    const closedOnly = { ...upcomingOnly, courses: upcomingOnly.courses.map((c) => ({ ...c, regStatus: "closed" as const, statusLabel: "Closed" })) };
    render(<SiteCourseStripView catalog={closedOnly} limit={3} />);
    expect(screen.queryByText(/waitlist/i)).not.toBeInTheDocument();
    expect(screen.getByText("See what's running now and what's coming next.")).toBeInTheDocument();
  });
});

const withStatusAll = (status: Record<string, "open" | "coming_soon" | "closed">) => {
  const cat = buildSiteCatalog({ courses: parseCatalogJson(CATALOG_JSON).courses, live: parseCoursePublic(FIRESTORE_JSON), status, siteUrl: SITE, today: TODAY, source: { catalog: "ok", live: "ok", status: "ok" } });
  const courses = cat.courses.filter((c) => c.group === "upcoming");
  return { ...cat, courses, sections: cat.sections.filter((x) => x.key === "upcoming") };
};

describe("site catalogue: LMS course registration status", () => {
  const withStatus = (status: Record<string, "open" | "coming_soon" | "closed">) =>
    buildSiteCatalog({ courses: parseCatalogJson(CATALOG_JSON).courses, live: parseCoursePublic(FIRESTORE_JSON), status, siteUrl: SITE, today: TODAY, source: { catalog: "ok", live: "ok", status: "ok" } });

  it("parses the status map defensively", () => {
    expect(parseCourseStatus({ data: { java: "open", "BAD SLUG!": "open", ai: "maybe", aws: "closed" }, updated_at: null })).toEqual({ java: "open", aws: "closed" });
    expect(() => parseCourseStatus({ nope: 1 })).toThrow();
    expect(courseStatusUrl({ TD_API_INTERNAL_URL: "http://api:8000/" })).toBe("http://api:8000/api/v1/public/courses/status");
    expect(courseStatusUrl({})).toBeNull();
  });

  it("the LMS status is the source of truth: badge, group and Register only when open", () => {
    const cat = withStatus({ "nextgen-career-accelerator-2026": "closed", "generative-ai": "open", "python-full-stack-development": "coming_soon" });
    const by = Object.fromEntries(cat.courses.map((c) => [c.slug, c]));
    expect(by["generative-ai"]).toMatchObject({ group: "open", regStatus: "open", regStatusSource: "lms", registrationOpen: true, statusLabel: "Registration open" });
    expect(by["python-full-stack-development"]).toMatchObject({ group: "upcoming", regStatus: "coming_soon", registrationOpen: false, statusLabel: "Coming soon" });
    expect(by["nextgen-career-accelerator-2026"]).toMatchObject({ group: "completed", regStatus: "closed", registrationOpen: false, statusLabel: "Closed" });
    // not listed by the LMS: derived from the live state
    expect(by["cloud-bootcamp"]).toMatchObject({ regStatus: "open", regStatusSource: "derived" });
    expect(by["aws-and-devops"]).toMatchObject({ regStatus: "closed", regStatusSource: "derived" });
  });

  it("cards: open -> Register (app for students, /register for visitors); coming soon / closed -> no link", () => {
    const cat = withStatus({ "generative-ai": "open", "python-full-stack-development": "coming_soon", "nextgen-career-accelerator-2026": "closed" });
    const get = (slug: string) => cat.courses.find((c) => c.slug === slug)!;
    const r1 = render(<SiteCourseCard course={get("generative-ai")} />);
    expect(screen.getByText("Registration open")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Register: Generative AI" })).toHaveAttribute("href", "/app/courses/generative-ai/register");
    r1.unmount();
    const r2 = render(<SiteCourseCard course={get("generative-ai")} audience="public" />);
    expect(screen.getByRole("link", { name: "Register: Generative AI" })).toHaveAttribute("href", "/register/generative-ai");
    r2.unmount();
    const r3 = render(<SiteCourseCard course={get("python-full-stack-development")} audience="public" />);
    // Live audit F-4: "Coming soon" once (the badge), and the website's waitlist form instead of a dead label.
    expect(screen.getAllByText("Coming soon")).toHaveLength(1);
    expect(screen.queryByRole("link", { name: /^Register/ })).not.toBeInTheDocument();
    const wl = screen.getByRole("link", { name: /^Join the waitlist on our website \(opens the Tech Drona website in a new tab\)/ });
    expect(wl).toHaveAttribute("href", `${SITE}/courses/python-full-stack-development#register`);
    expect(wl).toHaveAttribute("target", "_blank");
    r3.unmount();
    render(<SiteCourseCard course={get("nextgen-career-accelerator-2026")} />);
    expect(screen.getAllByText("Closed")).toHaveLength(1); // badge only, no duplicate disabled label
    expect(screen.queryByRole("link", { name: /^Register/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /waitlist/i })).not.toBeInTheDocument(); // closed: the website has no waitlist
  });

  it("strip: Register links only for open courses, per audience", () => {
    const cat = withStatus({ "nextgen-career-accelerator-2026": "open", "cloud-bootcamp": "closed" });
    render(<SiteCourseStripView catalog={cat} limit={3} audience="public" />);
    const links = screen.getAllByRole("link", { name: /^Register/ });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/register/nextgen-career-accelerator-2026"]);
    expect(screen.getAllByText("Closed").length).toBeGreaterThanOrEqual(1);
  });

  it("fetchSiteCatalog reads the status from the api when configured; failures fall back", async () => {
    const env = { ...ENV, TD_API_INTERNAL_URL: "http://api:8000" };
    const f = fakeFetch({ catalog: CATALOG_JSON, live: FIRESTORE_JSON, status: { data: { "generative-ai": "open" }, updated_at: null } });
    const cat = await fetchSiteCatalog({ fetchImpl: f, env, now: new Date("2026-11-11T06:00:00Z") });
    expect(f.calls).toContain("http://api:8000/api/v1/public/courses/status");
    expect(cat.source.status).toBe("ok");
    expect(cat.courses.find((c) => c.slug === "generative-ai")).toMatchObject({ group: "open", registrationOpen: true });
    const down = await fetchSiteCatalog({ fetchImpl: fakeFetch({ catalog: CATALOG_JSON, live: FIRESTORE_JSON, status: new Error("down") }), env });
    expect(down.source.status).toBe("unavailable");
    expect(down.courses.find((c) => c.slug === "generative-ai")).toMatchObject({ group: "upcoming", regStatusSource: "derived" });
  });
});
