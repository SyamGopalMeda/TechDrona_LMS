import { EmptyState, PageHeader } from "@/components/ui";
import { LinkButton } from "@/features/catalog/components/LinkButton";

/**
 * PUB-006 / PUB-007. The public company-hub APIs (CAT-03/04) are not built yet, so these pages
 * say so and point to what exists: the placement topics, courses and — for a signed-in learner —
 * the company preparation path in the app (GET /me/company-paths/{slug}). No company names,
 * patterns or numbers are invented here.
 */
export function CompaniesIndex() {
  return (
    <div className="space-y-6">
      <PageHeader title="Company hubs" description="Test patterns and preparation paths for the companies that hire on campus." />
      <EmptyState
        title="Company hubs are not published yet"
        description="Until they are, prepare with the placement topics and courses. Each topic shows how many questions are in the bank."
        action={
          <div className="flex flex-wrap justify-center gap-3">
            <LinkButton href="/placement">Placement topics</LinkButton>
            <LinkButton href="/courses" variant="secondary">
              Browse courses
            </LinkButton>
          </div>
        }
      />
    </div>
  );
}

export function CompanyHub({ slug, signedIn }: { slug: string; signedIn: boolean }) {
  const appHref = `/app/companies/${encodeURIComponent(slug)}`;
  return (
    <div className="space-y-6">
      <PageHeader title="Company hub" description="Test pattern, syllabus and a preparation path for this company." />
      <EmptyState
        title="This company hub is not public yet"
        description={
          signedIn
            ? "If your plan includes a preparation path for this company, you can open it in the app."
            : "Public company pages are not published yet. Signed-in learners can open company preparation paths included in their plan."
        }
        action={
          <div className="flex flex-wrap justify-center gap-3">
            {signedIn ? (
              <LinkButton href={appHref}>Open in the app</LinkButton>
            ) : (
              <LinkButton href={`/login?next=${encodeURIComponent(appHref)}`}>Log in</LinkButton>
            )}
            <LinkButton href="/placement" variant="secondary">
              Placement topics
            </LinkButton>
          </div>
        }
      />
    </div>
  );
}
