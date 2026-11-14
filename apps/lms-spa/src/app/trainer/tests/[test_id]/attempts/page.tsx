import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { LinkButton } from "@/components/ui";
import { AttemptLog } from "@/features/trainer/components/TestOps";
import { TestPageHeader } from "@/features/trainer/components/TestPageHeader";

export const metadata: Metadata = { title: "Attempt log" };

/** TRN-011 */
async function Page__server({ params }: { params: Promise<{ test_id: string }> }) {
  const { test_id } = await params;
  return (
    <div>
      <TestPageHeader
        testId={test_id}
        page="attempts"
        description="Attempts with status, score, integrity review state and device changes (rebinds)."
        actions={
          <LinkButton variant="secondary" href={`/trainer/tests/${encodeURIComponent(test_id)}/evaluation`}>
            Open evaluation
          </LinkButton>
        }
      />
      <AttemptLog testId={test_id} />
    </div>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/trainer/tests/[test_id]/attempts/page.tsx#Page");
