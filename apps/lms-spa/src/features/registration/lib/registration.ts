/**
 * Course registration with manual UPI payment. Signed-in students use /me/admissions/*; visitors
 * without an account use /public/admissions/* (through the same-origin /api/v1 BFF, which adds
 * the service token the api requires). Money is integer paise everywhere (ADR-0012).
 */
import { isApiError } from "@/lib/api/errors";

/** LMS registration status of a course (admin: Open for registration / Coming soon / Closed). */
export type CourseStatus = "open" | "coming_soon" | "closed";
export const COURSE_STATUSES: readonly CourseStatus[] = ["open", "coming_soon", "closed"];
export const isCourseStatus = (v: unknown): v is CourseStatus => typeof v === "string" && (COURSE_STATUSES as readonly string[]).includes(v);

export interface AmountOption {
  label: string;
  amount_paise: number;
}

export interface PlanInfo {
  slug: string;
  title: string;
  fee_paise: number;
  allow_instalments: boolean;
  schedule: { label: string; amount_paise: number; due: string }[];
  policy: string;
  min_first_paise: number;
  access_min_paise: number;
  instructions: string;
  active: boolean;
  amount_options: AmountOption[];
}

export interface PaymentInfo {
  upi_id: string;
  payee_name: string;
  phone: string;
  preferred_app: string;
  bank_details: string;
  instructions: string[];
}

export type ClaimStatus = "pending" | "needs_info" | "verified" | "rejected" | "reversed";

export interface MyClaim {
  claim_id: string;
  amount_paise: number;
  method: string;
  utr: string | null;
  paid_on: string | null;
  status: ClaimStatus;
  reason: string | null;
  proof_name: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
}

export type StudentState =
  | "awaiting_payment"
  | "pending"
  | "needs_info"
  | "payment_rejected"
  | "partially_paid"
  | "verified"
  | "enrolled"
  | "rejected"
  | "cancelled";

export interface MyRegistration {
  registration_id: string;
  reg_no: string;
  course_slug: string;
  course_title: string;
  status: string;
  state: StudentState;
  reason: string | null;
  fee_paise: number;
  verified_total_paise: number;
  balance_paise: number;
  open_claims: number;
  next_due: { label: string; amount_paise: number; due: string } | null;
  can_pay: boolean;
  pay_options: AmountOption[];
  enrolled: boolean;
  enrolled_at: string | null;
  course_href: string | null;
  /** The batch the student was added to (set when enrolled). */
  batch?: { batch_id: string; name: string } | null;
  created_at: string | null;
  claims: MyClaim[];
}

export interface Prefill {
  name: string;
  email: string;
  phone: string;
  college: string;
  branch: string;
  year: string;
}

export interface MyPlanView {
  course_slug: string;
  /** Registration status set by the admin; absent from older api builds. */
  course_status?: CourseStatus;
  plan: PlanInfo | null;
  pay_configured: boolean;
  payment: PaymentInfo | null;
  consent_text: string;
  prefill: Prefill;
  registration: MyRegistration | null;
  past: MyRegistration[];
}

export interface ClaimPayload {
  amount_paise: number;
  method: "upi" | "bank";
  utr: string;
  paid_on: string;
}

export interface ProofPayload {
  filename: string;
  data_b64: string;
  original_sha256: string;
}

export const MY_ADMISSIONS = "me/admissions";
export const myPlanPath = (slug: string) => `me/admissions/plans/${encodeURIComponent(slug)}`;
export const REGISTER_PATH = "me/admissions/registrations";
export const CLAIM_PATH = "me/admissions/claims";
export const registerHref = (slug: string) => `/app/courses/${encodeURIComponent(slug)}/register`;
export const MY_REGISTRATIONS_HREF = "/app/registrations";

/* Public (no account) registration. */
export const COURSE_STATUS_PATH = "public/courses/status";
export const publicPlanPath = (slug: string) => `public/admissions/plans/${encodeURIComponent(slug)}`;
export const PUBLIC_REGISTER_PATH = "public/admissions/registrations";
export const PUBLIC_STATUS_PATH = "public/admissions/status";
export const publicRegisterHref = (slug: string) => `/register/${encodeURIComponent(slug)}`;
export const PUBLIC_STATUS_HREF = "/register/status";
export const PUBLIC_COURSES_HREF = "/register";

