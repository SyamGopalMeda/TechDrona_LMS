"use client";

import { useState } from "react";
import { StatusBadge, Badge } from "@/components/ui";
import { cn } from "@/lib/ui/cn";
import { formatDateTime } from "@/features/admin/lib/console";
import { STATUS_LABELS, type AttachmentMeta, type TicketMessage, type TicketStatus } from "../lib/types";
import { attachmentDownloadUrl } from "../lib/attachments";

const AUTHOR: Record<TicketMessage["author_kind"], string> = { requester: "Requester", agent: "Support", system: "System" };

/** Ticket thread (oldest first). Internal notes only ever arrive for agent viewers. */
export function MessageThread({ ticketId, messages, viewer }: { ticketId: string; messages: TicketMessage[]; viewer: "requester" | "agent" }) {
  if (!messages.length) return <p className="text-sm text-fg-muted">No messages yet.</p>;
  return (
    <ol className="space-y-3" aria-label="Messages">
      {messages.map((m) => {
        const mine = viewer === "requester" ? m.author_kind === "requester" : m.author_kind === "agent";
        const label = viewer === "requester" && m.author_kind === "requester" ? "You" : AUTHOR[m.author_kind];
        return (
          <li
            key={m.message_id}
            className={cn(
              "rounded-lg border p-3 text-sm",
              m.visibility === "internal" ? "border-warning-border bg-warning-subtle" : mine ? "border-line bg-surface-sunken" : "border-line bg-surface",
            )}
          >
            <p className="mb-1 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <span className="font-semibold text-fg-secondary">{label}</span>
              <span>{formatDateTime(m.created_at)}</span>
              {m.visibility === "internal" ? <Badge tone="warning">Internal note</Badge> : null}
            </p>
            <p className="whitespace-pre-wrap break-words text-fg">{m.body}</p>
            <AttachmentList ticketId={ticketId} refId={m.message_id} items={m.attachments} />
          </li>
        );
      })}
    </ol>
  );
}

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  return <StatusBadge status={status} label={STATUS_LABELS[status] ?? status} />;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return "";
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/**
 * Files attached to the ticket (`refId="ticket"`) or to a message (`refId` = message id). Each
 * download asks the api for a short-lived URL (support/router.py attachment_download), so links
 * are never stored in the page.
 */
export function AttachmentList({ ticketId, refId, items }: { ticketId: string; refId: string; items?: AttachmentMeta[] }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  if (!items?.length) return null;
  const open = async (i: number) => {
    setBusy(i);
    setFailed(false);
    try {
      const url = await attachmentDownloadUrl(ticketId, refId, i);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="mt-2">
      <ul className="flex flex-wrap gap-2" aria-label="Attachments">
        {items.map((a, i) => (
          <li key={i}>
            <button type="button" className="rounded-md border border-line px-2 py-1 text-xs text-fg-link underline disabled:opacity-60" disabled={busy !== null} onClick={() => void open(i)}>
              {a.filename ?? `File ${i + 1}`}
              {a.size_bytes ? ` (${formatSize(a.size_bytes)})` : ""}
            </button>
          </li>
        ))}
      </ul>
      {failed ? (
        <p role="alert" className="mt-1 text-xs text-danger-fg">
          The file couldn&apos;t be opened. It may still be being scanned; try again shortly.
        </p>
      ) : null}
    </div>
  );
}
