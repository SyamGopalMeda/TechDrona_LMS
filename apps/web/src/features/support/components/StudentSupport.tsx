"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, FormField, Input, PageHeader, Pagination, Select, Skeleton, ErrorState, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { InlineProblem, KeyValueList, TextArea, linkButton, textLink } from "@/features/admin/components/console-ui";
import { formatDateTime, problemFieldErrors, useCursorList, useVersioned } from "@/features/admin/lib/console";
import { CATEGORY_LABELS, SUPPORT_ATTACHMENT_MAX_BYTES, SUPPORT_ATTACHMENT_MAX_COUNT, SUPPORT_ATTACHMENT_TYPES, TICKET_CATEGORIES, UUID_RE, topicToCategory, type Ticket, type TicketCategory, type TicketMessage, type TicketThread } from "../lib/types";
import { AttachmentList, MessageThread, TicketStatusBadge } from "./Thread";
import { uploadSupportAttachments, type UploadedAttachment } from "../lib/attachments";

/* ------------------------------------------------------------------- List */

/** STU-025 my support tickets (SUP-02). */
export function MyTickets() {
  const list = useCursorList<Ticket>("me/support/tickets");
  const cols: Column<Ticket>[] = [
    {
      key: "num",
      header: "Ticket",
      cell: (t) => (
        <Link className={textLink} href={`/app/support/${t.ticket_id}`}>
          {t.ticket_number}
        </Link>
      ),
    },
    { key: "subject", header: "Subject", cell: (t) => t.subject },
    { key: "cat", header: "Topic", cell: (t) => CATEGORY_LABELS[t.category] ?? t.category },
    { key: "status", header: "Status", cell: (t) => <TicketStatusBadge status={t.status} /> },
    { key: "updated", header: "Last update", cell: (t) => formatDateTime(t.updated_at) },
  ];
  return (
    <div>
      <PageHeader
        title="Support"
        description="Ask us for help with your account, payments, courses or tests."
        actions={
          <Link className={linkButton} href="/app/support/new">
            New ticket
          </Link>
        }
      />
      <Table caption="My tickets" columns={cols} rows={list.rows} rowKey={(t) => t.ticket_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No tickets yet", description: "When you contact support, your conversations appear here." }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
    </div>
  );
}

/* ------------------------------------------------------------------ Create */

interface ClientContext {
  route: string;
  browser: string;
  os: string;
}

function detectContext(from: string | undefined): ClientContext {
  const ua = typeof navigator !== "undefined" ? navigator.userAgent : "";
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Other";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad|iOS/.test(ua) ? "iOS" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "Other";
  const route = from && from.startsWith("/") ? from.slice(0, 200) : "/app/support/new";
  return { route, browser, os };
}

/** STU-025 new ticket (SUP-01). Browser, OS and the page you came from are attached and shown before sending. */
export function NewTicketForm({ from, topic, attemptId }: { from?: string; topic?: string; attemptId?: string }) {
  const router = useRouter();
  const toast = useToast();
  const [category, setCategory] = useState<TicketCategory | "">(() => topicToCategory(topic));
  const relatedAttemptId = attemptId && UUID_RE.test(attemptId) ? attemptId : null;
  const [files, setFiles] = useState<File[]>([]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [attachContext, setAttachContext] = useState(true);
  const [ctx, setCtx] = useState<ClientContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => setCtx(detectContext(from)), [from]);

  const submit = async () => {
    const e: Record<string, string> = {};
    if (!category) e.category = "Choose a topic.";
    if (subject.trim().length < 3) e.subject = "Enter a subject (3+ characters).";
    if (body.trim().length < 10) e.body = "Describe the problem (10+ characters).";
    const fileError = checkFiles(files);
    if (fileError) e.attachments = fileError;
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    setError(null);
    try {
      const attachments: UploadedAttachment[] = files.length ? await uploadSupportAttachments(files) : [];
      const res = await api.post<Ticket>(
        "support/tickets",
        {
          category,
          subject: subject.trim(),
          body: body.trim(),
          ...(attachments.length ? { attachments } : {}),
          ...(relatedAttemptId ? { related_attempt_id: relatedAttemptId } : {}),
          ...(attachContext && ctx ? { context: ctx } : {}),
        },
        { idempotencyKey: true },
      );
      if (res.kind === "ok") {
        toast.show({ title: `Ticket ${res.data.ticket_number} created.`, tone: "success" });
        router.push(`/app/support/${res.data.ticket_id}`);
      }
    } catch (err) {
      setErrors(problemFieldErrors(err));
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const rateLimited = error instanceof ApiError && error.code === "rate_limited";

  return (
    <div>
      <PageHeader title="New support ticket" />
      <Card className="max-w-2xl">
        <form
          className="space-y-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <FormField label="Topic" required error={errors.category}>
            {(f) => <Select {...f} value={category} onChange={(e) => setCategory(e.target.value as TicketCategory)} options={[{ value: "", label: "Choose a topic" }, ...TICKET_CATEGORIES.map((c) => ({ value: c, label: CATEGORY_LABELS[c] }))]} />}
          </FormField>
          {category === "account_access" || category === "device_reset" ? (
            <p className="text-sm text-fg-muted">
              If your account is restricted, you can also{" "}
              <Link className={textLink} href="/unblock-request">
                request a review
              </Link>
              .
            </p>
          ) : null}
          <FormField label="Subject" required error={errors.subject}>
            {(f) => <Input {...f} value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} />}
          </FormField>
          <FormField label="What happened?" required error={errors.body} hint="Never share your password or one-time codes.">
            {(f) => <TextArea {...f} value={body} onChange={(e) => setBody(e.target.value)} maxLength={5000} />}
          </FormField>
          {relatedAttemptId ? <p className="text-sm text-fg-muted">This ticket will be linked to your test attempt so our team can review it.</p> : null}
          <FormField label="Attachments (optional)" error={errors.attachments} hint={`Up to ${SUPPORT_ATTACHMENT_MAX_COUNT} files, 10 MB each: PDF, PNG, JPEG, WebP or text.`}>
            {(f) => (
              <input
                {...f}
                type="file"
                multiple
                accept={SUPPORT_ATTACHMENT_TYPES.join(",")}
                className="block text-sm"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              />
            )}
          </FormField>
          {ctx ? (
            <div className="rounded-lg border border-line bg-surface-sunken p-3 text-sm">
              <label className="flex items-center gap-2 font-medium">
                <input type="checkbox" checked={attachContext} onChange={(e) => setAttachContext(e.target.checked)} />
                Attach technical details to help us
              </label>
              <p className="mt-1 text-fg-muted">
                Browser: {ctx.browser} · System: {ctx.os} · Page: {ctx.route}
              </p>
            </div>
          ) : null}
          {rateLimited ? <p role="alert" className="text-sm font-medium text-danger-fg">You have opened many tickets today. Please reply on an existing ticket or try again tomorrow.</p> : <InlineProblem error={Object.keys(errors).length ? null : error} />}
          <div className="flex gap-2">
            <Button type="submit" loading={busy}>
              Send
            </Button>
            <Link className={linkButton} href="/app/support">
              Cancel
            </Link>
          </div>
        </form>
      </Card>
    </div>
  );
}

function checkFiles(files: File[]): string | null {
  if (files.length > SUPPORT_ATTACHMENT_MAX_COUNT) return `Attach at most ${SUPPORT_ATTACHMENT_MAX_COUNT} files.`;
  const badType = files.find((f) => !(SUPPORT_ATTACHMENT_TYPES as readonly string[]).includes(f.type));
  if (badType) return `${badType.name}: only PDF, PNG, JPEG, WebP or text files can be attached.`;
  const tooBig = files.find((f) => f.size > SUPPORT_ATTACHMENT_MAX_BYTES);
  if (tooBig) return `${tooBig.name} is larger than 10 MB.`;
  return null;
}

/* ------------------------------------------------------------------ Thread */

/** STU-025 ticket thread (SUP-03/04/05/06): reply, reopen a resolved ticket, rate the help. */
export function MyTicket({ ticketId }: { ticketId: string }) {
  const toast = useToast();
  const t = useVersioned<TicketThread>(`support/tickets/${encodeURIComponent(ticketId)}`);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [score, setScore] = useState("5");
  const [comment, setComment] = useState("");

  if (t.error) return <ErrorState error={t.error} onRetry={() => void t.reload()} />;
  if (!t.data) return <Skeleton className="h-60 w-full" />;
  const d = t.data;
  const done = d.status === "resolved" || d.status === "closed";

  const run = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      toast.show({ title: message, tone: "success" });
      await t.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title={d.subject} description={`${d.ticket_number} · ${CATEGORY_LABELS[d.category] ?? d.category}`} />
      <Card className="mb-4">
        <KeyValueList
          items={[
            { label: "Status", value: <TicketStatusBadge status={d.status} /> },
            { label: "Opened", value: formatDateTime(d.created_at) },
            { label: "We aim to reply by", value: d.first_responded_at ? "Replied" : formatDateTime(d.first_response_due_at) },
            ...(d.merged_into_id ? [{ label: "Continued in", value: <Link className={textLink} href={`/app/support/${d.merged_into_id}`}>another ticket</Link> }] : []),
          ]}
        />
      </Card>
      <Card title="Conversation" className="mb-4">
        <div className="mb-4 rounded-lg border border-line bg-surface-sunken p-3 text-sm">
          <p className="mb-1 text-xs font-semibold text-fg-secondary">You wrote</p>
          <p className="whitespace-pre-wrap break-words">{d.body}</p>
          <AttachmentList ticketId={d.ticket_id} refId="ticket" items={d.attachments} />
        </div>
        <MessageThread ticketId={d.ticket_id} messages={d.messages.filter((m) => m.visibility === "public")} viewer="requester" />
      </Card>
      <InlineProblem error={error} />
      {!done ? (
        <Card title="Reply" className="mt-4">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!reply.trim()) return;
              void run(async () => {
                await api.post<TicketMessage>(`support/tickets/${encodeURIComponent(ticketId)}/messages`, { body: reply.trim() }, { idempotencyKey: true });
                setReply("");
              }, "Reply sent.");
            }}
          >
            <FormField label="Your message">{(f) => <TextArea {...f} value={reply} onChange={(e) => setReply(e.target.value)} maxLength={10000} />}</FormField>
            <Button type="submit" loading={busy} disabled={!reply.trim()}>
              Send reply
            </Button>
          </form>
        </Card>
      ) : null}
      {d.status === "resolved" ? (
        <Card title="Still need help?" className="mt-4">
          <Button variant="secondary" loading={busy} onClick={() => void run(() => api.post<Ticket>(`support/tickets/${encodeURIComponent(ticketId)}/reopen`, {}, { idempotencyKey: true }), "Ticket reopened.")}>
            Reopen ticket
          </Button>
        </Card>
      ) : null}
      {done && d.csat_score === null ? (
        <Card title="How did we do?" className="mt-4">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() => api.post<Ticket>(`support/tickets/${encodeURIComponent(ticketId)}/csat`, { score: Number(score), comment: comment.trim() || null }, { idempotencyKey: true }), "Thanks for your feedback.");
            }}
          >
            <FormField label="Rating">
              {(f) => <Select {...f} value={score} onChange={(e) => setScore(e.target.value)} options={["5", "4", "3", "2", "1"].map((v) => ({ value: v, label: `${v} of 5` }))} />}
            </FormField>
            <FormField label="Comment (optional)">{(f) => <TextArea {...f} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} />}</FormField>
            <Button type="submit" loading={busy}>
              Send rating
            </Button>
          </form>
        </Card>
      ) : null}
      {d.csat_score !== null ? <p className="mt-4 text-sm text-fg-muted">You rated this {d.csat_score} of 5. Thank you.</p> : null}
    </div>
  );
}
