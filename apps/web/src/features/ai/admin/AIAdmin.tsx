"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorState, FormField, Input, PageHeader, Select, Skeleton, StatTile, Table, Tabs, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useResource } from "@/features/account/lib/use-resource";
import { InlineProblem } from "@/features/admin/components/console-ui";
import { formatDateTime, humanize, problemFieldErrors } from "@/features/admin/lib/console";
import { AI_ADMIN_API } from "./endpoints";
import type { AISettingsOut, AISettingsPatch, AIUsageOut, OrgApp, OrgAppsOut } from "../types";

/* ----------------------------------------------------------------- helpers */

const nf = new Intl.NumberFormat("en-IN");
const fmtInt = (n: number) => nf.format(n);

export function formatUSD(value: string | number): string {
  const n = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(n);
}

/**
 * A required whole number in [min, max] (WS3: caps can no longer be cleared to "unlimited").
 * Returns the value, or an error message.
 */
export function parseCap(raw: string, min = 0, max = Number.MAX_SAFE_INTEGER): { value: number | null; error?: string } {
  const v = raw.trim();
  if (v === "") return { value: null, error: "Enter a value." };
  if (!/^\d+$/.test(v)) return { value: null, error: "Enter a whole number." };
  const n = Number(v);
  if (!Number.isSafeInteger(n) || n > max) return { value: null, error: `Enter a number no larger than ${fmtInt(max)}.` };
  if (n < min) return { value: null, error: `Enter at least ${fmtInt(min)}.` };
  return { value: n };
}

export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}


const FEATURE_LABELS: Record<string, string> = {
  question_generation: "Question drafting",
  grading: "Grading suggestions",
  tutor: "Learning tutor",
  path_generation: "Learning path drafts",
};

const CATEGORY_LABELS: Record<string, string> = { learning: "Learning apps", ai: "AI apps" };

/* --------------------------------------------------------------- page shell */

/** ADM-003 AI settings, authorized apps and AI usage for the whole platform (Admin, `/admin/ai`). */
export function AIAdmin() {
  return (
    <div>
      <PageHeader title="AI & apps" description="Control AI features, which apps learners and staff can use, and review AI usage." />
      <Tabs
        label="AI and apps sections"
        items={[
          { id: "settings", label: "AI settings", content: <AISettingsSection /> },
          { id: "apps", label: "Authorized apps", content: <AuthorizedAppsSection /> },
          { id: "usage", label: "Usage", content: <AIUsageSection /> },
        ]}
      />
    </div>
  );
}

/* ------------------------------------------------------------- AI settings */

/** Numeric limits with the api's bounds (apps/api/app/modules/ai/router.py `AISettingsPatch`). */
const CAP_FIELDS = {
  monthly_call_cap: { label: "Monthly call cap", hint: "AI calls per calendar month, whole platform", min: 0, max: 100_000_000 },
  monthly_token_cap: { label: "Monthly token cap", hint: "Tokens per calendar month, whole platform", min: 0, max: 10_000_000_000 },
  per_activity_default_cap: { label: "Tutor messages per activity (default)", hint: "Per learner, per assignment or activity, unless the activity sets its own limit", min: 0, max: 10_000 },
  tutor_per_minute: { label: "Tutor messages per minute", hint: "Per learner rate limit", min: 1, max: 1000 },
  tutor_per_day: { label: "Tutor messages per day", hint: "Per learner rate limit", min: 1, max: 100_000 },
  generate_per_hour: { label: "AI drafts per hour", hint: "Per staff member (questions and paths)", min: 1, max: 10_000 },
  generate_per_day: { label: "AI drafts per day", hint: "Per staff member (questions and paths)", min: 1, max: 100_000 },
} as const;

type CapField = keyof typeof CAP_FIELDS;
const CAP_KEYS = Object.keys(CAP_FIELDS) as CapField[];

type SettingsForm = { enabled: boolean; model: string } & Record<CapField, string>;

function toForm(s: AISettingsOut): SettingsForm {
  const caps = Object.fromEntries(CAP_KEYS.map((k) => [k, String(s.ai[k])])) as Record<CapField, string>;
  return { enabled: s.ai.enabled, model: s.ai.model, ...caps };
}

