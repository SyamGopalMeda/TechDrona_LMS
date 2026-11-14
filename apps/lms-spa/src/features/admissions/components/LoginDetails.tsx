"use client";

import { useState } from "react";
import { Button, Checkbox, Dialog, buttonClasses, useToast } from "@/components/ui";
import { useIntegrations } from "@/components/shell/Integrations";
import { api } from "@/lib/api/client";
import { ActionDialog } from "@/features/admin/components/console-ui";
import { toOutcome } from "@/features/admin/lib/console";
import { emailStatusText, loginMessage, whatsappLink, type LoginDetails, type LoginEmailResult } from "../lib/admissions";
import { formatDateTime } from "@/lib/format";

/**
 * The student's LMS login (username + temporary password) after "Verify & add to batch" or a
 * (re)sent login email. The password exists only in this response: it is shown once, never
 * stored, so staff copy or share it before closing.
 */

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyButton({ value, what }: { value: string; what: string }) {
  const toast = useToast();
  return (
    <Button
      size="sm"
      variant="secondary"
      aria-label={`Copy ${what}`}
      onClick={() =>
        void copyText(value).then((ok) => toast.show(ok ? { title: `${what[0]!.toUpperCase()}${what.slice(1)} copied.`, tone: "success" } : { title: "Couldn't copy. Select the text and copy it yourself.", tone: "warning" }))
      }
    >
      Copy
    </Button>
  );
}

function Row({ label, value, mono, copy }: { label: string; value: string; mono?: boolean; copy: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line py-2 last:border-b-0">
      <div className="min-w-0">
        <dt className="text-xs text-fg-secondary">{label}</dt>
        <dd className={mono ? "select-all break-all font-mono text-base font-semibold" : "break-all text-sm"}>{value}</dd>
      </div>
      <CopyButton value={value} what={copy} />
    </div>
  );
}

/** Who the login email (re)send dialog is for. */
export interface LoginTarget {
  registration_id: string;
  name: string;
  phone: string;
  course_title: string;
  batch_name?: string | null;
  account_username?: string | null;
  login_email_sent_at?: string | null;
}

/**
 * "Send login email" / "Resend login email": always makes a new temporary password (the old one
 * stops working), with the "change it on first login" choice. Without email it still makes the
 * new password so staff can share it themselves.
 */
export function SendLoginEmailDialog({ target, open, onClose, onDone }: { target: LoginTarget; open: boolean; onClose: () => void; onDone: (d: LoginDetails) => void }) {
  const integrations = useIntegrations();
  const noEmail = integrations?.email === false;
  const [mustChange, setMustChange] = useState(true);
  const first = !target.login_email_sent_at;
  const title = noEmail ? "Make a new temporary password" : first ? "Send login email" : "Resend login email";
  return (
    <ActionDialog<LoginEmailResult>
      open={open}
      onClose={onClose}
      onOpen={() => setMustChange(true)}
      title={title}
      description={
        <>
          A new temporary password is made for {target.account_username ? <span className="font-mono font-semibold">{target.account_username}</span> : target.name}
          {noEmail ? "" : ` and emailed to ${target.name}`}. <strong>The old password stops working.</strong>
          {first || noEmail ? null : ` Last login email: ${formatDateTime(target.login_email_sent_at)}.`}
        </>
      }
      submitLabel={noEmail ? "Make new password" : first ? "Send login email" : "Resend login email"}
      onSubmit={async () =>
        toOutcome(await api.post<LoginEmailResult>(`admin/admissions/registrations/${target.registration_id}/login-email`, { reset_password: true, must_change_password: mustChange }))
      }
      onDone={(o) => {
        if (o.kind === "ok" && o.data) {
          onDone({ registration_id: target.registration_id, name: target.name, phone: target.phone, course_title: target.course_title, batch_name: target.batch_name ?? null, ...o.data });
        }
      }}
    >
      {noEmail ? <p className="text-sm text-fg-secondary">Email isn&apos;t connected yet — you&apos;ll get the new login details to share yourself.</p> : null}
      <Checkbox label="Ask the student to change this password on first login" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
    </ActionDialog>
  );
}

/** Username, email, temporary password, login page, email status, copy / WhatsApp / (re)send. */
export function LoginDetailsPanel({ details, onUpdate }: { details: LoginDetails; onUpdate: (d: LoginDetails) => void }) {
  const toast = useToast();
  const [resend, setResend] = useState(false);
  const integrations = useIntegrations();
  const noEmail = integrations?.email === false;
  const { account, email } = details;
  const message = loginMessage(details);
  const sent = email.sent;
  return (
    <div className="space-y-4">
      {account.temporary_password ? (
        <p role="note" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          <span className="font-semibold">The password is shown only once.</span> Copy it or share it on WhatsApp now: it can&apos;t be shown again after you leave this page.
        </p>
      ) : (
        <p className="text-sm text-fg-secondary">This student already had an LMS account, so their password didn&apos;t change. Send a login email to give them a new temporary password.</p>
      )}
      <dl className="rounded-md bg-surface-sunken px-3">
        <Row label="Username" value={account.username} mono copy="username" />
        <Row label="Email" value={account.email} copy="email" />
        {account.temporary_password ? <Row label="Temporary password" value={account.temporary_password} mono copy="password" /> : null}
        <Row label="Login page" value={details.login_url} copy="login link" />
      </dl>
      {account.temporary_password ? (
        <p className="text-sm text-fg-secondary">{account.must_change_password ? "The student must choose a new password when they first log in." : "The student can keep this password."}</p>
      ) : null}
      <p role="status" className={sent ? "text-sm font-medium text-success-fg" : "text-sm font-medium text-warning-fg"}>
        {emailStatusText(details)}
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Button variant="secondary" onClick={() => void copyText(message).then((ok) => toast.show(ok ? { title: "Login details copied.", tone: "success" } : { title: "Couldn't copy. Select the text and copy it yourself.", tone: "warning" }))}>
          Copy all
        </Button>
        <a className={buttonClasses({ variant: "primary" })} href={whatsappLink(details.phone, message)} target="_blank" rel="noreferrer">
          Share on WhatsApp
        </a>
        <Button variant="secondary" onClick={() => setResend(true)}>
          {noEmail ? "New temporary password" : sent ? "Resend login email (new password)" : "Send login email"}
        </Button>
      </div>
      <SendLoginEmailDialog
        target={{ ...details, account_username: account.username, login_email_sent_at: sent ? new Date().toISOString() : null }}
        open={resend}
        onClose={() => setResend(false)}
        onDone={(d) => {
          setResend(false);
          onUpdate(d);
        }}
      />
    </div>
  );
}

/** The panel in a dialog (after verify, or after a (re)send from a list). Closing forgets the password. */
export function LoginDetailsDialog({ details, onClose, onUpdate }: { details: LoginDetails | null; onClose: () => void; onUpdate: (d: LoginDetails) => void }) {
  return (
    <Dialog
      open={details !== null}
      onClose={onClose}
      size="lg"
      title="Login details"
      description={details ? `${details.name} · ${details.course_title}${details.batch_name ? ` · ${details.batch_name}` : ""}` : undefined}
      footer={<Button onClick={onClose}>Done</Button>}
    >
      {details ? <LoginDetailsPanel details={details} onUpdate={onUpdate} /> : null}
    </Dialog>
  );
}