/** `GET public/admissions/plans/{slug}` (api admissions/public.py public_plan). */
export interface PublicPlan {
  slug: string;
  title: string;
  fee_paise: number;
  allow_instalments: boolean;
  schedule: { label: string; amount_paise: number; due: string }[];
  policy: string;
  min_first_paise: number;
  access_min_paise: number;
  upi_id: string;
  payee_name: string;
  bank_details: string;
  instructions: string;
  active: boolean;
  course_status?: CourseStatus;
  pay: { phone: string; preferred_app: string; upi_id: string; payee_name: string; instructions: string };
  pay_configured: boolean;
  consent_text: string;
}

/** `POST public/admissions/registrations` 201 (202 `{status: "received"}` for the honeypot). */
export interface PublicRegistered {
  reg_no?: string;
  email?: string;
  status: string;
  course_title?: string;
}

/** `POST public/admissions/status` (api service.status_for_student). */
export interface PublicRegStatus {
  reg_no: string;
  email: string;
  course_slug: string;
  course_title: string;
  status: string;
  fee_paise: number;
  verified_total_paise: number;
  balance_paise: number;
  open_claims: number;
  next_due: { label: string; amount_paise: number; due: string } | null;
  enrolled: boolean;
}

/** Amounts payable first: the full fee, or the first instalment (api student._first_options). */
export function firstOptions(p: Pick<PublicPlan, "fee_paise" | "allow_instalments" | "schedule" | "min_first_paise">): AmountOption[] {
  const opts: AmountOption[] = [{ label: "Full fee", amount_paise: p.fee_paise }];
  const s0 = p.schedule[0];
  if (p.allow_instalments && s0) {
    const first = Math.max(s0.amount_paise, p.min_first_paise);
    if (first > 0 && first < p.fee_paise) opts.push({ label: s0.label, amount_paise: first });
  }
  return opts;
}

/** The public plan in the signed-in view's shape, so one form serves both (api student._payment rules). */
export function publicPlanToView(p: PublicPlan): MyPlanView {
  const open = p.active && p.fee_paise > 0;
  return {
    course_slug: p.slug,
    course_status: p.course_status,
    plan: open
      ? {
          slug: p.slug,
          title: p.title,
          fee_paise: p.fee_paise,
          allow_instalments: p.allow_instalments,
          schedule: p.schedule,
          policy: p.policy,
          min_first_paise: p.min_first_paise,
          access_min_paise: p.access_min_paise,
          instructions: p.instructions,
          active: p.active,
          amount_options: firstOptions(p),
        }
      : null,
    pay_configured: open && p.pay_configured,
    payment: open
      ? {
          upi_id: p.pay.upi_id || p.upi_id || "",
          payee_name: p.pay.payee_name || p.payee_name || "",
          phone: p.pay.phone || "",
          preferred_app: p.pay.preferred_app || "",
          bank_details: p.bank_details || "",
          instructions: [p.pay.instructions, p.instructions].filter(Boolean),
        }
      : null,
    consent_text: p.consent_text,
    prefill: { name: "", email: "", phone: "", college: "", branch: "", year: "" },
    registration: null,
    past: [],
  };
}

/** The course status a 409 `registration_closed` carries in `course_status` (null for any other error). */
export function closedStatusOf(err: unknown): Exclude<CourseStatus, "open"> | null {
  if (!isApiError(err) || err.code !== "registration_closed") return null;
  const s = (err.problem as { course_status?: unknown } | null)?.course_status;
  return isCourseStatus(s) && s !== "open" ? s : "closed";
}

/** A public status lookup in the student's terms (same rules as api student.student_state, without claims). */
export function publicState(r: Pick<PublicRegStatus, "status" | "enrolled" | "open_claims">): StudentState {
  if (r.enrolled || r.status === "enrolled" || r.status === "completed") return "enrolled";
  if (r.status === "rejected" || r.status === "cancelled") return r.status;
  if (r.open_claims > 0) return "pending";
  if (r.status === "payment_verified") return "verified";
  if (r.status === "partially_paid") return "partially_paid";
  return "awaiting_payment";
}

