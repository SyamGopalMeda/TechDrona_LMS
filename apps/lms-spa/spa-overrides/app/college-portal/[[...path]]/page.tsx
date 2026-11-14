import type { Metadata } from "next";
import { CollegePortalFallback } from "@/features/college-data/CollegePortalFallback";

export const metadata: Metadata = { title: "College Data Portal", robots: { index: false, follow: false } };

/**
 * SPA-only page (spa-overrides/app/college-portal): the College Data Portal is a separate static
 * app. Firebase Hosting serves its files before the SPA fallback, so the LMS app only reaches this
 * route when the portal is not deployed yet (live audit 2026-11-14, admin.md F1).
 */
export default function Page() {
  return <CollegePortalFallback />;
}
