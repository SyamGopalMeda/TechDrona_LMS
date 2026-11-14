import Link from "next/link";
import { EmptyState } from "@/components/ui";
import { LinkButton } from "@/features/catalog/components/LinkButton";
import type { TaxonomyNode } from "@/features/practice/lib/types";

const linkCls = "font-medium text-fg-link hover:text-fg-link-hover";

function count(n: number): string {
  return `${n} question${n === 1 ? "" : "s"}`;
}

export function topicHref(subject: TaxonomyNode, topic: TaxonomyNode): string {
  return `/placement/${encodeURIComponent(subject.slug)}/${encodeURIComponent(topic.slug)}`;
}

/** PUB-004 placement hub from PLC-01 (active taxonomy with published-question counts). */
export function PlacementHub({ subjects, signedIn }: { subjects: TaxonomyNode[]; signedIn: boolean }) {
  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold text-fg">Placement preparation</h1>
          <p className="mt-1 max-w-prose text-sm text-fg-muted">Subjects and topics in the question bank, with the number of published questions in each.</p>
        </div>
        <LinkButton href={signedIn ? "/app/practice" : "/signup?next=%2Fapp%2Fpractice"}>{signedIn ? "Start practising" : "Sign up to practise"}</LinkButton>
      </header>
      {subjects.length === 0 ? (
        <EmptyState icon="book"
          title="No subjects published yet"
          description="Check back soon, or browse the courses."
          action={
            <LinkButton href="/courses" variant="secondary">
              Browse courses
            </LinkButton>
          }
        />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {subjects.map((s) => (
            <li key={s.id}>
              <section aria-labelledby={`subj-${s.id}`} className="h-full rounded-xl border border-line bg-surface p-5">
                <div className="flex items-baseline justify-between gap-2">
                  <h2 id={`subj-${s.id}`} className="font-display text-lg font-semibold text-fg">
                    {s.name}
                  </h2>
                  <span className="text-xs tabular-nums text-fg-muted">{count(s.question_count)}</span>
                </div>
                {s.children.length ? (
                  <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
                    {s.children.map((t) => (
                      <li key={t.id}>
                        <Link href={topicHref(s, t)} className={linkCls}>
                          {t.name}
                        </Link>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-fg-muted">No topics yet.</p>
                )}
              </section>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Find `subjectSlug` at the root, then `topicSlug` anywhere below it. */
export function findTopic(subjects: TaxonomyNode[], subjectSlug: string, topicSlug: string): { subject: TaxonomyNode; topic: TaxonomyNode } | null {
  const subject = subjects.find((s) => s.slug === subjectSlug);
  if (!subject) return null;
  const queue = [...subject.children];
  while (queue.length) {
    const n = queue.shift()!;
    if (n.slug === topicSlug) return { subject, topic: n };
    queue.push(...n.children);
  }
  return null;
}

/**
 * PUB-005 topic page. The api has no public sample-question endpoint yet, so the page shows
 * the topic, its sub-topics and question count, and sends the visitor to practice (sign-in gate).
 */
export function PlacementTopic({ subject, topic, signedIn }: { subject: TaxonomyNode; topic: TaxonomyNode; signedIn: boolean }) {
  const practice = `/app/practice/${encodeURIComponent(subject.slug)}`;
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <nav aria-label="Breadcrumb" className="text-sm">
        <Link href="/placement" className={linkCls}>
          Placement
        </Link>
        <span className="text-fg-muted"> / {subject.name}</span>
      </nav>
      <header>
        <h1 className="font-display text-2xl font-bold text-fg">{topic.name}</h1>
        <p className="mt-1 text-sm text-fg-muted">
          {subject.name} · {count(topic.question_count)} in the bank
        </p>
      </header>
      {topic.children.length ? (
        <section aria-labelledby="subtopics" className="space-y-2">
          <h2 id="subtopics" className="font-display text-lg font-semibold text-fg">
            What this topic covers
          </h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-secondary">
            {topic.children.map((c) => (
              <li key={c.id}>
                {c.name} <span className="text-fg-muted">({count(c.question_count)})</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-labelledby="practise" className="space-y-3 rounded-xl border border-line bg-surface p-5">
        <h2 id="practise" className="font-display text-lg font-semibold text-fg">
          Practise {topic.name}
        </h2>
        <p className="text-sm text-fg-secondary">Questions come with explanations, and your mastery is tracked per topic. Practice needs an account.</p>
        {signedIn ? (
          <LinkButton href={practice}>Practise this topic</LinkButton>
        ) : (
          <div className="flex flex-wrap gap-3">
            <LinkButton href={`/signup?next=${encodeURIComponent(practice)}`}>Create a free account</LinkButton>
            <LinkButton href={`/login?next=${encodeURIComponent(practice)}`} variant="secondary">
              Log in
            </LinkButton>
          </div>
        )}
      </section>
    </div>
  );
}
