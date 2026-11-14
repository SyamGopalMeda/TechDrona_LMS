import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasSessionCookie } from "@/lib/api/server";
import { ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { CourseDetail } from "@/features/catalog/components/CourseDetail";
import { loadCourseDetail } from "@/features/catalog/lib/server";

type Params = Promise<{ slug: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { slug } = await params;
  const r = await loadCourseDetail(slug);
  // Throwing here (before the page streams) makes an unknown slug a real HTTP 404, not a soft one.
  if (!r.ok && r.status === 404) notFound();
  return r.ok ? { title: r.data.title, description: r.data.summary ?? undefined } : { title: "Course" };
}

/** PUB-003 course detail (CAT-02). Signed-in callers get `viewer` (owned / via a plan or batch). */
async function Page__server({ params }: { params: Params }) {
  const { slug } = await params;
  const [result, signedIn] = await Promise.all([loadCourseDetail(slug), hasSessionCookie()]);
  if (!result.ok && result.status === 404) notFound();
  if (!result.ok) return <ServerErrorState result={result} retryHref={`/courses/${encodeURIComponent(slug)}`} />;
  return <CourseDetail course={result.data} signedIn={signedIn} />;
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/courses/[slug]/page.tsx#Page");
