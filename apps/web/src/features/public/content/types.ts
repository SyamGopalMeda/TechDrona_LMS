/**
 * Structured static content for public policy and help pages (PUB-018/019). Content is data so
 * the pages stay consistent and testable; every statement is derived from the product docs
 * (privacy-and-data-retention.md, product-requirements.md, blueprint-brief.md,
 * account-unblock-workflow.md, analytics-event-schema.md). Nothing here is legal advice and
 * the policy texts carry a "Draft — pending legal review" banner until counsel signs off (E10).
 */
export interface ContentLink {
  href: string;
  label: string;
}

export interface ContentSection {
  id: string;
  heading: string;
  paragraphs?: string[];
  items?: string[];
  table?: { caption: string; head: string[]; rows: string[][] };
  links?: ContentLink[];
}

export interface ContentDoc {
  slug: string;
  title: string;
  summary: string;
  /** Policy pages are drafts until counsel review (implementation-roadmap E10). */
  draft: boolean;
  sections: ContentSection[];
}
