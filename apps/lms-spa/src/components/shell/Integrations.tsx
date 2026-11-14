"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

/**
 * Which outside services are really connected (GET public/integrations, no auth, booleans only).
 * Owner rule 2026-11-12: anything not integrated must SAY so by default, instead of pretending
 * ("We sent a code…" when no email can arrive). `null` = unknown (the check failed): show nothing.
 */
export type IntegrationKey = "email" | "sms" | "payments" | "ai" | "code_judge" | "video" | "website_sso";
export type Integrations = Partial<Record<IntegrationKey, boolean | null>> & {
  /**
   * Not a service: the owner's "simple authentication" switch (email + password only; no 2-step
   * verification, authenticator apps, device checks or session caps). Hides the removed features.
   */
  simple_auth?: boolean | null;
};

let cache: Promise<Integrations> | null = null;

/** Tests only. */
export function resetIntegrationsCache(): void {
  cache = null;
}

function load(): Promise<Integrations> {
  cache ??= api
    .get<{ integrations?: Integrations; simple_auth?: boolean }>("public/integrations", { handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false } })
    // The API sends simple_auth at the top level (next to `integrations`), not as a service.
    .then((r) => ({ ...(r.integrations ?? {}), ...(typeof r.simple_auth === "boolean" ? { simple_auth: r.simple_auth } : {}) }))
    .catch(() => {
      cache = null;
      return {};
    });
  return cache;
}

export function useIntegrations(): Integrations | null {
  const [state, setState] = useState<Integrations | null>(null);
  useEffect(() => {
    let live = true;
    void load().then((v) => {
      if (live) setState(v);
    });
    return () => {
      live = false;
    };
  }, []);
  return state;
}

/** `true` in simple-authentication mode, `false` when off, `null` while unknown (render as before). */
export function useSimpleAuth(): boolean | null {
  const st = useIntegrations();
  if (!st || typeof st.simple_auth !== "boolean") return null;
  return st.simple_auth;
}

export const INTEGRATION_LABELS: Record<IntegrationKey, string> = {
  email: "Email sending",
  sms: "SMS",
  payments: "Online payments",
  ai: "AI features",
  code_judge: "Code runner",
  video: "Video hosting",
  website_sso: "Website single sign-on",
};

const TEXT: Record<IntegrationKey, string> = {
  email: "Email sending isn't connected yet, so no email will arrive (sign-in codes, reset links, confirmations). Contact the Tech Drona admin for help.",
  sms: "SMS isn't connected yet, so no text message will arrive.",
  payments: "Online payments aren't connected yet. Pay by UPI or bank transfer as shown, and staff verify it.",
  ai: "AI isn't connected yet: it returns sample text, not real AI output.",
  code_judge: "The code runner isn't connected yet: code is not executed, so verdicts are not real.",
  video: "Video hosting isn't connected yet, so videos can't play.",
  website_sso: "Single sign-on to the website isn't set up yet. Sign in on the website with its own email and password.",
};

/** A "Not integrated yet" note for one service; renders nothing while connected or unknown. */
export function ServiceNotIntegrated({ service, text, className }: { service: IntegrationKey; text?: string; className?: string }) {
  const st = useIntegrations();
  if (!st || st[service] !== false) return null;
  return (
    <p role="note" className={`rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg ${className ?? ""}`}>
      <span className="font-semibold">Not integrated yet. </span>
      {text ?? TEXT[service]}
    </p>
  );
}
