"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, ErrorState, FormField, Skeleton } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatCountdown, retryAfterSeconds, toFormError, type FormErrorInfo } from "../lib/errors";
import { PURPOSE_LABELS } from "../lib/consents";
import type { GuardianConsentView, GuardianDecisionBody, OtpSentResponse } from "../lib/types";
import { FormAlert, Notice, OtpInput, useCountdown } from "./shared";

export type { GuardianConsentView } from "../lib/types";

/** Items shown to the guardian that are not in PURPOSE_LABELS (item G, minors only). */
const GUARDIAN_ITEM_LABELS: Record<string, string> = {
  core_service: "Account and learning service",
  assessment_integrity: "Test integrity checks during timed tests",
};


/** PUB-015 · AUTH-25 view, AUTH-26 OTP to guardian's contact, AUTH-27 decision. */
export function GuardianConsent({ token }: { token: string }) {
  const [view, setView] = useState<GuardianConsentView | null>(null);
  const [loadErr, setLoadErr] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState<"send" | "consent" | "decline" | null>(null);
  const [resendIn, setResendIn] = useCountdown();
  const [outcome, setOutcome] = useState<"consented" | "declined" | null>(null);
  const [declaration, setDeclaration] = useState(false);
  const [declErr, setDeclErr] = useState<string | undefined>();
  const alertRef = useRef<HTMLDivElement>(null);
  const path = `auth/guardian-consent/${encodeURIComponent(token)}`;

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      setView(await api.get<GuardianConsentView>(path, { handle: { auth: false, restriction: false } }));
    } catch (err) {
      setLoadErr(err);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  const fail = (err: unknown) => {
    if (err instanceof ApiError && (err.code === "otp_send_limited" || err.code === "otp_attempts_exceeded")) {
      const s = retryAfterSeconds(err);
      setError({ title: err.title, detail: s ? `Try again in ${formatCountdown(s)}.` : err.detail, requestId: err.requestId, code: err.code });
    } else if (err instanceof ApiError && err.code === "otp_invalid") {
      setError({ title: "That code didn't work", detail: "Check the code and try again.", requestId: err.requestId, code: err.code });
    } else setError(toFormError(err));
    setTimeout(() => alertRef.current?.focus(), 0);
  };

  const send = async () => {
    setBusy("send");
    setError(null);
    try {
      const res = await api.post<OtpSentResponse>(`${path}/verify-contact`, {}, { idempotencyKey: true, handle: { auth: false } });
      setSentTo((res.kind === "ok" && res.data?.sent_to) || view?.contact_masked || "your phone or email");
      setResendIn(45);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const decide = async (decision: "consent" | "decline", e?: FormEvent) => {
    e?.preventDefault();
    if (!/^\d{6}$/.test(code)) {
      setFieldErr("Enter the 6-digit code we sent you.");
      return;
    }
    setFieldErr(undefined);
    if (decision === "consent" && !declaration) {
      setDeclErr("Please confirm you are the parent or legal guardian.");
      return;
    }
    setDeclErr(undefined);
    setBusy(decision);
    setError(null);
    try {
      const body: GuardianDecisionBody = { decision, otp_code: code, declaration: decision === "consent" ? declaration : false };
      await api.post(`${path}/decision`, body, { idempotencyKey: true, handle: { auth: false } });
      setOutcome(decision === "consent" ? "consented" : "declined");
    } catch (err) {
      fail(err);
    } finally {
      setCode("");
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div aria-busy="true" className="space-y-3">
        <span className="sr-only">Loading…</span>
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  const child = view?.child_first_name ?? "your child";

  if (loadErr) {
    if (loadErr instanceof ApiError && (loadErr.code === "not_found" || loadErr.status === 410)) {
      return (
        <Notice tone="warning" title="This link has expired">
          Ask your child to send a new request from their Tech Drona account.
        </Notice>
      );
    }
    return <ErrorState error={loadErr} onRetry={load} />;
  }

  // Backend GuardianConsent.status: pending | verified (consented) | rejected (declined).
  const status = outcome ?? (view?.status === "verified" ? "consented" : view?.status === "rejected" ? "declined" : view?.status);
  if (status === "consented") return <Notice tone="success" title="Thank you — consent recorded">{child} can now start learning on Tech Drona. You can withdraw consent at any time.</Notice>;
  if (status === "declined") return <Notice title="You declined">We won&apos;t activate the account. {child} can still browse free content without an account.</Notice>;

  const items = view?.items ?? [];

  return (
    <div className="space-y-6">
      <p className="text-sm text-fg-secondary">
        {child} wants to use Tech Drona. Because they&apos;re under 18, we need a parent or guardian to agree first.
      </p>
      <section aria-labelledby="notice-h" className="space-y-3 rounded-lg border border-line bg-surface-subtle p-4">
        <h2 id="notice-h" className="font-display text-base font-semibold text-fg">
          Privacy notice for parents and guardians
          {view?.notice_version ? <span className="ml-2 text-xs font-normal text-fg-muted">version {view.notice_version}</span> : null}
        </h2>
        {items.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-fg-secondary" aria-label="What you are agreeing to">
            {items.map((it) => (
              <li key={it.purpose}>
                {GUARDIAN_ITEM_LABELS[it.purpose] ?? PURPOSE_LABELS[it.purpose]?.label ?? it.purpose.replace(/_/g, " ")} {it.required ? "(required)" : "(optional)"}
              </li>
            ))}
          </ul>
        ) : null}
        {view?.unavailable_for_minors?.length ? (
          <p className="text-sm text-fg-secondary">Tracking for personalisation, marketing and account-sharing checks is never turned on for under-18 accounts.</p>
        ) : null}
        <p className="text-sm text-fg-secondary">
          It explains what data we collect, why, who sees it and how to withdraw.{" "}
          <a href="/legal/privacy" target="_blank" rel="noopener" className="text-fg-link underline">
            Read the full Privacy Notice (opens in a new tab)
          </a>
        </p>
      </section>

      <form onSubmit={(e) => decide("consent", e)} noValidate className="space-y-4">
        <FormAlert ref={alertRef} error={error} />
        <p className="text-sm text-fg-secondary">First, confirm it&apos;s you. We&apos;ll send a 6-digit code to {view?.contact_masked ?? "your phone or email"}.</p>
        <Button variant={sentTo ? "ghost" : "secondary"} loading={busy === "send"} disabled={resendIn > 0 || busy !== null} onClick={send}>
          {sentTo ? (resendIn > 0 ? `Resend code in ${formatCountdown(resendIn)}` : "Resend code") : "Send code"}
        </Button>
        {sentTo ? (
          <>
            <p role="status" className="text-sm text-fg-secondary">
              We sent a code to {sentTo}.
            </p>
            <FormField label="6-digit code" error={fieldErr} required>
              {(f) => <OtpInput {...f} value={code} onValueChange={setCode} />}
            </FormField>
            <div>
              <Checkbox
                label={`I am ${child}'s parent or legal guardian`}
                checked={declaration}
                onChange={(e) => {
                  setDeclaration(e.target.checked);
                  setDeclErr(undefined);
                }}
                aria-invalid={declErr ? true : undefined}
              />
              {declErr ? (
                <p role="alert" className="mt-1 text-xs font-medium text-danger-fg">
                  {declErr}
                </p>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-3">
              <Button type="submit" loading={busy === "consent"} disabled={busy !== null}>
                I agree
              </Button>
              <Button variant="secondary" loading={busy === "decline"} disabled={busy !== null} onClick={() => decide("decline")}>
                I don&apos;t agree
              </Button>
            </div>
          </>
        ) : null}
      </form>
    </div>
  );
}
