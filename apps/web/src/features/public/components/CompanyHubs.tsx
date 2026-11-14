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
      <PageHeader title="Companies" description="Test patterns and preparation paths for the companies that hire on campus." />
      <EmptyState
        icon="users"
        title="Company guides are coming soon"
        description="We're writing a guide for each company that hires on campus: its test pattern, syllabus and a preparation path. Until then, the placement topics cover the same aptitude and coding areas."
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
        icon="users"
        title="This company guide is coming soon"
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
