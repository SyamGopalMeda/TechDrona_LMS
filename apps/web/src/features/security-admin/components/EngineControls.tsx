"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, Select, Skeleton, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useResource } from "@/features/account/lib/use-resource";
import { ActionDialog, TextArea, textLink } from "@/features/admin/components/console-ui";
import { formatCountdown, formatDateTime, toOutcome } from "@/features/admin/lib/console";
import type { EngineState } from "../lib/types";

export function riskMode(s: EngineState | undefined): string | undefined {
  return s?.["risk.mode"];
}

export function hcEnabled(s: EngineState | undefined): boolean | undefined {
  return s?.["risk.hc.auto_restrict_enabled"];
}

/**
 * 24 h ratification banner for kill-switch flips (SEC-42 → `risk.kill_switch.ratify`).
 * Unratified switches are not reverted automatically; this keeps them visible.
 */
export function RatificationBanner({ state }: { state: EngineState | undefined }) {
  const pending = state?.pending_ratifications ?? [];
  if (!pending.length) return null;
  return (
    <div role="alert" className="mb-4 space-y-2 rounded-lg border border-warning-border bg-warning-subtle p-4 text-sm">
      {pending.map((p) => {
        // verified: controls.py kill_switch — ratification is due 24 h after the request was created.
        const dueAt = p.created_at ? new Date(Date.parse(p.created_at) + 24 * 3_600_000).toISOString() : p.expires_at;
        const overdue = Date.parse(dueAt) < Date.now();
        return (
          <div key={p.approval_request_id}>
            <p className="font-semibold text-warning-fg">
              <span aria-hidden="true">⚠ </span>
              Kill switch needs ratification {overdue ? "— overdue" : formatCountdown(dueAt)}
            </p>
            <p className="text-fg-secondary">
              Flipped {p.created_at ? formatDateTime(p.created_at) : ""}
              {p.requested_by ? ` by ${p.requested_by}` : ""}
              {p.request_reason ? ` · “${p.request_reason}”` : ""}. A different approver must ratify within 24 h; the switch is not reverted automatically.{" "}
              <Link className={textLink} href="/security/approvals">
                Open approvals
              </Link>
            </p>
          </div>
        );
      })}
    </div>
  );
}

/** Engine state strip (SEC-43) + emergency kill switch (SEC-42, P5, single actor + 24 h ratification). */
export function EngineControls() {
  const toast = useToast();
  const state = useResource<EngineState>("security/engine/state");
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("risk_mode");
  const [ruleKey, setRuleKey] = useState("");
  const [reason, setReason] = useState("");

  if (state.error) return <ErrorState error={state.error} onRetry={() => void state.reload()} />;
  if (!state.data) return <Skeleton className="mb-4 h-16 w-full" />;
  const s = state.data;
  const mode = riskMode(s);
  const hc = hcEnabled(s);
  const tripped = s.rules.filter((b) => b.circuit_breaker === "open");

  return (
    <>
      <RatificationBanner state={s} />
      <Card className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">risk.mode</dt>
              <dd>
                <Badge tone={mode === "enforce" ? "brand" : mode === "shadow" ? "info" : "neutral"}>{mode ? mode.toUpperCase() : "—"}</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">HC auto-restrict</dt>
              <dd>{hc === undefined ? "—" : <Badge tone={hc ? "brand" : "neutral"}>{hc ? "ON" : "OFF"}</Badge>}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Circuit breakers</dt>
              <dd>{tripped.length ? <Badge tone="warning">⚠ {tripped.map((b) => b.rule_key).join(", ")} tripped</Badge> : <Badge tone="success">All closed</Badge>}</dd>
            </div>
          </dl>
          <Button variant="danger" onClick={() => setOpen(true)}>
            Kill switch
          </Button>
        </div>
        {mode === "shadow" ? <p className="mt-2 text-xs text-fg-muted">Shadow mode: sharing evaluations are recorded without actions. Takeover protections and deterministic caps always enforce.</p> : null}
      </Card>
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        title="Emergency kill switch"
        description="Moves toward safety only (shadow / off) and takes effect within 60 s. Restrictions already in force stay — use the bulk lift if they were wrong. Another approver must ratify within 24 h. Returning to enforcement is a dual-approved policy change."
        submitLabel="Flip kill switch"
        danger
        validate={() => (reason.trim().length < 10 ? "Describe why (10+ characters)." : target === "rule" && !ruleKey.trim() ? "Enter the rule key." : null)}
        onSubmit={async () => toOutcome(await api.post("security/engine/kill-switch", { target, ...(target === "rule" ? { rule_key: ruleKey.trim() } : {}), reason: reason.trim() }, { idempotencyKey: true }))}
        onDone={() => {
          setReason("");
          toast.show({ title: "Kill switch applied", description: "Ratification is now pending (24 h).", tone: "warning", duration: 0 });
          void state.reload();
        }}
      >
        <FormField label="Target" required>
          {(f) => (
            <Select
              {...f}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              options={[
                { value: "risk_mode", label: "risk.mode → shadow (all sharing actions stop)" },
                { value: "hc_all", label: "All high-confidence rules off" },
                { value: "rule", label: "One rule → shadow" },
              ]}
            />
          )}
        </FormField>
        {target === "rule" ? <FormField label="Rule key" required>{(f) => <Input {...f} value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} placeholder="HC-01" />}</FormField> : null}
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>
    </>
  );
}
