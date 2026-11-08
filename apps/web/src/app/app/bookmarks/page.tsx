import type { Metadata } from "next";
import Link from "next/link";
import { EmptyState, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Bookmarks" };

/**
 * STU-028 bookmarks & notes: the api has no bookmark or note endpoints yet, so this page says so
 * and points to what exists (practice review keeps questions you got wrong).
 */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Bookmarks" />
      <EmptyState
        title="Bookmarks aren't available yet"
        description={
          <>
            Saving lessons and questions is coming. Until then,{" "}
            <Link href="/app/practice/review" className="text-fg-link underline">
              practice review
            </Link>{" "}
            keeps the questions you got wrong.
          </>
        }
      />
    </div>
  );
}
