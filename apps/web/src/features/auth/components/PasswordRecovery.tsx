"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { Button, FormField, Input } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatCountdown, problemFieldErrors, retryAfterSeconds, toFormError, type FormErrorInfo } from "../lib/errors";
import { PASSWORD_MIN_WITH_MFA, validatePassword } from "../lib/validation";
import { FormAlert, Notice, PasswordInput } from "./shared";

/** PUB-013 · AUTH-16. Always shows the same generic confirmation (no account enumeration). */
export function ForgotPasswordForm() {
  const [identifier, setIdentifier] = useState("");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!identifier.trim()) {
      setFieldErr("Enter the email or mobile number you signed up with.");
      return;
    }
    setFieldErr(undefined);
    setBusy(true);
    setError(null);
    try {
      await api.post("auth/password/forgot", { identifier: identifier.trim() }, { idempotencyKey: true, handle: { auth: false } });
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "throttled") {
        const s = retryAfterSeconds(err);
        setError({ title: "Too many requests", detail: s ? `Try again in ${formatCountdown(s)}.` : "Please wait a little and try again.", requestId: err.requestId, code: err.code });
      } else {
        setError(toFormError(err));
      }
      setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Notice tone="success" title="Check your email or phone">
        If an account matches {identifier.trim()}, we&apos;ve sent a link (by email) or a code (by SMS) to reset your password. It expires soon, so use it in the next few minutes.{" "}
        <Link href="/login" className="text-fg-link underline">
          Back to sign in
        </Link>
      </Notice>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error} />
      <FormField label="Email or mobile" error={fieldErr} required>
        {(f) => <Input {...f} name="identifier" autoComplete="username" value={identifier} onChange={(e) => setIdentifier(e.target.value)} />}
      </FormField>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" loading={busy}>
          Send reset instructions
        </Button>
        <Link href="/login" className="text-sm text-fg-link underline">
          Back to sign in
        </Link>
      </div>
    </form>
  );
}

/** PUB-013 · AUTH-17 reset with the link token. All sessions are revoked by the API. */
export function ResetPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fe, setFe] = useState<{ password?: string; confirm?: string }>({});
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const next: typeof fe = {};
    // 8 is the floor with MFA; the API applies the 15-character rule to accounts without MFA.
    const pw = validatePassword(password, PASSWORD_MIN_WITH_MFA);
    if (pw) next.password = pw;
    if (!next.password && confirm !== password) next.confirm = "The passwords don't match.";
    setFe(next);
    if (next.password || next.confirm) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("auth/password/reset", { token, new_password: password }, { idempotencyKey: true, handle: { auth: false, restriction: false, sessionChoice: false } });
      setDone(true);
    } catch (err) {
      const f = problemFieldErrors(err);
      if (f.new_password || f.password) setFe({ password: f.new_password ?? f.password });
      else if (err instanceof ApiError && (err.code === "not_found" || err.code === "validation_failed" || err.code === "invalid_state_transition")) {
        setError({ title: "This reset link has expired or was already used", detail: "Request a new link to reset your password.", requestId: err.requestId, code: "link_invalid" });
      } else setError(toFormError(err));
      setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setPassword("");
      setConfirm("");
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Notice tone="success" title="Your password has been changed">
        We&apos;ve signed you out on all devices.{" "}
        <Link href="/login" className="text-fg-link underline">
          Sign in with your new password
        </Link>
        .
      </Notice>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error}>
        {error?.code === "link_invalid" ? (
          <p className="mt-2">
            <Link href="/forgot-password" className="text-fg-link underline">
              Request a new link
            </Link>
          </p>
        ) : null}
      </FormAlert>
      <FormField label="New password" hint="15+ characters, or 8+ if you use 2-step verification. Avoid passwords you use elsewhere." error={fe.password} required>
        {(f) => <PasswordInput {...f} name="new_password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </FormField>
      <FormField label="Confirm new password" error={fe.confirm} required>
        {(f) => <PasswordInput {...f} name="confirm_password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
      </FormField>
      <Button type="submit" loading={busy}>
        Set new password
      </Button>
    </form>
  );
}
