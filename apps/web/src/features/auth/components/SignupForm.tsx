"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, FormField, Input, LinkButton, Select } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { trackEvent } from "@/lib/firebase/analytics";
import { ADULT_ONLY, NOTICE_VERSION, REQUIRED_PURPOSES, SIGNUP_OPTIONAL, type Purpose } from "../lib/consents";
import { formatCountdown, problemFieldErrors, retryAfterSeconds, toFormError, type FormErrorInfo } from "../lib/errors";
import type { GuardianBody, SignupBody, SignupResponse } from "../lib/types";
import { PASSWORD_MIN, ageOn, isEmail, normaliseIndianMobile, validatePassword } from "../lib/validation";
import { ErrorSummary, FormAlert, Notice, PasswordInput } from "./shared";
import { ServiceNotIntegrated, useSimpleAuth } from "@/components/shell/Integrations";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

type Field = "full_name" | "email" | "mobile" | "date_of_birth" | "guardian" | "password" | "consents";

const API_FIELD: Record<string, Field> = {
  full_name: "full_name",
  email: "email",
  mobile: "mobile",
  date_of_birth: "date_of_birth",
  guardian: "guardian",
  password: "password",
  consents: "consents",
};

/**
 * PUB-011 · AUTH-01 self-signup with DOB age gate and itemised consents (none pre-ticked).
 * `next` is an already-validated same-origin path (safeNextPath) to continue to after signup (FE-10).
 */