/** Copy for a course that is not open for registration. */
export const NOT_OPEN_COPY: Record<Exclude<CourseStatus, "open">, { title: string; text: string }> = {
  coming_soon: { title: "Registration is coming soon", text: "Registration for this course isn't open yet. Check back soon, or explore other courses." },
  closed: { title: "Registration is closed", text: "Registration for this course is closed. Explore other courses that are open now." },
};

export const SUBMITTED_MESSAGE = "Payment submitted. We'll verify it and enrol you — usually within a day.";

const inrFormat = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2, minimumFractionDigits: 0 });
/** ₹5,000 / ₹1,250.50 */
export const inr = (paise: number) => inrFormat.format(paise / 100);

/** "upi://pay?pa=…&pn=…&am=5000.00&cu=INR&tn=…" (same as the website's upiLink). The UPI ID goes in
 *  unencoded: some UPI apps reject "%40" in place of "@". */
export function upiLink(upiId: string, payee: string, amountPaise: number, note: string): string {
  const q = new URLSearchParams({ pn: payee || "Tech Drona", am: (amountPaise / 100).toFixed(2), cu: "INR", tn: note.slice(0, 50) });
  return `upi://pay?pa=${upiId.replace(/[^\w.@-]/g, "")}&${q.toString().replace(/\+/g, "%20")}`;
}

const REG_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O/1/I (api rules.new_reg_no)
/** A registration number made in the browser so it can be the payment note before submitting. */
export function newRegNo(rand: (n: number) => Uint8Array = (n) => crypto.getRandomValues(new Uint8Array(n))): string {
  return `TDR-${Array.from(rand(8), (b) => REG_ALPHABET[b % REG_ALPHABET.length]).join("")}`;
}

/** Today's date in India (YYYY-MM-DD), the default payment date. */
export function todayIST(now: Date = new Date()): string {
  return new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10);
}

/** What is wrong with a UPI / bank reference (same rules as the api, rules.ref_problem). */
export function refProblem(ref: string, method: "upi" | "bank"): string | null {
  const r = ref.toUpperCase().replace(/[\s-]/g, "");
  if (!r) return "Enter the transaction reference (UTR) from your payment app or bank.";
  if (method === "upi") {
    if (/^[TP]/.test(r) || /[A-Z]/.test(r)) return "That looks like the app's own transaction ID. Enter the 12-digit UPI reference / UTR number instead (only digits).";
    if (!/^\d{12,16}$/.test(r)) return "A UPI reference (UTR) is usually 12 digits. Please check the number.";
  }
  if (!/^[A-Z0-9]{10,22}$/.test(r)) return "Enter the reference exactly as shown (10-22 letters and digits).";
  return null;
}

export type BadgeToneName = "neutral" | "brand" | "info" | "success" | "warning" | "danger";

export const STATE_LABEL: Record<StudentState, { label: string; tone: BadgeToneName; text: string }> = {
  awaiting_payment: { label: "Waiting for your payment", tone: "warning", text: "Pay the fee and upload the payment screenshot to complete your registration." },
  pending: { label: "Payment under verification", tone: "info", text: "We're checking your payment with the bank. We'll enrol you once it's verified — usually within a day." },
  needs_info: { label: "More information needed", tone: "warning", text: "We couldn't verify your payment yet. Read the note below and upload the payment proof again." },
  payment_rejected: { label: "Payment not accepted", tone: "danger", text: "We couldn't match this payment. Read the reason below; if you paid, upload the correct receipt." },
  partially_paid: { label: "Part payment verified", tone: "info", text: "Your payment so far is verified. Pay the rest to complete your registration." },
  verified: { label: "Payment verified", tone: "success", text: "Your payment is verified. We're setting up your course access." },
  enrolled: { label: "Enrolled", tone: "success", text: "You're enrolled. The course is in your LMS." },
  rejected: { label: "Registration not accepted", tone: "danger", text: "This registration was closed. Contact Tech Drona if you have questions." },
  cancelled: { label: "Registration cancelled", tone: "neutral", text: "This registration was cancelled. You can register again." },
};

export const CLAIM_LABEL: Record<ClaimStatus, string> = {
  pending: "Under verification",
  needs_info: "More information needed",
  verified: "Verified",
  rejected: "Not accepted",
  reversed: "Reversed",
};
