"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, FormField, Input, Select } from "@/components/ui";
import { useSimpleAuth } from "@/components/shell/Integrations";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { trackEvent } from "@/lib/firebase/analytics";
import type { FirebaseWebConfig } from "@/lib/firebase/config";
import { googleErrorMessage, resumeGoogleRedirect, signInWithGoogle, type GoogleUser } from "@/lib/firebase/google-auth";
import { NOTICE_VERSION, REQUIRED_PURPOSES, SIGNUP_OPTIONAL, type Purpose } from "../lib/consents";
import { toFormError, type FormErrorInfo } from "../lib/errors";
import { routeForLoginResult, routeForSessionCap } from "../lib/login-flow";
import type { LoginResponse } from "../lib/types";
import { ageOn, isEmail, normaliseIndianMobile } from "../lib/validation";
import { FormAlert, Notice } from "./shared";

type GoogleLoginResponse = LoginResponse & { new_account?: boolean };

interface SignupDetails {
  full_name: string;
  date_of_birth: string;
  consents: { purpose: Purpose; notice_version: string; granted: boolean }[];
  guardian: { name: string; email: string | null; phone: string | null; relationship: "parent" | "legal_guardian" } | null;
}

/**
 * "Continue with Google" for students (docs/firebase/MIGRATION-PLAN.md §5.1). Staff accounts
 * are refused by the API (they sign in with password + authenticator code). When no account
 * exists yet, a short details form collects what AUTH-01 needs (name, date of birth, consents,
 * guardian for under-18s); Google has already verified the email, so there is no password.
 */
