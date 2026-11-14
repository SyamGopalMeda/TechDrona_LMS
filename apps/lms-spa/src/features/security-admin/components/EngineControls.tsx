"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, FormField, Input, LoadingBlock, Select, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ActionDialog, TextArea, textLink } from "@/features/admin/components/console-ui";
import { toOutcome } from "@/features/admin/lib/console";
import { staffRef } from "../lib/ids";
import type { EngineState } from "../lib/types";
import { useResource } from "@/lib/api/use-resource";
import { formatDateTime, formatTimeUntil } from "@/lib/format";

export function riskMode(s: EngineState | undefined): string | undefined {
  return s?.["risk.mode"];
}

/** Engine mode in words: "shadow" only records, "enforce" acts on accounts. */
export function modeLabel(mode: string | undefined): string {
  if (mode === "enforce") return "Enforcing";
  if (mode === "shadow") return "Watching only (shadow)";
  if (mode === "off") return "Off";
  return mode ? mode.charAt(0).toUpperCase() + mode.slice(1) : "—";
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
              Kill switch needs ratification {overdue ? "— overdue" : formatTimeUntil(dueAt)}
            </p>
            <p className="text-fg-secondary">
              Flipped {p.created_at ? formatDateTime(p.created_at) : ""}
              {p.requested_by ? ` by ${staffRef(p.requested_by)}` : ""}
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
  if (!state.data) return <LoadingBlock label="Loading engine state…" rows={1} size="card" className="mb-4" />;
  const s = state.data;
  const mode = riskMode(s);
  const hc = hcEnabled(s);
  const tripped = s.rules.filter((b) => b.circuit_breaker === "open");

  return (
    <>
      <RatificationBanner state={s} />
      <Card className="mb-4">
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Engine mode</dt>
            <dd className="mt-1">
              <Badge dot tone={mode === "enforce" ? "brand" : mode === "shadow" ? "info" : "neutral"}>
                {modeLabel(mode)}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Automatic restrictions</dt>
            <dd className="mt-1">
              {hc === undefined ? "—" : <Badge dot tone={hc ? "brand" : "neutral"}>{hc ? "On" : "Off"}</Badge>}
              <span className="mt-1 block text-xs text-fg-muted">High-confidence rules may restrict an account without a reviewer.</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Rule safety cut-outs</dt>
            <dd className="mt-1">
              {tripped.length ? <Badge dot tone="warning">Tripped: {tripped.map((b) => b.rule_key).join(", ")}</Badge> : <Badge dot tone="success">All normal</Badge>}
              <span className="mt-1 block text-xs text-fg-muted">A rule is paused automatically when it misfires too often.</span>
            </dd>
          </div>
        </dl>
        {mode === "shadow" ? <p className="mt-3 text-xs text-fg-muted">Watching only: sharing checks are recorded but no action is taken. Takeover protections and fixed device/session limits always apply.</p> : null}
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
          <Button variant="danger-secondary" size="sm" onClick={() => setOpen(true)}>
            Emergency stop…
          </Button>
          <p className="text-xs text-fg-muted">Use only if the engine is restricting accounts wrongly. It moves the engine to watching only within 60 seconds.</p>
        </div>
      </Card>
      <ActionDialog
        open={open}
        onClose={() => setOpen(false)}
        onOpen={() => {
          setTarget("risk_mode");
          setRuleKey("");
          setReason("");
        }}
        title="Emergency stop (kill switch)"
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
                { value: "risk_mode", label: "Whole engine → watching only (all sharing actions stop)" },
                { value: "hc_all", label: "Turn off all automatic restrictions" },
                { value: "rule", label: "One rule → watching only" },
              ]}
            />
          )}
        </FormField>
        {target === "rule" ? <FormField label="Rule key" required hint="As shown under Risk rules, e.g. HC-01">{(f) => <Input {...f} value={ruleKey} onChange={(e) => setRuleKey(e.target.value)} placeholder="HC-01" />}</FormField> : null}
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}</FormField>
      </ActionDialog>
    </>
  );
}
