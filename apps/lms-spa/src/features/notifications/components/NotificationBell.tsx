"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import type { InboxResponse } from "../lib/types";
import { NOTIFICATIONS_CHANGED } from "./NotificationsInbox";

const POLL_MS = 120_000;

/**
 * Header bell with the unread count (NTF-01 `unread_count`, one-row page). Background polling
 * never triggers the global step-up / restriction / sign-in handling: a failed count is simply
 * not shown.
 */
export function NotificationBell({ href = "/app/notifications" }: { href?: string }) {
  const [count, setCount] = useState<number | null>(null);
  const pathname = usePathname();

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<InboxResponse>("me/notifications", {
        query: { unread_only: true, limit: 1 },
        handle: { stepUp: false, restriction: false, auth: false, sessionChoice: false },
      });
      setCount(typeof res.unread_count === "number" ? res.unread_count : null);
    } catch {
      setCount(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, pathname]);

  useEffect(() => {
    const onChange = () => void refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener(NOTIFICATIONS_CHANGED, onChange);
    document.addEventListener("visibilitychange", onVisible);
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    return () => {
      window.removeEventListener(NOTIFICATIONS_CHANGED, onChange);
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(t);
    };
  }, [refresh]);

  const label = count ? `Notifications, ${count} unread` : "Notifications";
  return (
    <Link
      href={href}
      aria-label={label}
      className="relative inline-flex h-touch w-touch items-center justify-center rounded-md text-fg-secondary hover:bg-surface-hover hover:text-fg focus-visible:shadow-focus focus-visible:outline-none"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      {count ? (
        <span aria-hidden="true" className="absolute -right-0.5 -top-0.5 min-w-[1.25rem] rounded-full bg-danger-solid px-1 text-center text-xs font-semibold leading-5 text-danger-on-solid">
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </Link>
  );
}
