import Link from "next/link";
import type { ReactNode } from "react";
import { LMS_CONTACT_HREF, LMS_COURSES_HREF, LMS_LEGAL_LINKS, LMS_SUPPORT_LINKS, SITE_CONTACT_HREF, SITE_FOOTER_COLS, SITE_INFO, siteHref, type SiteMenuLink } from "@/lib/site/website";
import { SiteHeader } from "./SiteHeader";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "Tech Drona";

/**
 * Footer link groups: the website's columns + the LMS's own support pages. Website links stay
 * absolute except where the LMS has its own page: Contact → the help centre's contact section and,
 * signed in, "All courses" → the in-app catalogue.
 */
export function footerGroups(signedIn = false): { label: string; links: SiteMenuLink[] }[] {
  const websiteCourses = siteHref("/courses");
  const local = (l: SiteMenuLink): SiteMenuLink =>
    l.href === SITE_CONTACT_HREF ? { ...l, href: LMS_CONTACT_HREF } : signedIn && l.href === websiteCourses ? { ...l, href: LMS_COURSES_HREF } : l;
  return [...SITE_FOOTER_COLS.map((c) => ({ label: c.title, links: c.links.map(local) })), { label: "Learner support", links: LMS_SUPPORT_LINKS }];
}

function MailIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 6h16v12H4zM4 7l8 6 8-6" />
    </svg>
  );
}
function PinIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z" />
    </svg>
  );
}

/**
 * Footer, a copy of the website footer (Layout.jsx `Footer`; CSS §46 .footer/.ft-grid/.ft-col/
 * .ft-bottom): navy gradient band, white lockup + about + contact, the website's columns, and an
 * LMS "Learner support" column. Legal links stay in the LMS.
 */
export function SiteFooter({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <footer className="td-footer">
      <div className="td-ft-container">
        <div className="td-ft-grid">
          <div className="td-ft-brand">
            {/* LMS home; a full page load because the edge proxy decides where "/" goes. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/" className="td-ft-logo inline-block rounded-md" aria-label={`${APP_NAME} LMS home`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/brand/logo-lockup-white.svg" alt="" width={220} height={48} loading="lazy" decoding="async" />
            </a>
            <p className="td-ft-about">{SITE_INFO.about}</p>
            <ul className="td-ft-contact">
              <li>
                <a href={`mailto:${SITE_INFO.email}`}>
                  <span className="td-ft-ic">
                    <MailIcon />
                  </span>
                  {SITE_INFO.email}
                </a>
              </li>
              <li>
                <span className="td-ft-ic">
                  <PinIcon />
                </span>
                {SITE_INFO.location}
              </li>
            </ul>
          </div>
          {footerGroups(signedIn).map((g) => (
            <nav key={g.label} className="td-ft-col" aria-label={g.label}>
              <h2>{g.label}</h2>
              <ul>
                {g.links.map((l) => (
                  <li key={l.href + l.label}>{l.href.startsWith("/") ? <Link href={l.href}>{l.label}</Link> : <a href={l.href}>{l.label}</a>}</li>
                ))}
              </ul>
            </nav>
          ))}
        </div>
        <div className="td-ft-bottom">
          <p>
            © {new Date().getFullYear()} {APP_NAME}. All rights reserved.
          </p>
          <p className="td-ft-tag">{SITE_INFO.tagline}</p>
          <nav aria-label="Policies">
            <ul className="td-ft-legal">
              {LMS_LEGAL_LINKS.map((l) => (
                <li key={l.href}>
                  <Link href={l.href}>{l.label}</Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </div>
    </footer>
  );
}

/**
 * Public chrome (login, signup, password recovery, verification, legal, help, 404): the company
 * website's header and footer, so the LMS reads as part of techdrona's site. The website's own
 * sections go to the main website (NEXT_PUBLIC_SITE_URL); logo, Contact, help, legal and (signed
 * in) Courses stay in the LMS. The LMS's own marketing nav is retired. Ivory canvas
 * (website --cream #FAF8F4). `signedIn` is a UX hint from the session cookie (the api decides).
 */
export function PublicShell({ children, signedIn = false }: { children: ReactNode; signedIn?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col bg-surface-warm text-fg">
      <SiteHeader signedIn={signedIn} />
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1240px] flex-1 px-4 py-8 focus:outline-none sm:px-6 sm:py-10 lg:px-8">
        {children}
      </main>
      <SiteFooter signedIn={signedIn} />
    </div>
  );
}
