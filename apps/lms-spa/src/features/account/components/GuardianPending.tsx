"use client";

import Link from "next/link";
import { ErrorState, Skeleton } from "@/components/ui";
import { Notice } from "@/features/auth/components/shared";
import type { Me } from "../lib/types";
import { useResource } from "@/lib/api/use-resource";

/**
 * Target of the api's `minor_consent_pending` problem (`guardian_flow_url`). The guardian acts
 * from the emailed link (public `/guardian-consent/{token}`, valid 7 days); there is no student
 * endpoint to resend it, so this page explains the state and what still works.
 */
export function GuardianPending() {
  const me = useResource<Me>("me", { handle: { restriction: false } });
  if (me.error) return <ErrorState error={me.error} onRetry={me.reload} />;
  if (!me.data) {
    return (
      <div aria-busy="true">
        <span className="sr-only">Loading…</span>
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (me.data.user.status !== "pending_guardian_consent") {
    return (
      <Notice tone="success" title="Your parent or guardian has already responded">
        Nothing is waiting on guardian consent.{" "}
        <Link href="/app" className="underline">
          Go to your dashboard
        </Link>
        .
      </Notice>
    );
  }
  return (
    <div className="space-y-4">
      <Notice tone="warning" title="Waiting for your parent or guardian">
        Because you are under 18, a parent or guardian must agree before you can use courses, tests and practice. We emailed them a link when you signed up. The link works for 7 days.
      </Notice>
      <div className="space-y-2 text-sm text-fg-secondary">
        <p>
          <strong className="text-fg">What you can do now:</strong> see your account status, manage your privacy choices and contact support.
        </p>
        <p>
          <strong className="text-fg">Didn&apos;t they get the email?</strong> Ask them to check their spam folder. If the link has expired or went to the wrong address,{" "}
          <Link href="/app/support/new" className="text-fg-link underline">
            contact support
          </Link>{" "}
          and we&apos;ll help.
        </p>
      </div>
      <nav aria-label="Guardian consent links" className="flex flex-wrap gap-4 text-sm">
        <Link href="/app/settings/privacy" className="text-fg-link underline">
          Privacy choices
        </Link>
        <Link href="/legal/privacy" className="text-fg-link underline">
          Privacy notice
        </Link>
      </nav>
    </div>
  );
}
