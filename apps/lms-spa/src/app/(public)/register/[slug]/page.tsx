import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import Link from "next/link";
import { CourseRegister } from "@/features/registration/components/CourseRegister";
import { registerHref } from "@/features/registration/lib/registration";
import { loadSiteCatalog } from "@/features/site-catalog/lib/server";
import { hasSessionCookie } from "@/lib/api/server";

export const metadata: Metadata = {
  title: "Register for a course",
  description: "Register for a Tech Drona course: your details, pay by UPI and upload the receipt. No account needed.",
};

/**
 * Public course registration (no account): details -> pay (UPI QR) -> upload receipt -> the
 * registration number. The admin verifies the payment, adds the student to the batch and the
 * LMS login is emailed. Signed-in students are pointed to the in-app page (it tracks the status).
 */
async function Page__server({ params }: { params: Promise<{ slug: string }> }) {
  const { slug: raw } = await params;
  const slug = decodeURIComponent(raw).toLowerCase();
  const [course, signedIn] = await Promise.all([
    loadSiteCatalog()
      .then((c) => c.courses.find((x) => x.slug === slug))
      .catch(() => undefined),
    hasSessionCookie(),
  ]);
  return (
    <div className="space-y-4">
      {signedIn ? (
        <p role="note" className="mx-auto max-w-2xl rounded-xl border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          You&apos;re signed in.{" "}
          <Link href={registerHref(slug)} className="font-semibold underline">
            Register from your account
          </Link>{" "}
          to follow your registration in the LMS.
        </p>
      ) : null}
      <CourseRegister mode="public" slug={slug} courseTitle={course?.title} courseStatus={course?.regStatusSource === "lms" ? course.regStatus : undefined} />
    </div>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/register/[slug]/page.tsx#Page");
