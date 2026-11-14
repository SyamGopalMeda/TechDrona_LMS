import "server-only";
import { loadSiteCatalog } from "@/features/site-catalog/lib/server";

/** Website course titles by slug for the admissions pages (empty when the catalogue is unreachable). */
export async function loadCourseTitles(): Promise<Record<string, string>> {
  try {
    const catalog = await loadSiteCatalog();
    return Object.fromEntries(catalog.courses.map((c) => [c.slug, c.title]));
  } catch {
    return {};
  }
}
