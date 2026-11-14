"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Dialog,
  ErrorState,
  FormField,
  InlineProblem,
  Input,
  LinkButton,
  LoadingBlock,
  PageHeader,
  Select,
  StatusBadge,
  TextArea,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { formatINR, problemFieldErrors } from "@/features/admin/lib/console";
import { textLink } from "@/features/admin/components/console-ui";
import { useResource } from "@/lib/api/use-resource";
import { formatDateTime } from "@/lib/format";
import {
  COURSE_STATUS_HREF,
  COURSE_STATUS_LABEL,
  COURSE_STATUS_TONE,
  courseRegistrationsHref,
  paiseToInput,
  toPaise,
  upiLink,
  type CourseStatus,
  type CourseStatusRow,
  type FeePlan,
  type PaySettings,
  type PlansEnvelope,
} from "../lib/admissions";

/**
 * Admin > Payments > Admissions > Fee plans (ADM-022).
 *
 * One row per website course (from the website catalogue) plus any plan for a course the
 * catalogue doesn't list: fee, instalments, linked batch, plan Active/Inactive and the course's
 * registration status. Edit / "Set up fee plan" opens the plan form in a dialog; Activate /
 * Deactivate saves the plan with only `active` changed. The default payment details (used when a
 * course has no UPI / bank details of its own) are a separate card below the list.
 *
 * Backend: GET/PUT /admin/admissions/plans, PUT /admin/admissions/pay-settings,
 * GET /admin/courses/status. A plan has to be active (with a fee) before Admissions > Courses can
 * open registration (409 no_fee_plan); an "open" course whose plan is inactive reads Closed.
 */

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,79}$/;
const UPI_RE = /^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_FEE_PAISE = 100_000_000;
const MAX_INSTALMENTS = 6;

export interface PlanForm {
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
  /** Set when editing a saved plan: the API then refuses a slug change (409 slug_locked). */
  fee_plan_id?: string;
}

const firstInstalment = () => [{ label: "First instalment", amount: "", due: "" }];

export const emptyPlan = (): PlanForm => ({
  slug: "",
  title: "",
  course_id: "",
  batch_id: "",
  fee: "",
  allow_instalments: false,
  schedule: firstInstalment(),
  min_first: "",
  access_min: "",
  upi_id: "",
  payee_name: "",
  bank_details: "",
  instructions: "",
  active: false,
});

export function planToForm(p: FeePlan): PlanForm {
  // A full-fee plan comes back with schedule [Full fee] and min_first = access_min = the fee:
  // don't carry those into the instalment fields, or ticking "Allow instalments" would start
  // with "minimum first payment = the whole fee".
  const inst = p.allow_instalments;
  return {
    slug: p.slug,
    title: p.title,
    course_id: p.course_id ?? "",
    batch_id: p.batch_id ?? "",
    fee: p.fee_paise ? paiseToInput(p.fee_paise) : "",
    allow_instalments: inst,
    schedule: inst && p.schedule.length ? p.schedule.map((x) => ({ label: x.label, amount: paiseToInput(x.amount_paise), due: x.due })) : firstInstalment(),
    min_first: inst ? paiseToInput(p.min_first_paise) : "",
    access_min: inst ? paiseToInput(p.access_min_paise) : "",
    upi_id: p.upi_id,
    payee_name: p.payee_name,
    bank_details: p.bank_details,
    instructions: p.instructions,
    active: p.active,
    fee_plan_id: p.fee_plan_id,
  };
}

/** The API tells us when a course is switched Open but students see Closed (inactive plan). */
type SavedPlan = FeePlan & { course_status?: string | null; effective_status?: string | null };
export function closedWhileOpen(p: SavedPlan | null | undefined): boolean {
  return !!p && p.course_status === "open" && p.effective_status !== "open";
}