export function AISettingsSection() {
  const toast = useToast();
  const res = useResource<AISettingsOut>(AI_ADMIN_API.settings);
  const [current, setCurrent] = useState<AISettingsOut>();
  const [form, setForm] = useState<SettingsForm>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (res.data) {
      setCurrent(res.data);
      setForm(toForm(res.data));
    }
  }, [res.data]);

  if (res.error && !current) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!current || !form) return <Skeleton className="h-64 w-full" />;

  const serverErrors = problemFieldErrors(error);
  const fieldError = (k: string) => clientErrors[k] ?? serverErrors[k] ?? serverErrors[`body.${k}`];
  const set = <K extends keyof SettingsForm>(k: K, v: SettingsForm[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const models = current.allowed_models.includes(form.model) ? current.allowed_models : [form.model, ...current.allowed_models].filter(Boolean);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const body: AISettingsPatch = { enabled: form.enabled, model: form.model };
    for (const k of CAP_KEYS) {
      const p = parseCap(form[k], CAP_FIELDS[k].min, CAP_FIELDS[k].max);
      if (p.error || p.value === null) errs[k] = p.error ?? "Enter a value.";
      else body[k] = p.value;
    }
    setClientErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setError(null);
    try {
      const out = await api.patch<AISettingsOut>(AI_ADMIN_API.settings, body);
      if (out.kind === "approval_pending") toast.show({ title: "Sent for approval.", tone: "success" });
      else {
        setCurrent(out.data);
        setForm(toForm(out.data));
        toast.show({ title: "AI settings saved.", tone: "success" });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="AI settings">
      <form onSubmit={submit} noValidate className="space-y-5" aria-label="AI settings">
        <Checkbox
          label="AI features — question drafting, grading suggestions and the learning tutor"
          description="When off, every AI feature is unavailable to staff and learners."
          checked={form.enabled}
          onChange={(e) => set("enabled", e.target.checked)}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="Model" error={fieldError("model")}>
            {(f) => <Select {...f} value={form.model} onChange={(e) => set("model", e.target.value)} options={models.map((m) => ({ value: m, label: m }))} />}
          </FormField>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-fg">Provider</p>
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span>{humanize(current.provider.name)}</span>
              <Badge tone={current.provider.configured ? "success" : "warning"}>{current.provider.configured ? "Configured" : "Not configured"}</Badge>
            </p>
            <p className="text-xs text-fg-muted">Provider keys are managed in the server secret store and are never shown here.</p>
          </div>
          {CAP_KEYS.map((k) => (
            <FormField key={k} label={CAP_FIELDS[k].label} hint={CAP_FIELDS[k].hint} error={fieldError(k)} required>
              {(f) => <Input {...f} inputMode="numeric" value={form[k]} onChange={(e) => set(k, e.target.value)} />}
            </FormField>
          ))}
        </div>
        <InlineProblem error={error} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-fg-muted">Last updated: {formatDateTime(current.ai.updated_at)}</p>
          <Button type="submit" loading={busy}>
            Save AI settings
          </Button>
        </div>
      </form>
    </Card>
  );
}

/* --------------------------------------------------------- Authorized apps */

export function AuthorizedAppsSection() {
  const toast = useToast();
  const res = useResource<OrgAppsOut>(AI_ADMIN_API.apps);
  const [apps, setApps] = useState<OrgApp[]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (res.data) setApps(res.data.apps);
  }, [res.data]);

  if (res.error && !apps) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!apps) return <Skeleton className="h-64 w-full" />;
  if (!apps.length) return <EmptyState title="No apps available" description="No apps can be authorized yet." />;

  const groups = Array.from(new Set(apps.map((a) => a.category)));
  const toggle = (key: string, enabled: boolean) => setApps((list) => list?.map((a) => (a.app_key === key ? { ...a, enabled } : a)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await api.patch<OrgAppsOut>(AI_ADMIN_API.apps, { apps: Object.fromEntries(apps.map((a) => [a.app_key, a.enabled])) });
      if (out.kind === "approval_pending") toast.show({ title: "Sent for approval.", tone: "success" });
      else {
        setApps(out.data.apps);
        toast.show({ title: "Authorized apps saved.", tone: "success" });
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Authorized apps">
      <form onSubmit={submit} className="space-y-5" aria-label="Authorized apps">
        {groups.map((cat) => (
          <fieldset key={cat}>
            <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">{CATEGORY_LABELS[cat] ?? humanize(cat)}</legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {apps
                .filter((a) => a.category === cat)
                .map((a) => (
                  <div key={a.app_key} className="rounded-lg border border-line bg-surface p-3">
                    <Checkbox label={a.label} description={a.enabled ? "Enabled" : "Disabled"} checked={a.enabled} onChange={(e) => toggle(a.app_key, e.target.checked)} />
                  </div>
                ))}
            </div>
          </fieldset>
        ))}
        <InlineProblem error={error} />
        <div className="flex justify-end">
          <Button type="submit" loading={busy}>
            Save apps
          </Button>
        </div>
      </form>
    </Card>
  );
}

