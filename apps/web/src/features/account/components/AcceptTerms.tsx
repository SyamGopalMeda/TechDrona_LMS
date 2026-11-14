"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button, Checkbox, LoadingBlock } from "@/components/ui";
import { api } from "@/lib/api/client";
import { FormAlert } from "@/features/auth/components/shared";
import { NOTICE_VERSION, REQUIRED_PURPOSES } from "@/features/auth/lib/consents";
import { toFormError, type FormErrorInfo } from "@/features/auth/lib/errors";
import type { ConsentChangeBody, ConsentsResponse } from "../lib/types";

/** Required purposes (terms, privacy notice, core service) this account has not granted yet. */
export async function missingRequiredConsents(): Promise<{ missing: string[]; notice: string } | null> {
  try {
    const res = await api.get<ConsentsResponse>("me/consents", { handle: { auth: false, restriction: false, sessionChoice: false, stepUp: false } });
    const granted = new Set((res.data ?? []).filter((c) => c.state === "granted").map((c) => c.purpose));
    return { missing: REQUIRED_PURPOSES.filter((p) => !granted.has(p)), notice: res.notice_version || NOTICE_VERSION };
  } catch {
    return null;
  }
}

/**
 * /accept-terms: an account created by an admin has not agreed to the Terms and Privacy Notice
 * yet, so the api answers `403 consent_required` on most pages. One tick grants the required
 * purposes (POST me/consents, exempt from that check), then on to `next`.
 */
export function AcceptTerms({ next }: { next: string }) {
  const router = useRouter();
  const [state, setState] = useState<{ missing: string[]; notice: string } | null | "loading">("loading");
  const [agree, setAgree] = useState(false);
  const [fieldErr, setFieldErr] = useState<string | undefined>();
  const [error, setError] = useState<FormErrorInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    void missingRequiredConsents().then((r) => {
      if (!live) return;
      // Nothing missing (or the check failed): nothing to ask here, carry on.
      if (!r || r.missing.length === 0) router.replace(next);
      else setState(r);
    });
    return () => {
      live = false;
    };
  }, [next, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (state === "loading" || !state) return;
    if (!agree) {
      setFieldErr("Tick the box to agree before you continue.");
      return;
    }
    setFieldErr(undefined);
    setBusy(true);
    setError(null);
    try {
      for (const purpose of state.missing) {
        const body: ConsentChangeBody = { purpose: purpose as ConsentChangeBody["purpose"], action: "granted", notice_version: state.notice };
        await api.post("me/consents", body, { idempotencyKey: true });
      }
      router.replace(next);
    } catch (err) {
      setError(toFormError(err));
      setTimeout(() => alertRef.current?.focus(), 0);
      setBusy(false);
    }
  };

  if (state === "loading" || !state) return <LoadingBlock label="Checking your account…" rows={1} size="row" />;

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormAlert ref={alertRef} error={error} />
      <Checkbox
        label={
          <>
            I agree to the{" "}
            <Link href="/legal/terms" className="text-fg-link underline" target="_blank">
              Terms of Use
            </Link>{" "}
            and{" "}
            <Link href="/legal/privacy" className="text-fg-link underline" target="_blank">
              Privacy Notice
            </Link>
          </>
        }
        aria-invalid={fieldErr ? true : undefined}
        checked={agree}
        onChange={(e) => setAgree(e.target.checked)}
      />
      {fieldErr ? (
        <p role="alert" className="text-sm text-danger-fg">
          {fieldErr}
        </p>
      ) : null}
      <Button type="submit" size="lg" className="w-full" loading={busy}>
        Continue
      </Button>
    </form>
  );
}
