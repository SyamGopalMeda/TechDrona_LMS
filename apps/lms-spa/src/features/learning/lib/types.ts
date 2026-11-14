/**
 * Learning DTOs (api-specification §12 LRN). The backend returns plain dicts (open objects in
 * OpenAPI); every shape below is verified against the router/service code cited on it.
 * Progress values are always server-computed (coverage + quiz evidence), never derived here.
 */

import type { Body } from "@/lib/api-types";

/** verified: app/modules/catalog/schemas.py LessonType. */
export type LessonKind = "video" | "article" | "pdf" | "practice_set" | "quiz" | "coding" | "assignment" | "live_link" | string;
export type LessonStatus = "not_started" | "in_progress" | "completed" | string;

/** verified: app/modules/learning/router.py enrolment_out (LRN-02 rows, LRN-01, LRN-03). */
export interface EnrolmentDto {
  id: string;
  course_id: string;
  course_slug: string | null;
  course_title: string | null;
  course_version_id: string;
  organization_id: string | null;
  batch_id: string | null;
  source: string;
  status: "active" | "completed" | "expired" | string;
  progress_pct: number;
  enrolled_at: string;
  completed_at: string | null;
  expires_at: string | null;
  last_activity_at: string | null;
}

/** verified: app/modules/learning/service.py certificate_out (LRN-11 rows, LRN-01). */
export interface CertificateDto {
  id: string;
  public_code: string;
  course_id: string;
  /** null on LRN-01 (dashboard calls certificate_out without a title). */
  course_title: string | null;
  name_on_certificate: string;
  issued_at: string;
  status: "valid" | "revoked";
  revoked_at: string | null;
  verify_url: string;
  pdf_available: boolean;
}

/** verified: app/modules/learning/router.py _assignment_out (+ my_status/my_score from _my_assignments). */
export interface AssignmentDto {
  id: string;
  title: string;
  instructions_md: string | null;
  submission_type: "file" | "text" | "link" | "code" | string;
  max_score: number;
  rubric: Record<string, unknown> | null;
  allowed_file_types: string[];
  course_id: string | null;
  batch_id: string | null;
  available_from: string | null;
  due_at: string | null;
  late_until: string | null;
  late_penalty_pct: number;
  max_attempts: number;
  status: string;
  grades_released: boolean;
  window: "on_time" | "late" | "closed";
}

/** verified: app/modules/learning/router.py _my_assignments (LRN-08 rows, LRN-01 assigned_work). */
export interface AssignmentListItemDto extends AssignmentDto {
  /** Latest submission status, or "not_submitted". */
  my_status: "not_submitted" | "submitted" | "late" | "graded" | "returned" | string;
  /** Only once grades are released. */
  my_score: number | null;
}

/** verified: app/modules/learning/router.py _submission_out. Grade fields only after release. */
export interface SubmissionDto {
  id: string;
  assignment_id: string;
  attempt_no: number;
  status: "submitted" | "late" | "graded" | "returned" | string;
  submitted_at: string | null;
  body_text: string | null;
  link_url: string | null;
  file_s3_keys: string[];
  code_submission_id: string | null;
  returned_reason: string | null;
  score?: number | null;
  rubric_scores?: Record<string, unknown> | null;
  feedback_md?: string | null;
  graded_at?: string | null;
}

/** verified: app/modules/learning/router.py my_assignment (LRN-09). */
export interface AssignmentDetailDto extends AssignmentDto {
  submissions: SubmissionDto[];
}

export type SubmissionBody = Body<"me/assignments/{assignment_id}/submissions", "post">;

/** verified: app/modules/media/router.py file_upload (MED-02) response. */
export interface UploadTicket {
  purpose: string;
  s3_key: string;
  upload: { url: string; fields: Record<string, string> };
  expires_at: string;
  max_bytes: number;
}

/** verified: app/modules/learning/router.py dashboard (LRN-01). `tests` and `banners` are always []. */
export interface DashboardDto {
  continue_learning: EnrolmentDto[];
  assigned_work: AssignmentListItemDto[];
  tests: unknown[];
  expiring: EnrolmentDto[];
  certificates: CertificateDto[];
  banners: unknown[];
}

/** verified: app/modules/catalog/service.py lesson_out(full=False) + course_overview additions. */
export interface CourseLessonRef {
  id: string;
  lesson_key: string;
  title: string;
  lesson_type?: LessonKind;
  position?: number;
  is_required?: boolean;
  is_free_preview?: boolean;
  duration_seconds?: number | null;
  est_reading_minutes?: number | null;
  status?: LessonStatus;
  progress_pct?: number;
  video_position_s?: number | null;
}

/** verified: app/modules/learning/router.py course_overview (LRN-04). */
export interface CourseOverviewDto {
  enrolment: EnrolmentDto;
  title: string;
  modules: { id: string; module_key: string; title: string; lessons: CourseLessonRef[] }[];
  next_lesson: { lesson_id: string; title: string } | null;
  certificate:
    | (Omit<CertificateDto, "status"> & { status: "issued" | "revoked" })
    | { status: "not_eligible" | "pending"; reason?: string | null };
  version_migration: { available_version_id: string; version_no: number; change_type: string | null; changelog: string | null } | null;
}

/** verified: app/modules/catalog/service.py asset_out. */
export interface LessonAssetDto {
  id: string;
  asset_type: "video" | "pdf" | "image" | "attachment" | "captions" | string;
  provider: string;
  status: "ready" | "uploading" | "processing" | "failed" | string;
  scan_status?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  duration_seconds?: number | null;
  position?: number;
}

/** verified: app/modules/learning/router.py lesson_payload `resources[]`. */
export interface LessonResourceDto {
  id: string;
  title: string;
  resource_type?: string | null;
  access_level?: string | null;
}

/** verified: app/modules/learning/router.py lesson_payload (LRN-05) = catalog lesson_out(full=True) + extras. */
export interface LessonDto {
  id: string;
  lesson_key: string;
  title: string;
  lesson_type: LessonKind;
  position?: number;
  is_required?: boolean;
  is_free_preview?: boolean;
  duration_seconds?: number | null;
  est_reading_minutes?: number | null;
  course_module_id?: string;
  /** Structured (JSONB) article document — not HTML. */
  article_body?: Record<string, unknown> | null;
  test_id?: string | null;
  coding_problem_id?: string | null;
  assignment_id?: string | null;
  live_url?: string | null;
  assets?: LessonAssetDto[];
  playback?: { token_url: string } | null;
  resources?: LessonResourceDto[];
  progress?: { status: LessonStatus; progress_pct: number; video_position_s: number | null; watched_seconds: number | null } | null;
  access?: { reason: string | null };
}

/** verified: learning/router.py certificate_pdf and media/router.py download. */
export interface SignedUrlDto {
  url: string | null;
  expires_at?: string | null;
}
