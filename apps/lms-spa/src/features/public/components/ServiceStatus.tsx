import { Badge } from "@/components/ui";
import type { ReadyDto } from "../lib/types";

export type CoreStatus = { kind: "operational"; checks: Record<string, "ok" | "fail">; release: string | null } | { kind: "unavailable"; status: number };

const CHECK_LABELS: Record<string, string> = { database: "Database", redis_cache: "Cache" };

/** Map the api readiness probe (GET /health/ready) to the status shown on PUB-020. */
export function coreStatusFrom(result: { ok: true; data: ReadyDto } | { ok: false; status: number }): CoreStatus {
  if (result.ok && result.data.status === "ok") return { kind: "operational", checks: result.data.checks ?? {}, release: result.data.release ?? null };
  return { kind: "unavailable", status: result.ok ? 503 : result.status };
}

/**
 * PUB-020 service status. Honest scope: only the core platform (api, database, cache) is
 * probed live, at page load. Code judge, video and payments have no public health signal
 * in the api yet, so they are listed as "not monitored here" rather than shown as green.
 */
export function ServiceStatus({ core, checkedAt }: { core: CoreStatus; checkedAt: string }) {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-2">
        <h1 className="font-display text-2xl font-bold text-fg sm:text-3xl">Service status</h1>
        <p className="text-sm text-fg-muted">Checked {checkedAt}. Reload the page to check again.</p>
      </header>
      <section aria-labelledby="status-core" className="space-y-3 rounded-lg border border-line bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="status-core" className="font-display text-lg font-semibold text-fg">
            Core platform
          </h2>
          <span role="status">
            {core.kind === "operational" ? <Badge tone="success">Operational</Badge> : <Badge tone="danger">Disruption</Badge>}
          </span>
        </div>
        {core.kind === "operational" ? (
          <ul className="space-y-1 text-sm text-fg-secondary">
            {Object.entries(core.checks).map(([k, v]) => (
              <li key={k}>
                {CHECK_LABELS[k] ?? k}: {v === "ok" ? "OK" : "Not responding"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-secondary">
            The platform did not pass its health check just now. Sign-in, courses and tests may not work. Please try again in a few minutes.
          </p>
        )}
      </section>
      <section aria-labelledby="status-other" className="space-y-2">
        <h2 id="status-other" className="font-display text-lg font-semibold text-fg">
          Code judge, video and payments
        </h2>
        <p className="text-sm text-fg-secondary">
          These services are not monitored on this page yet. If one of them is not working for you, open a support ticket from the help centre.
        </p>
      </section>
    </div>
  );
}
