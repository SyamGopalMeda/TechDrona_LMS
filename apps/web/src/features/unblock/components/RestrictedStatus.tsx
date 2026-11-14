"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ErrorState, Skeleton } from "@/components/ui";
import { ReferenceChip } from "@/features/auth/components/shared";
import { formatDateTime } from "@/features/auth/lib/format";
import { useResource } from "@/features/account/lib/use-resource";
import { cn } from "@/lib/ui/cn";
import type { SecurityStatus } from "../lib/types";
import { ReverifyPanel } from "./ReverifyPanel";
import { UnblockStatusCard } from "./UnblockStatus";

const linkBtn = "inline-flex min-h-touch items-center justify-center rounded-md px-4 text-sm font-medium focus-visible:shadow-focus focus-visible:outline-none";
const primary = cn(linkBtn, "bg-brand text-brand-on hover:bg-brand-hover");
const secondary = cn(linkBtn, "border border-line-control bg-surface text-fg hover:bg-surface-hover");

function durationText(start?: string | null, end?: string | null): string {
  const s = start ? Date.parse(start) : NaN;
  const e = end ? Date.parse(end) : NaN;
  if (Number.isNaN(s) || Number.isNaN(e) || e <= s) return "a limited time";
  const hours = Math.round((e - s) / 3_600_000);
  if (hours < 48) return `${hours} hours`;
  return `${Math.round(hours / 24)} days`;
}

function LevelMeter({ level }: { level: number }) {
  return (
    <span role="img" aria-label={`Level ${level} of 4`} className="inline-flex gap-1">
      {[1, 2, 3, 4].map((i) => (
        <span key={i} aria-hidden="true" className={cn("h-2 w-2 rounded-full", i <= level ? (level >= 4 ? "bg-risk-l4-border" : "bg-risk-l3-border") : "bg-line-strong")} />
      ))}
    </span>
  );
}

function Panel({ level, children }: { level: number; children: ReactNode }) {
  return (
    <section
      aria-labelledby="restriction-title"
      className={cn("rounded-xl border p-5 sm:p-6", level >= 4 ? "border-risk-l4-border bg-risk-l4-subtle" : level === 3 ? "border-risk-l3-border bg-risk-l3-subtle" : "border-line bg-surface")}
    >
      {children}
    </section>
  );
}

/**
 * PUB-021 status-only page content (L4) and L3/T-protect states, from SEC-01. Copy is verbatim
 * from account-unblock-workflow §1.3–§1.5. Query-string values (from the 403 problem) are only a
 * fallback while the status cannot be loaded.
 */