/* ------------------------------------------------------------------- Usage */

function CapMeter({ label, used, cap }: { label: string; used: number; cap: number | null }) {
  const pct = cap ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{label}</p>
      <p className="mt-1 font-display text-xl font-bold tabular-nums text-fg">
        {fmtInt(used)} <span className="text-sm font-normal text-fg-muted">/ {cap === null ? "Unlimited" : fmtInt(cap)}</span>
      </p>
      {cap !== null ? (
        <div role="progressbar" aria-label={`${label} used`} aria-valuemin={0} aria-valuemax={cap} aria-valuenow={Math.min(used, cap)} aria-valuetext={`${pct}% of cap`} className="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div className={pct >= 90 ? "h-full bg-danger-solid" : "h-full bg-brand"} style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}

type FeatureRow = AIUsageOut["by_feature"][number];
type DayRow = AIUsageOut["by_day"][number];

export function AIUsageSection() {
  const [month, setMonth] = useState(currentMonth());
  const res = useResource<AIUsageOut>(/^\d{4}-\d{2}$/.test(month) ? AI_ADMIN_API.usage(month) : null);
  const u = res.data;

  const featureCols: Column<FeatureRow>[] = [
    { key: "feature", header: "Feature", cell: (r) => FEATURE_LABELS[r.feature] ?? humanize(r.feature) },
    { key: "calls", header: "Calls", align: "right", cell: (r) => fmtInt(r.calls) },
    { key: "in", header: "Tokens in", align: "right", cell: (r) => fmtInt(r.tokens_in) },
    { key: "out", header: "Tokens out", align: "right", cell: (r) => fmtInt(r.tokens_out) },
    { key: "cost", header: "Est. cost", align: "right", cell: (r) => formatUSD(r.cost_estimate) },
  ];
  const maxTokens = Math.max(1, ...(u?.by_day ?? []).map((d) => d.tokens));
  const dayCols: Column<DayRow>[] = [
    { key: "date", header: "Date", cell: (r) => r.date },
    { key: "calls", header: "Calls", align: "right", cell: (r) => fmtInt(r.calls) },
    { key: "tokens", header: "Tokens", align: "right", cell: (r) => fmtInt(r.tokens) },
    {
      key: "bar",
      header: <span className="sr-only">Relative tokens</span>,
      cell: (r) => (
        <div aria-hidden="true" className="h-2 w-24 overflow-hidden rounded-full bg-surface-sunken sm:w-40">
          <div className="h-full bg-brand" style={{ width: `${Math.round((r.tokens / maxTokens) * 100)}%` }} />
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="max-w-xs">
        <FormField label="Month">{(f) => <Input {...f} type="month" value={month} max={currentMonth()} onChange={(e) => setMonth(e.target.value)} />}</FormField>
      </div>
      {res.error ? (
        <ErrorState error={res.error} onRetry={() => void res.reload()} />
      ) : !u || res.loading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <>
          <p className="text-sm text-fg-muted">
            {u.period_start} to {u.period_end}
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <CapMeter label="Calls" used={u.totals.calls} cap={u.caps.monthly_call_cap} />
            <CapMeter label="Tokens" used={u.totals.tokens_in + u.totals.tokens_out} cap={u.caps.monthly_token_cap} />
            <StatTile label="Tokens in / out" value={`${fmtInt(u.totals.tokens_in)} / ${fmtInt(u.totals.tokens_out)}`} />
            <StatTile label="Estimated cost" value={formatUSD(u.totals.cost_estimate)} hint="Estimate in USD" />
          </div>
          <Card title="By feature">
            <Table caption="AI usage by feature" columns={featureCols} rows={u.by_feature} rowKey={(r) => r.feature} empty={{ title: "No AI usage this month" }} />
          </Card>
          <Card title="By day">
            <Table caption="AI usage by day" columns={dayCols} rows={u.by_day} rowKey={(r) => r.date} empty={{ title: "No AI usage this month" }} />
          </Card>
        </>
      )}
    </div>
  );
}
