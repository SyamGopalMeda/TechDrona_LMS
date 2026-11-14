import type { Schema } from "@/lib/api-types";

/**
 * Corporate enquiry form (owner decision D8, docs/single-company/REMOVAL-PLAN.md section 8).
 * The form posts to the literal path `public/enquiries` (WS5, 202 {"status":"received"}) so the
 * contract test covers it; limits mirror the api's `EnquiryIn` (support module).
 */
export const ENQUIRY_LIMITS = { nameMin: 2, name: 100, companyMin: 2, company: 150, email: 254, phone: 20, messageMin: 10, messageMax: 4000 } as const;

export type EnquiryField = "name" | "company" | "email" | "phone" | "message" | "consent";

export interface EnquiryInput {
  name: string;
  company: string;
  email: string;
  phone: string;
  message: string;
  consent: boolean;
}

/** Request body sent to the api (phone omitted when blank). `website` is the honeypot. */
export type EnquiryBody = Schema<"EnquiryIn">;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
/** Digits with optional leading +, spaces, dashes or brackets; 7–15 digits. */
const PHONE = /^\+?[\d\s()-]+$/;

/** Client-side checks only; the api re-validates every field. Order matches the form. */
export function validateEnquiry(v: EnquiryInput): Partial<Record<EnquiryField, string>> {
  const e: Partial<Record<EnquiryField, string>> = {};
  const name = v.name.trim();
  if (!name) e.name = "Enter your name.";
  else if (name.length < ENQUIRY_LIMITS.nameMin) e.name = `Enter at least ${ENQUIRY_LIMITS.nameMin} characters.`;
  else if (name.length > ENQUIRY_LIMITS.name) e.name = `Keep your name under ${ENQUIRY_LIMITS.name} characters.`;
  const company = v.company.trim();
  if (!company) e.company = "Enter your company or organisation name.";
  else if (company.length < ENQUIRY_LIMITS.companyMin) e.company = `Enter at least ${ENQUIRY_LIMITS.companyMin} characters.`;
  else if (company.length > ENQUIRY_LIMITS.company) e.company = `Keep the company name under ${ENQUIRY_LIMITS.company} characters.`;
  const email = v.email.trim();
  if (!email) e.email = "Enter your work email address.";
  else if (email.length > ENQUIRY_LIMITS.email || !EMAIL.test(email)) e.email = "Enter an email address like name@company.com.";
  const phone = v.phone.trim();
  if (phone) {
    const digits = phone.replace(/\D/g, "");
    if (!PHONE.test(phone) || digits.length < 7 || digits.length > 15) e.phone = "Enter a phone number with 7 to 15 digits, or leave it blank.";
  }
  const message = v.message.trim();
  if (message.length < ENQUIRY_LIMITS.messageMin) e.message = `Tell us a little more (at least ${ENQUIRY_LIMITS.messageMin} characters).`;
  else if (message.length > ENQUIRY_LIMITS.messageMax) e.message = `Keep your message under ${ENQUIRY_LIMITS.messageMax} characters.`;
  if (!v.consent) e.consent = "Agree to be contacted about your enquiry.";
  return e;
}

export function toEnquiryBody(v: EnquiryInput, honeypot: string): EnquiryBody {
  const phone = v.phone.trim();
  return {
    name: v.name.trim(),
    company: v.company.trim(),
    email: v.email.trim(),
    ...(phone ? { phone } : {}),
    message: v.message.trim(),
    consent: true,
    ...(honeypot ? { website: honeypot } : {}),
  };
}
