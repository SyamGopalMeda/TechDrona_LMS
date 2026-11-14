"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Button,
  Card,
  Checkbox,
  Dialog,
  EmptyState,
  ErrorState,
  FormField,
  Input,
  KeyValueList,
  LinkButton,
  LoadingBlock,
  PageHeader,
  Pagination,
  Select,
  StatGrid,
  StatTile,
  StatusBadge,
  Table,
  TextArea,
  useToast,
  type Column,
} from "@/components/ui";
import { api, apiRequestRaw } from "@/lib/api/client";
import { cn } from "@/lib/ui/cn";
import { ActionDialog, FilterBar, InlineProblem, textLink } from "@/features/admin/components/console-ui";
import { cleanQuery, formatINR, humanize, toOutcome, useCursorList } from "@/features/admin/lib/console";
import {
  CLAIM_LABEL,
  METHOD_LABEL,
  REG_LABEL,
  REG_STATUSES,
  approvalEnrols,
  upiLink,
  isImageProof,
  paiseToInput,
  regHref,
  toPaise,
  type ActionResult,
  type Claim,
  type ClaimStatus,
  type FeePlan,
  type Instalment,
  type Overview,
  type PaySettings,
  type PlansEnvelope,
  type RegStatus,
  type Registration,
  type RegistrationDetail,
  type LoginDetails,
  type VerifyEnrolResult,
} from "../lib/admissions";
import { useIntegrations } from "@/components/shell/Integrations";
import { CourseStatusSection } from "./CourseStatus";
import { LoginDetailsDialog, SendLoginEmailDialog, type LoginTarget } from "./LoginDetails";
import { useResource } from "@/lib/api/use-resource";
import { formatDate, formatDateTime } from "@/lib/format";

/**
 * Admin > Admissions: registrations, instalment fees and manual UPI payment verification moved
 * from the company website (owner decision 2026-11-11). Backend: /admin/admissions/* (payment.read,
 * payment.verify, payment.reverse, price.manage). A screenshot never verifies money: staff find the
 * payment in PhonePe / the bank account first, then approve the amount that actually arrived.
 */

const STATUS_TONE: Record<string, string> = {
  pending: "pending",
  needs_info: "warning",
  verified: "active",
  rejected: "rejected",
  reversed: "revoked",
};

export function RegBadge({ status }: { status: RegStatus }) {
  return <StatusBadge status={status === "enrolled" ? "active" : status} label={REG_LABEL[status] ?? humanize(status)} />;
}

export function ClaimBadge({ status }: { status: ClaimStatus }) {
  return <StatusBadge status={STATUS_TONE[status] ?? status} label={CLAIM_LABEL[status] ?? humanize(status)} />;
}

function useWarningToast() {
  const toast = useToast();
  return (res: ActionResult | undefined, done: string) => {
    if (res?.warning) toast.show({ title: res.warning, tone: "warning" });
    else if (res?.just_enrolled) toast.show({ title: `${done} The student is now enrolled.`, tone: "success" });
    else toast.show({ title: done, tone: "success" });
  };
}

/* ================================================================== overview */

