"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui";
import { buttonClasses } from "@/components/ui/Button";
import { SITE_INFO } from "@/lib/site/website";
import { inr, upiLink, type PaymentInfo } from "../lib/registration";

/** Copies `text`; says "Copied" for a moment (falls back silently when the clipboard is blocked). */
export function CopyButton({ text, what }: { text: string; what: string }) {
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => setDone(false), 2000);
    return () => clearTimeout(t);
  }, [done]);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => setDone(true))
          .catch(() => {});
      }}
      className="shrink-0 rounded-md border border-line px-2 py-1 text-xs font-semibold text-brand hover:bg-surface-sunken focus-visible:shadow-focus focus-visible:outline-none"
      aria-label={`Copy ${what}`}
    >
      <span aria-live="polite">{done ? "Copied" : "Copy"}</span>
    </button>
  );
}

/** QR image of a upi://pay link, generated in the browser (`qrcode`, loaded on demand). */
export function UpiQr({ link, amountPaise }: { link: string; amountPaise: number }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let live = true;
    setSrc("");
    import("qrcode")
      .then((m) => (m.default ?? m).toDataURL(link, { width: 440, margin: 1, errorCorrectionLevel: "M", color: { dark: "#0a0f1fff", light: "#ffffffff" } }))
      .then((u) => {
        if (live) setSrc(u);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [link]);
  return (
    <div data-upi={link} className="mx-auto grid h-[220px] w-[220px] place-items-center rounded-xl border border-line bg-white p-2">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- data: URL generated in the browser
        <img src={src} width={200} height={200} alt={`UPI QR code to pay ${inr(amountPaise)}. Scan it with any UPI app.`} />
      ) : (
        <span className="h-[200px] w-[200px] animate-pulse rounded-lg bg-surface-sunken" aria-hidden="true" />
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line py-2 last:border-b-0">
      <dt className="shrink-0 text-sm text-fg-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2 text-right text-sm font-semibold text-fg-heading">{children}</dd>
    </div>
  );
}

export function PaymentNotConfigured({ subject }: { subject: string }) {
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-line bg-warning-subtle p-4 text-sm text-fg">
      <Icon name="alert" className="mt-0.5 h-5 w-5 shrink-0 text-warning-fg" />
      <p>
        Online payment details aren&apos;t set up yet — contact Tech Drona at{" "}
        <a className="font-semibold text-brand underline" href={`mailto:${SITE_INFO.email}?subject=${encodeURIComponent(subject)}`}>
          {SITE_INFO.email}
        </a>{" "}
        and we&apos;ll tell you how to pay.
      </p>
    </div>
  );
}

/**
 * Where to pay: a scannable UPI QR (amount + note filled in), the UPI ID with a copy button and an
 * "Open UPI app" link for phones; the payment number / bank details / instructions when set.
 */
export function PaymentPanel({ payment, amountPaise, note, subject }: { payment: PaymentInfo | null; amountPaise: number; note: string; subject: string }) {
  if (!payment || !(payment.upi_id || payment.phone || payment.bank_details)) return <PaymentNotConfigured subject={subject} />;
  const link = payment.upi_id && amountPaise > 0 ? upiLink(payment.upi_id, payment.payee_name, amountPaise, note) : "";
  const app = payment.preferred_app;
  return (
    <div className="space-y-4">
      {link ? (
        <div className="space-y-3 text-center">
          <UpiQr link={link} amountPaise={amountPaise} />
          <p className="text-sm text-fg-secondary">Scan with any UPI app{app ? ` (${app} preferred)` : ""}. The amount and note are filled in.</p>
          <a href={link} className={buttonClasses({ variant: "secondary", className: "w-full gap-1.5 sm:w-auto" })}>
            Open UPI app
            <Icon name="external" className="h-4 w-4" />
          </a>
        </div>
      ) : null}
      <dl className="rounded-xl border border-line bg-surface px-3">
        <Row label="Amount">
          <span>{inr(amountPaise)}</span>
        </Row>
        {payment.upi_id ? (
          <Row label="UPI ID">
            <code className="truncate">{payment.upi_id}</code>
            <CopyButton text={payment.upi_id} what="UPI ID" />
          </Row>
        ) : null}
        {payment.phone ? (
          <Row label={app ? `${app} number` : "Payment number"}>
            <code className="truncate">{payment.phone}</code>
            <CopyButton text={payment.phone} what="payment number" />
          </Row>
        ) : null}
        {payment.payee_name ? (
          <Row label="Payee">
            <span className="truncate">{payment.payee_name}</span>
          </Row>
        ) : null}
        <Row label="Note">
          <code className="truncate">{note}</code>
          <CopyButton text={note} what="payment note" />
        </Row>
      </dl>
      {payment.bank_details ? (
        <div className="rounded-xl border border-line p-3 text-sm">
          <p className="font-semibold text-fg-heading">Bank transfer (IMPS / NEFT)</p>
          <p className="mt-1 whitespace-pre-line text-fg-secondary">{payment.bank_details}</p>
          <p className="mt-1 text-fg-muted">Mention {note} in the transfer remarks.</p>
        </div>
      ) : null}
      {payment.instructions.map((t) => (
        <p key={t} className="whitespace-pre-line text-sm text-fg-secondary">
          {t}
        </p>
      ))}
      <p className="flex gap-2 text-xs text-fg-muted">
        <Icon name="shield" className="h-4 w-4 shrink-0" />
        Pay only to the details shown here. Never share your UPI PIN or OTP; we will never ask for it. After paying, take a screenshot of the success screen.
      </p>
    </div>
  );
}
