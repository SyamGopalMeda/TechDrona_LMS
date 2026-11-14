"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Chip, EmptyState, ErrorState, LinkButton, LoadingBlock, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { toFormError } from "@/features/auth/lib/errors";
import { cn } from "@/lib/ui/cn";
import { renderNotification } from "../lib/templates";
import type { InboxItem, InboxResponse, MarkAllReadResponse } from "../lib/types";
import { formatDateTime } from "@/lib/format";

const PAGE_SIZE = 20;

/** Broadcast so the shell badge refreshes after reads in the inbox. */
export const NOTIFICATIONS_CHANGED = "td:notifications-changed";

/**
 * STU-024 in-app inbox (NTF-01 list, NTF-02 mark read, NTF-03 mark all read). Preferences
 * (NTF-04/05) are Planned in the api, so there is no preferences card (a dead "not available yet"
 * box); one line under the inbox says which notices are always sent.
 */
export function NotificationsInbox() {
  const toast = useToast();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busyAll, setBusyAll] = useState(false);
  const seq = useRef(0);

  const load = useCallback(
    async (more: boolean, after: string | null) => {
      const id = ++seq.current;
      if (more) setLoadingMore(true);
      else {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await api.get<InboxResponse>("me/notifications", {
          query: { unread_only: unreadOnly || undefined, cursor: more ? after : undefined, limit: PAGE_SIZE },
        });
        if (id !== seq.current) return;
        setItems((prev) => (more ? [...prev, ...res.data] : res.data));
        setUnread(res.unread_count);
        setCursor(res.page?.next_cursor ?? null);
        setHasMore(Boolean(res.page?.has_more));
      } catch (err) {
        if (id !== seq.current) return;
        if (more) {
          const e = toFormError(err);
          toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
        } else setError(err);
      } finally {
        if (id === seq.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [unreadOnly, toast],
  );

  useEffect(() => {
    void load(false, null);
  }, [load]);

  const changed = () => {
    if (typeof window !== "undefined") window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
  };

  const markRead = async (n: InboxItem) => {
    if (n.read_at) return;
    try {
      await api.post(`me/notifications/${encodeURIComponent(n.notification_id)}/read`, {});
      const now = new Date().toISOString();
      setItems((prev) => (unreadOnly ? prev.filter((x) => x.notification_id !== n.notification_id) : prev.map((x) => (x.notification_id === n.notification_id ? { ...x, read_at: now } : x))));
      setUnread((u) => Math.max(0, u - 1));
      changed();
    } catch (err) {
      const e = toFormError(err);
      toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
    }
  };

  const markAll = async () => {
    setBusyAll(true);
    try {
      const res = await api.post<MarkAllReadResponse>("me/notifications/read-all", {});
      toast.show({ tone: "success", title: res.kind === "ok" && res.data.marked ? `Marked ${res.data.marked} as read.` : "All caught up." });
      changed();
      await load(false, null);
    } catch (err) {
      const e = toFormError(err);
      toast.show({ tone: "danger", title: e.title, description: e.detail, requestId: e.requestId });
    } finally {
      setBusyAll(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Filter notifications" className="flex flex-wrap gap-2">
          <Chip active={!unreadOnly} onClick={() => setUnreadOnly(false)}>
            All
          </Chip>
          <Chip active={unreadOnly} onClick={() => setUnreadOnly(true)}>
            {`Unread${unread ? ` (${unread})` : ""}`}
          </Chip>
        </div>
        {/* Shown only when there is something to mark (no pale disabled button on an empty inbox). */}
        {unread > 0 ? (
          <Button variant="secondary" size="sm" loading={busyAll} onClick={() => void markAll()}>
            Mark all as read
          </Button>
        ) : null}
      </div>

      <Card title="Inbox">
        {error ? (
          <ErrorState error={error} title="We couldn't load your notifications" onRetry={() => void load(false, null)} />
        ) : loading && items.length === 0 ? (
          <LoadingBlock label="Loading notifications…" rows={2} size="row" />
        ) : items.length === 0 ? (
          <EmptyState
            variant="inline"
            icon={unreadOnly ? "check" : "bell"}
            title={unreadOnly ? "No unread notifications" : "No notifications yet"}
            description={unreadOnly ? "You're all caught up." : "Updates about your account, tests and batches appear here."}
          />
        ) : (
          <ul className="divide-y divide-line-subtle" aria-label="Notifications">
            {items.map((n) => {
              const r = renderNotification(n);
              const isUnread = !n.read_at;
              return (
                <li key={n.notification_id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 text-sm">
                    <p className={cn("text-fg", isUnread && "font-semibold")}>
                      {isUnread ? (
                        <>
                          <span aria-hidden="true" className="mr-1.5 inline-block h-2 w-2 rounded-full bg-brand align-middle" />
                          <span className="sr-only">Unread: </span>
                        </>
                      ) : null}
                      {r.title}
                      {n.priority === "high" || n.priority === "critical" ? (
                        <Badge tone="warning" className="ml-2">
                          Important
                        </Badge>
                      ) : null}
                    </p>
                    {r.body ? <p className="mt-0.5 whitespace-pre-line text-fg-secondary">{r.body}</p> : null}
                    <p className="mt-0.5 text-xs text-fg-muted">{formatDateTime(n.created_at)}</p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {r.href ? (
                      <LinkButton href={r.href} variant="secondary" size="sm" onClick={() => void markRead(n)}>
                        {r.linkLabel ?? "Open"}
                      </LinkButton>
                    ) : null}
                    {isUnread ? (
                      <Button variant="ghost" size="sm" aria-label={`Mark “${r.title}” as read`} onClick={() => void markRead(n)}>
                        Mark read
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {hasMore && !error ? (
          <div className="mt-4">
            <Button variant="secondary" size="sm" loading={loadingMore} onClick={() => void load(true, cursor)}>
              Load more
            </Button>
          </div>
        ) : null}
      </Card>

      <p className="text-sm text-fg-muted">
        Security and account notices are always sent. Marketing messages follow your{" "}
        <Link href="/app/settings/privacy" className="text-fg-link underline">
          privacy choices
        </Link>
        .
      </p>
    </div>
  );
}
