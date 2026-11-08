"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, FormField, Input, Skeleton, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { toFormError } from "@/features/auth/lib/errors";
import { formatDate, formatDateTime, formatRelative } from "@/features/auth/lib/format";
import { deviceName, type DeviceRenameBody, type DevicesResponse, type OwnDevice, type OwnSession, type SessionsResponse } from "../lib/types";
import { useResource } from "../lib/use-resource";

const END_REASONS: Record<string, string> = {
  user_logout: "Signed out",
  user_revoked_other: "Signed out from another device",
  session_cap_evicted: "Signed out when you signed in on another device",
  replaced_same_device: "Replaced by a newer sign-in in this browser",
  idle_timeout: "Timed out (inactive)",
  absolute_timeout: "Timed out",
  password_change: "Signed out after a password change",
  password_changed: "Signed out after a password change",
  mfa_changed: "Signed out after a 2-step verification change",
  device_removed: "Signed out when the device was removed",
  signed_out_everywhere: "Signed out everywhere",
  takeover_protect: "Signed out to protect your account",
  privilege_change: "Signed out after an access change",
  admin_kill: "Signed out by support",
  security_action: "Signed out for your account's security",
  unblock_reset: "Signed out after re-verification",
};

function trustBadge(status: string) {
  if (status === "trusted") return <Badge tone="success">Trusted</Badge>;
  if (status === "pending_otp" || status === "pending" || status === "pending_verification") return <Badge tone="warning">Pending verification</Badge>;
  if (status === "revoked" || status === "removed") return <Badge tone="neutral">Removed</Badge>;
  return <Badge>{status.replace(/_/g, " ")}</Badge>;
}

type Confirm =
  | { kind: "session"; session: OwnSession }
  | { kind: "others" }
  | { kind: "device"; device: OwnDevice };

