"use client";

import Link from "next/link";
import { ServiceNotIntegrated } from "@/components/shell/Integrations";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, FormField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { formatCountdown, retryAfterSeconds, toFormError, type FormErrorInfo } from "../lib/errors";
import { formatDate, formatRelative } from "../lib/format";
import { routeForLoginResult, routeForSessionCap } from "../lib/login-flow";
import { readPendingLogin } from "../lib/pending-login";
import type { CapDevice, DeviceChannel, DeviceVerifyBody, LoginResponse, OtpSentResponse } from "../lib/types";
import { FormAlert, Notice, OtpInput, useCountdown } from "./shared";

const RESEND_SECONDS = 45;

interface DeviceCapState {
  devices: CapDevice[];
  maxTrusted: number | null;
  used: number | null;
  max: number | null;
  nextAt: string | null;
}

function parseDeviceCap(err: ApiError): DeviceCapState {
  const p = err.problem ?? ({} as Record<string, unknown>);
  const raw = Array.isArray(p.devices) ? (p.devices as unknown[]) : [];
  const devices = raw.filter((d): d is CapDevice => !!d && typeof d === "object" && typeof (d as CapDevice).user_device_id === "string");
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  return {
    devices: devices.map((d) => ({ ...d, label: (typeof d.user_label === "string" && d.user_label) || (typeof d.label === "string" && d.label) || "Unnamed device" })),
    maxTrusted: num(p.max_trusted),
    used: num(p.replacements_used),
    max: num(p.replacements_max),
    nextAt: typeof p.next_replacement_at === "string" ? p.next_replacement_at : null,
  };
}

