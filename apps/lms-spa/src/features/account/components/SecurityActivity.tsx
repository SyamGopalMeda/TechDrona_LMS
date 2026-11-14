"use client";

import { Badge, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/features/auth/lib/format";
import { useAccountScope } from "../lib/account-scope";
import type { DevicePolicy, LoginHistory } from "../lib/types";
import { useResource } from "../lib/use-resource";

const METHOD: Record<string, string> = { password: "Password", totp: "Authenticator app", recovery_code: "Recovery code", otp_sms: "SMS code", otp_email: "Email code", passkey: "Passkey" };
/** verified: identity/router.py record_login_attempt outcomes */
const RESULT: Record<string, { label: string; tone: "success" | "warning" | "danger" | "info" }> = {
  success: { label: "Signed in", tone: "success" },
  mfa_required: { label: "Asked for 2-step code", tone: "info" },
  device_otp_required: { label: "New device check", tone: "info" },
  bad_credentials: { label: "Wrong password", tone: "warning" },
  mfa_failed: { label: "Wrong 2-step code", tone: "warning" },
  throttled: { label: "Too many attempts", tone: "warning" },
  locked: { label: "Locked", tone: "danger" },
  restricted: { label: "Blocked to protect you", tone: "danger" },
};

/** FR-SEC-009 / STU-022 published limits (`GET /me/device-policy`). */
export function DevicePolicyCard() {
  const p = useResource<DevicePolicy>("me/device-policy");
  // Video playback is a student limit: not shown to staff on the shared Devices page.
  const scope = useAccountScope();
  const rows: [string, number | string | null | undefined][] = p.data
    ? [
        ["Trusted devices", p.data.devices?.max_trusted],
        ["Device replacements per 30 days", p.data.devices?.max_replacements_per_30d],
        ["Trusted device expires after inactivity (days)", p.data.devices?.trusted_inactivity_expiry_days],
        ["Signed-in sessions at once", p.data.sessions?.max_concurrent],
        ["Signed out after inactivity (minutes)", p.data.sessions?.idle_minutes],
        ["Maximum session length (hours)", p.data.sessions?.absolute_hours],
        ...(scope && !scope.student ? [] : [["Videos playing at once", p.data.streams?.max_concurrent] as [string, number | null | undefined]]),
      ]
    : [];
  return (
    <Card title="Your account limits">
      {p.error ? (
        <ErrorState error={p.error} onRetry={p.reload} />
      ) : !p.data ? (
        <div aria-busy="true">
          <span className="sr-only">Loading…</span>
          <Skeleton className="h-16 w-full" />
        </div>
      ) : (
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {rows.map(([label, v]) => (
            <div key={label}>
              <dt className="text-fg-muted">{label}</dt>
              <dd className="font-medium text-fg">{v ?? "—"}</dd>
            </div>
          ))}
        </dl>
      )}
    </Card>
  );
}

/** Last 90 days of sign-in attempts (`GET /me/login-history`). */
export function LoginHistoryCard() {
  const h = useResource<LoginHistory>("me/login-history");
  const attempts = (h.data?.attempts ?? []).slice(0, 20);
  return (
    <Card title="Recent sign-in activity">
      {h.error ? (
        <ErrorState error={h.error} onRetry={h.reload} />
      ) : !h.data ? (
        <div aria-busy="true">
          <span className="sr-only">Loading…</span>
          <Skeleton className="h-16 w-full" />
        </div>
      ) : attempts.length === 0 ? (
        <EmptyState icon="shield" title="No sign-ins in the last 90 days" />
      ) : (
        <ul className="divide-y divide-line-subtle text-sm" aria-label="Sign-in attempts">
          {attempts.map((a, i) => (
            <li key={`${a.at}-${i}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className="text-fg">
                {formatDateTime(a.at)} · {METHOD[a.method] ?? a.method}
                {a.mfa_method ? ` + ${METHOD[a.mfa_method] ?? a.mfa_method.replace(/_/g, " ")}` : ""}
                {a.ip ? <span className="ml-2 text-fg-muted">{a.ip}</span> : null}
              </span>
              <Badge tone={RESULT[a.result]?.tone ?? "neutral"}>{RESULT[a.result]?.label ?? a.result.replace(/_/g, " ")}</Badge>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-fg-muted">Showing up to 20 of the last 90 days. If you don&apos;t recognise an attempt, change your password and review your devices.</p>
    </Card>
  );
}