/** STU-022 Devices & sessions · SES-01/02/03/04/05/06. */
export function DevicesAndSessions() {
  const toast = useToast();
  const devices = useResource<DevicesResponse>("me/devices");
  const sessions = useResource<SessionsResponse>("me/sessions");
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState(false);
  const [rename, setRename] = useState<{ device: OwnDevice; value: string; error?: string } | null>(null);

  const fail = (err: unknown, fallback: string) => {
    const e = toFormError(err, fallback);
    toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
  };

  const run = async () => {
    if (!confirm) return;
    setBusy(true);
    try {
      if (confirm.kind === "session") {
        await api.delete(`me/sessions/${encodeURIComponent(confirm.session.session_id)}`);
        toast.show({ tone: "success", title: `Signed out ${confirm.session.device_label}.` });
      } else if (confirm.kind === "others") {
        const res = await api.post<{ revoked?: number }>("me/sessions/revoke-others", {}, { idempotencyKey: true });
        const n = res.kind === "ok" ? res.data?.revoked : undefined;
        toast.show({ tone: "success", title: typeof n === "number" ? `Signed out ${n} other session${n === 1 ? "" : "s"}.` : "Signed out all other sessions." });
      } else {
        await api.delete(`me/devices/${encodeURIComponent(confirm.device.user_device_id)}`);
        toast.show({ tone: "success", title: `Removed ${deviceName(confirm.device)}.` });
      }
      setConfirm(null);
      await Promise.all([sessions.reload(), devices.reload()]);
    } catch (err) {
      if (err instanceof ApiError && err.code === "device_replacement_quota_exhausted") {
        toast.show({ tone: "warning", title: "You've used all your device changes for now", description: "Contact support to change a device.", requestId: err.requestId });
      } else fail(err, "That didn't work");
    } finally {
      setBusy(false);
    }
  };

  const saveRename = async () => {
    if (!rename) return;
    const value = rename.value.trim();
    // Backend RenameIn: user_label 1-60 characters; a label cannot be cleared once set.
    if (!value) {
      setRename({ ...rename, error: "Enter a name." });
      return;
    }
    if (value.length > 60) {
      setRename({ ...rename, error: "Use 60 characters or fewer." });
      return;
    }
    setBusy(true);
    try {
      await api.patch(`me/devices/${encodeURIComponent(rename.device.user_device_id)}`, { user_label: value } satisfies DeviceRenameBody);
      setRename(null);
      toast.show({ tone: "success", title: "Device renamed." });
      await devices.reload();
    } catch (err) {
      setRename({ ...rename, error: toFormError(err).title });
    } finally {
      setBusy(false);
    }
  };

  const limits = devices.data?.limits;
  const quotaExhausted = !!limits && limits.replacements_used_30d >= limits.replacements_max_30d;
  const allSessions = sessions.data?.data ?? [];
  const active = allSessions.filter((s) => s.status === "active");
  const ended = allSessions.filter((s) => s.status !== "active");
  const others = active.filter((s) => !s.is_current);

  const historyColumns: Column<OwnSession>[] = [
    { key: "device", header: "Device", cell: (s) => s.device_label },
    { key: "login", header: "Started", cell: (s) => formatDateTime(s.login_at) },
    { key: "logout", header: "Ended", cell: (s) => formatDateTime(s.logout_at) },
    { key: "where", header: "Approx. location", cell: (s) => s.approx_region ?? "—" },
    { key: "ip", header: "IP", cell: (s) => <span className="font-mono text-xs">{s.ip ?? "—"}</span> },
    { key: "why", header: "Reason", cell: (s) => (s.end_reason ? (END_REASONS[s.end_reason] ?? s.end_reason.replace(/_/g, " ")) : s.status) },
  ];

  return (
    <div className="space-y-6">
      <Card title="Our published limits">
        {limits ? (
          <>
            <p className="text-sm text-fg-secondary">
              {limits.max_trusted} devices · {limits.replacements_max_30d} device changes per 30 days. Verifying a device with a code does not exempt simultaneous use from two different networks (for example home and office).{" "}
              <Link href="/legal/device-policy" className="text-fg-link underline">
                Read the device policy
              </Link>
            </p>
            <p className="mt-2 text-sm font-medium text-fg">
              Device changes: {limits.replacements_used_30d} of {limits.replacements_max_30d} used
              {limits.next_replacement_at ? ` · next frees up on ${formatDate(limits.next_replacement_at)}` : ""}
            </p>
          </>
        ) : devices.loading ? (
          <Skeleton className="h-10 w-full" />
        ) : (
          <p className="text-sm text-fg-muted">
            <Link href="/legal/device-policy" className="text-fg-link underline">
              Read the device policy
            </Link>
          </p>
        )}
      </Card>

      <Card title={limits ? `Your devices (${limits.trusted_counted} of ${limits.max_trusted})` : "Your devices"}>
        {devices.error ? (
          <ErrorState error={devices.error} onRetry={devices.reload} />
        ) : devices.loading && !devices.data ? (
          <div aria-busy="true" className="space-y-3">
            <span className="sr-only">Loading devices…</span>
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : (devices.data?.data.length ?? 0) === 0 ? (
          <EmptyState title="No devices yet" description="Devices appear here after you sign in on them." />
        ) : (
          <ul className="divide-y divide-line-subtle" aria-label="Devices">
            {devices.data!.data.map((d) => (
              <li key={d.user_device_id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm">
                  <p className="font-medium text-fg">
                    {d.user_label && d.label ? `${d.user_label} · ${d.label}` : deviceName(d)}
                    {d.is_current ? <span className="ml-2 text-fg-muted">(this device)</span> : null}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-fg-muted">
                    {trustBadge(d.trust_status)}
                    {d.counts_toward_cap === false ? <Badge tone="info">Doesn&apos;t count toward your limit</Badge> : null}
                    <span>first seen {formatDate(d.first_seen_at)}</span>
                    <span>· last used {formatRelative(d.last_used_at)}</span>
                    {d.approx_region ? <span>· {d.approx_region} (approx.)</span> : null}
                    {d.group_hint?.startsWith("probably_this_computer") ? <span>· probably the same computer as another entry</span> : null}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setRename({ device: d, value: d.user_label ?? "" })} aria-label={`Rename ${deviceName(d)}`}>
                    Rename
                  </Button>
                  {d.counts_toward_cap !== false && quotaExhausted && !d.is_current ? (
                    <span className="self-center text-xs text-fg-muted">Contact support to change a device</span>
                  ) : d.counts_toward_cap !== false ? (
                    <Button variant="secondary" size="sm" onClick={() => setConfirm({ kind: "device", device: d })} aria-label={`Remove ${deviceName(d)}`}>
                      Remove device
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title={`Signed-in sessions${active.length ? ` (${active.length})` : ""}`}
        actions={
          others.length > 0 ? (
            <Button variant="secondary" size="sm" onClick={() => setConfirm({ kind: "others" })}>
              Sign out all other sessions
            </Button>
          ) : null
        }
      >
        {sessions.error ? (
          <ErrorState error={sessions.error} onRetry={sessions.reload} />
        ) : sessions.loading && !sessions.data ? (
          <div aria-busy="true" className="space-y-3">
            <span className="sr-only">Loading sessions…</span>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : active.length === 0 ? (
          <EmptyState title="No active sessions" />
        ) : (
          <ul className="divide-y divide-line-subtle" aria-label="Signed-in sessions">
            {active.map((s) => (
              <li key={s.session_id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm">
                  <p className="font-medium text-fg">
                    {s.is_current ? "This session · " : ""}
                    {s.device_label}
                  </p>
                  <p className="mt-0.5 text-fg-muted">
                    started {formatDateTime(s.login_at)} · active {formatRelative(s.last_active_at)}
                    {s.approx_region ? ` · ${s.approx_region} (approx.)` : ""}
                    {s.ip ? <> · IP <span className="font-mono">{s.ip}</span></> : null}
                  </p>
                </div>
                {!s.is_current ? (
                  <Button variant="secondary" size="sm" onClick={() => setConfirm({ kind: "session", session: s })} aria-label={`Sign out ${s.device_label}`}>
                    Sign out
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <section aria-labelledby="history-h" className="space-y-3">
        <h2 id="history-h" className="font-display text-base font-semibold text-fg">
          Recent sessions
        </h2>
        <Table
          caption="Recent sessions that have ended"
          columns={historyColumns}
          rows={sessions.data ? ended : undefined}
          rowKey={(s) => s.session_id}
          loading={sessions.loading && !sessions.data}
          error={sessions.error}
          onRetry={sessions.reload}
          empty={{ title: "No ended sessions in the last 90 days" }}
        />
        <p className="text-sm text-fg-muted">
          Don&apos;t recognise something?{" "}
          <Link href="/app/settings/security" className="text-fg-link underline">
            Change your password
          </Link>{" "}
          and sign out the sessions you don&apos;t know.
        </p>
      </section>

      <Dialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        dismissible={!busy}
        title={
          confirm?.kind === "session"
            ? `Sign out ${confirm.session.device_label}?`
            : confirm?.kind === "device"
              ? `Remove ${deviceName(confirm.device)}?`
              : "Sign out all other sessions?"
        }
        description={
          confirm?.kind === "session"
            ? "That device will need to sign in again. A test in progress there keeps its time on our server."
            : confirm?.kind === "device"
              ? `It will be signed out${limits ? ` and this counts as 1 of your ${limits.replacements_max_30d} device changes if you add a new device within 30 days` : ""}.`
              : "Every device except this one will be signed out. Tests in progress keep their time on our server."
        }
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={run}>
              {confirm?.kind === "device" ? "Remove device" : "Sign out"}
            </Button>
          </>
        }
      />

      <Dialog
        open={rename !== null}
        onClose={() => setRename(null)}
        dismissible={!busy}
        title="Rename device"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRename(null)} disabled={busy}>
              Cancel
            </Button>
            <Button loading={busy} onClick={saveRename}>
              Save
            </Button>
          </>
        }
      >
        {rename ? (
          <FormField label="Name" hint={rename.device.label ? `Shown with "${rename.device.label}".` : undefined} error={rename.error}>
            {(f) => <Input {...f} maxLength={60} value={rename.value} onChange={(e) => setRename({ ...rename, value: e.target.value, error: undefined })} />}
          </FormField>
        ) : null}
      </Dialog>
    </div>
  );
}
