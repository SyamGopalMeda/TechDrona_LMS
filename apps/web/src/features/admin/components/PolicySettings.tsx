"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, Button, ErrorState, FormField, Input, PageHeader, Select, Skeleton, Table, Tabs, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Schema } from "@/lib/api-types";
import { useResource } from "@/features/account/lib/use-resource";
import { RatificationBanner, riskMode } from "@/features/security-admin/components/EngineControls";
import type { EngineState } from "@/features/security-admin/lib/types";
import { ActionDialog, TextArea, textLink } from "./console-ui";
import { humanize, problemFieldErrors, toOutcome } from "../lib/console";

/**
 * verified: app/modules/admin/policy.py setting_out + router.py list_settings (GET admin/policy-settings
 * returns {data}; `pending_changes` holds the ids of pending `policy.change` approval requests).
 */
export interface PolicySetting {
  setting_key: string;
  value: unknown;
  default: unknown;
  source: "platform_row" | "default";
  version: number;
  kind: "int" | "number" | "bool" | "enum" | "int_list" | "object" | "text";
  min_value: number | null;
  max_value: number | null;
  choices: string[] | null;
  plan_overridable: boolean;
  locked: boolean;
  pending_changes: string[];
}

const CATEGORY: Record<string, string> = {
  sessions: "Devices & sessions",
  devices: "Devices & sessions",
  playback: "Devices & sessions",
  commerce: "Refunds & commerce",
  grace: "Grace",
  otp: "OTP & login limits",
  login: "OTP & login limits",
  assessment: "Assessment",
  risk: "Risk engine",
  unblock: "Unblock",
};

