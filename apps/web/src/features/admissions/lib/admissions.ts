/**
 * Admissions (website registrations, instalment fees, manual UPI payment verification).
 * Backend: apps/api/app/modules/admissions (admin.py + service.py `*_out`). Money is paise.
 */

export const REG_STATUSES = [
  "registered",
  "pending_verification",
  "partially_paid",
  "payment_verified",
  "enrolled",
  "rejected",
  "cancelled",
  "completed",
] as const;
export type RegStatus = (typeof REG_STATUSES)[number];

export const REG_LABEL: Record<RegStatus, string> = {
  registered: "Registered",
  pending_verification: "Pending verification",
  partially_paid: "Partially paid",
  payment_verified: "Payment verified",
  enrolled: "Enrolled",
  rejected: "Rejected",
  cancelled: "Cancelled",
  completed: "Completed",
};

export const CLAIM_STATUSES = ["pending", "needs_info", "verified", "rejected", "reversed"] as const;
export type ClaimStatus = (typeof CLAIM_STATUSES)[number];
export const CLAIM_LABEL: Record<ClaimStatus, string> = {
  pending: "Pending verification",
  needs_info: "Correction requested",
  verified: "Verified",
  rejected: "Rejected",
  reversed: "Reversed",
};
export const METHOD_LABEL: Record<string, string> = { upi: "UPI", bank: "Bank transfer", cash: "Cash", other: "Other" };

export interface Instalment {
  label: string;
  amount_paise: number;
  due: string;
  covered_paise?: number;
  done?: boolean;
}

/** service.registration_out(full=False) */
export interface Registration {
  registration_id: string;
  reg_no: string;
  name: string;
  email: string;
  phone: string;
  college: string;
  course_slug: string;
  course_title: string;
  fee_paise: number;
  access_min_paise: number;
  verified_total_paise: number;
  balance_paise: number;
  payment_state: "unpaid" | "partial" | "paid";
  status: RegStatus;
  open_claims: number;
  enrolled_at: string | null;
  user_id: string | null;
  created_at: string;
  updated_at: string;
  /** Verification queue only: an LMS account already exists (linked, or one with this email). */
  has_account?: boolean;
  /** Registrations list only: the most recent payment's reference, date and status. */
  last_utr?: string | null;
  last_paid_on?: string | null;
  last_claim_status?: ClaimStatus | null;
  /** The student's LMS username once an account exists (verify-and-enrol creates it). */
  account_username?: string | null;
  /** When the login email (username + temporary password) last went out; null = never. */
  login_email_sent_at?: string | null;
}

/** service.claim_out */
export interface Claim {
  claim_id: string;
  registration_id: string;
  provider: "manual_upi" | "admin_entry";
  method: string;
  amount_paise: number;
  utr: string | null;
  paid_on: string;
  note: string | null;
  has_proof: boolean;
  proof_name: string | null;
  proof_type: string | null;
  status: ClaimStatus;
  verified_amount_paise: number;
  locks_released: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  submitted_at: string;
  registration?: Registration;
  flags?: string[];
}

export interface AdmissionEvent {
  event_id: string;
  registration_id: string | null;
  claim_id: string | null;
  action: string;
  amount_paise: number;
  actor: string;
  detail: string | null;
  at: string;
}

/** service.registration_out(full=True) + claims + events */
export interface RegistrationDetail extends Registration {
  branch: string;
  year: string;
  current_status: string | null;
  preferred_mode: string | null;
  message: string | null;
  policy: "full" | "instalments";
  allow_instalments: boolean;
  schedule: Instalment[];
  next_due: { label: string; amount_paise: number; due: string } | null;
  status_note: string | null;
  has_resume: boolean;
  resume_name: string | null;
  consent_text: string;
  consent_at: string;
  show_public: boolean;
  marketing_consent: boolean;
  source: string;
  entitlement_id: string | null;
  enrolment_id: string | null;
  enrolled_course_id: string | null;
  enrolled_batch_id: string | null;
  eligible: boolean;
  claims?: Claim[];
  events?: AdmissionEvent[];
}

/** Result of every money/enrolment action (service.finish_enrolment & co). */
export interface ActionResult {
  registration: RegistrationDetail;
  claim?: Claim;
  enrolled?: boolean;
  just_enrolled?: boolean;
  /** Enrolment created a new LMS account for the registration's email (password link emailed). */
  new_account?: boolean;
  /** Approve pressed again for an already approved payment: nothing changed. */
  already_verified?: boolean;
  warning?: string | null;
}

export interface CourseFigures {
  slug: string;
  title: string;
  registered: number;
  enrolled: number;
  expected_paise: number;
  collected_paise: number;
  outstanding_paise: number;
  pending: number;
  rejected: number;
}

export interface Overview {
  registered: number;
  enrolled: number;
  pending_claims: number;
  pending_amount_paise: number;
  needs_info_claims: number;
  rejected_claims: number;
  closed_registrations: number;
  collected_paise: number;
  expected_paise: number;
  outstanding_paise: number;
  courses: CourseFigures[];
  recent: AdmissionEvent[];
}

export interface PaySettings {
  phone: string;
  preferred_app: string;
  upi_id: string;
  payee_name: string;
  instructions: string;
}

export interface FeePlan {
  fee_plan_id: string;
  slug: string;
  title: string;
  course_id: string | null;
  batch_id: string | null;
  fee_paise: number;
  allow_instalments: boolean;
  schedule: Instalment[];
  policy: "full" | "instalments";
  min_first_paise: number;
  access_min_paise: number;
  upi_id: string;
  payee_name: string;
  bank_details: string;
  instructions: string;
  active: boolean;
  updated_at: string | null;
  problems: string[];
}

