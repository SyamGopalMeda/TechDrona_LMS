/** Admin documents API (apps/api/app/modules/learning/doc_admin.py). */

import type { OutboxStatus } from "./types";

export type DocStatus = "valid" | "revoked" | "superseded";
export type FieldKind = "text" | "date" | "longtext" | "money" | "select";

export interface DocField {
  key: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  hint?: string;
  options?: string[];
}

export interface LetterSections {
  hero?: string;
  benefits?: string[];
  terms?: string[];
  next?: string[];
  accept?: boolean;
}

export interface DocTypeDef {
  key: string;
  label: string;
  short: string;
  layout: "letter" | "certificate";
  prefix: string;
  fields: DocField[];
  paragraphs: string[];
  sections: LetterSections | null;
  email_key: string | null;
}

export interface DocTypesResponse {
  types: DocTypeDef[];
  emails: { key: string; label: string; attach: string | null }[];
  settings_problem: string | null;
}

export interface Recipient {
  name: string;
  email: string;
  college?: string;
  reg_no?: string;
}

export interface IssuedDoc {
  id: string;
  doc_type: string;
  label: string;
  short: string;
  layout: "letter" | "certificate";
  ref_no: string;
  recipient: Recipient;
  title: string | null;
  user_id: string | null;
  enrolment_id: string | null;
  course_id: string | null;
  fields: Record<string, string>;
  subject: string | null;
  issue_date: string;
  status: DocStatus;
  origin: string;
  replaces_id: string | null;
  superseded_by_id: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  pdf_available: boolean;
  content_sha256: string | null;
  template_version: string;
  verify_url: string;
  created_at: string | null;
  email_status: OutboxStatus | null;
}

export interface DocEmail {
  id: string;
  status: OutboxStatus;
  origin: string;
  attempts: number;
  last_error: string | null;
  to: string | null;
  subject: string | null;
  sent_at: string | null;
  created_at: string | null;
}

export interface IssuedDocDetail extends IssuedDoc {
  emails: DocEmail[];
  paragraphs: string[];
  related: { id: string; ref_no: string; label: string; status: DocStatus }[];
}

export interface PreviewResult {
  pdf_base64: string;
  missing: string[];
  leftovers: string[];
  settings_problem: string | null;
  subject: string;
}

export interface Prefill {
  recipient: Recipient;
  fields: Record<string, string>;
  user_id: string;
  enrolment_id: string;
  batch_id: string | null;
  course_id: string;
}

export interface DocSettings {
  company: string;
  legal_name: string;
  address: string;
  phone: string;
  email: string;
  website: string;
  reg_lines: string[];
  signatory: string;
  designation: string;
  signatory_email: string;
  signatory_phone: string;
  signatory2: string;
  designation2: string;
  portal_url: string;
  auto_admission_letter: boolean;
  images: Record<"signature" | "seal" | "signature2", boolean>;
  problem: string | null;
  auto_send: boolean;
}

export interface TemplateEntry<D> {
  label: string;
  attach?: string | null;
  default: D;
  override: Partial<D> | null;
}

export interface TemplatesCatalogue {
  documents: Record<string, TemplateEntry<{ paragraphs: string[]; sections: LetterSections | null }>>;
  emails: Record<string, TemplateEntry<{ subject: string; body: string }>>;
}

export const DOC_STATUS_LABEL: Record<DocStatus, string> = { valid: "Valid", revoked: "Revoked", superseded: "Superseded" };

/** Required fields of a type that are still empty (mirrors docdefs.missing_fields). */
/** Same rule as the api (learning/docdefs.py EMAIL_RE). */
export const isEmail = (s: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());

export function missingFields(def: DocTypeDef | undefined, recipient: Recipient, fields: Record<string, string>): string[] {
  if (!def) return [];
  const out: string[] = [];
  if (!recipient.name.trim()) out.push("Student name");
  const email = recipient.email.trim();
  if (!email) out.push("Student email");
  else if (!isEmail(email)) out.push("Valid student email");
  for (const f of def.fields) if (f.required && !(fields[f.key] ?? "").trim()) out.push(f.label);
  return out;
}

/** Lines of a textarea as a list (empty lines dropped). */
export const toLines = (s: string): string[] => s.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);

/** A PDF returned as base64 -> an object URL to open in a new tab. */
export function pdfUrlFromBase64(b64: string): string {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
}

/** Read a picked image file as a data URL (PNG / JPEG, under 300 KB). */
export function readImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!/^image\/(png|jpeg)$/.test(file.type)) return reject(new Error("Choose a PNG or JPEG image."));
    if (file.size > 300_000) return reject(new Error("Images must be under 300 KB."));
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(new Error("The image could not be read."));
    r.readAsDataURL(file);
  });
}
