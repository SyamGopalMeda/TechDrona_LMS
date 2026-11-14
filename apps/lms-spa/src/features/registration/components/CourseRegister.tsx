"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Checkbox, EmptyState, ErrorState, FormField, Icon, Input, LoadingBlock, PageHeader } from "@/components/ui";
import { buttonClasses } from "@/components/ui/Button";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import {
  CLAIM_PATH,
  MY_REGISTRATIONS_HREF,
  NOT_OPEN_COPY,
  PUBLIC_COURSES_HREF,
  PUBLIC_REGISTER_PATH,
  PUBLIC_STATUS_HREF,
  REGISTER_PATH,
  SUBMITTED_MESSAGE,
  closedStatusOf,
  inr,
  myPlanPath,
  newRegNo,
  publicPlanPath,
  publicPlanToView,
  type ClaimPayload,
  type CourseStatus,
  type MyPlanView,
  type MyRegistration,
  type ProofPayload,
  type PublicPlan,
  type PublicRegistered,
} from "../lib/registration";
import { PayAndUpload, RegistrationStep } from "./PayAndUpload";
import { CopyButton, PaymentNotConfigured } from "./PaymentPanel";
import { RegistrationStatus } from "./RegistrationStatus";
import { useResource } from "@/lib/api/use-resource";

/** "student": signed-in, /me/admissions/* (prefilled from the account). "public": no account, /public/admissions/*. */
export type RegisterMode = "student" | "public";

type Details = { name: string; email: string; phone: string; college: string; branch: string; year: string };
type FieldDef = { key: keyof Details; label: string; hint?: string; max: number; type?: "email"; inputMode?: "tel" | "email"; autoComplete?: string };
const DETAIL_FIELDS: FieldDef[] = [
  { key: "name", label: "Full name", max: 120, autoComplete: "name" },
  { key: "email", label: "Email", hint: "We send your LMS login details here.", max: 160, type: "email", inputMode: "email", autoComplete: "email" },
  { key: "phone", label: "Mobile number", hint: "10-digit Indian mobile number.", max: 20, inputMode: "tel", autoComplete: "tel-national" },
  { key: "college", label: "College", max: 160 },
  { key: "branch", label: "Branch / stream", hint: "e.g. CSE, ECE, B.Com", max: 60 },
  { key: "year", label: "Year of study", hint: "e.g. 3rd year, or Graduated 2025", max: 30 },
];

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function checkDetails(d: Details, consent: boolean, needEmail: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  if (d.name.trim().length < 2) e.name = "Enter your full name.";
  if (needEmail && !EMAIL_RE.test(d.email.trim())) e.email = "Enter a valid email address. We send your LMS login here.";
  const digits = d.phone.replace(/\D/g, "").replace(/^(91|0)(?=\d{10}$)/, "");
  if (!/^[6-9]\d{9}$/.test(digits)) e.phone = "Enter a 10-digit Indian mobile number (starting with 6-9).";
  if (!d.college.trim()) e.college = "Enter your college.";
  if (!d.branch.trim()) e.branch = "Enter your branch or stream.";
  if (!d.year.trim()) e.year = "Enter your year of study.";
  if (!consent) e.consent = "Please agree so we can process your registration and payment.";
  return e;
}

function useScrollIntoView<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, []);
  return ref;
}

function SubmittedBanner() {
  const ref = useScrollIntoView<HTMLParagraphElement>();
  return (
    <p ref={ref} role="status" className="rounded-xl bg-success-subtle p-4 text-sm font-semibold text-success-fg">
      {SUBMITTED_MESSAGE}
    </p>
  );
}

