"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { StepUpChallenge } from "@/lib/api/problem";
import { Button, Dialog, FormField, Input } from "@/components/ui";
import { ServiceNotIntegrated } from "@/components/shell/Integrations";

export interface StepUpRequest {
  challenge: StepUpChallenge;
  resolve: (ok: boolean) => void;
}

/** Methods this build can complete (passkey/WebAuthn is not built; the API does not offer it). */
export type StepUpMethod = "totp" | "email_otp" | "sms_otp" | "password";
const SUPPORTED: readonly StepUpMethod[] = ["totp", "email_otp", "sms_otp", "password"];

const METHOD_LABEL: Record<StepUpMethod, string> = {
  totp: "Authenticator app",
  email_otp: "Code by email",
  sms_otp: "Code by SMS",
  password: "Password",
};

interface OptionsOut {
  allowed_methods: string[];
  sent_to?: string;
}

function supportedOf(methods: readonly string[]): StepUpMethod[] {
  return SUPPORTED.filter((m) => methods.includes(m));
}

/** Plain-language message for a failed AUTH-19/AUTH-20 call. */
export function stepUpErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return "Something went wrong. Please try again.";
  if (err.problem?.reason === "code_already_used") {
    return "This code was already used. Wait for the next code in your authenticator app.";
  }
  switch (err.code) {
    case "otp_invalid":
      return "That code is not correct. Check it and try again.";
    case "otp_expired":
      return "That code has expired. Send a new code.";
    case "otp_attempts_exceeded":
      return "Too many incorrect codes. Please wait a few minutes and try again.";
    case "otp_send_limited":
      return err.retryAfter
        ? `Too many codes requested. Try again in ${Math.ceil(err.retryAfter / 60)} min.`
        : "Too many codes requested. Please wait before asking for another.";
    case "invalid_credentials":
      return "That password is not correct.";
    default:
      return err.problem?.detail ?? err.title;
  }
}

/**
 * Step-up confirmation (api-specification §1.6; AUTH-19/AUTH-20). Opened by the API client
 * on `401 step_up_required`; resolving `true` makes the client retry the original request
 * with the same Idempotency-Key.
 *
 * On open, AUTH-19 (`POST /auth/step-up/options`, no send) returns the methods this account
 * can actually use. TOTP: `{method:"totp", code}`. Students (SEC-09): email/SMS OTP —
 * AUTH-19 `{send_otp_via}` sends the code, then AUTH-20 `{method:"email_otp"|"sms_otp", code}`.
 * Password is offered only when the API lists it (a student with no other method).
 * Passkey (WebAuthn) is not built and is not offered by the API.
 */
