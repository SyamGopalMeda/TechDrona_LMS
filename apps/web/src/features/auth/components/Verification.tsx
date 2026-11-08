"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { Button, FormField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatCountdown, retryAfterSeconds, toFormError, type FormErrorInfo } from "../lib/errors";
import type { OtpSentResponse } from "../lib/types";
import { FormAlert, Notice, OtpInput, useCountdown } from "./shared";

/**
 * PUB-014 · AUTH-02. The link token is consumed only after an explicit click, so mail
 * scanners that open links do not burn it.
 */
export function VerifyEmail({ token }: { token: string }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "invalid">("idle");
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [resent, setResent] = useState(false);
  const [resending, setResending] = useState(false);

  const verify = async () => {
    setState("busy");
    setError(null);
    try {
      await api.post("auth/verify/email", { token }, { handle: { auth: false, restriction: false, sessionChoice: false } });
      setState("done");
    } catch (err) {
      if (err instanceof ApiError && (err.code === "not_found" || err.code === "validation_failed" || err.code === "invalid_state_transition" || err.status === 410)) {
        setState("invalid");
        setError({ title: "This link has expired or was already used", detail: "If your email isn't verified yet, send a new link.", requestId: err.requestId, code: err.code });
      } else {
        setState("idle");
        setError(toFormError(err));
      }
    }
  };

  const resend = async () => {
    setResending(true);
    try {
      await api.post("auth/verify/email/resend", undefined, { idempotencyKey: true });
      setResent(true);
    } catch (err) {
      setError(toFormError(err));
    } finally {
      setResending(false);
    }
  };

  if (state === "done") {
    return (
      <Notice tone="success" title="Your email is verified">
        Thanks — you can now buy plans and take timed tests.{" "}
        <Link href="/app" className="text-fg-link underline">
          Go to my dashboard
        </Link>
      </Notice>
    );
  }

  return (
    <div className="space-y-4">
      <FormAlert error={error}>
        {state === "invalid" ? (
          <p className="mt-2 text-fg-secondary">
            {resent ? (
              <span role="status">We&apos;ve sent a new link if your email still needs verifying.</span>
            ) : (
              <Button variant="secondary" size="sm" loading={resending} onClick={resend}>
                Send a new link
              </Button>
            )}{" "}
            You need to be signed in to send a new link.
          </p>
        ) : null}
      </FormAlert>
      {state !== "invalid" ? (
        <>
          <p className="text-sm text-fg-secondary">Confirm that this email address belongs to you.</p>
          <Button onClick={verify} loading={state === "busy"}>
            Verify my email
          </Button>
        </>
      ) : null}
    </div>
  );
}

/** PUB-014 · AUTH-04 send + AUTH-05 verify (signed-in user). */
export function VerifyMobile() {
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState<"send" | "verify" | null>(null);
  const [resendIn, setResendIn] = useCountdown();
  const [done, setDone] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const fail = (err: unknown) => {
    if (err instanceof ApiError && err.code === "otp_invalid") {
      const left = err.problem?.attempts_remaining;
      setError({ title: "That code didn't work", detail: typeof left === "number" ? `${left} attempts left.` : "Check the code and try again.", requestId: err.requestId, code: err.code });
    } else if (err instanceof ApiError && err.code === "otp_expired") {
      setError({ title: "That code has expired", detail: "Send a new code and try again.", requestId: err.requestId, code: err.code });
    } else if (err instanceof ApiError && (err.code === "otp_send_limited" || err.code === "otp_attempts_exceeded")) {
      const s = retryAfterSeconds(err);
      setError({ title: err.title, detail: s ? `Try again in ${formatCountdown(s)}.` : err.detail, requestId: err.requestId, code: err.code });
    } else setError(toFormError(err));
    setTimeout(() => alertRef.current?.focus(), 0);
  };

  const send = async () => {
    setBusy("send");
    setError(null);
    try {
      const res = await api.post<OtpSentResponse>("auth/verify/mobile/send-otp", {}, { idempotencyKey: true });
      setSentTo((res.kind === "ok" && res.data?.sent_to) || "your mobile");
      setResendIn(45);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  };

  const verify = async (e: FormEvent) => {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) {
      setFieldErr("Enter the 6-digit code.");
      return;
    }
    setFieldErr(undefined);
    setBusy("verify");
    setError(null);
    try {
      await api.post("auth/verify/mobile", { code }, { idempotencyKey: true });
      setDone(true);
    } catch (err) {
      fail(err);
    } finally {
      setCode("");
      setBusy(null);
    }
  };

  if (done) {
    return (
      <Notice tone="success" title="Your mobile number is verified">
        <Link href="/app" className="text-fg-link underline">
          Go to my dashboard
        </Link>
      </Notice>
    );
  }

  return (
    <form onSubmit={verify} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error} />
      {sentTo ? (
        <p role="status" className="text-sm text-fg-secondary">
          We sent a 6-digit code to {sentTo}.
        </p>
      ) : (
        <p className="text-sm text-fg-secondary">We&apos;ll send a 6-digit code by SMS to the mobile number on your account.</p>
      )}
      <Button variant={sentTo ? "ghost" : "primary"} loading={busy === "send"} disabled={resendIn > 0 || busy !== null} onClick={send}>
        {sentTo ? (resendIn > 0 ? `Resend code in ${formatCountdown(resendIn)}` : "Resend code") : "Send code"}
      </Button>
      {sentTo ? (
        <>
          <FormField label="6-digit code" error={fieldErr} required>
            {(f) => <OtpInput {...f} value={code} onValueChange={setCode} />}
          </FormField>
          <Button type="submit" loading={busy === "verify"}>
            Verify
          </Button>
        </>
      ) : null}
    </form>
  );
}
