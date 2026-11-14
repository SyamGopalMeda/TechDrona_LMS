"use client";

import { useState } from "react";
import { Button, FormField, Input } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import type { BoundElsewhere } from "../lib/types";
import { formatCountdown } from "@/lib/format";

export interface BoundElsewhereProps {
  testTitle: string | null;
  info: BoundElsewhere;
  remainingMs: number | null;
  onContinue: (otpCode: string | null) => Promise<void>;
  onSendOtp: () => Promise<void>;
  onGoBack: () => void;
}

/**
 * FR-SES-011 "This test is open on another device" (design-system §9.6). Read-only: no
 * answers can be changed here. Defaults to the safe choice (Go back is first in DOM order on
 * mobile only visually; primary is "Continue on this device" as the explicit action).
 */
export function BoundElsewhereView({ testTitle, info, remainingMs, onContinue, onSendOtp, onGoBack }: BoundElsewhereProps) {
  const [busy, setBusy] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canContinue = info.rebind_allowed !== false && !info.trainer_override_required && (info.rebinds_remaining ?? 1) > 0;
  const remaining = remainingMs === null ? "—" : formatCountdown(remainingMs / 1000);
  const left = info.rebinds_remaining;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(isApiError(e) ? e.detail : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto mt-10 max-w-lg rounded-xl border border-line bg-surface p-6 shadow-md" role="alertdialog" aria-labelledby="bound-title" aria-describedby="bound-body">
      <h1 id="bound-title" className="font-display text-xl font-semibold text-fg">
        This test is open on another device
      </h1>
      <p id="bound-body" className="mt-2 text-sm text-fg-secondary">
        <em>{testTitle ?? "This test"}</em> is in progress on {info.bound_device_label ?? "another device"}. The timer keeps running on our server:{" "}
        <strong className="font-mono tabular-nums">{remaining}</strong> left.
      </p>
      {info.trainer_override_required ? (
        <p className="mt-3 text-sm text-fg-secondary">This is a supervised drive. Ask your trainer to allow switching devices.</p>
      ) : canContinue ? (
        <p className="mt-3 text-sm text-fg-muted">
          Continuing here closes the test on the other device.
          {left !== undefined ? ` You can do this ${left} more time${left === 1 ? "" : "s"} for this test.` : null}
          {info.otp_required ? " We'll send a code to confirm it's you." : null}
        </p>
      ) : (
        <p className="mt-3 text-sm text-fg-secondary">You&apos;ve used all device switches for this test. Continue on the other device, or ask your trainer for help.</p>
      )}

      {canContinue && info.otp_required && otpSent ? (
        <div className="mt-4">
          <FormField label="6-digit code" hint="We sent it to your verified contact.">
            {(p) => <Input {...p} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />}
          </FormField>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger-fg">
          {error}
        </p>
      ) : null}

      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={onGoBack} disabled={busy}>
          Go back
        </Button>
        {canContinue ? (
          info.otp_required && !otpSent ? (
            <Button loading={busy} onClick={() => run(async () => { await onSendOtp(); setOtpSent(true); })}>
              Send code
            </Button>
          ) : (
            <Button loading={busy} disabled={info.otp_required && otp.length !== 6} onClick={() => run(() => onContinue(info.otp_required ? otp : null))}>
              Continue on this device
            </Button>
          )
        ) : null}
      </div>
    </div>
  );
}