export interface PlansEnvelope {
  data: FeePlan[];
  pay: PaySettings;
  batches: { batch_id: string; name: string; code: string; course_id: string | null; website_course_slug: string | null }[];
}

/** "2,500" | "2500.5" -> 250050 paise; NaN when it isn't an amount with at most 2 decimals (website toPaise). */
export function toPaise(v: string | number): number {
  const s = String(v ?? "").replace(/[₹,\s]/g, "");
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(s)) return Number.NaN;
  const [r, p = ""] = s.split(".");
  return Number(r) * 100 + Number(`${p}00`.slice(0, 2));
}

/** 250050 -> "2500.50" for an input field. */
export function paiseToInput(paise: number): string {
  return paise % 100 ? (paise / 100).toFixed(2) : String(paise / 100);
}

/** Proof file types the browser can show inline as an image (everything else opens in a tab). */
export const isImageProof = (type: string | null | undefined): boolean => /^image\/(jpeg|png|webp)$/.test(type ?? "");

/** Whether verifying `amount_paise` more reaches the registration's course-access threshold. */
export function approvalEnrols(reg: Pick<Registration, "verified_total_paise" | "access_min_paise" | "fee_paise" | "enrolled_at" | "status"> | undefined, amount_paise: number): boolean {
  if (!reg || reg.enrolled_at) return false;
  if (reg.status === "rejected" || reg.status === "cancelled" || reg.status === "completed") return false;
  const total = reg.verified_total_paise + amount_paise;
  return total >= reg.access_min_paise && (total > 0 || reg.fee_paise === 0);
}

/** UPI deep link a QR code encodes (`upi://pay`); amount in rupees when given. */
export function upiLink(upiId: string, payee: string, amountPaise?: number): string {
  const p = new URLSearchParams({ pa: upiId.trim(), pn: payee.trim() || "Tech Drona", cu: "INR" });
  if (amountPaise && amountPaise > 0) p.set("am", (amountPaise / 100).toFixed(2));
  return `upi://pay?${p.toString()}`;
}

export const regHref = (id: string) => `/finance/admissions/registrations/${id}`;

/* ------------------------------------------------------------------ course registration status */

/** Whether a course takes registrations (website + LMS read it within a minute). */
export const COURSE_STATUSES = ["open", "coming_soon", "closed"] as const;
export type CourseStatus = (typeof COURSE_STATUSES)[number];
export const COURSE_STATUS_LABEL: Record<CourseStatus, string> = {
  open: "Open for registration",
  coming_soon: "Coming soon",
  closed: "Closed",
};
/** StatusBadge tone per course status. */
export const COURSE_STATUS_TONE: Record<CourseStatus, string> = { open: "active", coming_soon: "pending", closed: "inactive" };

/** GET /admin/courses/status row. */
export interface CourseStatusRow {
  course_slug: string;
  status: CourseStatus;
  updated_at: string | null;
  fee_paise: number | null;
  plan_active: boolean;
  batch: { batch_id: string; name: string } | null;
}

/* ------------------------------------------------------------------ LMS login details */

export interface EmailOutcome {
  attempted: boolean;
  sent: boolean;
  reason: null | "email_not_connected" | "send_failed" | string;
}

export interface AccountOut {
  user_id: string;
  username: string;
  email: string;
  created?: boolean;
  /** Only when a password was just made: shown once, never stored in the browser. */
  temporary_password: string | null;
  must_change_password: boolean;
}

/** POST /admin/admissions/claims/{id}/verify-and-enrol */
export interface VerifyEnrolResult {
  registration_id: string;
  status: "enrolled";
  batch: { batch_id: string; name: string } | null;
  account: AccountOut;
  email: EmailOutcome;
  login_url: string;
}

/** POST /admin/admissions/registrations/{id}/login-email */
export interface LoginEmailResult {
  account: AccountOut;
  email: EmailOutcome;
  login_url: string;
}

/** Everything the "Login details" panel shows (and the WhatsApp message carries). */
export interface LoginDetails {
  registration_id: string;
  name: string;
  phone: string;
  course_title: string;
  batch_name: string | null;
  account: AccountOut;
  email: EmailOutcome;
  login_url: string;
}

/** One line on what happened to the login email. */
export function emailStatusText(d: Pick<LoginDetails, "email" | "account">): string {
  if (d.email.sent) return `Login email sent to ${d.account.email}.`;
  if (d.email.reason === "email_not_connected") return "Email isn't connected yet — share these details with the student yourself.";
  if (d.email.attempted) return `The login email to ${d.account.email} didn't go out. Share these details yourself, or try sending it again.`;
  return "No email was sent — share these details with the student yourself.";
}

/** The plain-text login message (Copy all / WhatsApp). */
export function loginMessage(d: LoginDetails): string {
  const lines = [`Hi ${d.name}, you're enrolled in ${d.course_title}${d.batch_name ? ` (${d.batch_name})` : ""} at Tech Drona.`, "", `Log in: ${d.login_url}`, `Username: ${d.account.username}`];
  if (d.account.temporary_password) {
    lines.push(`Temporary password: ${d.account.temporary_password}`);
    if (d.account.must_change_password) lines.push("", "You'll be asked to choose your own password when you first log in.");
  } else {
    lines.push("", "Use your existing password (or tap \"Forgot password\" on the login page).");
  }
  return lines.join("\n");
}

/** wa.me link with the message; Indian 10-digit numbers get the 91 country code. */
export function whatsappLink(phone: string | null | undefined, text: string): string {
  let digits = String(phone ?? "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length === 10) digits = `91${digits}`;
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}