/** The PUT /admin/admissions/plans body (AdmissionPlanIn) from the form. */
export function formToBody(form: PlanForm) {
  return {
    slug: form.slug.trim().toLowerCase(),
    title: form.title.trim(),
    course_id: form.course_id.trim() || null,
    batch_id: form.batch_id || null,
    fee_paise: toPaise(form.fee) || 0,
    allow_instalments: form.allow_instalments,
    schedule: form.allow_instalments ? form.schedule.map((x) => ({ label: x.label.trim(), amount_paise: toPaise(x.amount) || 0, due: x.due })) : [],
    min_first_paise: form.allow_instalments && form.min_first.trim() ? toPaise(form.min_first) : null,
    access_min_paise: form.allow_instalments && form.access_min.trim() ? toPaise(form.access_min) : null,
    upi_id: form.upi_id.trim() || null,
    payee_name: form.payee_name.trim() || null,
    bank_details: form.bank_details.trim() || null,
    instructions: form.instructions.trim() || null,
    active: form.active,
    ...(form.fee_plan_id ? { fee_plan_id: form.fee_plan_id } : {}),
  };
}

type Errors = Record<string, string>;

/** Client checks that mirror the api (rules.clean_terms, SLUG_RE, UPI_ID_RE); keys are form keys. */
export function validatePlan(form: PlanForm): Errors {
  const e: Errors = {};
  if (!SLUG_RE.test(form.slug.trim().toLowerCase())) e.slug = "Enter the website course slug (lower-case letters, digits and dashes).";
  if (!form.title.trim()) e.title = "Enter the course title.";
  if (form.course_id.trim() && !UUID_RE.test(form.course_id.trim())) e.course_id = "This isn't an LMS course id (it looks like 0193a…-…). Leave it empty to use the batch's course.";
  const fee = toPaise(form.fee);
  if (!form.fee.trim()) e.fee = "Enter the course fee.";
  else if (Number.isNaN(fee) || fee < 100 || fee > MAX_FEE_PAISE) e.fee = "Enter a fee between ₹1 and ₹10,00,000 (numbers only, like 5000).";
  if (form.allow_instalments) {
    let total = 0;
    form.schedule.forEach((x, i) => {
      const amt = toPaise(x.amount);
      if (Number.isNaN(amt) || amt <= 0) e[`schedule.${i}.amount`] = "Enter this instalment's amount.";
      else total += amt;
    });
    if (!e.fee && !Object.keys(e).some((k) => k.startsWith("schedule.")) && total !== fee) {
      e.schedule = `The instalments add up to ${formatINR(total)}, but the fee is ${formatINR(fee)}.`;
    }
    for (const k of ["min_first", "access_min"] as const) {
      const v = form[k].trim();
      if (v && (Number.isNaN(toPaise(v)) || toPaise(v) > fee)) e[k] = "Enter an amount up to the course fee, or leave it empty.";
    }
  }
  if (form.upi_id.trim() && !UPI_RE.test(form.upi_id.trim())) e.upi_id = "The UPI ID doesn't look right (it should look like name@bank).";
  return e;
}

/** Api field names (AdmissionPlanIn) -> form keys. */
function serverErrors(err: unknown): Errors {
  const out: Errors = {};
  for (const [k, v] of Object.entries(problemFieldErrors(err))) {
    const key = k
      .replace(/^fee_paise$/, "fee")
      .replace(/^min_first_paise$/, "min_first")
      .replace(/^access_min_paise$/, "access_min")
      .replace(/^schedule\.(\d+)\.amount_paise$/, "schedule.$1.amount");
    if (!(key in out)) out[key] = v;
  }
  return out;
}

