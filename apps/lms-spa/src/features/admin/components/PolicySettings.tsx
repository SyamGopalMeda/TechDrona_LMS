"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, Button, ErrorState, FormField, Input, LoadingBlock, PageHeader, Select, StatusBadge, Table, Tabs, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Schema } from "@/lib/api-types";
import { RatificationBanner, riskMode } from "@/features/security-admin/components/EngineControls";
import type { EngineState } from "@/features/security-admin/lib/types";
import { ActionDialog, TextArea, textLink } from "./console-ui";
import { problemFieldErrors, toOutcome } from "../lib/console";
import { settingLabel } from "../lib/policy-labels";
import { useResource } from "@/lib/api/use-resource";
import { istLocalToIso } from "@/lib/time";

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
  grace: "Payment grace period",
  otp: "Sign-in & codes",
  login: "Sign-in & codes",
  assessment: "Tests",
  risk: "Account security",
  unblock: "Unblock requests",
};

export function categoryOf(key: string): string {
  return CATEGORY[key.split(".")[0] ?? ""] ?? "Other";
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (Array.isArray(v)) return v.length ? v.map(String).join(", ") : "None";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** "1 to 10", "At least 1", "Up to 10" (no ∞ symbols, which screen readers read as "infinity"). */
export function boundsText(s: Pick<PolicySetting, "choices" | "min_value" | "max_value" | "kind">): string {
  if (s.kind === "bool") return "On or off";
  if (s.choices?.length) return s.choices.join(" / ");
  const lo = typeof s.min_value === "number" ? s.min_value : null;
  const hi = typeof s.max_value === "number" ? s.max_value : null;
  if (lo !== null && hi !== null) return `${lo} to ${hi}`;
  if (lo !== null) return `At least ${lo}`;
  if (hi !== null) return `Up to ${hi}`;
  return "—";
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
      return t === "true" || t === "false" ? { value: t === "true" } : { error: "Choose on or off." };
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
export function PolicySettings({ namespaces, eyebrow, showEngine = true, approvalsHref = "/admin/approvals" }: PolicySettingsProps) {
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
      header: "Setting",
      cell: (s) => (
        <span>
          <span className="font-medium text-fg">{settingLabel(s.setting_key)}</span>
          {s.locked ? (
            <Badge className="ml-1" tone="neutral">
              Locked
            </Badge>
          ) : null}
          {s.source === "default" ? <span className="block text-xs text-fg-muted">Using the default</span> : null}
        </span>
      ),
    },
    { key: "current", header: "Current", cell: (s) => <span className="tabular-nums">{show(s.value)}</span> },
    { key: "bounds", header: "Allowed", priority: "secondary", cell: (s) => boundsText(s) },
    {
      key: "proposed",
      header: "Proposed",
      cell: (s) => {
        if (s.pending_changes.length) return <span className="text-xs text-fg-muted">See approvals</span>;
        if (s.locked) return <span className="text-xs text-fg-muted">Can&apos;t be changed here</span>;
        const raw = drafts[s.setting_key] ?? "";
        const err = raw ? parseProposed(s, raw).error : undefined;
        const inputId = `p-${s.setting_key}`;
        return (
          <div className="min-w-[8rem]">
            <label htmlFor={inputId} className="sr-only">
              Proposed value for {settingLabel(s.setting_key)}
            </label>
            {s.kind === "enum" || s.kind === "bool" ? (
              <Select
                id={inputId}
                value={raw}
                onChange={(e) => setDrafts((d) => ({ ...d, [s.setting_key]: e.target.value }))}
                placeholder="—"
                options={s.kind === "bool" ? [{ value: "true", label: "On" }, { value: "false", label: "Off" }] : (s.choices ?? []).map((v) => ({ value: v, label: v }))}
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
            <StatusBadge status="pending" label="Waiting for approval" />
            {s.pending_changes.length > 1 ? <span className="block text-fg-muted">{s.pending_changes.length} requests</span> : null}
          </span>
        ) : (
          <span className="text-xs text-fg-muted">{s.plan_overridable ? "Can differ by plan" : "Same for everyone"}</span>
        ),
    },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (s) => {
        const raw = drafts[s.setting_key] ?? "";
        const parsed = raw ? parseProposed(s, raw) : null;
        return s.pending_changes.length || s.locked ? null : (
          <Button size="sm" variant="secondary" disabled={!parsed || !!parsed.error} onClick={() => setEditing(s)} aria-label={`Propose change to ${settingLabel(s.setting_key)}`}>
            Propose
          </Button>
        );
      },
    },
  ];

  const description = "Limits and rules for sign-in, devices, video, tests and account security. Each change is approved in Approvals (by another admin, or by you while you are the only admin) and applies to new activity only.";
  if (res.error)
    return (
      <div>
        <PageHeader eyebrow={eyebrow} title="Policy settings" description={description} />
        <ErrorState error={res.error} onRetry={() => void res.reload()} />
      </div>
    );

  const parsed = editing ? parseProposed(editing, drafts[editing.setting_key] ?? "") : null;

  return (
    <div>
      <PageHeader
        eyebrow={eyebrow}
        title="Policy settings"
        description={description}
        actions={
          <Link href={approvalsHref} className={`${textLink} inline-flex min-h-touch items-center md:min-h-9`}>
            Pending approvals ({pendingCount})
          </Link>
        }
      />
      {showEngine ? <RatificationBanner state={engine.data} /> : null}
      {mode === "shadow" ? (
        <p role="status" className="mb-4 rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          <span aria-hidden="true">ⓘ </span>Account security is watching only: account sharing is recorded but nothing is blocked. Switching to enforcing is a change that needs a second approval here; the emergency stop on the Security overview switches back to watching only.
        </p>
      ) : null}
      {!res.data ? (
        <LoadingBlock label="Loading settings…" size="row" rows={6} />
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
        onOpen={() => {
          setReason("");
          setEffective("");
          setScopeType("platform");
          setScopeId("");
          setServerErrors({});
        }}
        title={`Change “${editing ? settingLabel(editing.setting_key) : "setting"}”`}
        description="Another admin must approve this within 72 hours before it takes effect."
        submitLabel="Propose change"
        validate={() =>
          parsed?.error
            ? parsed.error
            : reason.trim().length < 10
              ? "Give a change reason (10+ characters)."
              : scopeType !== "platform" && !scopeId.trim()
                ? "Enter the plan id."
                : effective && !istLocalToIso(effective)
                  ? "Enter a valid date and time, or leave it empty."
                  : null
        }
        onSubmit={async () => {
          try {
            return toOutcome(
              await api.post(
                `admin/policy-settings/${encodeURIComponent(editing!.setting_key)}/changes`,
                { scope_type: scopeType as Schema<"ChangeIn">["scope_type"], scope_id: scopeType === "platform" ? null : scopeId.trim(), value: parsed?.value, effective_from: istLocalToIso(effective), change_reason: reason.trim() } satisfies Schema<"ChangeIn">,
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
          <div className="space-y-1 text-sm text-fg">
            <p>
              From <span className="font-semibold">{show(editing.value)}</span> to <span className="font-semibold">{show(parsed?.value)}</span>
            </p>
            <p className="text-xs text-fg-muted">
              Setting key: <span className="font-mono">{editing.setting_key}</span>
            </p>
          </div>
        ) : null}
        <FormField label="Applies to" error={serverErrors.scope_type}>
          {(f) => (
            <Select
              {...f}
              value={scopeType}
              onChange={(e) => setScopeType(e.target.value)}
              options={[
                { value: "platform", label: "Everyone" },
                { value: "plan", label: "One plan only", disabled: !editing?.plan_overridable },
              ]}
            />
          )}
        </FormField>
        {scopeType !== "platform" ? <FormField label="Plan id" required>{(f) => <Input {...f} value={scopeId} onChange={(e) => setScopeId(e.target.value)} />}</FormField> : null}
        <FormField label="Effective from (IST)" hint="India time. Optional: leave empty to apply as soon as it is approved." error={serverErrors.effective_from}>
          {(f) => <Input {...f} type="datetime-local" value={effective} onChange={(e) => setEffective(e.target.value)} />}
        </FormField>
        <FormField label="Change reason" required error={serverErrors.change_reason ?? serverErrors.value}>
          {(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />}
        </FormField>
        <p className="text-xs text-fg-muted">Changes apply to new activity only, within a minute of approval.</p>
      </ActionDialog>
    </div>
  );
}