/** After a public registration: the registration number to keep and where the login will be sent. */
export function PublicSubmitted({ regNo, email, courseTitle }: { regNo: string; email: string; courseTitle: string }) {
  const ref = useScrollIntoView<HTMLElement>();
  return (
    <section ref={ref} role="status" aria-labelledby="reg-done-h" className="space-y-4 rounded-2xl border border-line bg-surface p-5 text-center sm:p-6">
      <span aria-hidden="true" className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-success-subtle text-success-fg">
        <Icon name="check" className="h-7 w-7" />
      </span>
      <h2 id="reg-done-h" className="font-display text-xl font-extrabold text-fg-heading">
        Registration submitted
      </h2>
      <p className="text-[0.9375rem] text-fg">
        Thanks! Your registration number is <strong className="font-mono">{regNo}</strong>.
      </p>
      <div className="mx-auto flex max-w-xs items-center justify-between gap-2 rounded-xl border border-line bg-surface-sunken px-3 py-2">
        <code className="truncate font-mono text-base font-bold text-fg-heading">{regNo}</code>
        <CopyButton text={regNo} what="registration number" />
      </div>
      <p className="text-[0.9375rem] text-fg-secondary">
        We&apos;ll verify your payment and send your LMS login details to <strong className="break-all text-fg">{email}</strong>. Keep this number.
      </p>
      <p className="text-sm text-fg-muted">Registered for {courseTitle}. Verification usually takes less than a day.</p>
      <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:justify-center">
        <Link href={`${PUBLIC_STATUS_HREF}?reg_no=${encodeURIComponent(regNo)}`} className={buttonClasses({ className: "w-full sm:w-auto" })}>
          Check my registration
        </Link>
        <Link href={PUBLIC_COURSES_HREF} className={buttonClasses({ variant: "secondary", className: "w-full sm:w-auto" })}>
          Explore courses
        </Link>
      </div>
    </section>
  );
}

/** The course is not open for registration (admin status coming soon / closed). */
export function RegistrationNotOpen({ status, coursesHref }: { status: Exclude<CourseStatus, "open">; coursesHref: string }) {
  const copy = NOT_OPEN_COPY[status];
  return (
    <EmptyState
      icon={status === "coming_soon" ? "calendar" : "lock"}
      title={copy.title}
      description={copy.text}
      action={
        <Link href={coursesHref} className={buttonClasses({ size: "sm" })}>
          See all courses
        </Link>
      }
    />
  );
}

/** Pay the next amount on an existing registration (re-upload after "needs info" / rejection too). */
function PayMore({ view, reg, onDone }: { view: MyPlanView; reg: MyRegistration; onDone: (r: MyRegistration) => void }) {
  return (
    <PayAndUpload
      options={reg.pay_options}
      payment={view.payment}
      note={reg.reg_no}
      courseTitle={reg.course_title}
      submitLabel="Submit payment proof"
      onSubmit={async (claim: ClaimPayload, proof: ProofPayload) => {
        const r = await api.post<MyRegistration>(CLAIM_PATH, { registration_id: reg.registration_id, claim, proof });
        if (r.kind === "ok") onDone(r.data);
      }}
    />
  );
}

type NewRegistrationProps = {
  mode: RegisterMode;
  view: MyPlanView;
  title: string;
  onStudentDone: (r: MyRegistration) => void;
  onPublicDone: (r: { regNo: string; email: string; courseTitle: string }) => void;
  onClosed: (s: Exclude<CourseStatus, "open">) => void;
};

