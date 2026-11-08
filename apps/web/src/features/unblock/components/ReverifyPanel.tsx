"use client";

import { useState, type FormEvent } from "react";
import { Button, FormField } from "@/components/ui";
import { OtpInput } from "@/features/auth/components/shared";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";

interface SentTo {
  sent_to?: string;
  expires_in_seconds?: number;
}

/**
 * Unblock re-verification (AUTH-21 / AUTH-22, unblock doc §6). Shown when SEC-01 offers the
 * `reverify` action: a reviewer lifted the restriction (`lift_pending`) or an L3 reached its
 * end. A code to a contact verified before the restriction ends it; the api then revokes all
 * sessions, so the student signs in again. Unconfirmed devices are removed server-side.
 */
export function ReverifyPanel() {
  const [channel, setChannel] = useState<"email" | "sms" | null>(null);
  const [sent, setSent] = useState<SentTo | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (ch: "email" | "sms") => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<SentTo>("auth/reverify/start", { channel: ch }, { handle: { restriction: false } });
      if (r.kind === "ok") {
        setChannel(ch);
        setSent(r.data ?? {});
      }
    } catch (e) {
      setError(isApiError(e) ? (e.detail ?? e.title) : "We couldn't send a code. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const complete = async (e: FormEvent) => {
    e.preventDefault();
    if (code.length < 4) {
      setError("Enter the code we sent you.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.post("auth/reverify/complete", { otp_code: code }, { idempotencyKey: true, handle: { restriction: false, auth: false } });
      if (r.kind === "ok") window.location.assign("/login?reason=reverified");
    } catch (err) {
      setError(isApiError(err) ? (err.detail ?? err.title) : "We couldn't confirm the code. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="reverify-h" className="rounded-xl border border-success-border bg-success-subtle p-5">
      <h2 id="reverify-h" className="font-display text-lg font-semibold text-fg">
        Confirm it&apos;s you to get your access back
      </h2>
      <p className="mt-1 text-sm text-fg-secondary">
        We&apos;ll send a one-time code to a contact you verified before the pause. After you confirm, every device is signed out and you sign in again with full access.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
      {!sent ? (
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <Button onClick={() => void send("email")} loading={busy && channel === null}>
            Email me a code
          </Button>
          <Button variant="secondary" onClick={() => void send("sms")} disabled={busy}>
            Text me a code
          </Button>
        </div>
      ) : (
        <form className="mt-4 space-y-3" onSubmit={(e) => void complete(e)} noValidate>
          <p role="status" className="text-sm text-fg-secondary">
            Code sent{sent.sent_to ? ` to ${sent.sent_to}` : ""}.
          </p>
          <FormField label="6-digit code" required>
            {(f) => <OtpInput {...f} value={code} onValueChange={setCode} />}
          </FormField>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button type="submit" loading={busy}>
              Confirm and restore access
            </Button>
            <Button type="button" variant="ghost" onClick={() => channel && void send(channel)} disabled={busy}>
              Send a new code
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
