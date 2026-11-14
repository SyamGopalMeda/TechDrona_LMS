"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button, Card, Checkbox, EmptyState, ErrorState, PageHeader, LoadingBlock, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { InlineProblem } from "@/features/admin/components/console-ui";
import { humanize } from "@/features/admin/lib/console";
import { AI_ADMIN_API } from "./endpoints";
import type { AIProviderStatusOut, OrgApp, OrgAppsOut } from "../types";
import { useResource } from "@/lib/api/use-resource";

const CATEGORY_LABELS: Record<string, string> = { learning: "Learning apps", ai: "AI apps" };

/* --------------------------------------------------------------- page shell */

/**
 * ADM-003 Apps (Admin, `/admin/ai`): which apps learners and staff can use, platform-wide.
 * The AI settings and Usage tabs were removed (feature-removal plan §3.14; the AI provider is
 * disabled). The api routes `admin/ai-settings` and `admin/ai-usage` are kept.
 */
export function AIAdmin() {
  return (
    <div>
      <PageHeader title="Apps" description="Choose which apps learners and staff can use." />
      <AuthorizedAppsSection />
    </div>
  );
}

/* --------------------------------------------------------- Authorized apps */

export function AuthorizedAppsSection() {
  const toast = useToast();
  const res = useResource<OrgAppsOut>(AI_ADMIN_API.apps);
  // AI apps do nothing without a configured provider, so their toggles are hidden until one is.
  const provider = useResource<AIProviderStatusOut>(AI_ADMIN_API.settings);
  const aiHidden = provider.data?.provider.configured === false;
  const [apps, setApps] = useState<OrgApp[]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (res.data) setApps(res.data.apps);
  }, [res.data]);

  if (res.error && !apps) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!apps) return <LoadingBlock label="Loading apps…" size="card" rows={3} />;
  if (!apps.length) return <EmptyState title="No apps available" description="No apps can be authorized yet." />;

  const groups = Array.from(new Set(apps.map((a) => a.category))).filter((c) => !(aiHidden && c === "ai"));
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
        {aiHidden ? <p className="text-sm text-fg-muted">AI apps are hidden because no AI provider is connected.</p> : null}
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