/** The QR students scan, as the admin will see it (made from the UPI ID; no amount). */
export function UpiQrPreview({ upiId, payee }: { upiId: string; payee: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const valid = UPI_RE.test(upiId.trim());
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

/* ------------------------------------------------------------------ list */

interface CourseItem {
  slug: string;
  title: string;
  plan: FeePlan | null;
  /** On the website catalogue (false: a plan for a slug the catalogue doesn't list). */
  onWebsite: boolean;
  status: CourseStatusRow | null;
}

function courseItems(plans: FeePlan[], titles: Record<string, string>, statuses: CourseStatusRow[] | undefined): CourseItem[] {
  const bySlug = new Map(plans.map((p) => [p.slug, p]));
  const statusOf = new Map((statuses ?? []).map((s) => [s.course_slug, s]));
  const items: CourseItem[] = Object.entries(titles).map(([slug, title]) => ({ slug, title, plan: bySlug.get(slug) ?? null, onWebsite: true, status: statusOf.get(slug) ?? null }));
  for (const p of plans) if (!(p.slug in titles)) items.push({ slug: p.slug, title: p.title, plan: p, onWebsite: false, status: statusOf.get(p.slug) ?? null });
  return items;
}

/** What students see for the course's registration (the effective status). */
function regStatus(s: CourseStatusRow | null): CourseStatus {
  return s?.effective_status ?? s?.status ?? "coming_soon";
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-secondary">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function CourseRow({
  item,
  batchName,
  statusesLoaded,
  busy,
  problem,
  onEdit,
  onToggle,
}: {
  item: CourseItem;
  batchName: (id: string) => string | null;
  statusesLoaded: boolean;
  busy: boolean;
  problem: unknown;
  onEdit: () => void;
  onToggle: () => void;
}) {
  const p = item.plan;
  const status = regStatus(item.status);
  const shownClosed = item.status?.status === "open" && status !== "open";
  const linkText = p?.batch_id ? `Batch: ${batchName(p.batch_id) ?? "linked batch"}` : p?.course_id ? "LMS course (no batch)" : null;
  return (
    <li className="space-y-3 border-b border-line px-5 py-4 last:border-b-0 sm:px-6" aria-label={item.title}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-display text-base font-bold text-fg-heading">{item.title}</h3>
          <p className="text-xs text-fg-secondary">
            {item.slug}
            {item.onWebsite ? "" : " · not in the website catalogue"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {p ? <StatusBadge status={p.active ? "active" : "inactive"} label={p.active ? "Plan active" : "Plan inactive"} /> : <StatusBadge status="draft" tone="warning" label="No fee plan" />}
          {statusesLoaded ? <StatusBadge status={COURSE_STATUS_TONE[status]} label={`Registration: ${COURSE_STATUS_LABEL[status]}`} /> : null}
        </div>
      </div>
      {p ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          <Fact label="Fee">
            <span className="font-semibold">{p.fee_paise ? formatINR(p.fee_paise) : <span className="text-warning-fg">Not set</span>}</span>
          </Fact>
          <Fact label="Instalments">{p.allow_instalments ? `Yes · ${p.schedule.length} (access from ${formatINR(p.access_min_paise)})` : "No (full fee)"}</Fact>
          <Fact label="LMS link">{linkText ?? <span className="text-warning-fg">Not linked</span>}</Fact>
          <Fact label="Pays to">{p.upi_id || p.bank_details ? p.upi_id || "Course bank details" : "Default payment details"}</Fact>
        </dl>
      ) : (
        <p className="text-sm text-fg-secondary">No fee plan yet: students can&apos;t register for this course until it has an active fee plan.</p>
      )}
      {p?.problems.length ? (
        <ul className="list-disc pl-5 text-sm text-warning-fg">
          {p.problems.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      ) : null}
      {shownClosed ? (
        <p className="text-sm text-warning-fg">Registration is set to open, but students see it as closed because the fee plan is inactive. Activate the plan to take registrations.</p>
      ) : p?.active && statusesLoaded && status !== "open" ? (
        <p className="text-sm text-fg-secondary">The plan is active. Registration opens when you set this course to Open for registration under Courses.</p>
      ) : null}
      <InlineProblem error={problem} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={p ? "secondary" : "primary"} onClick={onEdit} aria-label={`${p ? "Edit fee plan" : "Set up fee plan"}: ${item.title}`}>
          {p ? "Edit" : "Set up fee plan"}
        </Button>
        {p ? (
          <Button size="sm" variant={p.active ? "ghost" : "primary"} loading={busy} onClick={onToggle} aria-label={`${p.active ? "Deactivate" : "Activate"} fee plan: ${item.title}`}>
            {p.active ? "Deactivate" : "Activate"}
          </Button>
        ) : null}
        <LinkButton size="sm" variant="ghost" href={COURSE_STATUS_HREF} aria-label={`Open registration (Courses): ${item.title}`}>
          {status === "open" ? "Registration status" : "Open registration"}
        </LinkButton>
        {p ? (
          <Link className={`${textLink} text-sm`} href={courseRegistrationsHref(item.slug)}>
            Registrations
          </Link>
        ) : null}
        {p?.updated_at ? <span className="text-xs text-fg-muted">Changed {formatDateTime(p.updated_at)}</span> : null}
      </div>
    </li>
  );
}

/* ------------------------------------------------------------------ plan form (dialog) */

function Section({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className="space-y-4 border-t border-line-subtle pt-4 first:border-t-0 first:pt-0">
      <div>
        <h3 id={id} className="font-display text-base font-bold text-fg-heading">
          {title}
        </h3>
        {description ? <p className="mt-0.5 text-sm text-fg-secondary">{description}</p> : null}
      </div>
      {children}
    </div>
  );
}

function PlanDialog({
  form,
  setForm,
  isNew,
  slugLocked,
  env,
  onClose,
  onSaved,
}: {
  form: PlanForm | null;
  setForm: (f: PlanForm | ((x: PlanForm | null) => PlanForm | null)) => void;
  /** No plan exists for this course yet. */
  isNew: boolean;
  /** The course is known (catalogue row or existing plan): the slug can't change here. */
  slugLocked: boolean;
  env: PlansEnvelope;
  onClose: () => void;
  onSaved: (saved: FeePlan | null, pending: boolean) => void;
}) {
  const formId = useId();
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<unknown>(null);
  const open = form !== null;
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setErrors({});
      setProblem(null);
    }
    wasOpen.current = open;
  }, [open]);

  if (!form) return <Dialog open={false} onClose={onClose} title="Fee plan" />;
  const upd = (k: keyof PlanForm) => (e: { target: { value: string } }) => setForm((x) => (x ? { ...x, [k]: e.target.value } : x));
  const setRow = (i: number, k: "label" | "amount" | "due", v: string) => setForm((x) => (x ? { ...x, schedule: x.schedule.map((y, j) => (j === i ? { ...y, [k]: v } : y)) } : x));
  const batch = env.batches.find((b) => b.batch_id === form.batch_id);
  const defaults = env.pay.upi_id || env.pay.phone ? `Default: ${env.pay.upi_id || env.pay.phone}${env.pay.payee_name ? ` (${env.pay.payee_name})` : ""}.` : "No default payment details are set yet.";
  const title = isNew ? (form.title ? `Set up fee plan: ${form.title}` : "New fee plan") : `Edit fee plan: ${form.title || form.slug}`;

  const save = async () => {
    const local = validatePlan(form);
    setErrors(local);
    setProblem(null);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      const res = await api.put<FeePlan>("admin/admissions/plans", formToBody(form));
      onSaved(res.kind === "ok" ? res.data : null, res.kind !== "ok");
    } catch (e) {
      const fe = serverErrors(e);
      setErrors(fe);
      // Field errors show next to their fields; anything else (or a field this form doesn't
      // show) goes in the box above the buttons.
      const shown = ["slug", "title", "course_id", "batch_id", "fee", "min_first", "access_min", "upi_id", "active", "schedule"];
      if (!Object.keys(fe).some((k) => shown.includes(k) || k.startsWith("schedule."))) setProblem(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      size="lg"
      title={title}
      description="Changing a plan affects new registrations only: existing registrations keep the fee they registered with."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            Save fee plan
          </Button>
        </>
      }
    >
      <form
        id={formId}
        noValidate
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Section title="Course & batch">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {slugLocked ? (
              <FormField label="Website course" hint="The course page on the website (/courses/…). It can't change here.">
                {(p) => <Input {...p} value={form.slug} readOnly aria-readonly="true" className="bg-surface-sunken" />}
              </FormField>
            ) : (
              <FormField label="Website course slug" hint="The part after /courses/ in the course page address, like java-full-stack." error={errors.slug} required>
                {(p) => <Input {...p} autoCapitalize="none" autoCorrect="off" value={form.slug} onChange={upd("slug")} />}
              </FormField>
            )}
            <FormField label="Course title" hint="Shown on the registration form and the receipt." error={errors.title} required>
              {(p) => <Input {...p} value={form.title} onChange={upd("title")} />}
            </FormField>
            <FormField label="LMS batch" hint="Verified students are added to this batch (and its course)." error={errors.batch_id}>
              {(p) => <Select {...p} value={form.batch_id} onChange={upd("batch_id")} options={[{ value: "", label: "No batch" }, ...env.batches.map((b) => ({ value: b.batch_id, label: `${b.name} (${b.code})` }))]} />}
            </FormField>
            <FormField
              label="LMS course id (optional)"
              hint={batch?.course_id ? `Leave empty: the batch's course is used (${batch.course_id}).` : "Only needed when there is no batch, or the batch has no course: the id of the LMS course students get."}
              error={errors.course_id}
            >
              {(p) => <Input {...p} autoCapitalize="none" autoCorrect="off" spellCheck={false} value={form.course_id} onChange={upd("course_id")} />}
            </FormField>
          </div>
          {!form.batch_id && !form.course_id.trim() ? <p className="text-sm text-warning-fg">Not linked: verified students can&apos;t be added to a batch until you choose one.</p> : null}
        </Section>

        <Section title="Fee">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="Course fee (₹)" hint="The full fee, for example 5000." error={errors.fee} required>
              {(p) => <Input {...p} inputMode="decimal" value={form.fee} onChange={upd("fee")} />}
            </FormField>
          </div>
          <Checkbox
            label="Allow instalments"
            description="Students pay in parts; course access starts once the access amount is verified."
            checked={form.allow_instalments}
            onChange={(e) => {
              const on = e.target.checked;
              setForm((x) => (x ? { ...x, allow_instalments: on } : x));
            }}
          />
          {form.allow_instalments ? (
            <div className="space-y-3 rounded-lg border border-line-subtle bg-surface-sunken p-3">
              {form.schedule.map((x, i) => (
                <div key={i} className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_9rem_10rem_auto]">
                  <FormField label={`Instalment ${i + 1} label`}>{(p) => <Input {...p} value={x.label} onChange={(e) => setRow(i, "label", e.target.value)} />}</FormField>
                  <FormField label={`Instalment ${i + 1} amount (₹)`} error={errors[`schedule.${i}.amount`]}>
                    {(p) => <Input {...p} inputMode="decimal" value={x.amount} onChange={(e) => setRow(i, "amount", e.target.value)} />}
                  </FormField>
                  <FormField label={`Instalment ${i + 1} due date`}>{(p) => <Input {...p} type="date" value={x.due} onChange={(e) => setRow(i, "due", e.target.value)} />}</FormField>
                  <div className="flex items-end">
                    <Button size="sm" variant="ghost" onClick={() => setForm((f) => (f ? { ...f, schedule: f.schedule.filter((_, j) => j !== i) } : f))} disabled={form.schedule.length <= 1} aria-label={`Remove instalment ${i + 1}`}>
                      Remove
                    </Button>
                  </div>
                </div>
              ))}
              {errors.schedule ? (
                <p role="alert" className="text-sm font-medium text-danger-fg">
                  {errors.schedule}
                </p>
              ) : null}
              {form.schedule.length < MAX_INSTALMENTS ? (
                <Button size="sm" variant="secondary" onClick={() => setForm((f) => (f ? { ...f, schedule: [...f.schedule, { label: `Instalment ${f.schedule.length + 1}`, amount: "", due: "" }] } : f))}>
                  Add instalment
                </Button>
              ) : null}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField label="Minimum first payment (₹)" hint="Empty: the first instalment." error={errors.min_first}>
                  {(p) => <Input {...p} inputMode="decimal" value={form.min_first} onChange={upd("min_first")} />}
                </FormField>
                <FormField label="Course access starts at (₹ verified)" hint="Empty: the first instalment." error={errors.access_min}>
                  {(p) => <Input {...p} inputMode="decimal" value={form.access_min} onChange={upd("access_min")} />}
                </FormField>
              </div>
            </div>
          ) : null}
        </Section>

        <Section title="Where students pay" description={`Leave these empty to use the default payment details (further down this page). ${defaults}`}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField label="Course UPI ID (optional)" hint="Like techdrona@ybl." error={errors.upi_id}>
              {(p) => <Input {...p} autoCapitalize="none" autoCorrect="off" value={form.upi_id} onChange={upd("upi_id")} />}
            </FormField>
            <FormField label="Course payee name (optional)">{(p) => <Input {...p} value={form.payee_name} onChange={upd("payee_name")} />}</FormField>
            <FormField label="Bank details (optional)">{(p) => <TextArea {...p} rows={3} maxLength={600} value={form.bank_details} onChange={upd("bank_details")} />}</FormField>
            <FormField label="Payment instructions (optional)">{(p) => <TextArea {...p} rows={3} maxLength={800} value={form.instructions} onChange={upd("instructions")} />}</FormField>
          </div>
        </Section>

        <Section title="Status">
          <Checkbox
            label="Fee plan active"
            description="Registration can open only while the plan is active (with a fee). Opening or closing registration itself is done under Admissions › Courses; deactivating the plan makes an open course read Closed to students."
            checked={form.active}
            onChange={(e) => {
              const on = e.target.checked;
              setForm((x) => (x ? { ...x, active: on } : x));
            }}
          />
          {errors.active ? (
            <p role="alert" className="text-sm font-medium text-danger-fg">
              {errors.active}
            </p>
          ) : null}
        </Section>
        <InlineProblem error={problem} />
      </form>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ default payment details */