export function SignupForm({ next }: { next?: string | null }) {
  const simple = useSimpleAuth();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [day, setDay] = useState("");
  const [month, setMonth] = useState("");
  const [year, setYear] = useState("");
  const [password, setPassword] = useState("");
  const [guardianName, setGuardianName] = useState("");
  const [guardianEmail, setGuardianEmail] = useState("");
  const [guardianPhone, setGuardianPhone] = useState("");
  const [relationship, setRelationship] = useState<GuardianBody["relationship"]>("parent");
  const [agree, setAgree] = useState(false);
  const [optional, setOptional] = useState<Partial<Record<Purpose, boolean>>>({});
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SignupResponse | null>(null);
  const alertRef = useRef<HTMLDivElement>(null);
  const base = useId();
  /** Error-summary targets: element id, or input name for FormField-wired controls. */
  const ids: Record<Field, string> = {
    full_name: "full_name",
    email: "email",
    mobile: "mobile",
    date_of_birth: `${base}-dob-day`,
    guardian: "guardian_name",
    password: "password",
    consents: `${base}-terms`,
  };

  const dob = day && month && year ? `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}` : "";
  const age = dob ? ageOn(dob) : null;
  const isMinor = age !== null && age < 18;
  const showOptional = age !== null && age >= 18;

  const years = useMemo(() => {
    const now = new Date().getFullYear();
    return Array.from({ length: 80 }, (_, i) => String(now - 10 - i));
  }, []);

  const validate = (): Partial<Record<Field, string>> => {
    const e: Partial<Record<Field, string>> = {};
    if (fullName.trim().length < 2) e.full_name = "Enter your full name.";
    const hasEmail = email.trim().length > 0;
    const hasMobile = mobile.trim().length > 0;
    if (!hasEmail && !hasMobile) e.email = "Enter an email address or a mobile number.";
    if (hasEmail && !isEmail(email)) e.email = "Enter a valid email address, like name@example.com.";
    if (hasMobile && !normaliseIndianMobile(mobile)) e.mobile = "Enter a 10-digit Indian mobile number.";
    if (!dob) e.date_of_birth = "Enter your date of birth.";
    else if (age === null) e.date_of_birth = "Enter a real date of birth.";
    else if (age < 10) e.date_of_birth = "Check the year of your date of birth.";
    if (isMinor) {
      const gEmail = guardianEmail.trim();
      const gPhone = guardianPhone.trim();
      if (!guardianName.trim()) e.guardian = "Enter your parent or guardian's name.";
      else if (!gEmail && !gPhone) e.guardian = "Enter your parent or guardian's email or mobile number.";
      else if (gEmail && !isEmail(gEmail)) e.guardian = "Enter a valid email address for your parent or guardian.";
      else if (gPhone && !normaliseIndianMobile(gPhone)) e.guardian = "Enter a 10-digit Indian mobile number for your parent or guardian.";
    }
    const pw = validatePassword(password);
    if (pw) e.password = pw === "Use at least 15 characters." ? "Use at least 15 characters (or 8+ once you turn on 2-step verification)." : pw;
    if (!agree) e.consents = "You need to agree to the Terms and Privacy Notice to create an account.";
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const e = validate();
    setErrors(e);
    setError(null);
    if (Object.keys(e).length) return;

    const consents = [
      ...REQUIRED_PURPOSES.map((p) => ({ purpose: p, notice_version: NOTICE_VERSION, granted: true })),
      ...SIGNUP_OPTIONAL.map(({ purpose }) => ({
        purpose,
        notice_version: NOTICE_VERSION,
        // Adult-only purposes are never granted for minors (AUTH-01); the server enforces this too.
        granted: !isMinor && showOptional && (!ADULT_ONLY.includes(purpose) || age !== null) && !!optional[purpose],
      })),
    ];
    setBusy(true);
    try {
      const body: SignupBody = {
        full_name: fullName.trim(),
        email: email.trim() || null,
        mobile: mobile.trim() ? normaliseIndianMobile(mobile) : null,
        date_of_birth: dob,
        password,
        consents,
        guardian: isMinor
          ? {
              name: guardianName.trim(),
              email: guardianEmail.trim() || null,
              phone: guardianPhone.trim() ? normaliseIndianMobile(guardianPhone) : null,
              relationship,
            }
          : null,
      };
      const res = await api.post<SignupResponse>(
        "auth/signup",
        body,
        { idempotencyKey: true, handle: { auth: false, restriction: false, sessionChoice: false } },
      );
      setPassword("");
      if (res.kind === "ok") {
        setResult(res.data);
        trackEvent("sign_up", { method: "password" });
      }
    } catch (err) {
      const fe = problemFieldErrors(err);
      const mapped: Partial<Record<Field, string>> = {};
      for (const [k, v] of Object.entries(fe)) {
        const f = API_FIELD[k.split(".")[0] ?? k] ?? API_FIELD[k.split("[")[0] ?? k];
        if (f) mapped[f] = v;
      }
      if (Object.keys(mapped).length) setErrors(mapped);
      if (err instanceof ApiError && err.code === "throttled") {
        const s = retryAfterSeconds(err);
        setError({ title: "Too many attempts", detail: s ? `Try again in ${formatCountdown(s)}.` : "Please wait a little and try again.", requestId: err.requestId, code: err.code });
      } else if (!Object.keys(mapped).length) {
        setError(toFormError(err));
      }
      setTimeout(() => alertRef.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  };

  if (result) return <SignupResult result={result} email={email.trim()} next={next} />;

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <ErrorSummary errors={errors as Record<string, string>} fieldIds={ids} />
      <FormAlert ref={alertRef} error={error} />

      <FormField label="Full name" error={errors.full_name} required>
        {(f) => <Input {...f} name="full_name" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />}
      </FormField>
      <FormField label="Email" hint="Email or mobile is required; add both to recover your account more easily." error={errors.email}>
        {(f) => <Input {...f} name="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />}
      </FormField>
      <FormField label="Mobile (+91)" error={errors.mobile}>
        {(f) => <Input {...f} name="mobile" type="tel" inputMode="tel" autoComplete="tel-national" placeholder="98765 43210" value={mobile} onChange={(e) => setMobile(e.target.value)} />}
      </FormField>

      <fieldset aria-describedby={`${base}-dob-hint${errors.date_of_birth ? ` ${base}-dob-err` : ""}`} className="space-y-1.5">
        <legend className="text-sm font-semibold text-fg">
          Date of birth<span className="text-danger-fg" aria-hidden="true"> *</span>
        </legend>
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1.2fr)] gap-2">
          <label className="sr-only" htmlFor={ids.date_of_birth}>Day</label>
          <Select id={ids.date_of_birth} aria-invalid={errors.date_of_birth ? true : undefined} value={day} onChange={(e) => setDay(e.target.value)} placeholder="DD" options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))} />
          <label className="sr-only" htmlFor={`${base}-dob-month`}>Month</label>
          <Select id={`${base}-dob-month`} aria-invalid={errors.date_of_birth ? true : undefined} value={month} onChange={(e) => setMonth(e.target.value)} placeholder="Month" options={MONTHS.map((m, i) => ({ value: String(i + 1), label: m }))} />
          <label className="sr-only" htmlFor={`${base}-dob-year`}>Year</label>
          <Select id={`${base}-dob-year`} aria-invalid={errors.date_of_birth ? true : undefined} value={year} onChange={(e) => setYear(e.target.value)} placeholder="YYYY" options={years.map((y) => ({ value: y, label: y }))} />
        </div>
        <p id={`${base}-dob-hint`} className="text-[0.8125rem] leading-snug text-fg-muted">
          Used to apply the right privacy protections.
        </p>
        {errors.date_of_birth ? (
          <p id={`${base}-dob-err`} className="flex items-start gap-1.5 text-[0.8125rem] font-medium leading-snug text-danger-fg before:mt-px before:inline-flex before:h-4 before:w-4 before:shrink-0 before:items-center before:justify-center before:rounded-full before:bg-danger-solid before:text-[0.625rem] before:font-bold before:text-danger-on-solid before:content-['!']">
            {errors.date_of_birth}
          </p>
        ) : null}
      </fieldset>

      {isMinor ? (
        <>
          <Notice title="A parent or guardian needs to agree">
            Because you&apos;re under 18, a parent or guardian needs to agree before you can start. We&apos;ll send them a link. You can still browse free content.
          </Notice>
          <fieldset className="space-y-3">
            <legend className="text-sm font-semibold text-fg">Your parent or guardian</legend>
            <FormField label="Their name" error={errors.guardian} required>
              {(f) => <Input {...f} name="guardian_name" autoComplete="off" value={guardianName} onChange={(e) => setGuardianName(e.target.value)} />}
            </FormField>
            <FormField label="Their email" hint="Email or mobile is required. We send the consent link here.">
              {(f) => <Input {...f} name="guardian_email" type="email" autoComplete="off" value={guardianEmail} onChange={(e) => setGuardianEmail(e.target.value)} />}
            </FormField>
            <FormField label="Their mobile (+91)">
              {(f) => <Input {...f} name="guardian_phone" type="tel" inputMode="tel" autoComplete="off" value={guardianPhone} onChange={(e) => setGuardianPhone(e.target.value)} />}
            </FormField>
            <FormField label="Relationship" required>
              {(f) => (
                <Select
                  {...f}
                  name="guardian_relationship"
                  value={relationship}
                  onChange={(e) => setRelationship(e.target.value === "legal_guardian" ? "legal_guardian" : "parent")}
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

      <FormField label="Password" hint={simple ? `At least ${PASSWORD_MIN} characters.` : "15+ characters, or 8+ if you turn on 2-step verification."} error={errors.password} required>
        {(f) => <PasswordInput {...f} name="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </FormField>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-fg">Your choices</legend>
        <div>
          <Checkbox
            id={ids.consents}
            checked={agree}
            onChange={(e) => setAgree(e.target.checked)}
            aria-invalid={errors.consents ? true : undefined}
            aria-describedby={errors.consents ? `${ids.consents}-err` : undefined}
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
            <p id={`${ids.consents}-err`} className="mt-1 flex items-start gap-1.5 text-[0.8125rem] font-medium leading-snug text-danger-fg before:mt-px before:inline-flex before:h-4 before:w-4 before:shrink-0 before:items-center before:justify-center before:rounded-full before:bg-danger-solid before:text-[0.625rem] before:font-bold before:text-danger-on-solid before:content-['!']">
              {errors.consents}
            </p>
          ) : null}
        </div>
        {showOptional
          ? SIGNUP_OPTIONAL.map((o) => (
              <Checkbox
                key={o.purpose}
                label={`${o.label} (optional)`}
                description={o.description}
                checked={!!optional[o.purpose]}
                onChange={(e) => setOptional((s) => ({ ...s, [o.purpose]: e.target.checked }))}
              />
            ))
          : null}
      </fieldset>

      <Button type="submit" loading={busy} size="lg" className="w-full">
        Create account
      </Button>
      <p className="text-center text-sm text-fg-muted">
        Already have an account?{" "}
        <Link href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"} className="text-fg-link underline">
          Log in
        </Link>
      </p>
    </form>
  );
}

/** Post-signup next steps (AUTH-01 `next_steps`; non-enumerating copy for `check_email`). */
export function SignupResult({ result, email, next }: { result: SignupResponse; email?: string; next?: string | null }) {
  const steps = result.next_steps ?? [];
  const headingRef = useRef<HTMLHeadingElement>(null);
  // The form that had focus is gone: move focus to the result heading (FE-22, WCAG 2.4.3).
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  const continueHref = next ?? "/app";
  return (
    <div className="space-y-4" role="status">
      <h2 ref={headingRef} tabIndex={-1} className="font-display text-xl font-bold text-fg-heading focus:outline-none">
        {steps.includes("guardian_consent") ? "Almost there" : "Check your inbox"}
      </h2>
      <ServiceNotIntegrated service="email" text="Email sending isn't connected yet, so the verification email won't arrive. You can still sign in; contact the Tech Drona admin if you need help." />
      {steps.includes("guardian_consent") || result.is_minor ? (
        <Notice title="A parent or guardian needs to agree">
          Because you&apos;re under 18, a parent or guardian needs to agree before you can start. We&apos;ll send them a link. You can still browse free content.
        </Notice>
      ) : null}
      {steps.includes("check_email") ? (
        <p className="text-sm text-fg-secondary">
          If you can create an account with these details, we&apos;ve sent the next steps to {email || "your email"}. An account with this email may already exist —{" "}
          <Link href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"} className="text-fg-link underline">
            Log in
          </Link>{" "}
          or{" "}
          <Link href="/forgot-password" className="text-fg-link underline">
            Reset password
          </Link>
          .
        </p>
      ) : null}
      {steps.includes("verify_email") ? (
        <p className="text-sm text-fg-secondary">We&apos;ve sent a verification link to {email || "your email"}. Open it on this or any device to confirm your address.</p>
      ) : null}
      <div className="flex flex-wrap gap-3">
        {steps.includes("verify_mobile") ? (
          <LinkButton href="/verify/mobile">Verify your mobile</LinkButton>
        ) : null}
        <LinkButton href={continueHref} variant={steps.includes("verify_mobile") ? "secondary" : "primary"}>
          {next ? "Continue" : "Go to my dashboard"}
        </LinkButton>
      </div>
    </div>
  );
}
