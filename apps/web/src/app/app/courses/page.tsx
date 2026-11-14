import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader, SectionHeader } from "@/components/ui";
import { formatDuration } from "@/features/catalog/lib/format";
import { serverLoad } from "@/features/catalog/lib/server";
import type { CourseCardDto, Paged } from "@/features/catalog/lib/types";
import { SiteCourseSections } from "@/features/site-catalog/components/SiteCourseSections";
import { loadSiteCatalog } from "@/features/site-catalog/lib/server";

export const metadata: Metadata = { title: "Explore courses" };

/**
 * Self-paced courses on this platform (CAT-01). The public `/courses` pages are served by the
 * website (marketing redirect), so this is the learner's way into the LMS catalogue: each card
 * opens the in-app overview, which offers "Enrol for free" or the access options.
 */
async function SelfPacedCourses() {
  const r = await serverLoad<Paged<CourseCardDto>>("catalog/courses?limit=50");
  if (!r.ok || r.data.data.length === 0) return null;
  return (
    <section aria-labelledby="self-paced-h" className="mb-10">
      <SectionHeader id="self-paced-h" title="Self-paced courses" description="Learn at your own pace on this platform: videos, readings and a certificate." />
      <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {r.data.data.map((c) => {
          const meta = [c.lesson_count ? `${c.lesson_count} lesson${c.lesson_count === 1 ? "" : "s"}` : null, formatDuration(c.duration_seconds ? c.duration_seconds / 60 : null)].filter(Boolean).join(" · ");
          return (
            <li key={c.id} className="flex flex-col rounded-xl border border-line bg-surface p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{c.price_type === "free" ? "Free" : "Paid"}</p>
              <h3 className="mt-1 font-display font-bold text-fg-heading">
                <Link href={`/app/courses/${encodeURIComponent(c.slug)}`} className="hover:underline focus-visible:shadow-focus focus-visible:outline-none">
                  {c.title}
                </Link>
              </h3>
              {c.summary ? <p className="mt-1 text-sm text-fg-secondary">{c.summary}</p> : null}
              {meta ? <p className="mt-auto pt-3 text-xs text-fg-muted">{meta}</p> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** STU-033 Explore courses: the platform's self-paced courses, then the website catalogue. */
export default async function Page() {
  const catalog = await loadSiteCatalog();
  return (
    <div>
      <PageHeader
        eyebrow="Tech Drona courses"
        title="Explore courses"
        description="Self-paced courses you can start here, and every Tech Drona course: register and pay for open courses right here, or see running, upcoming and past batches."
        actions={
          <Link href="/app/registrations" className="text-sm font-semibold text-brand hover:underline">
            My registrations
          </Link>
        }
      />
      <SelfPacedCourses />
      <SiteCourseSections catalog={catalog} />
    </div>
  );
}
