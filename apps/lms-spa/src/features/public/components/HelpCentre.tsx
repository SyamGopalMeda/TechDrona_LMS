import Link from "next/link";
import { PageHeader } from "@/components/ui";
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
      <PageHeader title="Help centre" description="Answers about your account, devices, payments and certificates, and how to reach us." />

      <section aria-labelledby="help-articles" className="space-y-3">
        <h2 id="help-articles" className="font-display text-lg font-bold text-fg-heading">
          Articles
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {HELP_ARTICLES.map((a) => (
            <li key={a.slug} className="relative rounded-xl border border-line bg-surface p-4 shadow-xs hover:border-brand/40">
              {/* The whole card is the link target (::after overlay); the title stays the accessible name. */}
              <Link href={`/help/${a.slug}`} className={`${linkCls} after:absolute after:inset-0 after:rounded-xl`}>
                {a.title}
              </Link>
              <p className="mt-1 text-sm text-fg-secondary">{a.summary}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="help-contact" className="space-y-3 rounded-xl border border-line bg-surface p-5 shadow-xs">
        <h2 id="help-contact" className="font-display text-lg font-bold text-fg-heading">
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
          Can&apos;t log in because your account is restricted?{" "}
          <Link href="/unblock-request" className={linkCls}>
            Request a review
          </Link>
          .
        </p>
      </section>

      <section aria-labelledby="help-grievance" className="space-y-2">
        <h2 id="help-grievance" className="font-display text-lg font-bold text-fg-heading">
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