export function categoryOf(key: string): string {
  return CATEGORY[key.split(".")[0] ?? ""] ?? "Other";
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Client-side bounds check (the api re-checks: `out_of_bounds`). Returns an error or the parsed value. */
export function parseProposed(s: PolicySetting, raw: string): { value?: unknown; error?: string } {
  const t = raw.trim();
  if (!t) return { error: "Enter a value." };
  switch (s.kind) {
    case "int":
    case "number": {
      const n = Number(t);
      if (Number.isNaN(n) || (s.kind === "int" && !Number.isInteger(n))) return { error: s.kind === "int" ? "Enter a whole number." : "Enter a number." };
      if (typeof s.min_value === "number" && n < s.min_value) return { error: `Min ${s.min_value}` };
      if (typeof s.max_value === "number" && n > s.max_value) return { error: `Max ${s.max_value}` };
      return { value: n };
    }
    case "bool":
      return t === "true" || t === "false" ? { value: t === "true" } : { error: "Choose true or false." };
    case "enum":
      return s.choices && !s.choices.includes(t) ? { error: `One of: ${s.choices.join(", ")}` } : { value: t };
    case "int_list":
    case "object":
      try {
        return { value: JSON.parse(t) as unknown };
      } catch {
        return { error: "Enter valid JSON." };
      }
    default:
      return { value: t };
  }
}

export interface PolicySettingsProps {
  /** Show only these namespaces (security reviewers propose for risk.*, sessions.*, …). */
  namespaces?: string[];
  eyebrow?: string;
  /** Show engine state (shadow banner + kill-switch ratification) — needs security.rule.read. */
  showEngine?: boolean;
  approvalsHref?: string;
}

/**
 * ADM-006 policy settings editor (ADM-07/ADM-09): bounds, locked keys, pending changes,
 * shadow mode, kill-switch ratification banner. Every change is Dual (`policy.change`):
 * the api answers 202 and another super admin approves within 72 h.
 */
export function PolicySettings({ namespaces, eyebrow = "ADM-006", showEngine = true, approvalsHref = "/admin/approvals" }: PolicySettingsProps) {
  const res = useResource<{ data: PolicySetting[] }>("admin/policy-settings");
  const engine = useResource<EngineState>(showEngine ? "security/engine/state" : null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<PolicySetting | null>(null);
  const [reason, setReason] = useState("");
  const [effective, setEffective] = useState("");
  const [scopeType, setScopeType] = useState("platform");
  const [scopeId, setScopeId] = useState("");
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  const all = useMemo(() => {
    const rows = res.data?.data ?? [];
    return namespaces ? rows.filter((r) => namespaces.some((n) => r.setting_key.startsWith(`${n}.`))) : rows;
  }, [res.data, namespaces]);

  const groups = useMemo(() => {
    const m = new Map<string, PolicySetting[]>();
    for (const r of all) {
      const c = categoryOf(r.setting_key);
      m.set(c, [...(m.get(c) ?? []), r]);
    }
    return [...m.entries()];
  }, [all]);

  const pendingCount = all.filter((r) => r.pending_changes.length > 0).length;
  const mode = riskMode(engine.data) ?? (all.find((r) => r.setting_key === "risk.mode")?.value as string | undefined);

  const columns: Column<PolicySetting>[] = [
    {
      key: "key",
      header: "Key",
      cell: (s) => (
        <span>
          <span className="font-mono text-xs">{s.setting_key}</span>
          {s.locked ? (
            <Badge className="ml-1" tone="neutral">
              <span aria-hidden="true">🔒 </span>Locked
            </Badge>
          ) : null}
          {s.source === "default" ? <span className="block text-xs text-fg-muted">Default value</span> : null}
        </span>
      ),
    },
    { key: "current", header: "Current", cell: (s) => <span className="tabular-nums">{show(s.value)}</span> },
    {
      key: "bounds",
      header: "Bounds",
      cell: (s) => (s.choices?.length ? s.choices.join(" / ") : typeof s.min_value === "number" || typeof s.max_value === "number" ? `${s.min_value ?? "−∞"}–${s.max_value ?? "∞"}` : "—"),
    },
    {
      key: "proposed",
      header: "Proposed",
      cell: (s) => {
        if (s.pending_changes.length) return <span className="text-xs text-fg-muted">See approvals</span>;
        const raw = drafts[s.setting_key] ?? "";
        const err = raw ? parseProposed(s, raw).error : undefined;
        const inputId = `p-${s.setting_key}`;
        return (
          <div className="min-w-[8rem]">
            <label htmlFor={inputId} className="sr-only">
              Proposed value for {s.setting_key}
            </label>
            {s.kind === "enum" || s.kind === "bool" ? (
              <Select
                id={inputId}
                value={raw}
                onChange={(e) => setDrafts((d) => ({ ...d, [s.setting_key]: e.target.value }))}
                placeholder="—"
                options={(s.kind === "bool" ? ["true", "false"] : (s.choices ?? [])).map((v) => ({ value: v, label: v }))}
              />
            ) : (
              <Input id={inputId} value={raw} aria-invalid={err ? true : undefined} aria-describedby={err ? `${inputId}-e` : undefined} onChange={(e) => setDrafts((d) => ({ ...d, [s.setting_key]: e.target.value }))} />
            )}
            {err ? (
              <p id={`${inputId}-e`} className="mt-1 text-xs font-medium text-danger-fg">
                {err}
              </p>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "status",
      header: "Status",
      cell: (s) =>
        s.pending_changes.length ? (
          <span className="text-xs">
            <Badge tone="warning">⏳ Pending ⇄</Badge>
            {s.pending_changes.length > 1 ? <span className="block text-fg-muted">{s.pending_changes.length} requests</span> : null}
          </span>
        ) : (
          <span className="text-xs text-fg-muted">{[s.plan_overridable ? "Plan" : null].filter(Boolean).join(" · ") || "Platform only"}</span>
        ),
    },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (s) => {
        const raw = drafts[s.setting_key] ?? "";
        const parsed = raw ? parseProposed(s, raw) : null;
        return s.pending_changes.length ? null : (
          <Button size="sm" variant="secondary" disabled={!parsed || !!parsed.error} onClick={() => setEditing(s)} aria-label={`Propose change to ${s.setting_key}`}>
            Propose
          </Button>
        );
      },
    },
  ];

  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;

  const parsed = editing ? parseProposed(editing, drafts[editing.setting_key] ?? "") : null;

  return (
    <div>
      <PageHeader
        eyebrow={eyebrow}
        title="Policy settings"
        description="Keys per account-security-and-risk-engine §3.2. Changes apply to new events only, within 60 s of approval."
        actions={
          <Link href={approvalsHref} className={textLink}>
            Pending approvals ({pendingCount})
          </Link>
        }
      />
      {showEngine ? <RatificationBanner state={engine.data} /> : null}
      {mode === "shadow" ? (
        <p role="status" className="mb-4 rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          <span aria-hidden="true">ⓘ </span>risk.mode is SHADOW: sharing evaluations are recorded without actions. Moving toward enforcement is a dual-approved change here; the emergency move to shadow is the kill switch.
        </p>
      ) : null}
      {!res.data ? (
        <Skeleton className="h-60 w-full" />
      ) : (
        <Tabs
          label="Policy categories"
          items={groups.map(([cat, rows]) => ({
            id: cat,
            label: cat,
            content: <Table caption={`${cat} settings`} columns={columns} rows={rows} rowKey={(r) => r.setting_key} />,
          }))}
        />
      )}

      <ActionDialog
        open={editing !== null}
        onClose={() => {
          setEditing(null);
          setServerErrors({});
        }}
        title={`Propose change · ${editing?.setting_key ?? ""}`}
        description="Another super admin must approve this. Requests expire after 72 h."
        submitLabel="Propose change"
        validate={() => (parsed?.error ? parsed.error : reason.trim().length < 10 ? "Give a change reason (10+ characters)." : scopeType !== "platform" && !scopeId.trim() ? "Enter the scope id." : null)}
        onSubmit={async () => {
          try {
            return toOutcome(
              await api.post(
                `admin/policy-settings/${encodeURIComponent(editing!.setting_key)}/changes`,
                { scope_type: scopeType as Schema<"ChangeIn">["scope_type"], scope_id: scopeType === "platform" ? null : scopeId.trim(), value: parsed?.value, effective_from: effective ? new Date(effective).toISOString() : null, change_reason: reason.trim() } satisfies Schema<"ChangeIn">,
                { idempotencyKey: true },
              ),
            );
          } catch (err) {
            setServerErrors(problemFieldErrors(err));
            throw err;
          }
        }}
        onDone={() => {
          setReason("");
          void res.reload();
        }}
      >
        {editing ? (
          <p className="text-sm text-fg">
            {editing.setting_key}: <span className="font-semibold">{show(editing.value)}</span> → <span className="font-semibold">{show(parsed?.value)}</span>
          </p>
        ) : null}
        <FormField label="Scope" error={serverErrors.scope_type}>
          {(f) => (
            <Select
              {...f}
              value={scopeType}
              onChange={(e) => setScopeType(e.target.value)}
              options={[
                { value: "platform", label: "Platform" },
                { value: "plan", label: "Plan", disabled: !editing?.plan_overridable },
              ]}
            />
          )}
        </FormField>
        {scopeType !== "platform" ? <FormField label="Scope id" required>{(f) => <Input {...f} value={scopeId} onChange={(e) => setScopeId(e.target.value)} />}</FormField> : null}
        <FormField label="Effective from" hint="Optional; defaults to on approval" error={serverErrors.effective_from}>
          {(f) => <Input {...f} type="datetime-local" value={effective} onChange={(e) => setEffective(e.target.value)} />}
        </FormField>
        <FormField label="Change reason" required error={serverErrors.change_reason ?? serverErrors.value}>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}
        </FormField>
        <p className="text-xs text-fg-muted">{humanize("changes_apply_to_new_events_only")}.</p>
      </ActionDialog>
    </div>
  );
}
