"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, FormField, Input } from "@/components/ui";
import { controlBase } from "@/components/ui/Input";
import { focusRing } from "@/components/ui/Button";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { uuid7 } from "@/lib/ids/uuid7";
import { cn } from "@/lib/ui/cn";
import { ErrorSummary, FormAlert, Notice } from "@/features/auth/components/shared";
import { problemFieldErrors, retryAfterSeconds, toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import { ENQUIRY_LIMITS, toEnquiryBody, validateEnquiry, type EnquiryField, type EnquiryInput } from "../lib/enquiries";

const EMPTY: EnquiryInput = { name: "", company: "", email: "", phone: "", message: "", consent: false };
const FIELDS: EnquiryField[] = ["name", "company", "email", "phone", "message", "consent"];
/** ErrorSummary focuses by element `name` when no id is given. */
const FIELD_TARGETS: Record<string, string> = Object.fromEntries(FIELDS.map((f) => [f, f]));

/**
 * PUB-010 corporate enquiry form (D8). No account needed; no CAPTCHA puzzle (WCAG 2.2 SC 3.3.8):
 * a hidden honeypot plus server-side rate limiting stop bots. Every field is re-validated by the api.
 */
export function EnquiryForm() {
  const [v, setV] = useState<EnquiryInput>(EMPTY);
  const [honeypot, setHoneypot] = useState("");
  const [errors, setErrors] = useState<Partial<Record<EnquiryField, string>>>({});
  const [formError, setFormError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const idemKey = useRef<string>(uuid7());
  const alertRef = useRef<HTMLDivElement>(null);

  const set = (k: Exclude<EnquiryField, "consent">) => (e: { target: { value: string } }) => setV((x) => ({ ...x, [k]: e.target.value }));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const errs = validateEnquiry(v);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.post("public/enquiries", toEnquiryBody(v, honeypot), {
        idempotencyKey: idemKey.current,
        handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false },
      });
      setSent(true);
    } catch (err) {
      const fe = problemFieldErrors(err);
      const known = Object.fromEntries(Object.entries(fe).filter(([k]) => (FIELDS as string[]).includes(k)));
      if (Object.keys(known).length) {
        setErrors(known);
      } else if (err instanceof ApiError && err.status === 429) {
        const wait = retryAfterSeconds(err);
        const minutes = wait ? Math.max(1, Math.ceil(wait / 60)) : null;
        setFormError({
          title: "Too many enquiries from this connection",
          detail: minutes ? `Please try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.` : "Please wait a few minutes and try again.",
          requestId: err.requestId,
          code: err.code,
        });
      } else {
        setFormError(toFormError(err, "We couldn't send your enquiry"));
      }
      // A fresh key: the failed request may be replayed otherwise.
      idemKey.current = uuid7();
      requestAnimationFrame(() => alertRef.current?.focus());
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <Notice tone="success" title="Thank you, we have your enquiry">
        Our team will reply to {v.email.trim()} within two working days. You don&apos;t need to send it again.
      </Notice>
    );
  }

  const summary = Object.fromEntries(Object.entries(errors).filter((e): e is [string, string] => !!e[1]));

  return (
    <form noValidate onSubmit={(e) => void onSubmit(e)} className="space-y-4" aria-label="Corporate enquiry">
      <ErrorSummary errors={summary} fieldIds={FIELD_TARGETS} />
      <FormAlert ref={alertRef} error={formError} />
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Your name" required error={errors.name}>
          {(p) => <Input {...p} name="name" autoComplete="name" maxLength={ENQUIRY_LIMITS.name} value={v.name} onChange={set("name")} />}
        </FormField>
        <FormField label="Company" required error={errors.company}>
          {(p) => <Input {...p} name="company" autoComplete="organization" maxLength={ENQUIRY_LIMITS.company} value={v.company} onChange={set("company")} />}
        </FormField>
        <FormField label="Work email" required error={errors.email}>
          {(p) => <Input {...p} name="email" type="email" inputMode="email" autoComplete="email" maxLength={ENQUIRY_LIMITS.email} value={v.email} onChange={set("email")} />}
        </FormField>
        <FormField label="Phone (optional)" hint="Include the country code if you are outside India." error={errors.phone}>
          {(p) => <Input {...p} name="phone" type="tel" inputMode="tel" autoComplete="tel" maxLength={ENQUIRY_LIMITS.phone} value={v.phone} onChange={set("phone")} />}
        </FormField>
      </div>
      <FormField label="How can we help?" required hint="For example: the skills you want to train, team size and timeline." error={errors.message}>
        {(p) => (
          <textarea
            {...p}
            name="message"
            rows={6}
            maxLength={ENQUIRY_LIMITS.messageMax}
            value={v.message}
            onChange={set("message")}
            className={cn(controlBase, "min-h-[8rem] py-2", errors.message ? "border-danger-border" : "border-line-control", focusRing)}
          />
        )}
      </FormField>
      {/* Honeypot: hidden from people and assistive tech; bots that fill it are dropped by the api. */}
      <div aria-hidden="true" className="absolute -left-[10000px] h-px w-px overflow-hidden">
        <label htmlFor="enquiry-website">Website</label>
        <input id="enquiry-website" name="website" type="text" tabIndex={-1} autoComplete="off" value={honeypot} onChange={(e) => setHoneypot(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Checkbox
          name="consent"
          checked={v.consent}
          onChange={(e) => setV((x) => ({ ...x, consent: e.target.checked }))}
          aria-invalid={errors.consent ? true : undefined}
          aria-required
          aria-describedby={errors.consent ? "enquiry-consent-error" : undefined}
          label={
            <>
              I agree that Tech Drona may store these details and contact me about this enquiry, as described in the{" "}
              <Link href="/legal/privacy" className="text-fg-link underline hover:text-fg-link-hover">
                privacy notice
              </Link>
              .
            </>
          }
        />
        {errors.consent ? (
          <p id="enquiry-consent-error" role="alert" className="text-xs font-medium text-danger-fg">
            {errors.consent}
          </p>
        ) : null}
      </div>
      <Button type="submit" loading={busy}>
        Send enquiry
      </Button>
    </form>
  );
}