function DefaultPaymentCard({ initial, onSaved }: { initial: PaySettings; onSaved: (p: PaySettings) => void }) {
  const toast = useToast();
  const [pay, setPay] = useState<PaySettings>(initial);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<unknown>(null);
  const errors = problemFieldErrors(problem);
  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const res = await api.put<PaySettings>("admin/admissions/pay-settings", pay);
      if (res.kind === "ok") {
        const saved = res.data && typeof res.data === "object" && "upi_id" in res.data ? res.data : pay;
        setPay(saved);
        toast.show({ title: "Default payment details saved.", tone: "success" });
        onSaved(saved);
      } else {
        toast.show({ title: "Sent for a second approval. The details change once it's approved.", tone: "info" });
      }
    } catch (e) {
      setProblem(e);
    } finally {
      setBusy(false);
    }
  };
  const known = new Set(["phone", "upi_id", "preferred_app", "payee_name", "instructions"]);
  return (
    <Card
      id="default-payment-details"
      className="scroll-mt-24"
      title="Default payment details (used when a course has none)"
      description="Where students pay (UPI QR or payment number). Every registration form shows these unless the course's fee plan has its own UPI ID or bank details."
    >
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField label="UPI ID (students scan a QR made from it)" hint="Like techdrona@ybl. Enter a UPI ID or a payment number." error={errors.upi_id}>
            {(p) => <Input {...p} autoCapitalize="none" autoCorrect="off" value={pay.upi_id} onChange={(e) => setPay({ ...pay, upi_id: e.target.value })} />}
          </FormField>
          <FormField label="Payment number (10 digits)" error={errors.phone}>
            {(p) => <Input {...p} inputMode="tel" value={pay.phone} onChange={(e) => setPay({ ...pay, phone: e.target.value })} />}
          </FormField>
          <FormField label="Preferred app" error={errors.preferred_app}>
            {(p) => <Input {...p} value={pay.preferred_app} onChange={(e) => setPay({ ...pay, preferred_app: e.target.value })} />}
          </FormField>
          <FormField label="Payee name (as the bank shows it)" error={errors.payee_name}>
            {(p) => <Input {...p} value={pay.payee_name} onChange={(e) => setPay({ ...pay, payee_name: e.target.value })} />}
          </FormField>
        </div>
        <div className="mt-4">
          <FormField label="Instructions (optional)" error={errors.instructions}>
            {(p) => <TextArea {...p} rows={2} maxLength={800} value={pay.instructions} onChange={(e) => setPay({ ...pay, instructions: e.target.value })} />}
          </FormField>
        </div>
        <UpiQrPreview upiId={pay.upi_id} payee={pay.payee_name} />
        {problem && !Object.keys(errors).some((k) => known.has(k)) ? (
          <div className="mt-4">
            <InlineProblem error={problem} />
          </div>
        ) : null}
        <Button type="submit" className="mt-4 w-full sm:w-auto" loading={busy}>
          Save payment details
        </Button>
      </form>
    </Card>
  );
}

