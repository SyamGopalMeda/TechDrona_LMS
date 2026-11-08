"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, FormField, Input } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { toFormError, type FormErrorInfo } from "../lib/errors";
import { routeForLoginResult, routeForSessionCap } from "../lib/login-flow";
import { readPendingLogin, writePendingLogin } from "../lib/pending-login";
import type { LoginResponse } from "../lib/types";
import { FormAlert, OtpInput } from "./shared";

type Method = "totp" | "recovery_code";

/** PUB-012 MFA step · AUTH-11 (TOTP and recovery code; passkey/SMS not in this build). */
export function MfaForm() {
  const router = useRouter();
  const [next, setNext] = useState<string | undefined>();
  const [methods, setMethods] = useState<string[] | null>(null);
  const [method, setMethod] = useState<Method>("totp");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = readPendingLogin();
    setNext(p?.next);
    const m = p?.mfaMethods ?? ["totp", "recovery_code"];
    setMethods(m);
    if (!m.includes("totp") && m.includes("recovery_code")) setMethod("recovery_code");
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const value = code.trim();
    if (method === "totp" && !/^\d{6}$/.test(value)) {
      setFieldErr("Enter the 6-digit code from your authenticator app.");
      return;
    }
    if (method === "recovery_code" && value.length < 6) {
      setFieldErr("Enter one of your recovery codes.");
      return;
    }
    setFieldErr(undefined);
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<LoginResponse>("auth/mfa/verify", { method, code: value }, { idempotencyKey: true, handle: { auth: false, sessionChoice: false, restriction: false, stepUp: false } });
      setCode("");
      if (res.kind === "ok") router.push(routeForLoginResult(res.data, next));
    } catch (err) {
      setCode("");
      if (err instanceof ApiError && err.code === "session_cap_reached") {
        router.push(routeForSessionCap(err, next));
        return;
      }
      if (err instanceof ApiError && err.code === "device_cap_reached") {
        // MFA passed but this new device would exceed the trusted-device cap: the api leaves the
        // sign-in pending device verification, where the student/staff member picks a device to
        // remove (PUB-012 chooser). Without this the MFA page was a dead end.
        writePendingLogin({ next, channels: [{ channel: "email", destination_masked: "your email" }] });
        router.push("/login/verify-device");
        return;
      }
      if (err instanceof ApiError && (err.code === "unauthenticated" || err.code === "session_expired")) {
        setError({ title: "Your sign-in timed out", detail: "Please sign in again.", requestId: err.requestId, code: err.code });
      } else if (err instanceof ApiError && err.code === "otp_invalid") {
        setError({ title: "That code didn't work. Check the time on your phone and try again.", requestId: err.requestId, code: err.code });
      } else {
        setError(toFormError(err));
      }
      setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  };

  if (methods === null) return <p aria-busy="true" className="text-sm text-fg-muted">Loading…</p>;
  const canRecovery = methods.includes("recovery_code");
  const hasTotp = methods.includes("totp");

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error}>
        {error?.code === "unauthenticated" || error?.code === "session_expired" ? (
          <p className="mt-2">
            <Link href="/login" className="text-fg-link underline">
              Sign in again
            </Link>
          </p>
        ) : null}
      </FormAlert>
      {!hasTotp && !canRecovery ? (
        <p className="text-sm text-fg-secondary">
          Your account uses {methods.join(", ")} for two-step verification, which this version of the site does not support yet. Please contact support.
        </p>
      ) : (
        <>
          <FormField
            label={method === "totp" ? "Authenticator code" : "Recovery code"}
            hint={method === "totp" ? "Enter the 6-digit code from your authenticator app." : "Each recovery code works once."}
            error={fieldErr}
            required
          >
            {(f) =>
              method === "totp" ? (
                <OtpInput {...f} value={code} onValueChange={setCode} autoFocus />
              ) : (
                <Input {...f} autoComplete="off" spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} />
              )
            }
          </FormField>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" loading={busy}>
              Verify
            </Button>
            {canRecovery && hasTotp ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setMethod((m) => (m === "totp" ? "recovery_code" : "totp"));
                  setCode("");
                  setFieldErr(undefined);
                }}
              >
                {method === "totp" ? "Use a recovery code instead" : "Use authenticator app instead"}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </form>
  );
}
