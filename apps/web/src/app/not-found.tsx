import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "@/components/shell/PublicShell";
import { hasSessionCookie } from "@/lib/api/server";

export const metadata: Metadata = { title: "Page not found", robots: { index: false } };

const linkCls = "font-medium text-fg-link underline hover:text-fg-link-hover";

/** FE-33: branded 404 inside the public chrome, with useful next steps. */
export default async function NotFound() {
  const signedIn = await hasSessionCookie();
  return (
    <PublicShell signedIn={signedIn}>
      <div className="mx-auto max-w-prose py-8 text-center">
        <p className="font-display text-5xl font-bold text-fg-muted" aria-hidden="true">
          404
        </p>
        <h1 className="mt-2 font-display text-2xl font-bold text-fg">Page not found</h1>
        <p className="mt-2 text-sm text-fg-muted">The page you are looking for does not exist or you don&apos;t have access to it.</p>
        <p className="mt-6 flex flex-wrap justify-center gap-4 text-sm">
          <Link href={signedIn ? "/app" : "/"} className={linkCls}>
            {signedIn ? "Go to my dashboard" : "Go to the home page"}
          </Link>
          <Link href="/courses" className={linkCls}>
            Browse courses
          </Link>
          <Link href="/help" className={linkCls}>
            Help centre
          </Link>
        </p>
      </div>
    </PublicShell>
  );
}
