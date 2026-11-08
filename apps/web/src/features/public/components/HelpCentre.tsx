import Link from "next/link";
import { HELP_ARTICLES } from "../content/help";

const linkCls = "font-medium text-fg-link underline hover:text-fg-link-hover";

/**
 * PUB-019 help centre. Contact routes are the ones that exist today: support tickets for
 * signed-in learners, the review request for restricted accounts and Settings → Privacy for
 * data rights. The public contact form (SUP-16) is not built in the api yet, so it is not offered.
 */
export function HelpCentre({ signedIn }: { signedIn: boolean }) {
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <header className="space-y-2">
        <h1 className="font-display text-2xl font-bold text-fg sm:text-3xl">Help centre</h1>
        <p className="max-w-prose text-fg-secondary">Answers about your account, devices, payments and certificates, and how to reach us.</p>
      </header>

      <section aria-labelledby="help-articles" className="space-y-3">
        <h2 id="help-articles" className="font-display text-lg font-semibold text-fg">
          Articles
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {HELP_ARTICLES.map((a) => (
            <li key={a.slug} className="rounded-lg border border-line bg-surface p-4">
              <Link href={`/help/${a.slug}`} className={linkCls}>
                {a.title}
              </Link>
              <p className="mt-1 text-sm text-fg-secondary">{a.summary}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="help-contact" className="space-y-3 rounded-lg border border-line bg-surface p-4">
        <h2 id="help-contact" className="font-display text-lg font-semibold text-fg">
          Contact us
        </h2>
        {signedIn ? (
          <p className="text-sm text-fg-secondary">
            Open a support ticket and we will reply in the app.{" "}
            <Link href="/app/support/new" className={linkCls}>
              Open a ticket
            </Link>
          </p>
        ) : (
          <p className="text-sm text-fg-secondary">
            Support tickets are answered in the app.{" "}
            <Link href="/login?next=%2Fapp%2Fsupport%2Fnew" className={linkCls}>
              Log in to open a ticket
            </Link>
            . A contact form for visitors without an account is not available yet.
          </p>
        )}
        <p className="text-sm text-fg-secondary">
          Can&apos;t sign in because your account is restricted?{" "}
          <Link href="/unblock-request" className={linkCls}>
            Request a review
          </Link>
          .
        </p>
      </section>

      <section aria-labelledby="help-grievance" className="space-y-2">
        <h2 id="help-grievance" className="font-display text-lg font-semibold text-fg">
          Grievance officer
        </h2>
        <p className="text-sm text-fg-secondary">How to raise a complaint about your data, a restriction or our service, and our response times.</p>
        <Link href="/help/grievance" className={linkCls}>
          Grievance officer and complaints
        </Link>
      </section>
    </div>
  );
}