/* ------------------------------------------------------------------ page */

interface Editing {
  form: PlanForm;
  isNew: boolean;
  slugLocked: boolean;
}

export function FeePlans({ titles = {} }: { titles?: Record<string, string> }) {
  const res = useResource<PlansEnvelope>("admin/admissions/plans");
  const statuses = useResource<{ data: CourseStatusRow[] }>("admin/courses/status");
  const toast = useToast();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [rowProblem, setRowProblem] = useState<{ slug: string; error: unknown } | null>(null);
  const [deactivate, setDeactivate] = useState<FeePlan | null>(null);

  // "Set the fee" (Admissions > Courses) and the site-catalogue card link here with ?edit=<slug>:
  // open that course's plan (a new one when it has none) once the plans are in.
  const editParam = (useSearchParams()?.get("edit") ?? "").trim().toLowerCase();
  const handled = useRef<string | null>(null);
  const env = res.data;
  const titleFor = (slug: string) => titles[slug] ?? env?.data.find((p) => p.slug === slug)?.title ?? "";

  const openFor = (slug: string, plan: FeePlan | null | undefined, title: string) => {
    setRowProblem(null);
    setEditing(
      plan
        ? { form: planToForm(plan), isNew: false, slugLocked: true }
        : { form: { ...emptyPlan(), slug, title }, isNew: true, slugLocked: Boolean(slug) },
    );
  };

  useEffect(() => {
    if (!editParam || !env || handled.current === editParam) return;
    handled.current = editParam;
    openFor(editParam, env.data.find((p) => p.slug === editParam), titleFor(editParam));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per ?edit= value, after the plans load
  }, [editParam, env]);

  if (res.error && !env) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!env) return <LoadingBlock label="Loading fee plans…" rows={4} />;

  const items = courseItems(env.data, titles, statuses.data?.data);
  const batchName = (id: string) => {
    const b = env.batches.find((x) => x.batch_id === id);
    return b ? `${b.name} (${b.code})` : null;
  };
  const refresh = async () => {
    await Promise.all([res.reload(), statuses.reload()]);
  };

  const setActive = async (plan: FeePlan, active: boolean) => {
    setToggling(plan.slug);
    setRowProblem(null);
    try {
      const out = await api.post<SavedPlan>(`admin/admissions/plans/${encodeURIComponent(plan.slug)}/active`, { active });
      if (out.kind !== "ok") toast.show({ title: "Sent for a second approval. The plan changes once it's approved.", tone: "info" });
      else
        toast.show({
          title: active ? `${plan.title}: fee plan active.` : `${plan.title}: fee plan inactive.`,
          description: closedWhileOpen(out.data)
            ? "This course is switched Open, but students now see it Closed until the plan is active again."
            : active ? "Now open registration for it under Admissions › Courses." : "Students can't register for this course until the plan is active again.",
          tone: closedWhileOpen(out.data) ? "warning" : "success",
        });
      await refresh();
    } catch (e) {
      // Activate reports next to the row; Deactivate runs in the confirm dialog, which shows it.
      if (active) setRowProblem({ slug: plan.slug, error: e });
      throw e;
    } finally {
      setToggling(null);
    }
  };

  const withPlans = items.filter((i) => i.plan).length;
  return (
    <div>
      <PageHeader
        title="Fee plans"
        description="Each website course needs an active fee plan (its fee, instalments, LMS batch and where students pay) before you can open registration under Admissions › Courses."
        actions={
          <Button variant="secondary" onClick={() => openFor("", null, "")}>
            Add plan for another course
          </Button>
        }
      />
      <div className="space-y-6">
        <Card
          title="Courses and fee plans"
          description={`${withPlans} of ${items.length} course${items.length === 1 ? "" : "s"} have a fee plan. Steps for a course: set up the fee plan → activate it → open registration.`}
          padding="none"
        >
          {statuses.error && !statuses.data ? <p className="px-5 pb-3 text-sm text-fg-secondary sm:px-6">Registration status couldn&apos;t be loaded; see Admissions › Courses.</p> : null}
          {items.length === 0 ? (
            <div className="px-5 pb-6 sm:px-6">
              <p className="text-sm text-fg-secondary">No courses yet. The website catalogue couldn&apos;t be read and no fee plans exist: use “Add plan for another course”.</p>
            </div>
          ) : (
            <ul aria-label="Courses and fee plans">
              {items.map((item) => (
                <CourseRow
                  key={item.slug}
                  item={item}
                  batchName={batchName}
                  statusesLoaded={Boolean(statuses.data)}
                  busy={toggling === item.slug}
                  problem={rowProblem?.slug === item.slug ? rowProblem.error : null}
                  onEdit={() => openFor(item.slug, item.plan, item.title)}
                  onToggle={() => {
                    if (!item.plan) return;
                    if (item.plan.active) setDeactivate(item.plan);
                    else void setActive(item.plan, true).catch(() => undefined);
                  }}
                />
              ))}
            </ul>
          )}
        </Card>

        <DefaultPaymentCard
          initial={env.pay}
          onSaved={() => {
            void res.reload();
          }}
        />
      </div>

      <PlanDialog
        form={editing?.form ?? null}
        isNew={editing?.isNew ?? false}
        slugLocked={editing?.slugLocked ?? false}
        env={env}
        setForm={(f) => setEditing((e) => (e ? { ...e, form: (typeof f === "function" ? f(e.form) : f) ?? e.form } : e))}
        onClose={() => setEditing(null)}
        onSaved={(saved, pending) => {
          setEditing(null);
          if (pending) toast.show({ title: "Sent for a second approval. The plan changes once it's approved.", tone: "info" });
          else
            toast.show({
              title: `Fee plan saved${saved?.title ? `: ${saved.title}` : ""}.`,
              description: closedWhileOpen(saved as SavedPlan | null)
                ? "This course is switched Open, but students see it Closed because the plan is inactive."
                : saved && !saved.active ? "It's inactive: activate it before opening registration." : "Existing registrations keep the fee they registered with.",
              tone: "success",
            });
          void refresh();
        }}
      />

      <ConfirmDialog
        open={deactivate !== null}
        onClose={() => setDeactivate(null)}
        title="Deactivate this fee plan?"
        description={deactivate ? `${deactivate.title}: new students can't register while the plan is inactive. If registration is open, students see the course as Closed. Existing registrations and payments aren't affected.` : undefined}
        confirmLabel="Deactivate plan"
        danger
        onConfirm={async () => {
          if (deactivate) await setActive(deactivate, false);
        }}
      />
    </div>
  );
}
