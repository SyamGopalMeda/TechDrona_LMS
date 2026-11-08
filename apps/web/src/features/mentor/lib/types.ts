/**
 * Hand-written DTOs for the mentoring + résumé api (api-spec §13.1 PLC-36..52; backend
 * `app/modules/mentoring`). Replace with the generated OpenAPI types once they are regenerated.
 */

export type SessionKind = "mock_interview" | "resume_review" | "career_guidance";
export type Duration = 30 | 45 | 60;

export interface Slot {
  id: string;
  mentor_id: string;
  mentor_name: string | null;
  organization_id: string | null;
  starts_at: string;
  ends_at: string;
  duration_minutes: Duration;
  session_kind: SessionKind;
  company_id: string | null;
  status: "open" | "booked" | "cancelled" | "completed";
}

export interface MentorSlot extends Slot {
  booking_id: string | null;
  student_id: string | null;
  student_name: string | null;
}

export const SCORE_KEYS = ["communication", "problem_solving", "technical_depth", "confidence", "overall"] as const;
export type ScoreKey = (typeof SCORE_KEYS)[number];
export type Scores = Record<ScoreKey, number>;

export interface Feedback {
  id: string;
  booking_id: string;
  mentor_id: string;
  scores: Scores;
  comments: string | null;
  released_at: string | null;
  created_at: string;
  starts_at: string;
  session_kind: SessionKind;
}

export type BookingStatus =
  | "booked"
  | "rescheduled"
  | "cancelled_by_student"
  | "cancelled_by_mentor"
  | "completed"
  | "student_no_show"
  | "mentor_no_show";

export interface Booking {
  id: string;
  slot_id: string;
  status: BookingStatus;
  starts_at: string;
  ends_at: string;
  duration_minutes: Duration;
  session_kind: SessionKind;
  company_id: string | null;
  mentor_id: string;
  mentor_name: string | null;
  meeting_url: string | null;
  quota_consumed: boolean;
  credit_restored: boolean;
  cancelled_at: string | null;
  created_at: string;
  /** starts_at − 12 h: changes before this keep the credit (FR-PLC-010). */
  free_change_until: string;
  feedback: Feedback | null;
}

export interface Quota {
  has_package: boolean;
  mentor_sessions_remaining: number;
  resume_reviews_remaining: number;
}

export interface Session extends Booking {
  student_id: string;
  student_name: string | null;
  feedback_due_at: string;
  feedback_overdue: boolean;
}

export interface Note {
  id: string;
  student_id: string;
  author_id: string;
  author_name: string | null;
  booking_id: string | null;
  body: string;
  created_at: string;
}

export interface SessionDetail extends Session {
  notes: Note[];
  weak_topics: string[];
}

export interface PageMeta {
  next_cursor: string | null;
  has_more: boolean;
  limit: number;
}

export interface SlotList {
  data: Slot[];
  page?: PageMeta;
  quota: Quota;
}

export interface BookingList {
  data: Booking[];
  page?: PageMeta;
  quota: Quota;
}

export interface SessionList {
  data: Session[];
  page?: PageMeta;
  counts?: { upcoming?: number; pending_feedback?: number };
}

export interface DeleteSlotResult {
  slot: MentorSlot;
  cancelled_booking_id: string | null;
  credited: boolean;
}

/* ------------------------------------------------------------------ résumé */

type Year = string | number;

export interface ResumeContent {
  headline?: string;
  summary?: string;
  education: { institution: string; degree: string; field?: string; start_year?: Year; end_year?: Year; score?: string }[];
  skills: string[];
  projects: { title: string; description?: string; tech?: string[]; link?: string }[];
  internships: { company: string; role: string; start?: string; end?: string; description?: string }[];
  achievements: string[];
  certifications: Certification[];
}

export interface Certification {
  title: string;
  issuer?: string | null;
  issued_on?: string | null;
  credential_id?: string | null;
}

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
}

export interface ReviewComment {
  section: string;
  comment: string;
}

export interface ResumeReview {
  id: string;
  resume_id: string;
  status: "requested" | "in_review" | "completed" | "cancelled";
  note: string | null;
  requested_at: string;
  completed_at: string | null;
  comments: ReviewComment[];
  summary: string | null;
}

export type TemplateKey = "ats_classic" | "ats_modern";

export interface Resume {
  id: string;
  template_key: TemplateKey;
  version_no: number;
  content: ResumeContent;
  checklist_score: number;
  checklist: ChecklistItem[];
  is_current: boolean;
  has_pdf: boolean;
  pdf_uploaded_at: string | null;
  created_at: string;
  updated_at: string;
  reviews: ResumeReview[];
}

export interface ResumeList {
  data: Resume[];
  quota: Quota;
  suggested_certifications: Certification[];
}

export interface PdfUpload {
  url: string;
  fields: Record<string, string>;
  key: string;
  expires_at: string;
}

export interface ReviewQueueItem extends ResumeReview {
  student_id: string;
  student_name: string | null;
  reviewer_id: string | null;
  resume: { id: string; template_key: TemplateKey; version_no: number; content: ResumeContent; checklist_score: number };
}

/** `GET /mentor/students` row (app/modules/placement/mentoring.py). */
export interface MentorStudentSummary {
  user_id: string;
  full_name: string | null;
  batch_id: string | null;
  batch_name: string | null;
  batches: { batch_id: string; name: string | null }[];
  target_companies: string[];
  next_session_at: string | null;
}

/** `GET /mentor/students/{id}` (PLC-46). */
export interface MentorStudentDetail extends MentorStudentSummary {
  readiness: unknown[];
  topics: { topic_id: string; name: string | null; mastery: number | null; band: string; attempts: number }[];
  weak_topics: string[];
  feedback: Feedback[];
  notes: Note[];
}
