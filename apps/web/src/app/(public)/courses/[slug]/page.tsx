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
  return r.ok ? { title: r.data.title, description: r.data.summary ?? undefined } : { title: "Course" };
}

/** PUB-003 course detail (CAT-02). Signed-in callers get `viewer` (owned / via a plan or batch). */
export default async function Page({ params }: { params: Params }) {
  const { slug } = await params;
  const [result, signedIn] = await Promise.all([loadCourseDetail(slug), hasSessionCookie()]);
  if (!result.ok && result.status === 404) notFound();
  if (!result.ok) return <ServerErrorState result={result} retryHref={`/courses/${encodeURIComponent(slug)}`} />;
  return <CourseDetail course={result.data} signedIn={signedIn} />;
}