/** PUB-012 "Confirm this new device" · AUTH-12 send, AUTH-13 verify (+ device-cap chooser). */
export function DeviceVerificationForm() {
  const router = useRouter();
  const [loaded, setLoaded] = useState(false);
  const [next, setNext] = useState<string | undefined>();
  const [channels, setChannels] = useState<DeviceChannel[]>([]);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState<string | null>(null);
  const [resendIn, setResendIn] = useCountdown();
  const [cap, setCap] = useState<DeviceCapState | null>(null);
  const [quotaExhausted, setQuotaExhausted] = useState<string | null | undefined>(undefined);
  const [removeId, setRemoveId] = useState<string>("");
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = readPendingLogin();
    setNext(p?.next);
    setChannels(p?.channels ?? []);
    setLoaded(true);
  }, []);

  const fail = (err: unknown) => {
    if (err instanceof ApiError && (err.code === "unauthenticated" || err.code === "session_expired")) {
      setError({ title: "Your sign-in timed out", detail: "Please sign in again.", requestId: err.requestId, code: err.code });
    } else if (err instanceof ApiError && err.code === "otp_invalid") {
      const left = err.problem?.attempts_remaining;
      setError({ title: "That code didn't work", detail: typeof left === "number" ? `Check the code and try again. ${left} attempts left.` : "Check the code and try again.", requestId: err.requestId, code: err.code });
    } else if (err instanceof ApiError && err.code === "otp_expired") {
      setError({ title: "That code has expired", detail: "Send a new code and try again.", requestId: err.requestId, code: err.code });
    } else if (err instanceof ApiError && (err.code === "otp_send_limited" || err.code === "otp_attempts_exceeded")) {
      const s = retryAfterSeconds(err);
      setError({ title: err.title, detail: s ? `Try again in ${formatCountdown(s)}.` : err.detail, requestId: err.requestId, code: err.code });
    } else {
      setError(toFormError(err));
    }
    setTimeout(() => alertRef.current?.focus(), 0);
  };

  const send = async (channel: string) => {
    setSending(channel);
    setError(null);
    try {
      const res = await api.post<OtpSentResponse>("auth/device-verification/send", { channel }, { idempotencyKey: true, handle: { auth: false, sessionChoice: false, restriction: false } });
      const masked = res.kind === "ok" ? res.data?.sent_to : undefined;
      setSentTo(masked ?? channels.find((c) => c.channel === channel)?.destination_masked ?? "your registered contact");
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      fail(err);
    } finally {
      setSending(null);
    }
  };

  const verify = async (e: FormEvent) => {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) {
      setFieldErr("Enter the 6-digit code.");
      return;
    }
    if (cap && !removeId) {
      setFieldErr(undefined);
      setError({ title: "Choose a device to remove", requestId: null, code: "client" });
      return;
    }
    setFieldErr(undefined);
    setBusy(true);
    setError(null);
    try {
      const body: DeviceVerifyBody = { code, method: "otp" };
      if (cap && removeId) body.remove_user_device_id = removeId;
      const res = await api.post<LoginResponse>("auth/device-verification/verify", body, { idempotencyKey: true, handle: { auth: false, sessionChoice: false, restriction: false } });
      setCode("");
      if (res.kind === "ok") router.push(routeForLoginResult(res.data, next));
    } catch (err) {
      if (err instanceof ApiError && err.code === "session_cap_reached") {
        router.push(routeForSessionCap(err, next));
        return;
      }
      if (err instanceof ApiError && err.code === "device_cap_reached") {
        setCap(parseDeviceCap(err));
        return;
      }
      if (err instanceof ApiError && err.code === "device_replacement_quota_exhausted") {
        const at = err.problem?.next_replacement_at;
        setQuotaExhausted(typeof at === "string" ? at : null);
        return;
      }
      setCode("");
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) return <p aria-busy="true" className="text-sm text-fg-muted">Loading…</p>;

  if (quotaExhausted !== undefined) {
    return (
      <Notice tone="warning" title="You've changed devices twice in 30 days">
        <p>
          Your next change is available{quotaExhausted ? ` on ${formatDate(quotaExhausted)}` : " later"}, or{" "}
          <Link href="/help" className="text-fg-link underline">
            contact support
          </Link>{" "}
          and we&apos;ll help.
        </p>
      </Notice>
    );
  }

  return (
    <form onSubmit={verify} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error}>
        {error?.code === "unauthenticated" || error?.code === "session_expired" ? (
          <p className="mt-2">
            <Link href="/login" className="text-fg-link underline">
              Sign in again
            </Link>
          </p>
        ) : null}
      </FormAlert>

      {cap ? (
        <fieldset className="space-y-3">
          <legend className="font-display text-lg font-semibold text-fg">You have {cap.maxTrusted ?? cap.devices.length} registered devices</legend>
          <p className="text-sm text-fg-secondary">
            Remove one to continue on this device. Removing a device counts as a replacement
            {cap.used !== null && cap.max !== null ? `: ${cap.used} of ${cap.max} used in the last 30 days` : ""}
            {cap.nextAt ? `; the next one frees up on ${formatDate(cap.nextAt)}` : ""}.
          </p>
          {cap.devices.map((d) => (
            <label key={d.user_device_id} className="flex min-h-[56px] cursor-pointer items-start gap-3 rounded-lg border border-line p-3 has-[:checked]:border-brand">
              <input type="radio" name="remove_device" value={d.user_device_id} checked={removeId === d.user_device_id} onChange={() => setRemoveId(d.user_device_id)} className="mt-1 h-4 w-4 accent-[var(--td-brand)]" />
              <span className="text-sm">
                <span className="block font-medium text-fg">{d.label}</span>
                <span className="block text-fg-muted">
                  last used {formatRelative(d.last_used_at)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : (
        <>
          {channels.length === 0 ? (
            <Notice tone="warning" title="We couldn't find your sign-in">
              <p>
                This step has expired.{" "}
                <Link href="/login" className="text-fg-link underline">
                  Sign in again
                </Link>
                .
              </p>
            </Notice>
          ) : (
            <div className="space-y-2">
              <ServiceNotIntegrated service="email" text="Sign-in codes are sent by email, which isn't connected yet, so the code won't reach your inbox. Ask the Tech Drona admin for the code, or set up an authenticator app in your security settings." />
              {sentTo ? (
                <p role="status" className="text-sm text-fg-secondary">
                  We sent a 6-digit code to {sentTo}. Enter it to add this device to your devices. Until then you can browse free content and your account settings.
                </p>
              ) : (
                <p className="text-sm text-fg-secondary">Choose where to send a 6-digit code.</p>
              )}
              <div className="flex flex-wrap gap-2">
                {channels.map((c) => (
                  <Button key={c.channel} variant={sentTo ? "ghost" : "secondary"} size="sm" loading={sending === c.channel} disabled={resendIn > 0 || sending !== null} onClick={() => send(c.channel)} className="!h-auto min-h-touch max-w-full !whitespace-normal break-words !py-2 text-left">
                    {sentTo ? "Resend" : "Send code"} by {c.channel === "sms" ? "SMS" : c.channel} to {c.destination_masked}
                  </Button>
                ))}
              </div>
              {resendIn > 0 ? <p className="text-xs text-fg-muted">Resend in {formatCountdown(resendIn)}</p> : null}
            </div>
          )}
        </>
      )}

      {channels.length > 0 || cap ? (
        <FormField label="6-digit code" error={fieldErr} required>
          {(f) => <OtpInput {...f} value={code} onValueChange={setCode} />}
        </FormField>
      ) : null}

      {channels.length > 0 || cap ? (
        <div className="flex flex-wrap gap-3">
          <Button type="submit" loading={busy}>
            {cap ? "Remove and continue" : "Confirm"}
          </Button>
          <Button variant="ghost" onClick={() => router.push("/")} className="!h-auto min-h-touch max-w-full !whitespace-normal !py-2 text-left">
            {cap ? "Cancel" : "Skip for now — browse free content only"}
          </Button>
        </div>
      ) : null}
    </form>
  );
}
