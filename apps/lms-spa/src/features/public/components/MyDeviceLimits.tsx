import type { DevicePolicyDto, PolicyValue } from "../lib/types";

function show(v: PolicyValue | undefined): string {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

/** The signed-in learner's own limits (GET /me/device-policy); policy overrides can differ from the defaults. */
export function MyDeviceLimits({ policy }: { policy: DevicePolicyDto }) {
  const rows: [string, string][] = [
    ["Trusted devices", show(policy.devices.max_trusted)],
    ["Signed-in sessions at the same time", show(policy.sessions.max_concurrent)],
    ["Videos playing at the same time", show(policy.streams.max_concurrent)],
    ["Device replacements per 30 days", show(policy.devices.max_replacements_per_30d)],
  ];
  return (
    <section aria-labelledby="sec-my-limits" className="space-y-2 rounded-lg border border-line bg-surface p-4">
      <h2 id="sec-my-limits" className="font-display text-lg font-semibold text-fg">
        Your account&apos;s current limits
      </h2>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 border-b border-line py-1.5">
            <dt className="text-fg-secondary">{k}</dt>
            <dd className="font-medium tabular-nums text-fg">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
