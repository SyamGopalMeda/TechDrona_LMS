import Link from "next/link";
import type { ReactNode } from "react";
import { LinkButton } from "@/components/ui/Button";
import { Logo } from "@/components/ui/Logo";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";
/** Organisation slogan from the website's structured data (tech drona/index.html, "slogan"). */
const TAGLINE = "Debug your career. Deploy your dreams.";

const NAV = [
  { href: "/courses", label: "Courses" },
  { href: "/placement", label: "Placement prep" },
  { href: "/companies", label: "Companies" },
  { href: "/pricing", label: "Pricing" },
  { href: "/enquiries", label: "Corporate enquiries" },
];

/** Footer per sitemap §2 ("every public page"), grouped for scanning. */
export const FOOTER_GROUPS: { label: string; links: { href: string; label: string }[] }[] = [
  {
    label: "Learn",
    links: [
      { href: "/courses", label: "Courses" },
      { href: "/placement", label: "Placement" },
      { href: "/companies", label: "Companies" },
      { href: "/free-resources", label: "Free resources" },
      { href: "/pricing", label: "Pricing" },
      { href: "/enquiries", label: "Corporate enquiries" },
    ],
  },
  {
    label: "Support",
    links: [
      { href: "/help", label: "Help" },
      { href: "/status", label: "Status" },
      { href: "/help/grievance", label: "Grievance officer" },
      { href: "/verify", label: "Certificate verification" },
    ],
  },
  {
    label: "Policies",
    links: [
      { href: "/legal/terms", label: "Terms" },
      { href: "/legal/privacy", label: "Privacy" },
      { href: "/legal/refund-policy", label: "Refund policy" },
      { href: "/legal/device-policy", label: "Device policy" },
    ],
  },
];

const navLinkCls =
  "inline-flex min-h-[2.5rem] items-center whitespace-nowrap rounded-md px-3 font-display text-sm font-semibold text-fg no-underline transition-colors duration-fast hover:bg-brand-subtle hover:text-brand focus-visible:shadow-focus focus-visible:outline-none";
const footLinkCls = "inline-block py-1 text-sm text-white/80 no-underline hover:text-white hover:underline focus-visible:shadow-focus focus-visible:outline-none";

/**
 * Public chrome, styled after the Tech Drona website (`tech drona/src/styles/global.css`):
 * ivory canvas (#FAF8F4), white header with the navy logo lockup, navy footer band with the white
 * lockup and mint column headings. `signedIn` is a UX hint from the session-cookie presence (the
 * api decides); a signed-in visitor gets "Go to dashboard" instead of Log in / Sign up (FE-11).
 * Phones: logo + account actions on the first row, the section links scroll sideways below.
 */
export function PublicShell({ children, signedIn = false }: { children: ReactNode; signedIn?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col bg-surface-warm text-fg">
      <header data-td-public-header="" className="sticky top-0 z-topbar border-b border-line bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
        <div className="mx-auto flex max-w-content flex-wrap items-center gap-x-4 px-4 sm:px-6">
          <Link href="/" aria-label={`${APP_NAME} home`} className="flex h-16 shrink-0 items-center rounded-md focus-visible:shadow-focus focus-visible:outline-none">
            <Logo alt="" className="h-8 sm:h-9" />
          </Link>
          <nav aria-label="Main" className="order-last -mx-4 w-[calc(100%+2rem)] overflow-x-auto border-t border-line-subtle px-2 py-1 md:order-none md:mx-0 md:ml-auto md:w-auto md:border-t-0 md:p-0">
            <ul className="flex items-center gap-0.5">
              {NAV.map((n) => (
                <li key={n.href}>
                  <Link href={n.href} className={navLinkCls}>
                    {n.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="ml-auto flex items-center gap-2 md:ml-0">
            {signedIn ? (
              <LinkButton href="/app" size="sm">
                Go to dashboard
              </LinkButton>
            ) : (
              <>
                <LinkButton href="/login" variant="ghost" size="sm">
                  Log in
                </LinkButton>
                <LinkButton href="/signup" size="sm">
                  Sign up
                </LinkButton>
              </>
            )}
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-content flex-1 px-4 py-8 focus:outline-none sm:px-6 sm:py-10">
        {children}
      </main>
      <footer className="bg-surface-brand text-white/75">
        <div className="mx-auto grid max-w-content gap-8 px-4 pb-8 pt-12 sm:grid-cols-2 sm:px-6 lg:grid-cols-[1.4fr_repeat(3,minmax(0,1fr))]">
          <div>
            <Logo tone="white" alt={APP_NAME} className="h-10" />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/70">{TAGLINE}</p>
          </div>
          {FOOTER_GROUPS.map((g) => (
            <nav key={g.label} aria-label={g.label}>
              <p className="font-display text-xs font-bold uppercase tracking-[0.1em] text-accent-on-brand">{g.label}</p>
              <ul className="mt-3 space-y-1">
                {g.links.map((l) => (
                  <li key={l.href}>
                    <Link href={l.href} className={footLinkCls}>
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="border-t border-white/10">
          <p className="mx-auto max-w-content px-4 py-5 text-xs text-white/60 sm:px-6">
            © {new Date().getFullYear()} {APP_NAME}. All rights reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
