import type { MetadataRoute } from "next";
import { PUBLIC_SITEMAP_PATHS, siteUrl } from "@/features/public/lib/seo";
import { HELP_ARTICLES } from "@/features/public/content/help";

/** FE-33: static public routes plus help articles (catalog pages are discoverable from /courses). */
export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  return [...PUBLIC_SITEMAP_PATHS, ...HELP_ARTICLES.map((a) => `/help/${a.slug}`)].map((p) => ({ url: `${base}${p}` }));
}
