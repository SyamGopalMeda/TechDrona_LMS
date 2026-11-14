import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "@/components/shell/PublicShell";
import { LinkButton } from "@/components/ui";
import { LMS_COURSES_HREF, siteHref } from "@/lib/site/website";
import { hasSessionCookie } from "@/lib/api/server";

export const metadata: Metadata = { title: "Page not found", robots: { index: false } };

const linkCls = "font-medium text-fg-link underline hover:text-fg-link-hover";

/** FE-33: branded 404 inside the public chrome, with one primary next step and two quieter ones. */
export default async function NotFound() {
  const signedIn = await hasSessionCookie();
  return (
    <PublicShell signedIn={signedIn}>
      <div className="mx-auto max-w-prose py-8 text-center">
        <p className="font-display text-5xl font-extrabold text-brand" aria-hidden="true">
          404
        </p>
        <h1 className="mt-2 font-display text-2xl font-extrabold text-fg-heading sm:text-[1.75rem]">Page not found</h1>
        <p className="mt-2 text-fg-secondary">The page you are looking for does not exist or you don&apos;t have access to it.</p>
        <div className="mt-6 flex justify-center">
          <LinkButton href={signedIn ? "/app" : "/"} size="lg">
            {signedIn ? "Go to my dashboard" : "Go to the home page"}
          </LinkButton>
        </div>
        <p className="mt-4 flex flex-wrap justify-center gap-4 text-sm">
          {/* Signed in: the LMS's own catalogue; signed out: the public catalogue lives on the website. */}
          {signedIn ? (
            <Link href={LMS_COURSES_HREF} className={linkCls}>
              Browse courses
            </Link>
          ) : (
            <a href={siteHref("/courses")} className={linkCls}>
              Browse courses
            </a>
          )}
          <Link href="/help" className={linkCls}>
            Help centre
          </Link>
        </p>
      </div>
    </PublicShell>
  );
}
