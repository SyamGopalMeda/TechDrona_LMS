"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { toFormError, type FormErrorInfo } from "../lib/errors";
import { formatRelative } from "../lib/format";
import { defaultCapChoice, routeForLoginResult } from "../lib/login-flow";
import { clearPendingLogin, readPendingLogin } from "../lib/pending-login";
import type { CapSession, LoginResponse, SessionChoiceBody } from "../lib/types";
import { FormAlert, Notice } from "./shared";

/** PUB-012 session-cap chooser for a `pending_session_choice` session · AUTH-14 (copy DS §9.4). */
export function SessionChoice() {
  const router = useRouter();
  const toast = useToast();
  const [loaded, setLoaded] = useState(false);
  const [sessions, setSessions] = useState<CapSession[]>([]);
  const [next, setNext] = useState<string | undefined>();
  const [selected, setSelected] = useState<string>("");
  const [confirmAttempt, setConfirmAttempt] = useState(false);
  const [busy, setBusy] = useState<"continue" | "cancel" | null>(null);
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [expired, setExpired] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = readPendingLogin();
    const list = p?.capSessions ?? [];
    setSessions(list);
    setNext(p?.next);
    setSelected(defaultCapChoice(list) ?? "");
    setLoaded(true);
  }, []);

  const handleErr = (err: unknown) => {
    if (err instanceof ApiError && (err.code === "session_expired" || err.code === "unauthenticated" || err.code === "invalid_state_transition")) {
      clearPendingLogin();
      setExpired(true);
      return;
    }
    setError(toFormError(err));
    setTimeout(() => alertRef.current?.focus(), 0);
  };

  const chosen = sessions.find((s) => s.session_id === selected);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!chosen) {
      setError({ title: "Choose a device to sign out", requestId: null, code: "client" });
      return;
    }
    if (chosen.has_active_attempt && !confirmAttempt) {
      setError({ title: "Confirm that you want to interrupt the test on that device", requestId: null, code: "client" });
      return;
    }
    setBusy("continue");
    setError(null);
    try {
      const body: SessionChoiceBody = { end_session_id: chosen.session_id, cancel: false, confirm_attempt_session: !!chosen.has_active_attempt };
      const res = await api.post<LoginResponse>("auth/session-choice", body, { idempotencyKey: true, handle: { auth: false, sessionChoice: false, restriction: false } });
      if (res.kind === "ok") {
        toast.show({ tone: "success", title: `Signed out ${chosen.device_label}.` });
        router.push(routeForLoginResult(res.data, next));
      }
    } catch (err) {
      handleErr(err);
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    setBusy("cancel");
    try {
      await api.post("auth/session-choice", { cancel: true }, { idempotencyKey: true, handle: { auth: false, sessionChoice: false, restriction: false } });
    } catch {
      /* the pending session expires on its own within 5 minutes */
    } finally {
      clearPendingLogin();
      setBusy(null);
      router.push("/login");
    }
  };

  if (!loaded) return <p aria-busy="true" className="text-sm text-fg-muted">Loading…</p>;

  if (expired || sessions.length === 0) {
    return (
      <Notice tone="warning" title="This sign-in has expired">
        <p>
          You have 5 minutes to choose a device.{" "}
          <Link href="/login" className="text-fg-link underline">
            Sign in again
          </Link>
          .
        </p>
      </Notice>
    );
  }

  const allBusy = sessions.every((s) => s.has_active_attempt);
  if (allBusy) {
    return (
      <div className="space-y-4">
        <Notice tone="warning" title="You can't sign in here right now">
          <p>
            Both of your other devices have a test in progress. Finish or submit the test there first, then sign in here.{" "}
            <Link href="/help" className="text-fg-link underline">
              Help
            </Link>
          </p>
        </Notice>
        <Button variant="secondary" loading={busy === "cancel"} onClick={cancel}>
          Back to sign in
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error} />
      <fieldset className="space-y-3">
        <legend className="sr-only">Choose a device to sign out</legend>
        {sessions.map((s) => {
          const hintId = `cap-${s.session_id}-hint`;
          return (
            <label key={s.session_id} className="flex min-h-[56px] cursor-pointer items-start gap-3 rounded-lg border border-line p-3 has-[:checked]:border-brand">
              <input
                type="radio"
                name="end_session_id"
                value={s.session_id}
                checked={selected === s.session_id}
                onChange={() => {
                  setSelected(s.session_id);
                  setConfirmAttempt(false);
                }}
                aria-describedby={s.has_active_attempt ? hintId : undefined}
                className="mt-1 h-4 w-4 accent-[var(--td-brand)]"
              />
              <span className="text-sm">
                <span className="block font-medium text-fg">{s.device_label}</span>
                <span className="block text-fg-muted">
                  {s.approx_region ? `${s.approx_region} (approx.) · ` : ""}active {formatRelative(s.last_active_at)}
                </span>
                {s.has_active_attempt ? (
                  <span id={hintId} className="mt-1 block font-medium text-warning-fg">
                    Test in progress. Signing out this device would interrupt your test. We recommend choosing the other one.
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </fieldset>
      {chosen?.has_active_attempt ? (
        <label className="flex items-start gap-3 text-sm">
          <input type="checkbox" checked={confirmAttempt} onChange={(e) => setConfirmAttempt(e.target.checked)} className="mt-0.5 h-5 w-5 accent-[var(--td-brand)]" />
          <span>I understand the test on {chosen.device_label} will be interrupted. It keeps its time on the server, but I&apos;ll need to reopen it.</span>
        </label>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Button type="submit" loading={busy === "continue"} disabled={busy !== null}>
          Sign out selected and continue
        </Button>
        <Button variant="secondary" loading={busy === "cancel"} disabled={busy !== null} onClick={cancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
