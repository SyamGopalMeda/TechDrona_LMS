import { SITE_URL } from "@/lib/site/website";

type Env = Record<string, string | undefined>;

/**
 * Website origin (no trailing slash). Reads `NEXT_PUBLIC_SITE_URL` at request time on the server
 * (dynamic lookup, so a restart picks up a new value), falling back to the build-time value /
 * default in `@/lib/site/website`. Anything that is not an http(s) URL is ignored.
 */
export function siteBaseUrl(env: Env = process.env): string {
  const raw = (env["NEXT_PUBLIC_SITE_URL"] ?? "").trim();
  if (raw) {
    try {
      const u = new URL(raw);
      if (u.protocol === "https:" || u.protocol === "http:") return `${u.origin}${u.pathname}`.replace(/\/+$/, "");
    } catch {
      /* fall through */
    }
  }
  return SITE_URL;
}

export const siteCourseUrl = (site: string, slug: string) => `${site}/courses/${encodeURIComponent(slug)}`;