export function GoogleSignIn({ config, next, staffHint = true }: { config: FirebaseWebConfig; next?: string | null; /** Show the "staff use email and password" line (log-in page only; staff never sign up). */ staffHint?: boolean }) {
  const router = useRouter();
  const simple = useSimpleAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [pending, setPending] = useState<{ user: GoogleUser; suggestedName: string } | null>(null);
  const alertRef = useRef<HTMLDivElement>(null);

  const fail = (info: FormErrorInfo) => {
    setError(info);
    setTimeout(() => alertRef.current?.focus(), 0);
  };

  const complete = async (user: GoogleUser, signup?: SignupDetails): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      // Each token is accepted once: a second call (signup details) needs a fresh one.
      const idToken = await user.idToken(!!signup);
      const res = await api.post<GoogleLoginResponse>(
        "auth/login/google",
        { id_token: idToken, remember_device: false, ...(signup ? { signup } : {}) },
        { idempotencyKey: true, handle: { auth: false, restriction: false, sessionChoice: false, stepUp: false } },
      );
      await user.signOut().catch(() => undefined);
      setPending(null);
      if (res.kind !== "ok") return true;
      if (res.data.new_account) trackEvent("sign_up", { method: "google" });
      else trackEvent("login", { method: "google" });
      router.push(routeForLoginResult(res.data, next ?? undefined));
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.code === "google_signup_required") {
        const raw = err.problem?.suggested_name;
        setPending({ user, suggestedName: typeof raw === "string" ? raw : user.displayName ?? "" });
        return false; // keep the Firebase user for a fresh token
      }
      if (signup && err instanceof ApiError && (err.code === "validation_failed" || err.code === "consent_required")) {
        fail(toFormError(err));
        return false; // let them fix the details form
      }
      await user.signOut().catch(() => undefined);
      setPending(null);
      if (err instanceof ApiError && err.code === "session_cap_reached") {
        router.push(routeForSessionCap(err, next ?? undefined));
        return true;
      }
      if (err instanceof ApiError && err.code === "google_signin_not_allowed") {
        fail({ title: "Use your password to sign in", detail: simple ? "Staff accounts sign in with their email and password." : "Staff accounts sign in with email, password and an authenticator code.", requestId: err.requestId, code: err.code });
      } else if (err instanceof ApiError && err.code === "google_token_invalid") {
        fail({ title: "Google sign-in could not be verified", detail: "Please try again.", requestId: err.requestId, code: err.code });
      } else {
        fail(toFormError(err));
      }
      return true;
    } finally {
      setBusy(false);
    }
  };

  // Redirect fallback: finish the sign-in when Google sends the browser back here.
  useEffect(() => {
    let cancelled = false;
    void resumeGoogleRedirect(config)
      .then((user) => {
        if (user && !cancelled) void complete(user);
      })
      .catch((e: unknown) => {
        const msg = googleErrorMessage(e);
        if (msg && !cancelled) fail({ title: msg, requestId: null, code: "google_auth_error" });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per page load
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const user = await signInWithGoogle(config);
      if (user === "redirecting") return;
      await complete(user);
    } catch (e) {
      const msg = googleErrorMessage(e);
      if (msg) fail({ title: msg, requestId: null, code: "google_auth_error" });
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    await pending?.user.signOut().catch(() => undefined);
    setPending(null);
    setError(null);
  };

  if (pending) {
    return (
      <div className="space-y-4">
        <FormAlert ref={alertRef} error={error} />
        <GoogleSignupDetails
          email={pending.user.email}
          suggestedName={pending.suggestedName}
          busy={busy}
          onSubmit={(details) => complete(pending.user, details)}
          onCancel={cancel}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <FormAlert ref={alertRef} error={error} />
      <Button type="button" variant="secondary" size="lg" className="w-full" loading={busy} onClick={start}>
        <GoogleMark />
        Continue with Google
      </Button>
      {staffHint ? (
        <p className="text-center text-xs text-fg-muted">{simple ? "Optional. You can always use your email and password below." : "Students and staff. Staff may be asked for their authenticator code next."}</p>
      ) : null}
    </div>
  );
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function GoogleSignupDetails({
  email,
  suggestedName,
  busy,
  onSubmit,
  onCancel,
}: {
  email: string | null;
  suggestedName: string;
  busy: boolean;
  onSubmit: (d: SignupDetails) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [fullName, setFullName] = useState(suggestedName);
  const [day, setDay] = useState("");
  const [month, setMonth] = useState("");
  const [year, setYear] = useState("");
  const [agree, setAgree] = useState(false);
  const [optional, setOptional] = useState<Partial<Record<Purpose, boolean>>>({});
  const [gName, setGName] = useState("");
  const [gEmail, setGEmail] = useState("");
  const [gPhone, setGPhone] = useState("");
  const [relationship, setRelationship] = useState<"parent" | "legal_guardian">("parent");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const dob = day && month && year ? `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}` : "";
  const age = dob ? ageOn(dob) : null;
  const isMinor = age !== null && age < 18;
  const now = new Date().getFullYear();
  const years = Array.from({ length: 80 }, (_, i) => String(now - 10 - i));

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const e: Record<string, string> = {};
    if (fullName.trim().length < 2) e.full_name = "Enter your full name.";
    if (!dob || age === null) e.date_of_birth = "Enter your date of birth.";
    else if (age < 10) e.date_of_birth = "Check the year of your date of birth.";
    if (isMinor) {
      if (!gName.trim()) e.guardian = "Enter your parent or guardian's name.";
      else if (!gEmail.trim() && !gPhone.trim()) e.guardian = "Enter your parent or guardian's email or mobile number.";
      else if (gEmail.trim() && !isEmail(gEmail)) e.guardian = "Enter a valid email address for your parent or guardian.";
      else if (gPhone.trim() && !normaliseIndianMobile(gPhone)) e.guardian = "Enter a 10-digit Indian mobile number for your parent or guardian.";
    }
    if (!agree) e.consents = "You need to agree to the Terms and Privacy Notice to create an account.";
    setErrors(e);
    if (Object.keys(e).length) return;
    await onSubmit({
      full_name: fullName.trim(),
      date_of_birth: dob,
      consents: [
        ...REQUIRED_PURPOSES.map((p) => ({ purpose: p, notice_version: NOTICE_VERSION, granted: true })),
        ...SIGNUP_OPTIONAL.map(({ purpose }) => ({ purpose, notice_version: NOTICE_VERSION, granted: !isMinor && !!optional[purpose] })),
      ],
      guardian: isMinor
        ? { name: gName.trim(), email: gEmail.trim() || null, phone: gPhone.trim() ? normaliseIndianMobile(gPhone) : null, relationship }
        : null,
    });
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-5" aria-labelledby="google-signup-heading">
      <div className="space-y-1">
        <h2 id="google-signup-heading" ref={headingRef} tabIndex={-1} className="font-display text-lg font-semibold text-fg focus:outline-none">
          Create your account
        </h2>
        <p className="text-sm text-fg-secondary">
          Signed in with Google{email ? ` as ${email}` : ""}. A few details and you&apos;re in.
        </p>
      </div>
      <FormField label="Full name" error={errors.full_name} required>
        {(f) => <Input {...f} name="full_name" autoComplete="name" value={fullName} onChange={(ev) => setFullName(ev.target.value)} />}
      </FormField>
      <fieldset className="space-y-1.5">
        <legend className="text-sm font-medium text-fg">
          Date of birth<span className="text-danger-fg" aria-hidden="true"> *</span>
        </legend>
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1.2fr)] gap-2">
          <label className="sr-only" htmlFor="g-dob-day">Day</label>
          <Select id="g-dob-day" value={day} onChange={(ev) => setDay(ev.target.value)} placeholder="DD" options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))} />
          <label className="sr-only" htmlFor="g-dob-month">Month</label>
          <Select id="g-dob-month" value={month} onChange={(ev) => setMonth(ev.target.value)} placeholder="Month" options={MONTHS.map((m, i) => ({ value: String(i + 1), label: m }))} />
          <label className="sr-only" htmlFor="g-dob-year">Year</label>
          <Select id="g-dob-year" value={year} onChange={(ev) => setYear(ev.target.value)} placeholder="YYYY" options={years.map((y) => ({ value: y, label: y }))} />
        </div>
        <p className="text-xs text-fg-muted">Used to apply the right privacy protections.</p>
        {errors.date_of_birth ? (
          <p role="alert" className="text-xs font-medium text-danger-fg">
            {errors.date_of_birth}
          </p>
        ) : null}
      </fieldset>
      {isMinor ? (
        <>
          <Notice title="A parent or guardian needs to agree">
            Because you&apos;re under 18, a parent or guardian needs to agree before you can start. We&apos;ll send them a link.
          </Notice>
          <fieldset className="space-y-3">
            <legend className="text-sm font-medium text-fg">Your parent or guardian</legend>
            <FormField label="Their name" error={errors.guardian} required>
              {(f) => <Input {...f} name="guardian_name" autoComplete="off" value={gName} onChange={(ev) => setGName(ev.target.value)} />}
            </FormField>
            <FormField label="Their email" hint="Email or mobile is required. We send the consent link here.">
              {(f) => <Input {...f} name="guardian_email" type="email" autoComplete="off" value={gEmail} onChange={(ev) => setGEmail(ev.target.value)} />}
            </FormField>
            <FormField label="Their mobile (+91)">
              {(f) => <Input {...f} name="guardian_phone" type="tel" inputMode="tel" autoComplete="off" value={gPhone} onChange={(ev) => setGPhone(ev.target.value)} />}
            </FormField>
            <FormField label="Relationship" required>
              {(f) => (
                <Select
                  {...f}
                  name="guardian_relationship"
                  value={relationship}
                  onChange={(ev) => setRelationship(ev.target.value === "legal_guardian" ? "legal_guardian" : "parent")}
                  options={[
                    { value: "parent", label: "Parent" },
                    { value: "legal_guardian", label: "Legal guardian" },
                  ]}
                />
              )}
            </FormField>
          </fieldset>
        </>
      ) : null}
      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-fg">Your choices</legend>
        <div>
          <Checkbox
            id="g-terms"
            checked={agree}
            onChange={(ev) => setAgree(ev.target.checked)}
            aria-invalid={errors.consents ? true : undefined}
            label={
              <>
                I agree to the{" "}
                <Link href="/legal/terms" className="text-fg-link underline" target="_blank">
                  Terms
                </Link>{" "}
                and{" "}
                <Link href="/legal/privacy" className="text-fg-link underline" target="_blank">
                  Privacy Notice
                </Link>{" "}
                (required)
              </>
            }
          />
          {errors.consents ? (
            <p role="alert" className="mt-1 text-xs font-medium text-danger-fg">
              {errors.consents}
            </p>
          ) : null}
        </div>
        {age !== null && age >= 18
          ? SIGNUP_OPTIONAL.map((o) => (
              <Checkbox
                key={o.purpose}
                label={`${o.label} (optional)`}
                description={o.description}
                checked={!!optional[o.purpose]}
                onChange={(ev) => setOptional((s) => ({ ...s, [o.purpose]: ev.target.checked }))}
              />
            ))
          : null}
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <Button type="submit" size="lg" loading={busy} className="flex-1">
          Create account
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Google "G" mark (brand guidelines: multicolour logo on a neutral button). */
function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 48 48" className="mr-2 h-5 w-5 shrink-0">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}
