import type { Metadata } from "next";
import { EmptyState, LinkButton, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Notification templates", robots: { index: false } };

/**
 * ADM-011 placeholder, reachable only by URL (no nav entry). Instead of a "Not yet implemented"
 * box it says plainly what happens today and where to go next.
 */
export default function Page() {
  return (
    <div>
      <PageHeader breadcrumbs={[{ label: "Dashboard", href: "/admin" }, { label: "Notification templates" }]} title="Notification templates" />
      <EmptyState
        icon="bell"
        title="Templates can't be edited here yet"
        description="Emails and in-app notifications use the built-in wording for each event. To change the wording, ask the engineering team; the change ships with the next release."
        action={
          <LinkButton href="/admin" variant="secondary">
            Back to dashboard
          </LinkButton>
        }
      />
    </div>
  );
}