/** `titles`: website course titles by slug (the page loads them from the website catalogue). */
export function AdmissionsOverview({ titles = {} }: { titles?: Record<string, string> }) {
  const res = useResource<Overview>("admin/admissions/overview");
  const o = res.data;
  const courseTitles: Record<string, string> = { ...Object.fromEntries((o?.courses ?? []).map((c) => [c.slug, c.title])), ...titles };
  const cols: Column<Overview["courses"][number]>[] = [
    { key: "title", header: "Course", cell: (c) => c.title },
    { key: "reg", header: "Registered", cell: (c) => c.registered, align: "right" },
    { key: "enr", header: "Enrolled", cell: (c) => c.enrolled, align: "right" },
    { key: "pend", header: "Waiting", cell: (c) => c.pending, align: "right" },
    { key: "col", header: "Collected", cell: (c) => formatINR(c.collected_paise), align: "right" },
    { key: "out", header: "Outstanding", cell: (c) => formatINR(c.outstanding_paise), align: "right", priority: "secondary" },
  ];
  return (
    <div>
      <PageHeader
        title="Admissions"
        description="Open or close course registration, verify payments and add students to their batch. Only payments you verify count."
        actions={
          <LinkButton href="/finance/admissions/verify">{o?.pending_claims ? `Verify payments (${o.pending_claims})` : "Verify payments"}</LinkButton>
        }
      />
      <div className="mb-6">
        <CourseStatusSection titles={courseTitles} />
      </div>
      {res.error && !o ? (
        <ErrorState error={res.error} onRetry={() => void res.reload()} />
      ) : !o ? (
        <LoadingBlock label="Loading admissions…" rows={4} />
      ) : (
        <div className="space-y-6">
          <StatGrid columns={4}>
            <StatTile label="Waiting for verification" value={String(o.pending_claims)} hint={formatINR(o.pending_amount_paise)} tone={o.pending_claims ? "warning" : "neutral"} href="/finance/admissions/verify" icon="clock" />
            <StatTile label="Registered" value={String(o.registered)} hint={`${o.enrolled} enrolled`} icon="users" href="/finance/admissions/registrations" />
            <StatTile label="Verified revenue" value={formatINR(o.collected_paise)} tone="highlight" />
            <StatTile label="Outstanding balance" value={formatINR(o.outstanding_paise)} hint={`of ${formatINR(o.expected_paise)} expected`} />
          </StatGrid>
          <StatGrid columns={3}>
            <StatTile size="compact" label="Correction requested" value={String(o.needs_info_claims)} tone={o.needs_info_claims ? "warning" : "neutral"} />
            <StatTile size="compact" label="Rejected payments" value={String(o.rejected_claims)} tone="neutral" />
            <StatTile size="compact" label="Rejected / cancelled registrations" value={String(o.closed_registrations)} tone="neutral" />
          </StatGrid>
          <Card title="Registrations by course" padding="none">
            <Table caption="Course figures" columns={cols} rows={o.courses} rowKey={(c) => c.slug} empty={{ title: "No registrations yet", description: "Course registrations appear here." }} />
          </Card>
          <Card title="Recent activity">
            {o.recent.length === 0 ? (
              <p className="text-sm text-fg-secondary">Nothing yet.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {o.recent.map((e) => (
                  <li key={e.event_id} className="flex flex-wrap gap-x-2">
                    <span className="text-fg-secondary">{formatDateTime(e.at)}</span>
                    <span className="font-semibold">{humanize(e.action)}</span>
                    <span>{e.detail}</span>
                    <span className="text-fg-muted">by {e.actor}</span>
                    {e.registration_id ? (
                      <Link className={textLink} href={regHref(e.registration_id)}>
                        Open
                      </Link>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

/* ================================================================== receipts */

const proofPath = (claimId: string) => `admin/admissions/claims/${claimId}/proof`;

/**
 * Opens a private file (PDF receipt, resume) in a new tab. The tab is opened inside the click
 * (phones block pop-ups opened after an await) and then pointed at the short-lived link.
 */
async function openPrivate(path: string): Promise<void> {
  const tab = typeof window.open === "function" ? window.open("", "_blank") : null;
  try {
    const out = await api.get<{ url: string }>(path);
    if (tab) {
      tab.opener = null;
      tab.location.href = out.url;
    } else {
      window.location.assign(out.url);
    }
  } catch (e) {
    tab?.close();
    throw e;
  }
}

/** The receipt image through the staff session (`/proof/file`), as a blob: URL the CSP allows. */
async function proofImageUrl(claimId: string): Promise<string> {
  const res = await apiRequestRaw(`${proofPath(claimId)}/file`, { headers: { accept: "image/*, application/problem+json" } });
  return URL.createObjectURL(await res.blob());
}

/**
 * The uploaded receipt: an image shows as a thumbnail that opens full size; a PDF opens in a new
 * tab. Each view is audited by the api.
 */
export function Receipt({ claim, size = "md" }: { claim: Claim; size?: "md" | "sm" }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [full, setFull] = useState(false);
  const urlRef = useRef<string | null>(null);
  const image = isImageProof(claim.proof_type);
  const auto = size === "md";

  const load = useCallback(async () => {
    setError(null);
    try {
      const next = await proofImageUrl(claim.claim_id);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = next;
      setUrl(next);
      return next;
    } catch (e) {
      setError(e);
      return null;
    }
  }, [claim.claim_id]);

  useEffect(() => {
    if (claim.has_proof && image && auto) void load();
  }, [claim.has_proof, image, auto, load]);
  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  if (!claim.has_proof) return <span className="text-sm text-fg-secondary">No receipt</span>;
  if (!image) {
    return (
      <Button size="sm" variant="secondary" onClick={() => void openPrivate(proofPath(claim.claim_id)).catch(setError)}>
        Open receipt (PDF)
      </Button>
    );
  }
  const openFull = async () => {
    if (url || (await load())) setFull(true);
  };
  return (
    <>
      {url && auto ? (
        <button type="button" onClick={() => setFull(true)} className="block h-32 w-24 shrink-0 overflow-hidden rounded-md border border-line bg-surface-sunken" aria-label={`Open the receipt of ${claim.registration?.name ?? "this payment"} full size`}>
          {/* eslint-disable-next-line @next/next/no-img-element -- blob: URL of a private file */}
          <img src={url} alt="Payment receipt" className="h-full w-full object-cover object-top" />
        </button>
      ) : auto && !error ? (
        <div className="grid h-32 w-24 shrink-0 place-items-center rounded-md border border-line bg-surface-sunken text-xs text-fg-secondary">Loading…</div>
      ) : (
        <Button size="sm" variant="secondary" onClick={() => void openFull()}>
          {error ? "Retry receipt" : "View receipt"}
        </Button>
      )}
      <Dialog open={full} onClose={() => setFull(false)} title="Payment receipt" description={`${formatINR(claim.amount_paise)} · UTR ${claim.utr ?? "—"} · paid ${formatDate(claim.paid_on)}`} size="xl">
        {/* eslint-disable-next-line @next/next/no-img-element -- blob: URL of a private file */}
        {url ? <img src={url} alt="Payment receipt, full size" className="mx-auto h-auto max-w-full" /> : null}
      </Dialog>
    </>
  );
}

/* ================================================================== claim actions */

type ClaimAction = "verify" | "needs-info" | "reject" | "reverse" | "release-locks";

/** What happened, in one line for a toast / the "just decided" list. */
function outcomeText(action: ClaimAction, res: ActionResult | undefined, reg: Registration | undefined): string {
  const who = reg?.name ?? "The student";
  if (action === "verify") {
    if (res?.already_verified) return "This payment was already approved. Nothing changed.";
    if (res?.just_enrolled) return `Approved. ${who} is now enrolled in ${reg?.course_title ?? "the course"}.${res.new_account ? " A new LMS account was created and a set-password link emailed." : ""}`;
    if (res?.registration?.enrolled_at) return "Approved. The student was already enrolled.";
    return `Approved. ${formatINR(res?.registration?.balance_paise)} still due before course access.`;
  }
  if (action === "reject") return "Payment rejected. The student is emailed your reason.";
  if (action === "needs-info") return "Correction requested. The student is emailed your message.";
  if (action === "reverse") return "Approval reversed.";
  return "Done.";
}

/** Login details from a verify-and-enrol result plus the registration it belongs to. */
function enrolDetails(res: VerifyEnrolResult, reg: Registration | undefined, regId: string): LoginDetails {
  return {
    registration_id: res.registration_id || regId,
    name: reg?.name ?? "the student",
    phone: reg?.phone ?? "",
    course_title: reg?.course_title ?? "the course",
    batch_name: res.batch?.name ?? null,
    account: res.account,
    email: res.email,
    login_url: res.login_url,
  };
}

/**
 * "Verify & add to batch": the payment is checked in PhonePe, then one click verifies it, adds the
 * student to the batch, makes their LMS account (random username + temporary password) and,
 * when email is connected, emails the login details.
 */
function VerifyEnrolDialog({ claim, reg, open, onClose, onEnrolled }: { claim: Claim; reg: Registration | undefined; open: boolean; onClose: () => void; onEnrolled: (d: LoginDetails) => void }) {
  const integrations = useIntegrations();
  const noEmail = integrations?.email === false;
  const plans = useResource<PlansEnvelope>(open ? "admin/admissions/plans" : null);
  const [amount, setAmount] = useState("");
  const [checked, setChecked] = useState(false);
  const [batch, setBatch] = useState<string | null>(null);
  const [mustChange, setMustChange] = useState(true);
  const [sendEmail, setSendEmail] = useState(true);
  const received = toPaise(amount);
  const plan = plans.data?.data.find((p) => p.slug === reg?.course_slug);
  const batches = plans.data?.batches ?? [];
  // The course plan's batch first; the admin can pick another one.
  const chosen = batch ?? plan?.batch_id ?? "";
  useEffect(() => {
    if (noEmail) setSendEmail(false);
  }, [noEmail]);
  const ours = (b: (typeof batches)[number]) => Number(b.website_course_slug === reg?.course_slug || b.batch_id === plan?.batch_id);
  const options = [
    ...(chosen === "" ? [{ value: "", label: plans.loading ? "Loading batches…" : "The course's linked batch" }] : []),
    ...[...batches].sort((a, b) => ours(b) - ours(a)).map((b) => ({ value: b.batch_id, label: `${b.name} (${b.code})${b.batch_id === plan?.batch_id ? " · course batch" : ""}` })),
  ];
  return (
    <ActionDialog<VerifyEnrolResult>
      open={open}
      onClose={onClose}
      onOpen={() => {
        setAmount(paiseToInput(claim.amount_paise));
        setChecked(false);
        setBatch(null);
        setMustChange(true);
        setSendEmail(!noEmail);
      }}
      title="Verify & add to batch"
      description={reg ? `${reg.name} · ${reg.course_title}` : undefined}
      submitLabel="Verify & add to batch"
      validate={() => (!checked ? "Confirm that you found this payment in PhonePe (same UTR and amount)." : !(received > 0) ? "Enter the amount that actually arrived." : null)}
      onSubmit={async () =>
        toOutcome(
          await api.post<VerifyEnrolResult>(`admin/admissions/claims/${claim.claim_id}/verify-and-enrol`, {
            amount_paise: received,
            batch_id: chosen || null,
            must_change_password: mustChange,
            send_email: sendEmail,
            note: null,
          }),
        )
      }
      onDone={(o) => {
        if (o.kind === "ok" && o.data) onEnrolled(enrolDetails(o.data, reg, claim.registration_id));
      }}
    >
      <div className="flex gap-3">
        <dl className="grid min-w-0 flex-1 grid-cols-1 gap-y-2 rounded-md bg-surface-sunken p-3 text-sm sm:grid-cols-2 sm:gap-x-4">
          {reg ? (
            <>
              <Fact label="Student">{reg.name}</Fact>
              <Fact label="Email">
                <span className="break-all">{reg.email}</span>
              </Fact>
              <Fact label="Phone">{reg.phone || "—"}</Fact>
              <Fact label="Course">{reg.course_title}</Fact>
            </>
          ) : null}
          <Fact label="Amount paid">
            <span className="font-semibold">{formatINR(claim.amount_paise)}</span>
          </Fact>
          <Fact label="UTR / transaction ID">
            <code className="break-all font-mono">{claim.utr ?? "—"}</code>
          </Fact>
        </dl>
        {claim.has_proof ? <Receipt claim={claim} /> : null}
      </div>
      <Checkbox label="I found this payment in PhonePe: same UTR / transaction ID and amount." checked={checked} onChange={(e) => setChecked(e.target.checked)} />
      <FormField label="Amount received (₹)" hint="Change it only if a different amount arrived.">
        {(f) => <Input {...f} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}
      </FormField>
      <FormField label="Add to batch" hint={plans.data && !plan?.batch_id && batches.length === 0 ? "No batches yet: create one under Batches, or link one in the fee plan." : undefined}>
        {(f) => <Select {...f} value={chosen} onChange={(e) => setBatch(e.target.value)} options={options} />}
      </FormField>
      <Checkbox label="Ask the student to change this password on first login" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
      <Checkbox
        label="Email the login details to the student"
        description={noEmail ? "Email isn't connected yet — you'll get the login details to share yourself." : reg ? `To ${reg.email}` : undefined}
        checked={sendEmail}
        disabled={noEmail}
        onChange={(e) => setSendEmail(e.target.checked)}
      />
      {reg?.has_account ? <p className="text-sm text-fg-secondary">This email already has an LMS account: the student keeps it and is added to the batch.</p> : null}
    </ActionDialog>
  );
}

export function ClaimActions({
  claim,
  registration,
  onChanged,
  onEnrolled,
  layout = "inline",
}: {
  claim: Claim;
  registration?: Registration;
  onChanged: (r: ActionResult | undefined, action: ClaimAction) => void;
  /** After "Verify & add to batch": show the login details (else shown here). */
  onEnrolled?: (d: LoginDetails) => void;
  layout?: "inline" | "queue";
}) {
  const toast = useToast();
  const reg = registration ?? claim.registration;
  const [open, setOpen] = useState<ClaimAction | "enrol" | null>(null);
  const [details, setDetails] = useState<LoginDetails | null>(null);
  const [amount, setAmount] = useState("");
  const [checked, setChecked] = useState(false);
  const [text, setText] = useState("");
  const [release, setRelease] = useState(false);
  const openClaim = claim.status === "pending" || claim.status === "needs_info";
  const big = layout === "queue";
  const received = toPaise(amount);
  const shown = received > 0 ? received : claim.amount_paise;
  const enrols = approvalEnrols(reg, shown);

  const post = async <T,>(action: ClaimAction, body: unknown) => toOutcome(await api.post<T>(`admin/admissions/claims/${claim.claim_id}/${action}`, body));
  const reset = () => {
    setAmount(paiseToInput(claim.amount_paise));
    setChecked(false);
    setText("");
    setRelease(false);
  };
  const finish = (action: ClaimAction) => (o: { kind: string; data?: ActionResult }) => {
    const res = o.kind === "ok" ? o.data : undefined;
    if (o.kind === "ok") {
      if (res?.warning) toast.show({ title: res.warning, tone: "warning" });
      else toast.show({ title: outcomeText(action, res, reg), tone: "success" });
    }
    onChanged(res, action);
  };
  const question = `Approve ${formatINR(shown)}${enrols && reg ? ` and enrol ${reg.name} in ${reg.course_title}` : ""}?`;
  // A payment that gives course access goes through "Verify & add to batch" (account + login email);
  // an instalment below the access threshold, or a payment from an enrolled student, is just approved.
  const enrolFlow = !!reg && approvalEnrols(reg, claim.amount_paise);

  return (
    <div className={big ? "grid grid-cols-2 gap-2" : "flex flex-wrap gap-2"}>
      {!big && claim.has_proof ? <Receipt claim={claim} size="sm" /> : null}
      {openClaim ? (
        <>
          {enrolFlow ? (
            <Button size={big ? "lg" : "sm"} onClick={() => setOpen("enrol")}>
              Verify &amp; add to batch
            </Button>
          ) : (
            <Button size={big ? "lg" : "sm"} onClick={() => setOpen("verify")}>
              {reg?.enrolled_at ? "Approve payment" : "Approve part payment"}
            </Button>
          )}
          <Button size={big ? "lg" : "sm"} variant="danger-secondary" onClick={() => setOpen("reject")}>
            Reject
          </Button>
          {claim.status === "pending" ? (
            <Button className={big ? "col-span-2" : undefined} size="sm" variant="ghost" onClick={() => setOpen("needs-info")}>
              Ask the student to correct it
            </Button>
          ) : null}
        </>
      ) : null}
      {claim.status === "verified" ? (
        <Button size="sm" variant="secondary" onClick={() => setOpen("reverse")}>
          Reverse
        </Button>
      ) : null}
      {(claim.status === "rejected" || claim.status === "reversed") && !claim.locks_released ? (
        <Button size="sm" variant="secondary" onClick={() => setOpen("release-locks")}>
          Allow reference again
        </Button>
      ) : null}

      <VerifyEnrolDialog
        claim={claim}
        reg={reg}
        open={open === "enrol"}
        onClose={() => setOpen(null)}
        onEnrolled={(d) => {
          toast.show({ title: `${d.name} is in ${d.batch_name ?? "the batch"}. Share the login details.`, tone: "success" });
          if (onEnrolled) onEnrolled(d);
          else setDetails(d);
          onChanged(undefined, "verify");
        }}
      />
      {onEnrolled ? null : <LoginDetailsDialog details={details} onClose={() => setDetails(null)} onUpdate={setDetails} />}

      <ActionDialog<ActionResult>
        open={open === "verify"}
        onClose={() => setOpen(null)}
        onOpen={reset}
        title="Approve payment"
        description={question}
        submitLabel={enrols ? "Approve and enrol" : "Approve"}
        validate={() => (!checked ? "Confirm that you found this payment in PhonePe (same UTR and amount)." : !(received > 0) ? "Enter the amount that actually arrived." : null)}
        onSubmit={() => post<ActionResult>("verify", { amount_paise: received, checked, note: null })}
        onDone={finish("verify")}
      >
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md bg-surface-sunken p-3 text-sm">
          <div>
            <dt className="text-fg-secondary">Claimed</dt>
            <dd className="font-semibold">{formatINR(claim.amount_paise)}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-fg-secondary">UTR / transaction ID</dt>
            <dd className="break-all font-mono">{claim.utr ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-fg-secondary">Paid on</dt>
            <dd>{formatDate(claim.paid_on)}</dd>
          </div>
          {reg ? (
            <div className="min-w-0">
              <dt className="text-fg-secondary">Email</dt>
              <dd className="break-all">{reg.email}</dd>
            </div>
          ) : null}
        </dl>
        {enrols && reg && reg.has_account === false ? (
          <p className="text-sm text-fg-secondary">No LMS account uses {reg.email} yet: approving creates one and emails a link to set the password.</p>
        ) : null}
        <Checkbox label="I found this payment in PhonePe: same UTR / transaction ID and amount." checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        <FormField label="Amount received (₹)" hint="Change it only if a different amount arrived.">
          {(f) => <Input {...f} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </FormField>
      </ActionDialog>

      <ActionDialog<ActionResult>
        open={open === "needs-info" || open === "reject" || open === "reverse"}
        onClose={() => setOpen(null)}
        onOpen={reset}
        title={open === "reject" ? "Reject payment" : open === "reverse" ? "Reverse approval" : "Ask for a correction"}
        description={
          open === "reverse"
            ? "Undo an approval made by mistake. The balance goes back up; if the verified total falls below the access threshold, course access is removed."
            : open === "reject"
              ? "The payment isn't in PhonePe, or the receipt is fake or already used. The student sees your reason by email and on their registration."
              : "Something is wrong but fixable (cut-off screenshot, typo in the UTR). The student sees your message and can send a new receipt."
        }
        submitLabel={open === "reject" ? "Reject" : open === "reverse" ? "Reverse" : "Send to student"}
        danger={open !== "needs-info"}
        validate={() => (text.trim().length < 4 ? "Write a short reason." : null)}
        onSubmit={() => post<ActionResult>(open as ClaimAction, open === "reject" ? { reason: text, release_locks: release } : { reason: text })}
        onDone={finish(open === "needs-info" || open === "reverse" ? open : "reject")}
      >
        <FormField label={open === "needs-info" ? "What should the student correct? (they see this)" : open === "reject" ? "Reason (the student sees this)" : "Reason"} required>
          {(f) => <TextArea {...f} rows={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />}
        </FormField>
        {open === "reject" ? (
          <Checkbox label="Let this UTR and receipt be used again (e.g. the student typed someone else's UTR)." checked={release} onChange={(e) => setRelease(e.target.checked)} />
        ) : null}
      </ActionDialog>

      <ActionDialog<{ claim: Claim }>
        open={open === "release-locks"}
        onClose={() => setOpen(null)}
        title="Allow this reference again"
        description="The UTR and receipt of this closed payment can be submitted again."
        submitLabel="Allow"
        onSubmit={() => post<{ claim: Claim }>("release-locks", {})}
        onDone={() => onChanged(undefined, "release-locks")}
      />
    </div>
  );
}

/* ================================================================== verification queue */

const QUEUE_FILTERS: { value: string; label: string }[] = [
  { value: "open", label: "Waiting (pending + correction asked)" },
  { value: "pending", label: CLAIM_LABEL.pending },
  { value: "needs_info", label: CLAIM_LABEL.needs_info },
  { value: "verified", label: "Approved" },
  { value: "rejected", label: CLAIM_LABEL.rejected },
  { value: "reversed", label: CLAIM_LABEL.reversed },
];

function Fact({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2 min-w-0" : "min-w-0"}>
      <dt className="text-xs text-fg-secondary">{label}</dt>
      <dd className="break-words text-sm">{children}</dd>
    </div>
  );
}

/** One payment waiting for a decision: who, how much, the UTR, the receipt and the two buttons. */
export function ClaimCard({ claim, onChanged, onEnrolled }: { claim: Claim; onChanged: (r: ActionResult | undefined, action: ClaimAction) => void; onEnrolled?: (d: LoginDetails) => void }) {
  const r = claim.registration;
  const waiting = claim.status === "pending" || claim.status === "needs_info";
  return (
    <Card>
      <div className="flex gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            {r ? (
              <Link className={cn(textLink, "text-base font-semibold")} href={regHref(claim.registration_id)}>
                {r.name}
              </Link>
            ) : null}
            <ClaimBadge status={claim.status} />
          </div>
          {r ? (
            <>
              <a className="block break-all text-sm text-fg" href={`mailto:${r.email}`}>
                {r.email}
              </a>
              <a className="block text-sm text-fg" href={`tel:${r.phone}`}>
                {r.phone}
              </a>
              <p className="text-sm font-medium">{r.course_title}</p>
            </>
          ) : null}
        </div>
        {claim.has_proof ? <Receipt claim={claim} /> : null}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
        <Fact label="Amount paid">
          <span className="text-lg font-bold">{formatINR(claim.amount_paise)}</span>
        </Fact>
        <Fact label="UTR / transaction ID">
          <code className="break-all font-mono">{claim.utr ?? "—"}</code>
        </Fact>
        <Fact label="Paid on">
          {formatDate(claim.paid_on)} · {METHOD_LABEL[claim.method] ?? claim.method}
        </Fact>
        <Fact label="Submitted">{formatDateTime(claim.submitted_at)}</Fact>
        {r ? (
          <>
            <Fact label="Course fee">
              {formatINR(r.fee_paise)} ({formatINR(r.verified_total_paise)} approved)
            </Fact>
            <Fact label="Registration">{r.reg_no}</Fact>
          </>
        ) : null}
        {claim.note ? (
          <Fact label="Student's note" wide>
            {claim.note}
          </Fact>
        ) : null}
        {claim.review_note ? (
          <Fact label={claim.status === "needs_info" ? "Correction asked" : "Team note"} wide>
            {claim.review_note}
          </Fact>
        ) : null}
      </dl>
      {claim.flags?.length ? (
        <ul className="mt-2 list-disc pl-4 text-xs text-warning-fg">
          {claim.flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : null}
      {r && r.has_account === false && waiting ? <p className="mt-2 text-xs text-fg-secondary">No LMS account with this email yet: verifying creates one with a username and temporary password.</p> : null}
      <div className="mt-4">
        <ClaimActions claim={claim} onChanged={onChanged} onEnrolled={onEnrolled} layout="queue" />
      </div>
    </Card>
  );
}

interface Decided {
  claim_id: string;
  registration_id: string;
  name: string;
  text: string;
  status: ClaimStatus;
  warning?: string | null;
  /** "Verify & add to batch": the login details, to show again until the page is left. */
  login?: LoginDetails;
}

export function VerifyQueue() {
  const [status, setStatus] = useState("open");
  const [decided, setDecided] = useState<Decided[]>([]);
  const [details, setDetails] = useState<LoginDetails | null>(null);
  const list = useCursorList<Claim>("admin/admissions/claims", cleanQuery({ status }));
  const remember = (c: Claim) => (d: LoginDetails) => {
    const entry: Decided = {
      claim_id: c.claim_id,
      registration_id: c.registration_id,
      name: d.name,
      text: `Verified and added to ${d.batch_name ?? "the batch"}. Username ${d.account.username}. ${d.email.sent ? "Login email sent." : "Share the login details yourself."}`,
      status: "verified",
      login: d,
    };
    setDecided((x) => [entry, ...x.filter((y) => y.claim_id !== c.claim_id)].slice(0, 10));
    setDetails(d);
  };
  const update = (d: LoginDetails) => {
    setDetails(d);
    setDecided((x) => x.map((y) => (y.registration_id === d.registration_id && y.login ? { ...y, login: d } : y)));
  };
  const onChanged = (c: Claim) => (res: ActionResult | undefined, action: ClaimAction) => {
    if (res && (action === "verify" || action === "reject" || action === "needs-info")) {
      const fallback: ClaimStatus = action === "verify" ? "verified" : action === "reject" ? "rejected" : "needs_info";
      const entry: Decided = {
        claim_id: c.claim_id,
        registration_id: c.registration_id,
        name: c.registration?.name ?? c.registration_id,
        text: outcomeText(action, res, c.registration),
        status: res.claim?.status ?? fallback,
        warning: res.warning,
      };
      setDecided((d) => [entry, ...d.filter((x) => x.claim_id !== c.claim_id)].slice(0, 10));
    }
    void list.reload();
  };
  const rows = list.rows ?? [];
  return (
    <div>
      <PageHeader
        title="Verify payments"
        description="Check each payment in PhonePe (same UTR / transaction ID and amount), then press Verify & add to batch: the student joins the batch and gets an LMS login. Oldest first."
      />
      <FilterBar label="Payment filters">
        <FormField label="Show">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={QUEUE_FILTERS} />}</FormField>
      </FilterBar>
      {decided.length ? (
        <Card title="Just decided" className="mb-4">
          <ul className="space-y-2 text-sm" aria-live="polite">
            {decided.map((d) => (
              <li key={d.claim_id} className="flex flex-wrap items-center gap-2">
                <ClaimBadge status={d.status} />
                <Link className={textLink} href={regHref(d.registration_id)}>
                  {d.name}
                </Link>
                <span>{d.warning ?? d.text}</span>
                {d.login ? (
                  <Button size="sm" variant="secondary" onClick={() => setDetails(d.login!)}>
                    Login details
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {list.error && !list.rows ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : list.loading && !list.rows ? (
        <LoadingBlock label="Loading payments…" rows={3} />
      ) : rows.length === 0 ? (
        <EmptyState title={status === "open" ? "Nothing waiting" : "No payments here"} description="New payment receipts from students appear here." icon="check" />
      ) : (
        <ul className="space-y-3" aria-label="Payments">
          {rows.map((c) => (
            <li key={c.claim_id}>
              <ClaimCard claim={c} onChanged={onChanged(c)} onEnrolled={remember(c)} />
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4">
        <Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />
      </div>
      <LoginDetailsDialog details={details} onClose={() => setDetails(null)} onUpdate={update} />
    </div>
  );
}

/* ================================================================== registrations */

/** "Login email: sent 12 Nov 2026" / "not sent". */
export function loginEmailText(at: string | null | undefined): string {
  return at ? `Login email: sent ${formatDateTime(at)}` : "Login email: not sent";
}

const loginTarget = (r: Registration): LoginTarget => ({
  registration_id: r.registration_id,
  name: r.name,
  phone: r.phone,
  course_title: r.course_title,
  account_username: r.account_username,
  login_email_sent_at: r.login_email_sent_at,
});

/** Send (first time) / Resend login email for an enrolled student; the new login details open in a dialog. */
export function LoginEmailButton({ registration, onSent, size = "sm" }: { registration: Registration; onSent?: () => void; size?: "sm" | "md" }) {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState<LoginDetails | null>(null);
  return (
    <>
      <Button size={size} variant="secondary" onClick={() => setOpen(true)}>
        {registration.login_email_sent_at ? "Resend login email" : "Send login email"}
      </Button>
      <SendLoginEmailDialog
        target={loginTarget(registration)}
        open={open}
        onClose={() => setOpen(false)}
        onDone={(d) => {
          setOpen(false);
          setDetails(d);
          onSent?.();
        }}
      />
      <LoginDetailsDialog details={details} onClose={() => setDetails(null)} onUpdate={setDetails} />
    </>
  );
}

export function RegistrationsList() {
  const [status, setStatus] = useState<RegStatus | "">("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const list = useCursorList<Registration>("admin/admissions/registrations", cleanQuery({ status, q: search }));
  const cols: Column<Registration>[] = [
    {
      key: "name",
      header: "Student",
      cell: (r) => (
        <div>
          <Link className={textLink} href={regHref(r.registration_id)}>
            {r.name}
          </Link>
          <div className="text-xs text-fg-secondary">
            {r.reg_no} · {r.email}
          </div>
        </div>
      ),
    },
    { key: "course", header: "Course", cell: (r) => r.course_title },
    { key: "fee", header: "Fee", cell: (r) => formatINR(r.fee_paise), align: "right" },
    { key: "paid", header: "Paid (approved)", cell: (r) => formatINR(r.verified_total_paise), align: "right" },
    { key: "bal", header: "Balance", cell: (r) => formatINR(r.balance_paise), align: "right" },
    { key: "status", header: "Status", cell: (r) => <RegBadge status={r.status} /> },
    {
      key: "login",
      header: "LMS login",
      cell: (r) =>
        r.account_username || r.user_id ? (
          <div className="space-y-1">
            {r.account_username ? <code className="break-all font-mono text-sm">{r.account_username}</code> : null}
            <div className="text-xs text-fg-secondary">{loginEmailText(r.login_email_sent_at)}</div>
            <LoginEmailButton registration={r} onSent={() => void list.reload()} />
          </div>
        ) : (
          <span className="text-sm text-fg-secondary">Not yet</span>
        ),
    },
    {
      key: "last",
      header: "Last payment",
      cell: (r) =>
        r.last_utr || r.last_claim_status ? (
          <div>
            <code className="break-all text-sm">{r.last_utr ?? "—"}</code>
            <div className="text-xs text-fg-secondary">
              {r.last_claim_status ? (r.last_claim_status === "verified" ? "Approved" : CLAIM_LABEL[r.last_claim_status]) : ""}
              {r.last_paid_on ? ` · paid ${formatDate(r.last_paid_on)}` : ""}
            </div>
          </div>
        ) : (
          "—"
        ),
      priority: "secondary",
    },
    { key: "at", header: "Registered", cell: (r) => formatDate(r.created_at), priority: "secondary" },
  ];
  return (
    <div>
      <PageHeader title="Registrations" description="Everyone who registered for a course (website or LMS), their registered email and what they have paid." />
      {/* One form: FilterBar is the <form>, so the search box must not be a nested <form>
          (invalid HTML — the parser drops it and the page fails hydration, React #418). */}
      <FilterBar label="Registration filters" onSubmit={() => setSearch(q.trim())}>
        <FormField label="Status">
          {(f) => (
            <Select {...f} value={status} onChange={(e) => setStatus(e.target.value as RegStatus | "")} options={[{ value: "", label: "Any" }, ...REG_STATUSES.map((s) => ({ value: s, label: REG_LABEL[s] }))]} />
          )}
        </FormField>
        <div className="flex items-end gap-2">
          <FormField label="Search">{(f) => <Input {...f} type="search" placeholder="Name, email, mobile or TDR-…" value={q} onChange={(e) => setQ(e.target.value)} />}</FormField>
          <Button type="submit" variant="secondary">
            Search
          </Button>
        </div>
      </FilterBar>
      <Table
        caption="Registrations"
        columns={cols}
        rows={list.rows}
        rowKey={(r) => r.registration_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No registrations", description: "Course registrations appear here.", icon: "users" }}
        footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />}
      />
    </div>
  );
}

type RegAction = "record" | "status" | "contact" | "fee" | "enrol";

export function RegistrationView({ registrationId }: { registrationId: string }) {
  const res = useResource<RegistrationDetail>(`admin/admissions/registrations/${registrationId}`);
  const notify = useWarningToast();
  const [details, setDetails] = useState<LoginDetails | null>(null);
  const [open, setOpen] = useState<RegAction | null>(null);
  const [f, setF] = useState<Record<string, string>>({});
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const set = (k: string) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  if (res.error && !res.data) return <ErrorState error={res.error} onRetry={() => void res.reload()} secondaryAction={{ href: "/finance/admissions/registrations", label: "Back to registrations" }} />;
  const r = res.data;
  if (!r) return <LoadingBlock label="Loading the registration…" rows={6} />;
  const base = `admin/admissions/registrations/${registrationId}`;
  const done = (msg: string) => (o: { kind: string; data?: ActionResult }) => {
    if (o.kind === "ok") notify(o.data, msg);
    void res.reload();
  };
  const closed = r.status === "rejected" || r.status === "cancelled" || r.status === "completed";
  const claimCols: Column<Claim>[] = [
    { key: "amt", header: "Amount", cell: (c) => <span className="font-semibold">{formatINR(c.amount_paise)}</span> },
    { key: "ver", header: "Approved", cell: (c) => (c.verified_amount_paise ? formatINR(c.verified_amount_paise) : "—") },
    { key: "ref", header: "UTR / transaction ID", cell: (c) => <code className="break-all text-sm">{c.utr ?? "—"}</code> },
    { key: "how", header: "Method", cell: (c) => `${METHOD_LABEL[c.method] ?? c.method}${c.provider === "admin_entry" ? " (team)" : ""}`, priority: "secondary" },
    { key: "on", header: "Paid on", cell: (c) => formatDate(c.paid_on), priority: "secondary" },
    { key: "sub", header: "Submitted", cell: (c) => formatDateTime(c.submitted_at), priority: "secondary" },
    { key: "st", header: "Status", cell: (c) => <div><ClaimBadge status={c.status} />{c.review_note ? <div className="mt-1 text-xs text-fg-secondary">{c.review_note}</div> : null}</div> },
    { key: "act", header: "Actions", cell: (c) => <ClaimActions claim={c} registration={r} onChanged={() => void res.reload()} onEnrolled={setDetails} /> },
  ];

  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Registrations", href: "/finance/admissions/registrations" }, { label: r.reg_no }]}
        title={r.name}
        meta={<RegBadge status={r.status} />}
        description={`${r.reg_no} · ${r.course_title} · registered ${formatDateTime(r.created_at)}`}
        actions={
          <div className="flex flex-wrap gap-2">
            {!closed ? (
              <Button onClick={() => { setF({ method: "upi", paid_on: new Date().toISOString().slice(0, 10) }); setChecked(false); setOpen("record"); }}>Record a payment</Button>
            ) : null}
            {r.eligible && !r.enrolled_at ? (
              <Button variant="secondary" onClick={() => setOpen("enrol")}>
                Enrol now
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => { setF({ status: closed ? "reopen" : "cancelled", reason: "" }); setOpen("status"); }}>
              Change status
            </Button>
            <Button variant="secondary" onClick={() => { setF({ name: r.name, email: r.email, phone: r.phone }); setOpen("contact"); }}>
              Edit contact details
            </Button>
            <Button variant="secondary" onClick={() => { setF({ fee: paiseToInput(r.fee_paise), reason: "" }); setOpen("fee"); }}>
              Adjust fee
            </Button>
          </div>
        }
      />
      <InlineProblem error={error} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <StatGrid columns={3}>
            <StatTile label="Course fee" value={formatINR(r.fee_paise)} hint={r.policy === "instalments" ? `Access from ${formatINR(r.access_min_paise)}` : "Paid in full"} />
            <StatTile label="Verified" value={formatINR(r.verified_total_paise)} tone="highlight" />
            <StatTile label="Balance" value={formatINR(r.balance_paise)} tone={r.balance_paise > 0 ? "warning" : "success"} hint={r.next_due ? `Next: ${r.next_due.label}` : "Fully paid"} />
          </StatGrid>
          <Card title="Payments" padding="none">
            <Table caption="Payments" columns={claimCols} rows={r.claims ?? []} rowKey={(c) => c.claim_id} empty={{ title: "No payments yet" }} />
          </Card>
          {r.schedule.length > 1 ? (
            <Card title="Instalments">
              <ul className="space-y-1 text-sm">
                {r.schedule.map((x: Instalment, i) => (
                  <li key={i} className="flex justify-between gap-3">
                    <span>
                      {x.label}
                      {x.due ? <span className="text-fg-secondary"> · due {formatDate(x.due)}</span> : null}
                    </span>
                    <span className={x.done ? "font-semibold text-success-fg" : ""}>
                      {formatINR(x.covered_paise ?? 0)} / {formatINR(x.amount_paise)}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
          <Card title="History">
            <ul className="space-y-2 text-sm">
              {(r.events ?? []).map((e) => (
                <li key={e.event_id}>
                  <span className="text-fg-secondary">{formatDateTime(e.at)}</span> · <span className="font-semibold">{humanize(e.action)}</span> · {e.detail} <span className="text-fg-muted">({e.actor})</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Contact">
            <KeyValueList
              columns={1}
              items={[
                { label: "Email (course access)", value: r.email },
                { label: "Mobile", value: <a className={textLink} href={`https://wa.me/${r.phone.replace(/\D/g, "")}`} target="_blank" rel="noreferrer">{r.phone}</a> },
                { label: "College", value: r.college },
                { label: "Branch / year", value: `${r.branch} · ${r.year}` },
                { label: "Current status", value: r.current_status },
                { label: "Preferred mode", value: r.preferred_mode },
                { label: "Questions", value: r.message, wide: true },
              ]}
            />
            {r.has_resume ? (
              <Button className="mt-4" size="sm" variant="secondary" onClick={() => void openPrivate(`${base}/resume`).catch(setError)}>
                View resume
              </Button>
            ) : null}
          </Card>
          <Card title="LMS access">
            <KeyValueList
              columns={1}
              items={[
                { label: "Enrolled", value: r.enrolled_at ? formatDateTime(r.enrolled_at) : "Not yet" },
                { label: "Username", value: r.account_username ? <code className="break-all font-mono">{r.account_username}</code> : r.user_id ? "—" : "Made when you verify the payment" },
                { label: "Login email", value: r.login_email_sent_at ? `Sent ${formatDateTime(r.login_email_sent_at)}` : "Not sent" },
                { label: "LMS account", value: r.user_id ? <Link className={textLink} href={`/admin/users/${r.user_id}`}>Open user</Link> : "None yet: created by Verify & add to batch" },
                { label: "Status note", value: r.status_note },
                { label: "Consent", value: `${formatDateTime(r.consent_at)}${r.marketing_consent ? " · marketing opt-in" : ""}` },
              ]}
            />
            {r.user_id || r.account_username ? (
              <div className="mt-4">
                <LoginEmailButton registration={r} size="md" onSent={() => void res.reload()} />
              </div>
            ) : null}
          </Card>
        </div>
      </div>

      <ActionDialog<ActionResult>
        open={open === "record"}
        onClose={() => setOpen(null)}
        title="Record a payment"
        description="Money received outside the registration form (cash, a direct transfer). It counts as verified at once."
        submitLabel="Record"
        validate={() => (!checked ? "Confirm that this money was received." : !(toPaise(f.amount ?? "") > 0) ? "Enter the amount received." : null)}
        onSubmit={async () =>
          toOutcome(await api.post<ActionResult>(`${base}/payments`, { amount_paise: toPaise(f.amount ?? ""), method: f.method, utr: f.utr || null, paid_on: f.paid_on, note: f.note || null, checked }))
        }
        onDone={done("Payment recorded.")}
      >
        <FormField label="Amount (₹)" required>{(p) => <Input {...p} inputMode="decimal" value={f.amount ?? ""} onChange={set("amount")} />}</FormField>
        <FormField label="Method">{(p) => <Select {...p} value={f.method ?? "upi"} onChange={set("method")} options={Object.entries(METHOD_LABEL).map(([value, label]) => ({ value, label }))} />}</FormField>
        <FormField label="Reference (optional)">{(p) => <Input {...p} value={f.utr ?? ""} onChange={set("utr")} />}</FormField>
        <FormField label="Received on">{(p) => <Input {...p} type="date" value={f.paid_on ?? ""} onChange={set("paid_on")} />}</FormField>
        <FormField label="Note (optional)">{(p) => <TextArea {...p} rows={2} value={f.note ?? ""} onChange={set("note")} />}</FormField>
        <Checkbox label="This money was received in our account." checked={checked} onChange={(e) => setChecked(e.target.checked)} />
      </ActionDialog>

      <ActionDialog<ActionResult>
        open={open === "status"}
        onClose={() => setOpen(null)}
        title="Change status"
        description="Rejecting or cancelling an enrolled student removes their course access and frees the email for a new registration."
        submitLabel="Save"
        danger={f.status === "rejected" || f.status === "cancelled"}
        validate={() => (f.status !== "completed" && (f.reason ?? "").trim().length < 4 ? "Write a short reason." : null)}
        onSubmit={async () => toOutcome(await api.post<ActionResult>(`${base}/status`, { status: f.status, reason: f.reason || null }))}
        onDone={done("Status changed.")}
      >
        <FormField label="New status">
          {(p) => (
            <Select
              {...p}
              value={f.status ?? ""}
              onChange={set("status")}
              options={closed ? [{ value: "reopen", label: "Reopen (status follows the payments)" }] : [{ value: "cancelled", label: "Cancelled" }, { value: "rejected", label: "Rejected" }, { value: "completed", label: "Completed" }]}
            />
          )}
        </FormField>
        <FormField label="Reason">{(p) => <TextArea {...p} rows={2} maxLength={500} value={f.reason ?? ""} onChange={set("reason")} />}</FormField>
      </ActionDialog>

      <ActionDialog<ActionResult>
        open={open === "contact"}
        onClose={() => setOpen(null)}
        title="Edit contact details"
        description="Course access uses the email: correct typos before the student is enrolled."
        submitLabel="Save"
        onSubmit={async () => toOutcome(await api.patch<ActionResult>(`${base}/contact`, { name: f.name, email: f.email, phone: f.phone }))}
        onDone={done("Contact details saved.")}
      >
        <FormField label="Name">{(p) => <Input {...p} value={f.name ?? ""} onChange={set("name")} />}</FormField>
        <FormField label="Email">{(p) => <Input {...p} type="email" value={f.email ?? ""} onChange={set("email")} />}</FormField>
        <FormField label="Mobile">{(p) => <Input {...p} value={f.phone ?? ""} onChange={set("phone")} />}</FormField>
      </ActionDialog>

      <ActionDialog<ActionResult>
        open={open === "fee"}
        onClose={() => setOpen(null)}
        title="Adjust this student's fee"
        description="Scholarship, discount or batch change. It can't go below what is already verified."
        submitLabel="Save fee"
        validate={() => (!(toPaise(f.fee ?? "") >= 0) ? "Enter the fee." : (f.reason ?? "").trim().length < 4 ? "Write why the fee is changing." : null)}
        onSubmit={async () => toOutcome(await api.post<ActionResult>(`${base}/fee`, { fee_paise: toPaise(f.fee ?? ""), reason: f.reason }))}
        onDone={done("Fee changed.")}
      >
        <FormField label="Fee (₹)">{(p) => <Input {...p} inputMode="decimal" value={f.fee ?? ""} onChange={set("fee")} />}</FormField>
        <FormField label="Reason">{(p) => <TextArea {...p} rows={2} maxLength={500} value={f.reason ?? ""} onChange={set("reason")} />}</FormField>
      </ActionDialog>

      <ActionDialog<ActionResult>
        open={open === "enrol"}
        onClose={() => setOpen(null)}
        title="Enrol now"
        description="Gives course access without a new payment (for example a scholarship). It creates (or finds) the student's LMS account and adds them to the linked batch; then use Send login email to give them their login."
        submitLabel="Enrol"
        onSubmit={async () => toOutcome(await api.post<ActionResult>(`${base}/enrol`, {}))}
        onDone={done("Enrolled.")}
      />
      <LoginDetailsDialog
        details={details}
        onClose={() => setDetails(null)}
        onUpdate={(d) => {
          setDetails(d);
          void res.reload();
        }}
      />
    </div>
  );
}

/* ================================================================== fee plans */

interface PlanForm {
  slug: string;
  title: string;
  course_id: string;
  batch_id: string;
  fee: string;
  allow_instalments: boolean;
  schedule: { label: string; amount: string; due: string }[];
  min_first: string;
  access_min: string;
  upi_id: string;
  payee_name: string;
  bank_details: string;
  instructions: string;
  active: boolean;
}

const emptyPlan = (): PlanForm => ({
  slug: "",
  title: "",
  course_id: "",
  batch_id: "",
  fee: "",
  allow_instalments: false,
  schedule: [{ label: "First instalment", amount: "", due: "" }],
  min_first: "",
  access_min: "",
  upi_id: "",
  payee_name: "",
  bank_details: "",
  instructions: "",
  active: false,
});

function planToForm(p: FeePlan): PlanForm {
  return {
    slug: p.slug,
    title: p.title,
    course_id: p.course_id ?? "",
    batch_id: p.batch_id ?? "",
    fee: paiseToInput(p.fee_paise),
    allow_instalments: p.allow_instalments,
    schedule: p.schedule.map((x) => ({ label: x.label, amount: paiseToInput(x.amount_paise), due: x.due })),
    min_first: paiseToInput(p.min_first_paise),
    access_min: paiseToInput(p.access_min_paise),
    upi_id: p.upi_id,
    payee_name: p.payee_name,
    bank_details: p.bank_details,
    instructions: p.instructions,
    active: p.active,
  };
}

/** The QR students scan, as the admin will see it (made from the UPI ID; no amount). */
function UpiQrPreview({ upiId, payee }: { upiId: string; payee: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const valid = /^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$/.test(upiId.trim());
  const link = valid ? upiLink(upiId, payee) : "";
  useEffect(() => {
    let live = true;
    if (!link) {
      setSrc(null);
      return;
    }
    import("qrcode")
      .then((q) => q.toDataURL(link, { margin: 1, width: 220 }))
      .then((url) => {
        if (live) setSrc(url);
      })
      .catch(() => {
        if (live) setSrc(null);
      });
    return () => {
      live = false;
    };
  }, [link]);
  if (!upiId.trim()) return null;
  if (!valid) return <p className="mt-3 text-sm text-warning-fg">The UPI ID doesn&apos;t look right (it should look like name@bank).</p>;
  return (
    <div className="mt-4 flex flex-wrap items-center gap-4">
      {/* eslint-disable-next-line @next/next/no-img-element -- generated data: URL */}
      {src ? <img src={src} alt={`UPI QR code for ${upiId}`} width={160} height={160} className="rounded-md border border-line bg-white p-1" /> : null}
      <p className="max-w-xs text-sm text-fg-secondary">Scan it with PhonePe to check it opens a payment to {payee.trim() || upiId}. Students scan this QR to pay the course fee.</p>
    </div>
  );
}

export function FeePlans({ titles = {} }: { titles?: Record<string, string> }) {
  const res = useResource<PlansEnvelope>("admin/admissions/plans");
  const toast = useToast();
  const [pay, setPay] = useState<PaySettings | null>(null);
  const [form, setForm] = useState<PlanForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const formRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (res.data) setPay(res.data.pay);
  }, [res.data]);
  // On a phone the plan form opens above the list: bring it into view.
  const formOpen = form !== null;
  // "Set the fee" from the Courses switch links here with ?edit=<slug>: open that course's plan.
  const [editSlug, setEditSlug] = useState<string | null>(null);
  useEffect(() => {
    const slug = new URLSearchParams(window.location.search).get("edit");
    if (slug) setEditSlug(slug.toLowerCase());
  }, []);
  useEffect(() => {
    if (!editSlug || !res.data) return;
    const plan = res.data.data.find((p) => p.slug === editSlug);
    setForm(plan ? planToForm(plan) : { ...emptyPlan(), slug: editSlug, title: titles[editSlug] ?? "" });
    setEditSlug(null);
  }, [editSlug, res.data, titles]);
  useEffect(() => {
    if (formOpen) formRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [formOpen]);

  if (res.error && !res.data) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data || !pay) return <LoadingBlock label="Loading fee plans…" rows={4} />;
  const env = res.data;

  const savePay = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.put("admin/admissions/pay-settings", pay);
      toast.show({ title: "Payment details saved.", tone: "success" });
      await res.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const savePlan = async () => {
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      await api.put("admin/admissions/plans", {
        slug: form.slug.trim().toLowerCase(),
        title: form.title.trim(),
        course_id: form.course_id.trim() || null,
        batch_id: form.batch_id || null,
        fee_paise: toPaise(form.fee) || 0,
        allow_instalments: form.allow_instalments,
        schedule: form.allow_instalments ? form.schedule.map((x) => ({ label: x.label, amount_paise: toPaise(x.amount) || 0, due: x.due })) : [],
        min_first_paise: form.min_first ? toPaise(form.min_first) : null,
        access_min_paise: form.access_min ? toPaise(form.access_min) : null,
        upi_id: form.upi_id || null,
        payee_name: form.payee_name || null,
        bank_details: form.bank_details || null,
        instructions: form.instructions || null,
        active: form.active,
      });
      toast.show({ title: "Fee plan saved. Existing registrations keep the fee they registered with.", tone: "success" });
      setForm(null);
      await res.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const upd = (k: keyof PlanForm) => (e: { target: { value: string } }) => setForm((x) => (x ? { ...x, [k]: e.target.value } : x));
  const cols: Column<FeePlan>[] = [
    { key: "title", header: "Course", cell: (p) => <div><div className="font-semibold">{p.title}</div><div className="text-xs text-fg-secondary">{p.slug}</div></div> },
    { key: "fee", header: "Fee", cell: (p) => `${formatINR(p.fee_paise)}${p.allow_instalments ? ` · ${p.schedule.length} instalments` : ""}` },
    { key: "access", header: "Access from", cell: (p) => formatINR(p.access_min_paise), priority: "secondary" },
    { key: "link", header: "LMS link", cell: (p) => (p.batch_id ? "Batch" : p.course_id ? "Course" : <span className="text-warning-fg">Not linked</span>) },
    { key: "open", header: "Plan", cell: (p) => <StatusBadge status={p.active ? "active" : "inactive"} label={p.active ? "Active" : "Inactive"} /> },
    { key: "edit", header: "", cell: (p) => <Button size="sm" variant="secondary" onClick={() => setForm(planToForm(p))}>Edit</Button> },
  ];

  return (
    <div>
      <PageHeader
        title="Fee plans"
        description="Per course: the fee (for example ₹5,000), instalments, when course access starts and where students pay. Changing a plan affects new registrations only."
        actions={<Button onClick={() => setForm(emptyPlan())}>Add fee plan</Button>}
      />
      <InlineProblem error={error} />
      <div className="space-y-6">
        <Card title="Payment details" description="Where students pay (UPI QR). Shown on every registration form; until set, the form says payment details aren't set up.">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="UPI ID (students scan a QR made from it)" hint="Like techdrona@ybl. Enter a UPI ID or a payment number.">{(p) => <Input {...p} autoCapitalize="none" autoCorrect="off" value={pay.upi_id} onChange={(e) => setPay({ ...pay, upi_id: e.target.value })} />}</FormField>
            <FormField label="Payment number (10 digits)">{(p) => <Input {...p} inputMode="tel" value={pay.phone} onChange={(e) => setPay({ ...pay, phone: e.target.value })} />}</FormField>
            <FormField label="Preferred app">{(p) => <Input {...p} value={pay.preferred_app} onChange={(e) => setPay({ ...pay, preferred_app: e.target.value })} />}</FormField>
            <FormField label="Payee name (as the bank shows it)">{(p) => <Input {...p} value={pay.payee_name} onChange={(e) => setPay({ ...pay, payee_name: e.target.value })} />}</FormField>
          </div>
          <div className="mt-4">
            <FormField label="Instructions (optional)">{(p) => <TextArea {...p} rows={2} maxLength={800} value={pay.instructions} onChange={(e) => setPay({ ...pay, instructions: e.target.value })} />}</FormField>
          </div>
          <UpiQrPreview upiId={pay.upi_id} payee={pay.payee_name} />
          <Button className="mt-4 w-full sm:w-auto" loading={busy} onClick={() => void savePay()}>
            Save payment details
          </Button>
        </Card>

        {form ? (
          <Card ref={formRef} title={form.slug ? `Fee plan: ${form.title || form.slug}` : "New fee plan"}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField label="Website course slug" hint="The course page slug (the part after /courses/).">{(p) => <Input {...p} value={form.slug} onChange={upd("slug")} />}</FormField>
              <FormField label="Course title">{(p) => <Input {...p} value={form.title} onChange={upd("title")} />}</FormField>
              <FormField label="LMS batch" hint="Enrolment adds the student to this batch (and its course).">
                {(p) => <Select {...p} value={form.batch_id} onChange={upd("batch_id")} options={[{ value: "", label: "No batch" }, ...env.batches.map((b) => ({ value: b.batch_id, label: `${b.name} (${b.code})` }))]} />}
              </FormField>
              <FormField label="LMS course id (optional)" hint="Needed when the batch has no course, or without a batch.">{(p) => <Input {...p} value={form.course_id} onChange={upd("course_id")} />}</FormField>
              <FormField label="Course fee (₹)">{(p) => <Input {...p} inputMode="decimal" value={form.fee} onChange={upd("fee")} />}</FormField>
            </div>
            <Checkbox className="mt-4" label="Allow instalments" checked={form.allow_instalments} onChange={(e) => setForm({ ...form, allow_instalments: e.target.checked })} />
            {form.allow_instalments ? (
              <div className="mt-3 space-y-2">
                {form.schedule.map((x, i) => (
                  <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-4">
                    <FormField label={`Instalment ${i + 1} label`}>{(p) => <Input {...p} value={x.label} onChange={(e) => setForm({ ...form, schedule: form.schedule.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)) })} />}</FormField>
                    <FormField label="Amount (₹)">{(p) => <Input {...p} inputMode="decimal" value={x.amount} onChange={(e) => setForm({ ...form, schedule: form.schedule.map((y, j) => (j === i ? { ...y, amount: e.target.value } : y)) })} />}</FormField>
                    <FormField label="Due date">{(p) => <Input {...p} type="date" value={x.due} onChange={(e) => setForm({ ...form, schedule: form.schedule.map((y, j) => (j === i ? { ...y, due: e.target.value } : y)) })} />}</FormField>
                    <div className="flex items-end">
                      <Button size="sm" variant="secondary" onClick={() => setForm({ ...form, schedule: form.schedule.filter((_, j) => j !== i) })} disabled={form.schedule.length <= 1}>
                        Remove
                      </Button>
                    </div>
                  </div>
                ))}
                {form.schedule.length < 6 ? (
                  <Button size="sm" variant="secondary" onClick={() => setForm({ ...form, schedule: [...form.schedule, { label: `Instalment ${form.schedule.length + 1}`, amount: "", due: "" }] })}>
                    Add instalment
                  </Button>
                ) : null}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <FormField label="Minimum first payment (₹)" hint="Default: the first instalment.">{(p) => <Input {...p} inputMode="decimal" value={form.min_first} onChange={upd("min_first")} />}</FormField>
                  <FormField label="Course access starts at (₹ verified)" hint="Default: the first instalment.">{(p) => <Input {...p} inputMode="decimal" value={form.access_min} onChange={upd("access_min")} />}</FormField>
                </div>
              </div>
            ) : null}
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField label="Course UPI ID (optional)">{(p) => <Input {...p} value={form.upi_id} onChange={upd("upi_id")} />}</FormField>
              <FormField label="Course payee name (optional)">{(p) => <Input {...p} value={form.payee_name} onChange={upd("payee_name")} />}</FormField>
              <FormField label="Bank details (optional)">{(p) => <TextArea {...p} rows={3} maxLength={600} value={form.bank_details} onChange={upd("bank_details")} />}</FormField>
              <FormField label="Instructions (optional)">{(p) => <TextArea {...p} rows={3} maxLength={800} value={form.instructions} onChange={upd("instructions")} />}</FormField>
            </div>
            <Checkbox className="mt-4" label="Fee plan active (needed to open registration)" description="Open or close registration itself under Admissions > Courses." checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
            <div className="mt-4 flex gap-2">
              <Button loading={busy} onClick={() => void savePlan()}>
                Save fee plan
              </Button>
              <Button variant="secondary" onClick={() => setForm(null)}>
                Cancel
              </Button>
            </div>
          </Card>
        ) : null}

        <Card title="Fee plans" padding="none">
          <Table caption="Fee plans" columns={cols} rows={env.data} rowKey={(p) => p.slug} empty={{ title: "No fee plans yet", description: "Add one per course that takes online registrations." }} />
        </Card>
      </div>
    </div>
  );
}
