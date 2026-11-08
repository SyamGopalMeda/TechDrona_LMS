import Link from "next/link";
import { hasSessionCookie } from "@/lib/api/server";
import { CourseGrid } from "@/features/catalog/components/CatalogParts";
import { LinkButton } from "@/features/catalog/components/LinkButton";
import { serverLoad } from "@/features/catalog/lib/server";
import type { CourseCardDto, Paged } from "@/features/catalog/lib/types";

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
          {signedIn ? (
            <LinkButton href="/app">Go to dashboard</LinkButton>
          ) : (
            <LinkButton href="/signup">Create a free account</LinkButton>
          )}
          <LinkButton href="/courses" variant="secondary">
            Browse courses
          </LinkButton>
          {/* Ghost buttons use text-fg, which fails contrast on the brand surface (axe color-contrast). */}
          <Link
            href="/pricing"
            className="inline-flex h-10 items-center rounded-md px-4 text-sm font-medium text-fg-on-surface-brand underline underline-offset-4 hover:no-underline focus-visible:shadow-focus focus-visible:outline-none"
          >
            See pricing
          </Link>
        </div>
      </section>

      {courses.length > 0 ? (
        <section aria-labelledby="free-h" className="space-y-4">
          <div className="flex items-end justify-between gap-3">
            <h2 id="free-h" className="font-display text-xl font-semibold text-fg">
              Start with a free course
            </h2>
            <Link href="/courses?price_type=free" className="text-sm font-medium text-fg-link hover:text-fg-link-hover">
              All free courses
            </Link>
          </div>
          <CourseGrid courses={courses} headingLevel={3} />
        </section>
      ) : null}

      <section aria-labelledby="rules-h" className="rounded-xl border border-line bg-surface p-6">
        <h2 id="rules-h" className="font-display text-lg font-semibold text-fg">
          Rules we publish
        </h2>
        <p className="mt-2 text-sm text-fg-secondary">
          One account is for one person. See the device policy for how many devices, signed-in sessions and videos at a time your account allows.
        </p>
        <p className="mt-2 text-sm text-fg-secondary">The refund rule shown at checkout is the same text as in our refund policy, including for discounted purchases.</p>
        <p className="mt-3 flex flex-wrap gap-4 text-sm">
          <Link href="/legal/device-policy" className="font-medium text-fg-link hover:text-fg-link-hover">
            Device policy
          </Link>
          <Link href="/legal/refund-policy" className="font-medium text-fg-link hover:text-fg-link-hover">
            Refund policy
          </Link>
        </p>
      </section>

      <section aria-labelledby="teams-h" className="rounded-xl border border-line bg-surface p-6">
        <h2 id="teams-h" className="font-display text-lg font-semibold text-fg">
          Training a team?
        </h2>
        <p className="mt-2 text-sm text-fg-secondary">Tell us about your team or new hires and we will put together a training plan with Tech Drona courses, practice and assessments.</p>
        <p className="mt-3 text-sm">
          <Link href="/enquiries" className="font-medium text-fg-link hover:text-fg-link-hover">
            Make a corporate enquiry
          </Link>
        </p>
      </section>
    </div>
  );
}
