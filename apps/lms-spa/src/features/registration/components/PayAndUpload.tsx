"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button, FormField, Icon, Input } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { prepareProof, ProofFileError, PROOF_ACCEPT, type PreparedProof } from "../lib/proof-file";
import { inr, refProblem, todayIST, type AmountOption, type ClaimPayload, type PaymentInfo, type ProofPayload } from "../lib/registration";
import { PaymentPanel } from "./PaymentPanel";

/** Fields this form owns (others in a 422 go to `onOtherErrors`). */
const OWN_FIELDS = new Set(["amount_paise", "method", "utr", "paid_on", "proof", "claim"]);

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`step-${n}`} className="space-y-4 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <h2 id={`step-${n}`} className="flex items-center gap-2 font-display text-base font-bold text-fg-heading">
        <span aria-hidden="true" className="grid h-7 w-7 place-items-center rounded-full bg-brand-subtle text-sm text-brand-on-subtle">
          {n}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}
export { Step as RegistrationStep };

export interface PayAndUploadProps {
  options: AmountOption[];
  payment: PaymentInfo | null;
  /** Payment note (the registration number). */
  note: string;
  courseTitle: string;
  submitLabel: string;
  /** Step number of "Pay" (the details step comes first on a new registration). */
  firstStep?: number;
  /** Rendered before the pay step (e.g. the student's details). */
  before?: ReactNode;
  /** Rendered after the upload step, before the button (e.g. the consent checkbox). */
  after?: ReactNode;
  /** Client checks of the fields in `before` / `after`; return field errors to stop. */
  validateExtra?: () => Record<string, string>;
  onOtherErrors?: (errors: Record<string, string>) => void;
  onSubmit: (claim: ClaimPayload, proof: ProofPayload) => Promise<void>;
}

