import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/ui";
import { DisownEvent } from "@/features/account/components/SecuritySettings";

export const metadata: Metadata = { title: "This wasn't me" };

/** "This wasn't me" from a sign-in / session-replay notice (SEC-46; unblock §1.6a). */
async function Page__server({ params }: { params: Promise<{ event_ref: string }> }) {
  const { event_ref } = await params;
  if (!/^[A-Za-z0-9_-]{4,64}$/.test(event_ref)) notFound();
  return (
    <div className="max-w-2xl">
      <PageHeader title="Secure your account" description="Tell us if you don't recognise a sign-in." />
      <DisownEvent eventRef={event_ref} />
    </div>
  );
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/app/settings/security/not-me/[event_ref]/page.tsx#Page");