function NewRegistration({ mode, view, title, onStudentDone, onPublicDone, onClosed }: NewRegistrationProps) {
  const plan = view.plan!;
  const isPublic = mode === "public";
  const regNo = useMemo(() => newRegNo(), []);
  const [d, setD] = useState<Details>({
    name: view.prefill.name,
    email: view.prefill.email,
    phone: view.prefill.phone,
    college: view.prefill.college,
    branch: view.prefill.branch,
    year: view.prefill.year,
  });
  const [consent, setConsent] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});

  if (!view.pay_configured) return <PaymentNotConfigured subject={`Payment details for ${title}`} />;

  const fields = isPublic ? DETAIL_FIELDS : DETAIL_FIELDS.filter((f) => f.key !== "email");
  const details = (
    <RegistrationStep n={1} title="Your details">
      <p className="text-sm text-fg-secondary">
        {isPublic ? (
          <>No account needed. </>
        ) : (
          <>
            Registering as <strong className="break-all">{view.prefill.email}</strong>.{" "}
          </>
        )}
        Your registration number is <strong className="font-mono">{regNo}</strong>.
      </p>
      {fields.map((f) => (
        <FormField key={f.key} label={f.label} hint={f.hint} error={errs[f.key]} required>
          {(p) => (
            <Input
              {...p}
              name={f.key}
              type={f.type}
              value={d[f.key]}
              maxLength={f.max}
              inputMode={f.inputMode}
              autoComplete={f.autoComplete}
              onChange={(e) => setD((x) => ({ ...x, [f.key]: e.target.value }))}
            />
          )}
        </FormField>
      ))}
    </RegistrationStep>
  );
  const consentBox = (
    <div className="space-y-1">
      <Checkbox label={view.consent_text} checked={consent} onChange={(e) => setConsent(e.target.checked)} aria-invalid={errs.consent ? true : undefined} />
      {errs.consent ? <p className="text-sm text-danger-fg">{errs.consent}</p> : null}
    </div>
  );

  const send = async (claim: ClaimPayload, proof: ProofPayload) => {
    const { email, ...rest } = d;
    try {
      if (isPublic) {
        const mail = email.trim();
        const r = await api.post<PublicRegistered>(PUBLIC_REGISTER_PATH, { course_slug: view.course_slug, reg_no: regNo, ...rest, email: mail, consent, claim, proof }, { handle: { auth: false } });
        if (r.kind === "ok") onPublicDone({ regNo: r.data?.reg_no || regNo, email: r.data?.email || mail, courseTitle: r.data?.course_title || title });
      } else {
        const r = await api.post<MyRegistration>(REGISTER_PATH, { course_slug: view.course_slug, reg_no: regNo, ...rest, consent, claim, proof });
        if (r.kind === "ok") onStudentDone(r.data);
      }
    } catch (err) {
      const closed = closedStatusOf(err);
      if (closed) {
        onClosed(closed);
        return;
      }
      throw err;
    }
  };

  return (
    <PayAndUpload
      options={plan.amount_options}
      payment={view.payment}
      note={regNo}
      courseTitle={title}
      firstStep={2}
      before={details}
      after={consentBox}
      submitLabel={isPublic ? "Submit registration" : "Register and submit payment"}
      validateExtra={() => {
        const e = checkDetails(d, consent, isPublic);
        setErrs(e);
        return e;
      }}
      onOtherErrors={(e) => setErrs((x) => ({ ...x, ...e }))}
      onSubmit={send}
    />
  );
}

const emptyView = (slug: string): MyPlanView => ({
  course_slug: slug,
  plan: null,
  pay_configured: false,
  payment: null,
  consent_text: "",
  prefill: { name: "", email: "", phone: "", college: "", branch: "", year: "" },
  registration: null,
  past: [],
});

export interface CourseRegisterProps {
  slug: string;
  /** Website catalogue title (used before / without a fee plan). */
  courseTitle?: string;
  mode?: RegisterMode;
  /** Registration status known by the server page (the plan view's own `course_status` wins). */
  courseStatus?: CourseStatus;
}

/**
 * Course registration inside the LMS: details, the fee with the UPI QR / ID, the payment
 * screenshot + UTR. Signed-in students then see the live status of the registration; visitors
 * (mode "public", no account) get their registration number and are emailed the LMS login once
 * the payment is verified. Only courses the admin marked "Open for registration" take new
 * registrations (the api answers 409 `registration_closed` otherwise).
 */
