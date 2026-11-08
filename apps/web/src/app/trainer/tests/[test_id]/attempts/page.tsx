import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { AttemptLog } from "@/features/trainer/components/TestOps";

export const metadata: Metadata = { title: "Attempt log" };

/** TRN-011 */
export default async function Page({
  params,
}: {
  params: Promise<{ test_id: string }>;
}) {
  const { test_id } = await params;
  return (
    <div>
      <PageHeader
        title="Attempt log"
        eyebrow="TRN-011"
        description="Attempts with status, score, integrity review state and device changes (rebinds)."
      />
      <p className="mb-4 text-sm">
        <Link className="text-fg-link underline" href={`/trainer/tests/${encodeURIComponent(test_id)}/evaluation`}>
          Open evaluation (grading, integrity badges, publish results)
        </Link>
      </p>
      <AttemptLog testId={test_id} />
    </div>
  );
}
