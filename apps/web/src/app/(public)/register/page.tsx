import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { SiteCourseSections } from "@/features/site-catalog/components/SiteCourseSections";
import { loadSiteCatalog } from "@/features/site-catalog/lib/server";
import { hasSessionCookie } from "@/lib/api/server";

export const metadata: Metadata = {
  title: "Register for a course",
  description: "Tech Drona courses open for registration. Register and pay by UPI, no account needed.",
};

/** Public course list for registration: open courses link to /register/<slug> (signed in: the app page). */
export default async function Page() {
  const [catalog, signedIn] = await Promise.all([loadSiteCatalog(), hasSessionCookie()]);
  return (
    <div>
      <PageHeader
        eyebrow="Tech Drona courses"
        title="Register for a course"
        description="Pick a course that's open, fill in your details and pay by UPI. We verify your payment and email your LMS login."
        actions={
          <Link href="/register/status" className="text-sm font-semibold text-brand hover:underline">
            Check my registration
          </Link>
        }
      />
      <SiteCourseSections catalog={catalog} audience={signedIn ? "student" : "public"} />
    </div>
  );
}
