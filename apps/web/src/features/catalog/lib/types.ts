/**
 * Catalog / commerce public DTOs (api-specification §10 CAT, §17 COM-01, §12 LRN-13).
 * The backend returns plain dicts (open objects in OpenAPI); every shape below is verified
 * against the router/service code cited on each interface.
 */

export type PriceType = "free" | "paid";

/** verified: app/modules/catalog/service.py public_card (CAT-01 / CAT-07 list rows). */
export interface CourseCardDto {
  id: string;
  slug: string;
  title: string;
  summary?: string | null;
  course_kind?: string | null;
  category?: string | null;
  level?: string | null;
  language?: string | null;
  tags?: string[];
  price_type: PriceType;
  is_free?: boolean;
  lesson_count?: number | null;
  duration_seconds?: number | null;
  completeness_pct?: number | null;
  published_at?: string | null;
}

/** verified: app/modules/catalog/service.py lesson_out(full=False). */
export interface SyllabusLessonDto {
  id: string;
  lesson_key: string;
  title: string;
  lesson_type?: string | null;
  position?: number;
  is_required?: boolean;
  is_free_preview?: boolean;
  duration_seconds?: number | null;
  est_reading_minutes?: number | null;
}

/** verified: app/modules/catalog/router.py course_detail `syllabus[]` (no module id). */
export interface SyllabusModuleDto {
  title: string;
  position: number;
  lessons: SyllabusLessonDto[];
}

/** verified: app/modules/catalog/router.py course_detail `access_options[]`. */
export type CatalogAccessOptionDto = { type: "free"; action: "enrol" } | { type: "paid"; action: "view_plans"; products_url: string };

/**
 * verified: app/modules/catalog/router.py course_detail (CAT-02). Public, cached and
 * anonymous: there is no `viewer` block (ownership/enrolment is not returned) and no prices.
 */
export interface CourseDetailDto extends CourseCardDto {
  description_md?: string | null;
  outcomes?: string[];
  syllabus?: SyllabusModuleDto[];
  free_preview_lesson_ids?: string[];
  certificate?: { available: boolean; rule: Record<string, unknown> | null } | null;
  access_options?: CatalogAccessOptionDto[];
  refund_rule_text?: string | null;
  version_no?: number;
}

/**
 * A purchasable option for one course, derived on the server from COM-01 products whose
 * `unlocks` include this course (see CourseDetail). Not an api shape.
 */
export interface AccessOptionDto {
  sku: string;
  price_id: string;
  name: string;
  product_kind?: string | null;
  total_paise: number;
  access_days?: number | null;
  interval?: "month" | "year" | null;
}

/** verified: app/modules/commerce/admin.py plan_json `prices[]` (current prices only on COM-01). */
export interface PriceDto {
  price_id: string;
  amount_paise: number;
  currency: string;
  tax_inclusive: boolean;
  is_recurring: boolean;
  valid_from: string;
  valid_until: string | null;
  is_active: boolean;
  gst_breakup_intra_state?: { taxable_paise: number; cgst_paise: number; sgst_paise: number };
}

/** verified: app/modules/commerce/admin.py plan_json. */
export interface PlanDto {
  plan_id: string;
  code: string;
  billing_type: "one_time" | "recurring";
  interval_unit: "month" | "year" | null;
  interval_count: number | null;
  access_duration_days: number | null;
  status?: string;
  prices: PriceDto[];
}

/** verified: app/modules/commerce/admin.py product_json `unlocks[]`. */
export interface ProductUnlockDto {
  item_type: "course" | "test" | "company_path" | "topic_practice" | "feature" | string;
  ref_id: string | null;
  feature_key: string | null;
  quantity: number | null;
}

/** verified: app/modules/commerce/admin.py product_json via commerce/router.py list_products (COM-01). */
export interface ProductDto {
  product_id: string;
  sku: string;
  name: string;
  product_kind: string;
  description_md?: string | null;
  refund_rule?: string | null;
  status?: string;
  unlocks?: ProductUnlockDto[];
  plans: PlanDto[];
}

/** verified: app/modules/learning/router.py verify_certificate (LRN-13). Dates are IST days. */
export interface CertificateVerificationDto {
  public_code?: string;
  status: "valid" | "revoked" | "superseded" | string;
  name_on_certificate?: string;
  course_title?: string;
  issued_at?: string;
  identity_verified?: boolean;
  issuer?: string;
  revoked_on?: string;
  /** issued documents (learning.documents.verify_public): letters and other certificates */
  kind?: "certificate" | "document";
  ref_no?: string;
  doc_type?: string;
  label?: string;
  layout?: "letter" | "certificate";
  recipient?: string;
  program?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  details?: Record<string, string>;
  signatory?: string | null;
  replaces?: string | null;
  superseded_by?: string | null;
  superseded_on?: string | null;
  revoked_reason?: string | null;
  related?: { ref_no: string; label: string }[];
  pdf_check?: boolean;
}

/** Issued-document reference: TD-AL-2026-7K3QX9 (the website printed TD/AL/2026/7K3QX9). */
export const DOC_REF = /^TD-(OL|EO|AL|CC|IC|CA|CP|LR)-\d{4}-[A-HJ-NP-Z2-9]{6}$/;
export const normaliseDocRef = (code: string): string =>
  code.trim().toUpperCase().replace(/[\s/_.-]+/g, "-").replace(/^-+|-+$/g, "");

/** verified: app/core/pagination.py page_meta envelope. */
export interface Paged<T> {
  data: T[];
  page?: { next_cursor: string | null; has_more: boolean; limit: number };
}
