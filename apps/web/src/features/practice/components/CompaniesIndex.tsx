import { EmptyState, LinkButton, PageHeader } from "@/components/ui";

/**
 * Company paths index. The backend has no student-facing list of companies or target-company
 * readiness yet (only GET me/company-paths/{slug} and the staff-only studio/companies), so this is
 * an honest "coming soon" with next steps that work today inside the app (the public company page
 * is also still empty, so we don't send students there).
 */
export function CompaniesIndex() {
  return (
    <div>
      <PageHeader title="Company paths" description="Preparation paths for the companies you're aiming for." />
      <EmptyState
        icon="users"
        title="Company paths are coming soon"
        description="Soon you'll be able to pick target companies and see how ready you are for each one. Until then, practise the aptitude and coding topics most campus tests cover."
        action={
          <div className="flex flex-wrap justify-center gap-3">
            <LinkButton href="/app/practice">Go to practice</LinkButton>
            <LinkButton href="/app/tests" variant="secondary">
              Take a mock test
            </LinkButton>
          </div>
        }
      />
    </div>
  );
}