export function CourseRegister({ slug, courseTitle, mode = "student", courseStatus }: CourseRegisterProps) {
  const isPublic = mode === "public";
  const mine = useResource<MyPlanView>(isPublic ? null : myPlanPath(slug));
  const pub = useResource<PublicPlan>(isPublic ? publicPlanPath(slug) : null);
  const res = isPublic ? pub : mine;
  const noPlan = isPublic && isApiError(pub.error) && pub.error.status === 404;
  const view: MyPlanView | undefined = useMemo(
    () => (isPublic ? (pub.data ? publicPlanToView(pub.data) : noPlan ? emptyView(slug) : undefined) : mine.data),
    [isPublic, pub.data, noPlan, slug, mine.data],
  );
  const [reg, setReg] = useState<MyRegistration | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [publicDone, setPublicDone] = useState<{ regNo: string; email: string; courseTitle: string } | null>(null);
  const [closedNow, setClosedNow] = useState<Exclude<CourseStatus, "open"> | null>(null);
  useEffect(() => {
    setReg(view?.registration ?? null);
  }, [view]);

  const coursesHref = isPublic ? PUBLIC_COURSES_HREF : "/app/courses";
  const title = view?.plan?.title || reg?.course_title || courseTitle || slug.replace(/-/g, " ");
  const header = (
    <PageHeader
      eyebrow="Course registration"
      title={title}
      description={
        view?.plan && !publicDone
          ? isPublic
            ? `Course fee ${inr(view.plan.fee_paise)}. Fill in your details, pay by UPI and upload the payment screenshot. We verify it and email you your LMS login.`
            : `Course fee ${inr(view.plan.fee_paise)}. Pay by UPI and upload the payment screenshot; we verify it and enrol you here in the LMS.`
          : undefined
      }
      back={{ href: coursesHref, label: "Courses" }}
    />
  );
  if (res.loading && !view) return (<div className="mx-auto max-w-2xl">{header}<LoadingBlock label="Loading registration…" /></div>);
  if (!view) return (<div className="mx-auto max-w-2xl">{header}<ErrorState error={res.error} onRetry={() => void res.reload()} /></div>);

  if (publicDone) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        {header}
        <PublicSubmitted {...publicDone} />
      </div>
    );
  }

  // Explicit status only (api plan view, a 409, or the LMS status the page passed); without one the
  // fee plan decides (none: "opens soon").
  const status: CourseStatus | null = closedNow ?? view.course_status ?? courseStatus ?? null;
  const done = (r: MyRegistration) => {
    setReg(r);
    setSubmitted(true);
  };

  let body: ReactNode;
  if (reg) {
    body = (
      <>
        <RegistrationStatus reg={reg} action={<Link href={MY_REGISTRATIONS_HREF} className="self-center text-sm font-semibold text-brand">My registrations</Link>} />
        {reg.can_pay && !submitted ? (
          <>
            <h2 className="pt-2 font-display text-lg font-bold text-fg-heading">{reg.state === "needs_info" || reg.state === "payment_rejected" ? "Upload your payment proof again" : "Pay the next amount"}</h2>
            <PayMore key={reg.registration_id + reg.claims.length} view={view} reg={reg} onDone={done} />
          </>
        ) : null}
      </>
    );
  } else if (status && status !== "open") {
    body = <RegistrationNotOpen status={status} coursesHref={coursesHref} />;
  } else if (view.plan) {
    body = <NewRegistration mode={mode} view={view} title={title} onStudentDone={done} onPublicDone={setPublicDone} onClosed={setClosedNow} />;
  } else {
    body = (
      <EmptyState
        icon="calendar"
        title="Registration for this course opens soon"
        description="Online registration isn't open for this course yet. Check back soon, or explore other courses."
        action={
          <Link href={coursesHref} className="font-semibold text-brand">
            Explore courses
          </Link>
        }
      />
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {header}
      {submitted ? <SubmittedBanner /> : null}
      {body}
      {isPublic && !reg ? (
        <p className="text-center text-sm text-fg-secondary">
          Already registered?{" "}
          <Link href={PUBLIC_STATUS_HREF} className="font-semibold text-brand">
            Check my registration
          </Link>
        </p>
      ) : null}
      {!reg && view.past.length ? (
        <section aria-labelledby="past-h" className="space-y-3 pt-2">
          <h2 id="past-h" className="font-display text-base font-bold text-fg-heading">Earlier registrations</h2>
          {view.past.map((p) => (
            <RegistrationStatus key={p.registration_id} reg={p} headingLevel="h3" />
          ))}
        </section>
      ) : null}
    </div>
  );
}