export function RestrictedStatus({
  fallbackCaseRef,
  fallbackLevel,
  details,
}: {
  fallbackCaseRef?: string | null;
  fallbackLevel?: number | null;
  /** Extra sections rendered under the status panel from the same SEC-01 response (STU-026). */
  details?: (s: SecurityStatus) => ReactNode;
}) {
  const status = useResource<SecurityStatus>("me/security/status", { handle: { restriction: false } });

  if (status.loading && !status.data) {
    return (
      <div aria-busy="true" className="space-y-3">
        <span className="sr-only">Loading your account status…</span>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (status.error || !status.data) {
    return (
      <div className="space-y-4">
        <ErrorState error={status.error} title="We couldn't load your account status" onRetry={status.reload} />
        {fallbackCaseRef ? (
          <p className="text-sm text-fg-secondary">
            Case reference: <ReferenceChip value={fallbackCaseRef} />
            {fallbackLevel ? ` · Level ${fallbackLevel}` : ""}
          </p>
        ) : null}
        <p className="text-sm">
          <Link href="/help" className="text-fg-link underline">
            Contact support
          </Link>
        </p>
      </div>
    );
  }

  if (!details) return <StatusPanel s={status.data} fallbackCaseRef={fallbackCaseRef} />;
  return (
    <div className="space-y-6">
      <StatusPanel s={status.data} fallbackCaseRef={fallbackCaseRef} />
      {details(status.data)}
    </div>
  );
}

function StatusPanel({ s, fallbackCaseRef }: { s: SecurityStatus; fallbackCaseRef?: string | null }) {
  const caseRef = s.case_ref ?? fallbackCaseRef ?? null;
  const reasons = s.reasons ?? [];
  const reviewHref = `/unblock-request${caseRef ? `?case_ref=${encodeURIComponent(caseRef)}` : ""}`;
  const hasRequest = !!s.unblock_request?.reference;
  const canRequest = (s.available_actions ?? ["request_review"]).includes("request_review") && !hasRequest;
  const reverify = (s.available_actions ?? []).includes("reverify") ? <ReverifyPanel /> : null;

  if (s.takeover?.protect_locked) {
    return (
      <Panel level={4}>
        <h1 id="restriction-title" className="font-display text-2xl font-bold text-fg">
          We&apos;ve secured your account
        </h1>
        <p className="mt-2 text-sm text-fg-secondary">
          We noticed sign-in activity that may not have been you, so we&apos;ve signed out all devices to protect your account. Reference: {caseRef ? <ReferenceChip value={caseRef} /> : "—"}
        </p>
        <p className="mt-2 text-sm text-fg-secondary">To continue, verify with a code sent to your registered contact and choose a new password.</p>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <Link href="/forgot-password" className={primary}>
            Secure my account
          </Link>
        </div>
        <p className="mt-3 text-sm">
          If you can&apos;t access your registered phone or email,{" "}
          <Link href="/help" className="text-fg-link underline">
            get help recovering your account
          </Link>
          .
        </p>
      </Panel>
    );
  }

  if (s.level >= 4) {
    const reason = reasons.map((r) => r.text).join(" ") || "see the case details";
    return (
      <div className="space-y-6">
        {reverify}
        <Panel level={4}>
          <div className="flex items-center gap-3">
            <LevelMeter level={4} />
          </div>
          <h1 id="restriction-title" className="mt-2 font-display text-2xl font-bold text-fg">
            Your account is suspended pending review
          </h1>
          <p className="mt-2 text-sm text-fg">Case reference: {caseRef ? <ReferenceChip value={caseRef} /> : "—"}</p>
          <p className="mt-3 text-sm text-fg-secondary">After reviewing activity on your account, our security team has suspended access while the case is open. Reason: {reason}.</p>
          <p className="mt-2 text-sm text-fg-secondary">
            You can still sign in to see this page, ask for a review, contact support, manage billing (including cancelling renewals), and make privacy requests. Your data and purchases have not been deleted.
          </p>
          <p className="mt-2 text-sm text-fg-secondary">
            <strong>To ask for a review</strong>, tell us what happened. We&apos;ll reply within 48 hours and decide within 5 days.
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            {canRequest ? (
              <Link href={reviewHref} className={primary}>
                Request a review
              </Link>
            ) : null}
            <Link href="/help" className={secondary}>
              Contact support
            </Link>
          </div>
        </Panel>
        {hasRequest ? <UnblockStatusCard reference={s.unblock_request!.reference!} /> : null}
      </div>
    );
  }

  if (s.level === 3) {
    const until = formatDateTime(s.until);
    // An L3 past its end stays enforced until the learner re-verifies (RE §6.1): a headline
    // "paused until <a past date>" reads as a bug, so say what is still needed instead.
    const ended = !!s.until && new Date(s.until).getTime() <= Date.now();
    return (
      <div className="space-y-6">
        {reverify}
        <Panel level={3}>
          <LevelMeter level={3} />
          <h1 id="restriction-title" className="mt-2 font-display text-2xl font-bold text-fg">
            {ended ? "Learning access is still paused" : `Learning access paused until ${until}`}
          </h1>
          {ended ? (
            <p className="mt-1 text-sm text-fg">
              The pause period ended on {until}. {reverify ? "Confirm it’s you above to get your access back." : "Access returns once your account is confirmed."}
            </p>
          ) : null}
          <p className="mt-2 text-sm text-fg">Case reference: {caseRef ? <ReferenceChip value={caseRef} /> : "—"}</p>
          <p className="mt-3 text-sm text-fg-secondary">
            Our account-protection system paused video lessons, tests and practice on your account for {durationText(s.starts_at, s.until)}. Here&apos;s why:
          </p>
          {reasons.length ? (
            <ul className="mt-1 list-disc pl-5 text-sm text-fg-secondary">
              {reasons.map((r) => (
                <li key={r.explanation_key}>{r.text}</li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-sm text-fg-secondary">
            Our Terms allow one person per account, with up to {s.policy?.max_concurrent_sessions ?? 2} signed-in devices and {s.policy?.max_concurrent_streams ?? 1} video at a time (
            <Link href="/legal/device-policy" className="text-fg-link underline">
              Device policy
            </Link>
            ).
          </p>
          <p className="mt-2 text-sm text-fg-secondary">
            <strong>What still works:</strong> your dashboard and progress, your devices page, billing, support and your privacy requests. Nothing has been deleted. Your subscription, progress and certificates are safe.
          </p>
          <p className="mt-2 text-sm text-fg-secondary">
            <strong>What happens next:</strong> when the pause ends, you&apos;ll confirm your identity with a code and review your devices, and then access returns automatically.
          </p>
          <p className="mt-2 text-sm text-fg-secondary">
            <strong>Think this is a mistake?</strong> Ask for a review now. A person, not a computer, will look at it, usually within 24 hours.
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            {canRequest ? (
              <Link href={reviewHref} className={primary}>
                Request a review
              </Link>
            ) : null}
            <Link href="/app/settings/devices" className={secondary}>
              Review my devices
            </Link>
            <Link href="/legal/device-policy" className={secondary}>
              Read the device policy
            </Link>
          </div>
        </Panel>
        {hasRequest ? <UnblockStatusCard reference={s.unblock_request!.reference!} /> : null}
      </div>
    );
  }

  return (
    <Panel level={s.level}>
      <h1 id="restriction-title" className="font-display text-2xl font-bold text-fg">
        {s.level === 0 ? "All clear — no restrictions on your account" : s.level === 2 ? "Confirm it's you" : "New activity on your account"}
      </h1>
      <p className="mt-2 text-sm text-fg-secondary">
        {s.level === 0 ? "You have full access." : s.level === 2 ? "Videos and tests are paused on an unverified device until you confirm it's yours." : "If you don't recognise a device, sign it out and change your password."}
      </p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <Link href="/app" className={primary}>
          Go to my dashboard
        </Link>
        {s.level > 0 ? (
          <Link href="/app/settings/devices" className={secondary}>
            Review my devices
          </Link>
        ) : null}
      </div>
    </Panel>
  );
}
