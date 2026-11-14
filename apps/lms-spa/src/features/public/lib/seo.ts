/**
 * Public, indexable routes (sitemap §2). Token, account and portal routes are excluded, and so are
 * the marketing pages Firebase Hosting redirects to the website (courses, pricing, …) and `/`.
 */
export const PUBLIC_SITEMAP_PATHS = [
  "/help",
  "/verify",
  "/legal/terms",
  "/legal/privacy",
  "/legal/refund-policy",
  "/legal/device-policy",
] as const;

/** Canonical origin from NEXT_PUBLIC_BASE_URL (no trailing slash). */
export function siteUrl(): string {
  return (process.env.NEXT_PUBLIC_BASE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
}
