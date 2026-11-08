"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, FormField, Input } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatCountdown, retryAfterSeconds, toFormError, type FormErrorInfo } from "../lib/errors";
import { routeForLoginResult, routeForSessionCap } from "../lib/login-flow";
import type { LoginResponse } from "../lib/types";
import { FormAlert, PasswordInput, useCountdown } from "./shared";

const COPY = {
  invalid: "That email/mobile and password don't match. Check them and try again.",
};

/** PUB-012 · AUTH-06 password login (passkey and Google sign-in are not in this build). */
export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fieldErr, setFieldErr] = useState<{ identifier?: string; password?: string }>({});
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [protectUrl, setProtectUrl] = useState<string | null>(null);
  const [throttle, setThrottle] = useCountdown();
  const [throttled, setThrottled] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);
  const idPrefix = useId();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const fe: typeof fieldErr = {};
    if (!identifier.trim()) fe.identifier = "Enter your email or mobile number.";
    if (!password) fe.password = "Enter your password.";
    setFieldErr(fe);
    if (fe.identifier || fe.password) return;

    setBusy(true);
    setError(null);
    setProtectUrl(null);
    setThrottled(false);
    try {
      const res = await api.post<LoginResponse>(
        "auth/login",
        { identifier: identifier.trim(), password, remember_device: remember },
        { idempotencyKey: true, handle: { auth: false, restriction: false, sessionChoice: false, stepUp: false } },
      );
      if (res.kind !== "ok") return;
      setPassword("");
      router.push(routeForLoginResult(res.data, next));
    } catch (err) {
      setPassword("");
      if (err instanceof ApiError && err.code === "session_cap_reached") {
        router.push(routeForSessionCap(err, next));
        return;
      }
      if (err instanceof ApiError && err.code === "invalid_credentials") {
        setError({ title: COPY.invalid, requestId: err.requestId, code: err.code });
      } else if (err instanceof ApiError && err.code === "throttled") {
        setThrottled(true);
        setThrottle(retryAfterSeconds(err) ?? 0);
        setError({ title: "Too many attempts", requestId: err.requestId, code: err.code });
      } else if (err instanceof ApiError && err.code === "account_protect_locked") {
        // The API sends recovery_url "/auth/recover", which has no page in this app yet; recovery is the reset-password flow.
        const raw = err.problem?.recovery_url;
        const url = typeof raw === "string" && raw.startsWith("/") && !raw.startsWith("/auth/") ? raw : "/forgot-password";
        setProtectUrl(url);
        setError({
          title: "We've secured your account",
          detail: "We noticed sign-in activity that may not have been you, so we've signed out all devices to protect your account. To continue, verify with a code and choose a new password.",
          requestId: err.requestId,
          code: err.code,
        });
      } else {
        setError(toFormError(err));
      }
      setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-describedby={error ? `${idPrefix}-alert` : undefined}>
      <div id={`${idPrefix}-alert`}>
        <FormAlert ref={alertRef} error={error}>
          {throttled ? (
            <p className="mt-1 text-fg-secondary">
              {throttle > 0 ? <>Try again in <span aria-live="off">{formatCountdown(throttle)}</span>, or </> : "Wait a little before trying again, or "}
              <Link href="/forgot-password" className="text-fg-link underline">
                reset your password
              </Link>
              .
            </p>
          ) : null}
          {protectUrl ? (
            <p className="mt-2">
              <a href={protectUrl} className="font-medium text-fg-link underline">
                Secure my account
              </a>
            </p>
          ) : null}
        </FormAlert>
      </div>
      <FormField label="Email or mobile" error={fieldErr.identifier} required>
        {(f) => (
          <Input {...f} name="identifier" autoComplete="username" inputMode="email" value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
        )}
      </FormField>
      <FormField label="Password" error={fieldErr.password} required>
        {(f) => <PasswordInput {...f} name="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </FormField>
      <Checkbox
        label="Remember this device (30 days)"
        description="Only on your own trusted device."
        checked={remember}
        onChange={(e) => setRemember(e.target.checked)}
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button type="submit" loading={busy} disabled={throttle > 0}>
          Sign in
        </Button>
        <Link href="/forgot-password" className="text-sm text-fg-link underline">
          Forgot password?
        </Link>
      </div>
      <p className="text-sm text-fg-muted">
        New to Tech Drona?{" "}
        <Link href={next ? `/signup?next=${encodeURIComponent(next)}` : "/signup"} className="text-fg-link underline">
          Create an account
        </Link>
      </p>
    </form>
  );
}
