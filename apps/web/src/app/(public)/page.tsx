import Link from "next/link";
import { hasSessionCookie } from "@/lib/api/server";
import { CourseGrid } from "@/features/catalog/components/CatalogParts";
import { LinkButton } from "@/features/catalog/components/LinkButton";
import { serverLoad } from "@/features/catalog/lib/server";
import type { CourseCardDto, Paged } from "@/features/catalog/lib/types";

const FEATURES = [
  {
    href: "/placement",
    title: "Placement practice",
    body: "Aptitude, reasoning and coding questions, sorted by topic so you can practise your weak areas.",
    cta: "See topics",
    icon: "M4 20h16M7 16v-5m5 5V8m5 8v-3",
  },
  {
    href: "/courses",
    title: "Courses with certificates",
    body: "Lessons you can finish at your own pace, with certificates that employers can verify online.",
    cta: "Browse courses",
    icon: "M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM13 4h5.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H13z",
  },
  {
    href: "/pricing",
    title: "Mock tests and plans",
    body: "Timed mock tests to rehearse the real thing. Start free and upgrade only when you need more.",
    cta: "See plans",
    icon: "M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z",
  },
] as const;

/**
 * PUB-001 home. Static copy (no outcome numbers or testimonials until they exist with a
 * cohort and sample size) + live free courses from CAT-01. If the catalog call fails the
 * row is hidden (wireframe X state), the rest of the page is static.
 */
export default async function HomePage() {
  const [signedIn, featured] = await Promise.all([hasSessionCookie(), serverLoad<Paged<CourseCardDto>>("catalog/courses?price_type=free&limit=6")]);
  const courses = featured.ok ? featured.data.data : [];

  return (
    <div className="space-y-12">
      <section aria-labelledby="hero-h" className="rounded-2xl bg-surface-brand px-6 py-10 text-fg-on-surface-brand sm:px-10">
        <h1 id="hero-h" className="max-w-2xl font-display text-3xl font-bold sm:text-4xl">
          Know exactly how ready you are for your placement drive.
        </h1>
        <p className="mt-3 max-w-prose">
          Company-pattern mocks, explained practice and courses that track what you have actually learned, with the method published.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {/* On the navy band: `inverse` (white fill) is the main action, `inverse-secondary` (white
              outline) the alternative. Plain primary would be navy on navy (UI audit 0.3). */}
          {signedIn ? (
            <LinkButton href="/app" variant="inverse" size="lg">
              Go to dashboard
            </LinkButton>
          ) : (
            <LinkButton href="/signup" variant="inverse" size="lg">
              Create a free account
            </LinkButton>
          )}
          <LinkButton href="/courses" variant="inverse-secondary" size="lg">
            Browse courses
          </LinkButton>
          {/* Ghost buttons use text-fg, which fails contrast on the brand surface (axe color-contrast). */}
          <Link
            href="/pricing"
            className="inline-flex min-h-touch items-center rounded-md px-4 font-display text-sm font-semibold text-fg-on-surface-brand underline underline-offset-4 hover:no-underline focus-visible:shadow-focus focus-visible:outline-none"
          >
            See pricing
          </Link>
        </div>
      </section>

      <section aria-labelledby="why-h" className="space-y-4">
        <h2 id="why-h" className="font-display text-xl font-bold text-fg-heading">
          Everything you need for campus placements
        </h2>
        <ul className="grid gap-4 sm:grid-cols-3">
          {FEATURES.map((f) => (
            <li key={f.href} className="relative flex flex-col rounded-xl border border-line bg-surface p-5 shadow-xs hover:border-brand/40">
              <span aria-hidden="true" className="mb-3 grid h-10 w-10 place-items-center rounded-lg bg-brand-subtle text-brand">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                  <path d={f.icon} />
                </svg>
              </span>
              <h3 className="font-display text-base font-bold text-fg-heading">
                {/* The whole card is the link target (::after overlay); the heading text is its name. */}
                <Link href={f.href} className="after:absolute after:inset-0 after:rounded-xl focus-visible:outline-none focus-visible:after:shadow-focus">
                  {f.title}
                </Link>
              </h3>
              <p className="mt-1 text-sm text-fg-secondary">{f.body}</p>
              <span aria-hidden="true" className="mt-3 text-sm font-semibold text-fg-link">
                {f.cta} →
              </span>
            </li>
          ))}
        </ul>
      </section>

      {courses.length > 0 ? (
        <section aria-labelledby="free-h" className="space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h2 id="free-h" className="font-display text-xl font-bold text-fg-heading">
              Start with a free course
            </h2>
            <Link href="/courses?price_type=free" className="whitespace-nowrap text-sm font-semibold text-fg-link hover:text-fg-link-hover">
              All free courses
            </Link>
          </div>
          <CourseGrid courses={courses} headingLevel={3} />
        </section>
      ) : null}

      <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
        <section aria-labelledby="teams-h" className="rounded-xl border border-line bg-surface p-6 shadow-xs">
          <h2 id="teams-h" className="font-display text-lg font-bold text-fg-heading">
            Training a team?
          </h2>
          <p className="mt-2 text-sm text-fg-secondary">Tell us about your team or new hires and we will put together a training plan with Tech Drona courses, practice and assessments.</p>
          <div className="mt-4">
            <LinkButton href="/enquiries" variant="secondary">
              Make a corporate enquiry
            </LinkButton>
          </div>
        </section>

        <section aria-labelledby="rules-h" className="rounded-xl border border-line bg-surface-subtle p-6">
          <h2 id="rules-h" className="font-display text-base font-bold text-fg-heading">
            Fair and clear
          </h2>
          <p className="mt-2 text-sm text-fg-secondary">One account is for one person, and the refund rule at checkout is the same as our published policy.</p>
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <Link href="/legal/device-policy" className="font-medium text-fg-link hover:text-fg-link-hover">
              Device policy
            </Link>
            <Link href="/legal/refund-policy" className="font-medium text-fg-link hover:text-fg-link-hover">
              Refund policy
            </Link>
          </p>
        </section>
      </div>
    </div>
  );
}