/** Choose the amount, pay by UPI QR / ID, then upload the screenshot + UTR and submit. */
export function PayAndUpload({ options, payment, note, courseTitle, submitLabel, firstStep = 1, before, after, validateExtra, onOtherErrors, onSubmit }: PayAndUploadProps) {
  const [choice, setChoice] = useState(0);
  const amount = options[choice]?.amount_paise ?? options[0]?.amount_paise ?? 0;
  const bankOnly = !!payment && !payment.upi_id && !payment.phone && !!payment.bank_details;
  const [method, setMethod] = useState<"upi" | "bank">(bankOnly ? "bank" : "upi");
  const [utr, setUtr] = useState("");
  const [paidOn, setPaidOn] = useState(todayIST());
  const [proof, setProof] = useState<PreparedProof | null>(null);
  const [checking, setChecking] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [general, setGeneral] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const today = todayIST();

  useEffect(() => () => {
    if (proof?.preview) URL.revokeObjectURL(proof.preview);
  }, [proof]);

  const pick = async (file: File | undefined) => {
    setProof(null);
    setErrors((e) => ({ ...e, proof: "" }));
    if (!file) return;
    setChecking(true);
    try {
      setProof(await prepareProof(file));
    } catch (err) {
      setErrors((e) => ({ ...e, proof: err instanceof ProofFileError ? err.message : "We couldn't read that file. Choose it again." }));
      if (fileRef.current) fileRef.current.value = "";
    } finally {
      setChecking(false);
    }
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (busy || checking) return;
    setGeneral("");
    const extra = validateExtra?.() ?? {};
    const own: Record<string, string> = {};
    const ref = refProblem(utr, method);
    if (ref) own.utr = ref;
    if (!paidOn) own.paid_on = "Enter the date you paid.";
    else if (paidOn > today) own.paid_on = "The payment date can't be in the future.";
    if (!proof) own.proof = "Upload the payment screenshot or receipt.";
    setErrors(own);
    const extraBad = Object.values(extra).some(Boolean);
    if (extraBad || Object.keys(own).length) {
      if (extraBad) onOtherErrors?.(extra);
      setGeneral("Please fix the highlighted fields.");
      return;
    }
    setBusy(true);
    try {
      await onSubmit(
        { amount_paise: amount, method, utr: utr.toUpperCase().replace(/[\s-]/g, ""), paid_on: paidOn },
        { filename: proof!.filename, data_b64: proof!.data_b64, original_sha256: proof!.original_sha256 },
      );
    } catch (err) {
      if (err instanceof ApiError) {
        const items = (err.problem?.errors ?? []) as { field?: string; message?: string }[];
        const mine: Record<string, string> = {};
        const others: Record<string, string> = {};
        for (const it of items) {
          const f = (it.field ?? "").replace(/^(body\.|claim\.)/, "").replace(/^proof\..*/, "proof");
          if (!f || !it.message) continue;
          if (OWN_FIELDS.has(f)) mine[f === "amount_paise" ? "amount" : f] ??= it.message;
          else others[f] ??= it.message;
        }
        setErrors(mine);
        if (Object.keys(others).length) onOtherErrors?.(others);
        setGeneral(items.length ? "Please fix the highlighted fields." : err.detail);
      } else {
        setGeneral("Something went wrong. Check your connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form noValidate onSubmit={submit} className="space-y-4">
      {before}
      <Step n={firstStep} title={`Pay ${inr(amount)}`}>
        {options.length > 1 ? (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-semibold text-fg">How much are you paying now?</legend>
            {options.map((o, i) => (
              <label key={o.label} className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-line p-3 has-[:checked]:border-brand">
                <span className="flex items-center gap-2 text-sm">
                  <input type="radio" name="amount" checked={choice === i} onChange={() => setChoice(i)} />
                  {o.label}
                </span>
                <strong className="text-sm">{inr(o.amount_paise)}</strong>
              </label>
            ))}
            {errors.amount ? <p className="text-sm text-danger-fg">{errors.amount}</p> : null}
          </fieldset>
        ) : errors.amount ? (
          <p className="text-sm text-danger-fg">{errors.amount}</p>
        ) : null}
        <PaymentPanel payment={payment} amountPaise={amount} note={note} subject={`Payment details for ${courseTitle} (${note})`} />
      </Step>

      <Step n={firstStep + 1} title="Upload payment proof">
        {payment?.bank_details && (payment.upi_id || payment.phone) ? (
          <fieldset className="flex flex-wrap gap-4 text-sm">
            <legend className="mb-1 w-full font-semibold text-fg">How did you pay?</legend>
            <label className="flex items-center gap-2">
              <input type="radio" name="method" checked={method === "upi"} onChange={() => setMethod("upi")} /> UPI
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="method" checked={method === "bank"} onChange={() => setMethod("bank")} /> Bank transfer
            </label>
          </fieldset>
        ) : null}
        <FormField
          label={method === "upi" ? "UPI reference (UTR)" : "Transaction reference (UTR)"}
          hint={method === "upi" ? "The 12-digit number on the payment success screen (UPI Ref. No. / UTR)." : "The reference number from your bank."}
          error={errors.utr}
          required
        >
          {(p) => <Input {...p} name="utr" value={utr} onChange={(e) => setUtr(e.target.value)} inputMode={method === "upi" ? "numeric" : "text"} autoComplete="off" maxLength={40} />}
        </FormField>
        <FormField label="Payment date" error={errors.paid_on} required>
          {(p) => <Input {...p} type="date" name="paid_on" value={paidOn} max={today} onChange={(e) => setPaidOn(e.target.value)} />}
        </FormField>
        <FormField label="Payment screenshot or receipt" hint="JPG, PNG or WebP screenshot, or a PDF receipt. Up to 10 MB (photos are shrunk before upload)." error={errors.proof} required>
          {(p) => (
            <input
              {...p}
              ref={fileRef}
              type="file"
              name="proof"
              accept={PROOF_ACCEPT}
              onChange={(e) => void pick(e.target.files?.[0])}
              className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-brand-subtle file:px-3 file:py-2 file:font-semibold file:text-brand-on-subtle"
            />
          )}
        </FormField>
        {checking ? (
          <p role="status" className="text-sm text-fg-muted">
            Checking the file…
          </p>
        ) : null}
        {proof ? (
          <div className="flex items-center gap-3 rounded-xl border border-line p-2">
            {proof.preview ? (
              // eslint-disable-next-line @next/next/no-img-element -- local preview (object URL)
              <img src={proof.preview} alt={`Preview of ${proof.filename}`} className="h-14 w-14 rounded-lg object-cover" />
            ) : (
              <Icon name="document" className="h-8 w-8 text-fg-muted" />
            )}
            <span className="min-w-0 text-sm">
              <strong className="block truncate">{proof.filename}</strong>
              <small className="text-fg-muted">{Math.max(1, Math.round(proof.size / 1024))} KB, ready to upload</small>
            </span>
          </div>
        ) : null}
      </Step>

      {after}
      {general ? (
        <p role="alert" className="rounded-lg bg-danger-subtle p-3 text-sm font-semibold text-danger-fg">
          {general}
        </p>
      ) : null}
      <Button type="submit" loading={busy} disabled={checking} className="w-full sm:w-auto">
        {submitLabel}
      </Button>
    </form>
  );
}
