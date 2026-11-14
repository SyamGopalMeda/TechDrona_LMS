"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, FormField } from "@/components/ui";
import { useSimpleAuth } from "@/components/shell/Integrations";
import { useSignOut } from "@/components/shell/SignOutButton";
import { ACCEPT_TERMS_PATH, api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { FormAlert, Notice, PasswordInput } from "@/features/auth/components/shared";
import { problemFieldErrors, toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import { PASSWORD_MIN, PASSWORD_MIN_WITH_MFA, validatePassword } from "@/features/auth/lib/validation";
import type { ChangePasswordBody } from "../lib/types";
import { missingRequiredConsents } from "./AcceptTerms";

/**
 * AUTH-18 change password (POST auth/password/change). Shared by Settings → Security and the
 * forced /change-password page (admin ticked "Must change password on first login").
 *
 * `forced`: the current password is the one the admin gave; other sessions are always signed
 * out (no checkbox) and the button is the page's primary action.
 */
export function ChangePasswordForm({ forced = false, onChanged }: { forced?: boolean; onChanged: (signedOutOthers: boolean) => void }) {
  const simple = useSimpleAuth();
  // Simple authentication: 6+ characters. Otherwise the 2-step floor; the api applies the real rule.
  const min = simple || (forced && simple === null) ? PASSWORD_MIN : PASSWORD_MIN_WITH_MFA;
  const hint = min === PASSWORD_MIN ? `At least ${PASSWORD_MIN} characters.` : "15+ characters, or 8+ with 2-step verification turned on.";
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [signOutOthers, setSignOutOthers] = useState(true);
  const [fe, setFe] = useState<{ current?: string; next?: string; confirm?: string }>({});
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v: typeof fe = {};
    if (!current) v.current = forced ? "Enter the password your admin gave you." : "Enter your current password.";
    const pw = validatePassword(next, min);
    if (pw) v.next = pw;
    else if (next === current) v.next = "Choose a password different from your current one.";
    if (!v.next && confirm !== next) v.confirm = "The passwords don't match.";
    setFe(v);
    if (Object.keys(v).length) return;
    setBusy(true);
    setError(null);
    const revoke = forced || signOutOthers;
    let ok = false;
    try {
      const body: ChangePasswordBody = { current_password: current, new_password: next, revoke_other_sessions: revoke };
      await api.post("auth/password/change", body, { idempotencyKey: true });
      setFe({});
      ok = true;
    } catch (err) {
      const f = problemFieldErrors(err);
      if (f.current_password || f.new_password) setFe({ current: f.current_password, next: f.new_password });
      else if (err instanceof ApiError && err.code === "invalid_credentials") setFe({ current: "That password isn't right." });
      else {
        setError(toFormError(err));
        setTimeout(() => alertRef.current?.focus(), 0);
      }
    } finally {
      setCurrent("");
      setNext("");
      setConfirm("");
      setBusy(false);
    }
    if (ok) onChanged(revoke);
  };

  return (
    <form onSubmit={submit} noValidate className="max-w-md space-y-4">
      <FormAlert ref={alertRef} error={error} />
      <FormField label="Current password" hint={forced ? "The password your admin gave you." : undefined} error={fe.current} required>
        {(f) => <PasswordInput {...f} name="current_password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />}
      </FormField>
      <FormField label="New password" hint={hint} error={fe.next} required>
        {(f) => <PasswordInput {...f} name="new_password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />}
      </FormField>
      <FormField label="Confirm new password" error={fe.confirm} required>
        {(f) => <PasswordInput {...f} name="confirm_password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
      </FormField>
      {forced ? null : (
        <Checkbox label="Sign out my other sessions" description="Recommended if you think someone else knows your password." checked={signOutOthers} onChange={(e) => setSignOutOthers(e.target.checked)} />
      )}
      <Button type="submit" variant={forced ? "primary" : "secondary"} size={forced ? "lg" : undefined} className={forced ? "w-full" : undefined} loading={busy}>
        {forced ? "Save new password" : "Change password"}
      </Button>
    </form>
  );
}

/**
 * /change-password: the admin ticked "Must change password on first login", so every api call
 * answers `403 password_change_required` until a new password is saved. Then on to `next`.
 */
export function RequiredPasswordChange({ next }: { next: string }) {
  const router = useRouter();
  const { busy, start, dialog } = useSignOut();
  const [done, setDone] = useState(false);
  if (done) {
    return (
      <Notice tone="success" title="Password saved">
        Taking you to your portal…
      </Notice>
    );
  }
  return (
    <div className="space-y-5">
      <ChangePasswordForm
        forced
        onChanged={() => {
          setDone(true);
          // A brand-new admin-created account may not have agreed to the terms yet: ask that next,
          // instead of landing on a page that only shows a consent_required error.
          void missingRequiredConsents().then((r) =>
            router.replace(r && r.missing.length ? `${ACCEPT_TERMS_PATH}?next=${encodeURIComponent(next)}` : next),
          );
        }}
      />
      <p className="text-center text-sm text-fg-muted">
        Not you?{" "}
        <button type="button" onClick={() => void start()} disabled={busy} className="text-fg-link underline disabled:opacity-60">
          Sign out
        </button>
      </p>
      {dialog}
    </div>
  );
}
