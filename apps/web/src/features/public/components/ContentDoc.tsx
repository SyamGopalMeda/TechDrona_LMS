import Link from "next/link";
import type { ReactNode } from "react";
import { NOTICE_VERSION } from "@/features/auth/lib/consents";
import type { ContentDoc, ContentSection } from "../content/types";

/** Visible on every policy text until counsel signs off (FIX-BRIEF decision; roadmap E10). */
export function DraftBanner() {
  return (
    <div role="note" aria-label="Draft notice" className="rounded-lg border border-warning-border bg-warning-subtle p-4 text-sm">
      <p className="font-semibold text-warning-fg">Draft — pending legal review</p>
      <p className="mt-1 text-fg-secondary">
        This text describes how Tech Drona works today. It has not yet been reviewed by legal counsel and may change before it takes effect.
      </p>
    </div>
  );
}

const linkCls = "font-medium text-fg-link underline hover:text-fg-link-hover";

function Section({ section }: { section: ContentSection }) {
  const hid = `sec-${section.id}`;
  return (
    <section aria-labelledby={hid} className="space-y-3">
      <h2 id={hid} className="font-display text-lg font-semibold text-fg">
        {section.heading}
      </h2>
      {section.paragraphs?.map((p) => (
        <p key={p} className="text-sm leading-relaxed text-fg-secondary">
          {p}
        </p>
      ))}
      {section.items?.length ? (
        <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-fg-secondary">
          {section.items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      ) : null}
      {section.table ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
            <caption className="sr-only">{section.table.caption}</caption>
            <thead className="bg-surface-subtle">
              <tr>
                {section.table.head.map((h, i) => (
                  <th key={`${h}-${i}`} scope="col" className="px-3 py-2 font-semibold text-fg">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.table.rows.map((row) => (
                <tr key={row.join("|")} className="border-t border-line align-top">
                  {row.map((cell, i) =>
                    i === 0 ? (
                      <th key={i} scope="row" className="px-3 py-2 font-medium text-fg">
                        {cell}
                      </th>
                    ) : (
                      <td key={i} className="px-3 py-2 text-fg-secondary">
                        {cell}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {section.links?.length ? (
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {section.links.map((l) => (
            <Link key={l.href} href={l.href} className={linkCls}>
              {l.label}
            </Link>
          ))}
        </p>
      ) : null}
    </section>
  );
}

/**
 * PUB-018 / PUB-019 static document: title, summary, draft banner and version line for
 * policies, then the structured sections. `children` renders live data after the sections
 * (e.g. the refund rule returned by COM-01, or the signed-in learner's own device limits).
 */
export function ContentDocView({ doc, kind, children, back }: { doc: ContentDoc; kind: "policy" | "article"; children?: ReactNode; back?: { href: string; label: string } }) {
  return (
    <article className="mx-auto max-w-3xl space-y-6">
      {back ? (
        <Link href={back.href} className="text-sm font-medium text-fg-link hover:text-fg-link-hover">
          ← {back.label}
        </Link>
      ) : null}
      <header className="space-y-2">
        <h1 className="font-display text-2xl font-bold text-fg sm:text-3xl">{doc.title}</h1>
        <p className="max-w-prose text-fg-secondary">{doc.summary}</p>
        {kind === "policy" ? (
          <p className="text-xs text-fg-muted">
            Version: draft for notice {NOTICE_VERSION} · Effective date: not set yet (set when the text is approved)
          </p>
        ) : null}
      </header>
      {doc.draft ? <DraftBanner /> : null}
      {doc.sections.map((s) => (
        <Section key={s.id} section={s} />
      ))}
      {children}
    </article>
  );
}
