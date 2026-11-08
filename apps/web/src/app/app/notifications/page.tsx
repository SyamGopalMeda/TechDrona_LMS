import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { NotificationsInbox } from "@/features/notifications/components/NotificationsInbox";

export const metadata: Metadata = { title: "Notifications" };

/** STU-024 in-app notifications (NTF-01..03). */
export default function Page() {
  return (
    <div className="max-w-4xl">
      <PageHeader title="Notifications" description="Updates about your account, tests, reviews and batch announcements." />
      <NotificationsInbox />
    </div>
  );
}
