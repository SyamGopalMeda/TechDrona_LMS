/**
 * Hand-written DTOs for the résumé api (`/me/resumes*`; backend `app/modules/mentoring`, kept as the
 * résumé home). Replace with the generated OpenAPI types once they are regenerated.
 */

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
}

export interface ResumeList {
  data: Resume[];
  suggested_certifications: Certification[];
}

export interface PdfUpload {
  url: string;
  fields: Record<string, string>;
  key: string;
  expires_at: string;
}
