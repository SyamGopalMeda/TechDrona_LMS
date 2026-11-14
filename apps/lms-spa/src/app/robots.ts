import type { MetadataRoute } from "next";
import { siteUrl } from "@/features/public/lib/seo";

/** FE-33: crawl public pages only; portals, BFF and token links stay out of the index. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/app", "/trainer", "/evaluator", "/mentor", "/studio", "/desk", "/finance", "/security", "/admin", "/account/", "/guardian-consent/", "/reset-password/", "/verify/email/", "/login", "/signup", "/unblock-request", "/college-portal"],
      },
    ],
    sitemap: `${siteUrl()}/sitemap.xml`,
    host: siteUrl(),
  };
}
