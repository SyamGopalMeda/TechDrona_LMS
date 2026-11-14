"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Badge, Icon } from "@/components/ui";
import { buttonClasses } from "@/components/ui/Button";
import { formatDate } from "@/features/catalog/lib/format";
import { CLAIM_LABEL, inr, STATE_LABEL, type MyRegistration } from "../lib/registration";

const CLAIM_TONE = { pending: "info", needs_info: "warning", verified: "success", rejected: "danger", reversed: "neutral" } as const;

/** One registration as the student sees it: state, reason, money, payments, next action. */
export function RegistrationStatus({ reg, action, headingLevel = "h2" }: { reg: MyRegistration; action?: ReactNode; headingLevel?: "h2" | "h3" }) {
  const meta = STATE_LABEL[reg.state] ?? STATE_LABEL.pending;
  const H = headingLevel;
  return (
    <article aria-labelledby={`reg-${reg.registration_id}`} className="space-y-3 rounded-2xl border border-line bg-surface p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <H id={`reg-${reg.registration_id}`} className="font-display text-base font-bold text-fg-heading">
            {reg.course_title}
          </H>
          <p className="text-xs text-fg-muted">
            Registration <span className="font-mono">{reg.reg_no}</span>
            {reg.created_at ? ` · ${formatDate(reg.created_at)}` : ""}
          </p>
        </div>
        <Badge tone={meta.tone} dot>
          {meta.label}
        </Badge>
      </header>
      <p className="text-sm text-fg-secondary">{meta.text}</p>
      {reg.reason ? (
        <div role="note" className="rounded-xl bg-warning-subtle p-3 text-sm">
          <p className="font-semibold text-warning-fg">{reg.state === "needs_info" ? "What to correct" : "Reason"}</p>
          <p className="mt-0.5 whitespace-pre-line text-fg">{reg.reason}</p>
        </div>
      ) : null}
      <dl className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-surface-sunken px-2 py-2">
          <dt className="text-[0.7rem] font-semibold uppercase tracking-wide text-fg-muted">Fee</dt>
          <dd className="text-sm font-bold text-fg-heading">{inr(reg.fee_paise)}</dd>
        </div>
        <div className="rounded-lg bg-surface-sunken px-2 py-2">
          <dt className="text-[0.7rem] font-semibold uppercase tracking-wide text-fg-muted">Verified</dt>
          <dd className="text-sm font-bold text-fg-heading">{inr(reg.verified_total_paise)}</dd>
        </div>
        <div className="rounded-lg bg-surface-sunken px-2 py-2">
          <dt className="text-[0.7rem] font-semibold uppercase tracking-wide text-fg-muted">Balance</dt>
          <dd className="text-sm font-bold text-fg-heading">{inr(Math.max(0, reg.balance_paise))}</dd>
        </div>
      </dl>
      {reg.claims.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer font-semibold text-brand">Payments you submitted ({reg.claims.length})</summary>
          <ul className="mt-2 space-y-2">
            {reg.claims.map((c) => (
              <li key={c.claim_id} className="rounded-lg border border-line p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold">{inr(c.amount_paise)}</span>
                  <Badge tone={CLAIM_TONE[c.status] ?? "neutral"}>{CLAIM_LABEL[c.status] ?? c.status}</Badge>
                </div>
                <p className="text-xs text-fg-muted">
                  {c.utr ? `Ref ${c.utr}` : ""}
                  {c.paid_on ? ` · paid ${formatDate(c.paid_on)}` : ""}
                </p>
                {c.reason ? <p className="mt-1 text-xs text-fg-secondary">Note: {c.reason}</p> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {reg.enrolled || action ? (
        <div className="flex flex-wrap gap-2 pt-1">
          {reg.enrolled ? (
            <Link href={reg.course_href ?? "/app/learning"} className={buttonClasses({ size: "sm", className: "gap-1.5" })}>
              Open course
              <Icon name="arrowRight" className="h-4 w-4" />
            </Link>
          ) : null}
          {action}
        </div>
      ) : null}
    </article>
  );
}
