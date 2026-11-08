"use client";

import { useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Skeleton, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { NOTICE_VERSION, PURPOSE_LABELS } from "@/features/auth/lib/consents";
import { toFormError } from "@/features/auth/lib/errors";
import { formatDate } from "@/features/auth/lib/format";
import type { ConsentChangeBody, ConsentsResponse } from "../lib/types";
import { useResource } from "../lib/use-resource";
import { PrivacyRequests } from "@/features/privacy/components/PrivacyRequests";

/** Purposes shown as toggles. `core_service` withdrawal is account closure (privacy flow), not a toggle. */
const TOGGLABLE: ConsentChangeBody["purpose"][] = ["security_monitoring", "analytics_personalisation", "marketing_email", "marketing_sms", "analytics_product"];

/** STU-023 Privacy & consent · ME-05 / ME-06 (one click per item, withdrawal always possible). */
export function PrivacySettings() {
  const toast = useToast();
  const consents = useResource<ConsentsResponse>("me/consents");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmWithdraw, setConfirmWithdraw] = useState<string | null>(null);

  const list = consents.data?.data ?? [];
  const notice = consents.data?.notice_version || NOTICE_VERSION;
  // Purposes unavailable to this account (adult-only items on under-18 accounts) are hidden.
  const rows = list.filter((c) => (TOGGLABLE as string[]).includes(c.purpose) && c.available !== false);

  const change = async (purpose: string, action: ConsentChangeBody["action"]) => {
    setBusy(purpose);
    try {
      const body: ConsentChangeBody = { purpose: purpose as ConsentChangeBody["purpose"], action, notice_version: notice };
      await api.post("me/consents", body, { idempotencyKey: true });
      toast.show({ tone: "success", title: action === "granted" ? "Turned on." : "Turned off. This takes effect within 24 hours." });
      setConfirmWithdraw(null);
      await consents.reload();
    } catch (err) {
      const e = toFormError(err);
      toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <Card title="Your choices">
        {consents.error ? (
          <ErrorState error={consents.error} onRetry={consents.reload} />
        ) : consents.loading && !consents.data ? (
          <div aria-busy="true" className="space-y-3">
            <span className="sr-only">Loading…</span>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState title="No optional choices for your account" description="Under-18 accounts don't have optional tracking or marketing." />
        ) : (
          <ul className="divide-y divide-line-subtle" aria-label="Consent choices">
            {rows.map((c) => {
              const meta = PURPOSE_LABELS[c.purpose] ?? { label: c.purpose.replace(/_/g, " "), description: "" };
              const on = c.state === "granted";
              return (
                <li key={c.purpose} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="max-w-prose text-sm">
                    <p className="font-medium text-fg">
                      {meta.label} <Badge tone={on ? "success" : "neutral"}>{on ? "On" : "Off"}</Badge>
                    </p>
                    <p className="mt-0.5 text-fg-muted">{meta.description}</p>
                    {c.effective_at ? <p className="mt-0.5 text-xs text-fg-muted">Since {formatDate(c.effective_at)}</p> : null}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={busy === c.purpose}
                    aria-label={`${on ? "Turn off" : "Turn on"} ${meta.label}`}
                    onClick={() => (on && c.purpose === "security_monitoring" ? setConfirmWithdraw(c.purpose) : change(c.purpose, on ? "withdrawn" : "granted"))}
                  >
                    {on ? "Turn off" : "Turn on"}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-3 text-xs text-fg-muted">Notice version {notice}. Changes take effect within 24 hours.</p>
      </Card>

      <PrivacyRequests />

      <Dialog
        open={confirmWithdraw !== null}
        onClose={() => setConfirmWithdraw(null)}
        dismissible={busy === null}
        title="Turn off account protection checks?"
        description="Device and session limits still apply. Your account moves to limits-only mode, and paid plans may require this setting — we'll explain your options, including ending the paid licence with a pro-rata refund."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmWithdraw(null)} disabled={busy !== null}>
              Keep it on
            </Button>
            <Button variant="danger" loading={busy !== null} onClick={() => confirmWithdraw && change(confirmWithdraw, "withdrawn")}>
              Turn off
            </Button>
          </>
        }
      />
    </div>
  );
}
