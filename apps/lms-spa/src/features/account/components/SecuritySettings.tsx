"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, Checkbox, Dialog, ErrorState, FormField, LoadingBlock, StatusBadge, useToast, buttonClasses } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { FormAlert, Notice, OtpInput } from "@/features/auth/components/shared";
import { toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import { formatDate } from "@/features/auth/lib/format";
import { useSimpleAuth } from "@/components/shell/Integrations";
import type { MfaFactor, TotpEnrolment } from "../lib/types";
import { useResource } from "../lib/use-resource";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { LoginHistoryCard } from "./SecurityActivity";

/**
 * STU-021 Security: password (AUTH-18), MFA factors (ME-07/08/09/12), recovery codes (ME-13).
 * Simple authentication (owner 2026-11-12): password + sign-in history only, no 2-step section.
 */
export function SecuritySettings() {
  const simple = useSimpleAuth();
  return (
    <div className="space-y-6">
      <ChangePasswordCard />
      {simple ? null : <MfaCard />}
      <LoginHistoryCard />
    </div>
  );
}

/* ------------------------------------------------------------ Password */

export function ChangePasswordCard() {
  const toast = useToast();
  return (
    <Card title="Password">
      <ChangePasswordForm
        onChanged={(signedOutOthers) =>
          toast.show({ tone: "success", title: "Password changed", description: signedOutOthers ? "Your other sessions were signed out." : undefined })
        }
      />
    </Card>
  );
}

/* ------------------------------------------------------------ MFA */

function secretFromUri(uri: string): string | null {
  try {
    const u = new URL(uri);
    return u.searchParams.get("secret");
  } catch {
    return null;
  }
}

const FACTOR_LABEL: Record<string, string> = { totp: "Authenticator app", passkey: "Passkey", recovery_codes: "Recovery codes", sms: "SMS" };

export function MfaCard() {
  const toast = useToast();
  const factors = useResource<{ data: MfaFactor[] }>("me/mfa/factors");
  const [enrol, setEnrol] = useState<TotpEnrolment | null>(null);
  const [code, setCode] = useState("");
  const [codeErr, setCodeErr] = useState<string | undefined>();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [removing, setRemoving] = useState<MfaFactor | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);

  const list = factors.data?.data ?? [];
  // Unconfirmed TOTP enrolments are listed by the API with `confirmed: false`; hide them.
  const confirmed = list.filter((f) => f.confirmed);
  const hasTotp = confirmed.some((f) => f.type === "totp");

  const startTotp = async () => {
    setBusy("start");
    setError(null);
    try {
      const res = await api.post<TotpEnrolment>("me/mfa/totp", {}, { idempotencyKey: true });
      if (res.kind === "ok") setEnrol(res.data);
    } catch (err) {
      setError(toFormError(err));
    } finally {
      setBusy(null);
    }
  };

  const confirmTotp = async (e: FormEvent) => {
    e.preventDefault();
    if (!enrol) return;
    if (!/^\d{6}$/.test(code)) {
      setCodeErr("Enter the 6-digit code from your authenticator app.");
      return;
    }
    setCodeErr(undefined);
    setBusy("confirm");
    try {
      await api.post(`me/mfa/totp/${encodeURIComponent(enrol.factor_id)}/confirm`, { code }, { idempotencyKey: true });
      setEnrol(null);
      toast.show({ tone: "success", title: "Authenticator app added", description: "Next, save your recovery codes." });
      await factors.reload();
    } catch (err) {
      if (err instanceof ApiError && err.code === "otp_invalid") setCodeErr("That code didn't work. Check the time on your phone and try again.");
      else setError(toFormError(err));
    } finally {
      setCode("");
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!removing) return;
    setBusy("remove");
    try {
      await api.delete(`me/mfa/factors/${encodeURIComponent(removing.factor_id)}`);
      toast.show({ tone: "success", title: `${FACTOR_LABEL[removing.type] ?? "Method"} removed.` });
      setRemoving(null);
      await factors.reload();
    } catch (err) {
      const e = toFormError(err);
      toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
    } finally {
      setBusy(null);
    }
  };

  const generateCodes = async () => {
    setBusy("codes");
    setError(null);
    try {
      // verified: app/modules/identity/router.py recovery_codes
      const res = await api.post<{ codes: string[]; factor_id: string }>("me/mfa/recovery-codes", {}, { idempotencyKey: true });
      if (res.kind === "ok") setCodes(res.data?.codes ?? []);
    } catch (err) {
      setError(toFormError(err));
    } finally {
      setBusy(null);
    }
  };

  const secret = enrol ? (enrol.secret || secretFromUri(enrol.otpauth_uri)) : null;

  return (
    <Card title="2-step verification">
      <div className="space-y-4">
        <p className="text-sm text-fg-secondary">Add an authenticator app so a stolen password isn&apos;t enough to get into your account. With it on, your password can be as short as 8 characters.</p>
        <FormAlert error={error} />
        {factors.error ? (
          <ErrorState error={factors.error} onRetry={factors.reload} />
        ) : factors.loading && !factors.data ? (
          <LoadingBlock label="Loading your 2-step verification methods" rows={1} size="row" />
        ) : confirmed.length === 0 ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface-subtle p-3 text-sm">
            <span className="font-semibold text-fg">2-step verification</span>
            <StatusBadge status="disabled" />
            <span className="w-full text-fg-secondary">Add an authenticator app such as Google Authenticator or Microsoft Authenticator.</span>
          </div>
        ) : (
          <ul className="divide-y divide-line-subtle" aria-label="Your 2-step verification methods">
            {confirmed.map((f) => (
              <li key={f.factor_id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                <span>
                  <span className="font-medium text-fg">{f.label || FACTOR_LABEL[f.type] || f.type}</span>{" "}
                  <Badge tone="success">On</Badge>
                  <span className="ml-2 text-fg-muted">added {formatDate(f.created_at)}</span>
                  {f.type === "recovery_codes" && typeof f.remaining_codes === "number" ? <span className="ml-2 text-fg-muted">· {f.remaining_codes} codes left</span> : null}
                </span>
                <Button variant="ghost" size="sm" onClick={() => setRemoving(f)} aria-label={`Remove ${f.label || FACTOR_LABEL[f.type] || f.type}`}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        {enrol ? (
          <form onSubmit={confirmTotp} noValidate className="space-y-3 rounded-lg border border-line p-4">
            <h3 className="text-sm font-semibold text-fg">Set up your authenticator app</h3>
            <ol className="list-decimal space-y-1 pl-5 text-sm text-fg-secondary">
              <li>
                Open your authenticator app on your phone and add an account.{" "}
                <a href={enrol.otpauth_uri} className="text-fg-link underline">
                  Open in authenticator app
                </a>{" "}
                (on this device).
              </li>
              <li>
                Or enter this setup key: <span className="select-all break-all font-mono text-fg">{secret ?? "shown in your app link"}</span>
              </li>
              <li>Enter the 6-digit code the app shows.</li>
            </ol>
            <FormField label="6-digit code" error={codeErr} required>
              {(f) => <OtpInput {...f} value={code} onValueChange={setCode} />}
            </FormField>
            <div className="flex gap-2">
              <Button type="submit" loading={busy === "confirm"}>
                Turn on
              </Button>
              <Button variant="ghost" onClick={() => setEnrol(null)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap gap-2">
            {!hasTotp ? (
              <Button onClick={startTotp} loading={busy === "start"}>
                Add authenticator app
              </Button>
            ) : null}
            {hasTotp ? (
              <Button variant="secondary" onClick={generateCodes} loading={busy === "codes"}>
                Generate new recovery codes
              </Button>
            ) : null}
          </div>
        )}
        <p className="text-xs text-fg-muted">Passkeys: coming soon. Some changes ask you to confirm it&apos;s you first.</p>
      </div>

      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        dismissible={busy !== "remove"}
        title={`Remove ${removing ? (removing.label || FACTOR_LABEL[removing.type] || removing.type) : ""}?`}
        description="You'll no longer be able to use it to sign in."
        footer={
          <>
            <Button variant="secondary" onClick={() => setRemoving(null)} disabled={busy === "remove"}>
              Cancel
            </Button>
            <Button variant="danger" onClick={remove} loading={busy === "remove"}>
              Remove
            </Button>
          </>
        }
      />

      <Dialog
        open={codes !== null}
        onClose={() => setCodes(null)}
        title="Your recovery codes"
        description="Each code works once. Save them somewhere safe — we won't show them again."
        footer={<Button onClick={() => setCodes(null)}>I&apos;ve saved them</Button>}
      >
        {codes && codes.length ? (
          <ul className="grid grid-cols-2 gap-2 font-mono text-sm" aria-label="Recovery codes">
            {codes.map((c) => (
              <li key={c} className="select-all rounded bg-surface-subtle px-2 py-1">
                {c}
              </li>
            ))}
          </ul>
        ) : (
          <Notice tone="warning">No codes were returned. Please try again.</Notice>
        )}
      </Dialog>
    </Card>
  );
}

/**
 * /app/settings/security/mfa (target of `mfa_enrolment_required`): the enrolment card with the
 * reason first; in simple authentication 2-step verification isn't used, so just say so.
 */
export function MfaEnrolment() {
  const simple = useSimpleAuth();
  if (simple) {
    return (
      <Notice title="2-step verification isn't used">
        <p>You sign in with just your email and password. There&apos;s nothing to set up here.</p>
        <p className="mt-2">
          <Link href="/app/settings/security" className="font-medium text-fg-link underline">
            Back to Security
          </Link>
        </p>
      </Notice>
    );
  }
  return (
    <div className="space-y-6">
      <Notice tone="warning" title="2-step verification is required for your account">
        Your role requires 2-step verification. Add an authenticator app below, then go back to what you were doing.
      </Notice>
      <MfaCard />
    </div>
  );
}

/* ------------------------------------------------------------ This wasn't me */

/** "This wasn't me" for a session-replay / new-sign-in notice (SEC-46, unblock §1.6a). */
export function DisownEvent({ eventRef }: { eventRef: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [result, setResult] = useState<{ recovery_url?: string } | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!confirmed) {
      setError({ title: "Tick the box to confirm", requestId: null, code: "client" });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // verified: app/modules/security/api_student.py disown
      const res = await api.post<{ result: string; must_change_password?: boolean; recovery_url?: string }>(`me/security/events/${encodeURIComponent(eventRef)}/disown`, { confirm: true }, { handle: { auth: false } });
      if (res.kind === "ok") setResult(res.data ?? {});
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_state_transition") setError({ title: "You've already reported this", detail: "We've secured your account. Check your email or SMS for the next steps.", requestId: err.requestId, code: err.code });
      else if (err instanceof ApiError && err.code === "not_found") setError({ title: "We couldn't find this notice", detail: "It may have expired. If you think someone else is using your account, change your password now.", requestId: err.requestId, code: err.code });
      else setError(toFormError(err));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    // The API returns "/auth/forgot", which is not a route in this app; the reset flow lives at /forgot-password.
    const url = result.recovery_url && result.recovery_url.startsWith("/") && result.recovery_url !== "/auth/forgot" ? result.recovery_url : "/forgot-password";
    return (
      <Notice tone="success" title="We've secured your account">
        <p>We&apos;ve signed out all devices, including this one. To continue, verify with a code and choose a new password.</p>
        <p className="mt-2">
          <a href={url} className="font-medium text-fg-link underline">
            Secure my account
          </a>
        </p>
      </Notice>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormAlert error={error} />
      <p className="text-sm text-fg-secondary">
        If you didn&apos;t sign in, we&apos;ll sign out <strong>all</strong> devices (including this one) and ask you to choose a new password. Your courses, progress and purchases are not affected.
      </p>
      <Checkbox label="I don't recognise this activity — secure my account" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
      <div className="flex flex-wrap gap-3">
        <Button type="submit" variant="danger" loading={busy}>
          This wasn&apos;t me — secure my account
        </Button>
        <Link href="/app/settings/devices" className={buttonClasses({ variant: "ghost" })}>
          This was me
        </Link>
      </div>
    </form>
  );
}
