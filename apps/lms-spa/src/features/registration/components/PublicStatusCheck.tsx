"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Badge, Button, FormField, Input } from "@/components/ui";
import { buttonClasses } from "@/components/ui/Button";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { PUBLIC_STATUS_PATH, STATE_LABEL, inr, publicState, type PublicRegStatus } from "../lib/registration";

const REG_RE = /^TDR-[A-Z0-9]{8}$/;

/** "tdr-1a2b 3c4d" / "1A2B3C4D" -> "TDR-1A2B3C4D" (api rules.normalize_reg_no). */
export function normaliseRegNo(raw: string): string {
  const s = raw.toUpperCase().replace(/[\s-]/g, "");
  const core = s.startsWith("TDR") ? s.slice(3) : s;
  return `TDR-${core}`;
}

function Result({ r }: { r: PublicRegStatus }) {
  const state = publicState(r);
  const meta = STATE_LABEL[state];
  const enrolled = state === "enrolled";
  return (
    <article aria-labelledby="reg-result-h" className="space-y-3 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="reg-result-h" className="font-display text-base font-bold text-fg-heading">
            {r.course_title}
          </h2>
          <p className="text-xs text-fg-muted">
            Registration <span className="font-mono">{r.reg_no}</span>
          </p>
        </div>
        <Badge tone={meta.tone} dot>
          {meta.label}
        </Badge>
      </header>
      <p className="text-sm text-fg-secondary">
        {enrolled
          ? "You're enrolled. We emailed your LMS username and a temporary password. Log in, set a new password and your course is on your dashboard."
          : state === "pending"
            ? "We're checking your payment. Once it's verified we'll add you to the batch and email your LMS login details."
            : meta.text}
      </p>
      <dl className="grid grid-cols-3 gap-2 text-center">
        {[
          ["Fee", r.fee_paise],
          ["Verified", r.verified_total_paise],
          ["Balance", Math.max(0, r.balance_paise)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-lg bg-surface-sunken px-2 py-2">
            <dt className="text-[0.7rem] font-semibold uppercase tracking-wide text-fg-muted">{k}</dt>
            <dd className="text-sm font-bold text-fg-heading">{inr(Number(v))}</dd>
          </div>
        ))}
      </dl>
      {enrolled ? (
        <Link href="/login" className={buttonClasses({ className: "w-full sm:w-auto" })}>
          Log in to the LMS
        </Link>
      ) : null}
    </article>
  );
}

/** Public "Check my registration": registration number + email -> status (POST public/admissions/status). */
export function PublicStatusCheck({ initialRegNo = "", initialEmail = "" }: { initialRegNo?: string; initialEmail?: string }) {
  const [regNo, setRegNo] = useState(initialRegNo);
  const [email, setEmail] = useState(initialEmail);
  const [errors, setErrors] = useState<{ reg_no?: string; email?: string }>({});
  const [general, setGeneral] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PublicRegStatus | null>(null);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (busy) return;
    const reg = normaliseRegNo(regNo.trim());
    const mail = email.trim();
    const e: typeof errors = {};
    if (!REG_RE.test(reg)) e.reg_no = "Enter the registration number as shown on your confirmation, e.g. TDR-1A2B3C4D.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(mail)) e.email = "Enter the email you registered with.";
    setErrors(e);
    setGeneral("");
    setResult(null);
    if (e.reg_no || e.email) return;
    setBusy(true);
    try {
      const r = await api.post<PublicRegStatus>(PUBLIC_STATUS_PATH, { reg_no: reg, email: mail }, { handle: { auth: false } });
      if (r.kind === "ok") setResult(r.data);
    } catch (err) {
      if (isApiError(err)) {
        const items = (err.problem?.errors ?? []) as { field?: string; message?: string }[];
        const fe: typeof errors = {};
        for (const it of items) {
          const f = (it.field ?? "").replace(/^body\./, "");
          if ((f === "reg_no" || f === "email") && it.message) fe[f] ??= it.message;
        }
        setErrors(fe);
        setGeneral(err.status === 429 ? "Too many checks. Please wait a few minutes and try again." : items.length ? "Please fix the highlighted fields." : err.detail);
      } else {
        setGeneral("Something went wrong. Check your connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <form noValidate onSubmit={submit} className="space-y-4 rounded-2xl border border-line bg-surface p-4 sm:p-5">
        <FormField label="Registration number" hint="On your confirmation, e.g. TDR-1A2B3C4D." error={errors.reg_no} required>
          {(p) => <Input {...p} name="reg_no" value={regNo} onChange={(e) => setRegNo(e.target.value)} autoComplete="off" autoCapitalize="characters" maxLength={20} />}
        </FormField>
        <FormField label="Email" hint="The email you registered with." error={errors.email} required>
          {(p) => <Input {...p} name="email" type="email" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={160} />}
        </FormField>
        {general ? (
          <p role="alert" className="rounded-lg bg-danger-subtle p-3 text-sm font-semibold text-danger-fg">
            {general}
          </p>
        ) : null}
        <Button type="submit" loading={busy} className="w-full sm:w-auto">
          Check status
        </Button>
      </form>
      {result ? <Result r={result} /> : null}
    </div>
  );
}