export function StepUpDialog({ request, onDone }: { request: StepUpRequest | null; onDone: () => void }) {
  const [methods, setMethods] = useState<StepUpMethod[]>([]);
  const [method, setMethod] = useState<StepUpMethod | null>(null);
  const [loadingMethods, setLoadingMethods] = useState(false);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!request) return;
    let cancelled = false;
    const fallback = supportedOf(request.challenge.allowed_methods);
    setLoadingMethods(true);
    api
      .post<OptionsOut>("auth/step-up/options", {}, { handle: { stepUp: false } })
      .then((res) => {
        if (cancelled) return;
        const got = res.kind === "ok" ? supportedOf(res.data.allowed_methods ?? []) : fallback;
        setMethods(got);
        setMethod(got[0] ?? null);
      })
      .catch(() => {
        if (cancelled) return;
        setMethods(fallback);
        setMethod(fallback[0] ?? null);
      })
      .finally(() => {
        if (!cancelled) setLoadingMethods(false);
      });
    return () => {
      cancelled = true;
    };
  }, [request]);

  const reset = () => {
    setCode("");
    setPassword("");
    setSentTo(null);
    setError(null);
    setRequestId(null);
  };

  const finish = (ok: boolean) => {
    request?.resolve(ok);
    reset();
    setMethods([]);
    setMethod(null);
    onDone();
  };

  const choose = (m: StepUpMethod) => {
    setMethod(m);
    reset();
  };

  const showError = (err: unknown) => {
    setError(stepUpErrorMessage(err));
    setRequestId(err instanceof ApiError ? err.requestId : null);
  };

  const sendCode = async () => {
    if (method !== "email_otp" && method !== "sms_otp") return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<OptionsOut>(
        "auth/step-up/options",
        { send_otp_via: method === "email_otp" ? "email" : "sms" },
        { handle: { stepUp: false } },
      );
      setSentTo(res.kind === "ok" ? (res.data.sent_to ?? "your contact") : "your contact");
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!method) return;
    let body: Record<string, string>;
    if (method === "password") {
      if (!password) {
        setError("Enter your password.");
        return;
      }
      body = { method, password };
    } else {
      if (!/^\d{6}$/.test(code)) {
        setError(method === "totp" ? "Enter the 6-digit code from your authenticator app." : "Enter the 6-digit code we sent you.");
        return;
      }
      body = { method, code };
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("auth/step-up", body, { handle: { stepUp: false } });
      finish(true);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };

  const isOtp = method === "email_otp" || method === "sms_otp";

  return (
    <Dialog
      open={request !== null}
      onClose={() => finish(false)}
      dismissible={!busy}
      title="Please confirm it's you"
      description="This action needs a fresh confirmation."
    >
      {loadingMethods ? (
        <p className="text-sm text-fg-secondary" role="status">
          Loading confirmation options…
        </p>
      ) : method === null ? (
        <div className="space-y-4">
          <p className="text-sm text-fg-secondary">
            No confirmation method is available for your account. Set up an authenticator app in your security settings, or contact support.
          </p>
          <div className="flex justify-end">
            <Button variant="secondary" onClick={() => finish(false)}>
              Close
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          {methods.length > 1 ? (
            <fieldset className="space-y-1">
              <legend className="text-sm font-medium text-fg">Confirm with</legend>
              <div className="flex flex-wrap gap-3">
                {methods.map((m) => (
                  <label key={m} className="flex items-center gap-1.5 text-sm text-fg">
                    <input type="radio" name="step-up-method" value={m} checked={method === m} onChange={() => choose(m)} disabled={busy} />
                    {METHOD_LABEL[m]}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}

          {method === "password" ? (
            <FormField label="Password" error={error ?? undefined} required>
              {(field) => (
                <Input {...field} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              )}
            </FormField>
          ) : isOtp && sentTo === null ? (
            <div className="space-y-2">
              <ServiceNotIntegrated service={method === "email_otp" ? "email" : "sms"} />
              <p className="text-sm text-fg-secondary">
                We will send a 6-digit code {method === "email_otp" ? "to your email address" : "by SMS to your mobile number"}.
              </p>
              {error ? (
                <p className="text-sm text-danger-fg" role="alert">
                  {error}
                </p>
              ) : null}
              <Button onClick={() => void sendCode()} loading={busy}>
                Send code
              </Button>
            </div>
          ) : (
            <FormField
              label={method === "totp" ? "Authenticator code" : "Confirmation code"}
              hint={method === "totp" ? "6 digits from your authenticator app" : `6 digits sent to ${sentTo ?? "you"}`}
              error={error ?? undefined}
              required
            >
              {(field) => (
                <Input
                  {...field}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />
              )}
            </FormField>
          )}

          {isOtp && sentTo !== null ? (
            <button type="button" className="text-sm text-brand underline" onClick={() => void sendCode()} disabled={busy}>
              Send a new code
            </button>
          ) : null}
          {requestId ? <p className="text-xs text-fg-muted">Reference: {requestId}</p> : null}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={() => finish(false)} disabled={busy}>
              Cancel
            </Button>
            {isOtp && sentTo === null ? null : (
              <Button type="submit" loading={busy}>
                Confirm
              </Button>
            )}
          </div>
        </form>
      )}
    </Dialog>
  );
}
