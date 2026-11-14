"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button, Checkbox, FormField } from "@/components/ui";
import { deviceName, type DevicesResponse, type OwnDevice } from "@/features/account/lib/types";
import { OtpInput, PasswordInput } from "@/features/auth/components/shared";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { useResource } from "@/lib/api/use-resource";

interface SentTo {
  sent_to?: string;
  expires_in_seconds?: number;
}

/**
 * Unblock re-verification (AUTH-21 / AUTH-22, unblock doc §6). Shown when SEC-01 offers the
 * `reverify` action: a reviewer lifted the restriction (`lift_pending`) or an L3 reached its
 * end. A code to a contact verified before the restriction ends it; the api then revokes all
 * sessions, so the student signs in again. The learner reviews their devices here: only the
 * ones ticked "keep" are sent, every other device is removed by the api (UNB §6 step 6).
 * "Text me a code" is offered only with a verified mobile (the api has no other number to use).
 */
export function ReverifyPanel() {
  const [channel, setChannel] = useState<"email" | "sms" | null>(null);
  const [sent, setSent] = useState<SentTo | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The api asks for a new password when the case decision requires one (422
  // `password_reset_required` on `new_password`); the field appears only then.
  const [needsPassword, setNeedsPassword] = useState(false);
  const [password, setPassword] = useState("");
  const NO_REDIRECT = { handle: { restriction: false } } as const;
  const me = useResource<{ user?: { mobile_verified?: boolean } }>("me", NO_REDIRECT);
  const devices = useResource<DevicesResponse>("me/devices", NO_REDIRECT);
  const canSms = me.data?.user?.mobile_verified === true;
  const [keep, setKeep] = useState<Record<string, boolean>>({});
  // This device is kept by default; any other device has to be ticked by the learner.
  useEffect(() => {
    if (devices.data) setKeep((k) => (Object.keys(k).length ? k : Object.fromEntries(devices.data!.data.map((d: OwnDevice) => [d.user_device_id, !!d.is_current]))));
  }, [devices.data]);

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
    if (needsPassword && password.length < 12) {
      setError("Choose a new password of at least 12 characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const deviceList = (devices.data?.data ?? []).map((d) => ({ user_device_id: d.user_device_id, keep: !!keep[d.user_device_id] }));
      const body = {
        otp_code: code,
        ...(deviceList.length ? { devices: deviceList } : {}),
        ...(needsPassword ? { new_password: password } : {}),
      };
      const r = await api.post("auth/reverify/complete", body, { idempotencyKey: true, handle: { restriction: false, auth: false } });
      if (r.kind === "ok") window.location.assign("/login?reason=reverified");
    } catch (err) {
      const errs = isApiError(err) ? (err.problem?.errors as { field?: string; code?: string; message?: string }[] | undefined) : undefined;
      const pw = errs?.find((x) => x.field === "new_password");
      if (pw) {
        setNeedsPassword(true);
        setError(pw.code === "password_reset_required" ? "Your account needs a new password before access returns. Choose one below." : (pw.message ?? "Choose a different password."));
        return;
      }
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
          {canSms ? (
            <Button variant="secondary" onClick={() => void send("sms")} disabled={busy}>
              Text me a code
            </Button>
          ) : null}
        </div>
      ) : (
        <form className="mt-4 space-y-3" onSubmit={(e) => void complete(e)} noValidate>
          <p role="status" className="text-sm text-fg-secondary">
            Code sent{sent.sent_to ? ` to ${sent.sent_to}` : ""}.
          </p>
          <FormField label="6-digit code" required>
            {(f) => <OtpInput {...f} value={code} onValueChange={setCode} />}
          </FormField>
          {devices.data && devices.data.data.length ? (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-fg">Review your devices</legend>
              <p className="text-sm text-fg-secondary">Tick the devices that are yours. Unticked devices are signed out and removed; you can add them again by signing in on them.</p>
              {devices.data.data.map((d) => (
                <Checkbox
                  key={d.user_device_id}
                  label={`${deviceName(d)}${d.is_current ? " (this device)" : ""}`}
                  checked={!!keep[d.user_device_id]}
                  onChange={(e) => setKeep((k) => ({ ...k, [d.user_device_id]: e.target.checked }))}
                />
              ))}
            </fieldset>
          ) : null}
          {needsPassword ? (
            <FormField label="New password" required hint="At least 12 characters.">
              {(f) => <PasswordInput {...f} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
            </FormField>
          ) : null}
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
