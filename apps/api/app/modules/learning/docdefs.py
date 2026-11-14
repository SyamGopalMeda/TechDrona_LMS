# ruff: noqa: E501, RUF001  (wording data ported verbatim from the website; long lines are sentences)
"""Student documents and their emails: what each document is, which details it needs, its default
wording, and the placeholder engine. Pure data + helpers (no DB), shared by the PDF renderer
(``docpdf``), the service (``documents``), the admin API (``doc_admin``) and the tests.

Ported from the company website (``tech drona/src/lib/docdefs.js``) so documents issued here read
exactly like the website's. Wording uses ``{{placeholders}}``; owners can override any document's
paragraphs / letter sections and any email's subject / body (``document_templates``), these
defaults are used otherwise. Nothing here names a real person, number or registration: company
details and the signatory come from the document settings.

Reference numbers: ``TD-<prefix>-<year>-<6 chars>`` (e.g. ``TD-AL-2026-7K3QX9``). The website
printed ``TD/AL/2026/7K3QX9``; the verify page accepts both spellings.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

# --------------------------------------------------------------------------- fields
# kind: text | date | longtext | money (free text such as "Rs 5,000 per month" or "Unpaid") | select
FIELDS: dict[str, dict[str, Any]] = {
    "program": {"label": "Program / course", "kind": "text", "required": True},
    "role": {
        "label": "Internship role / track",
        "kind": "text",
        "required": True,
        "hint": "e.g. Full Stack Development Intern",
    },
    "position": {"label": "Position", "kind": "text", "required": True},
    "department": {"label": "Department / team", "kind": "text"},
    "start_date": {"label": "Start date", "kind": "date", "required": True},
    "end_date": {"label": "End date", "kind": "date"},
    "joining_date": {"label": "Date of joining", "kind": "date", "required": True},
    "duration": {
        "label": "Duration",
        "kind": "text",
        "required": True,
        "hint": "e.g. 3 months, 16 weeks, 45 hours",
    },
    "mode": {"label": "Mode", "kind": "select", "options": ["Online", "On-site", "Hybrid"], "required": True},
    "location": {"label": "Location", "kind": "text", "hint": "City / office, or Remote"},
    "stipend": {"label": "Stipend", "kind": "money", "hint": "e.g. ₹5,000 per month, or Unpaid"},
    "intern_stipend": {
        "label": "Stipend",
        "kind": "money",
        "required": True,
        "hint": "e.g. ₹5,000 per month — or type Unpaid (printed as an unpaid internship)",
    },
    "work_hours": {
        "label": "Working days and hours",
        "kind": "text",
        "hint": "e.g. Monday to Friday, 10 AM–6 PM IST (about 40 hours a week)",
    },
    "responsibilities": {
        "label": "Responsibilities (one per line)",
        "kind": "longtext",
        "hint": "What the intern will work on. Printed as a list (at most 8).",
    },
    "course_year": {
        "label": "Student's course and year",
        "kind": "text",
        "hint": "e.g. B.Tech CSE, 3rd year — colleges need this for internship credit",
    },
    "roll_no": {"label": "College roll / register no.", "kind": "text"},
    "no_fee": {
        "label": "Print “no fee charged”",
        "kind": "select",
        "options": ["Yes", "No"],
        "hint": "Yes adds “no fee is charged for this internship” — choose it only when that is true.",
    },
    "minor": {
        "label": "Candidate under 18?",
        "kind": "select",
        "options": ["No", "Yes"],
        "hint": "Yes adds a parent / guardian countersignature to the acceptance form.",
    },
    "compensation": {
        "label": "Compensation (CTC)",
        "kind": "money",
        "required": True,
        "hint": "e.g. ₹3,60,000 per annum",
    },
    "probation": {"label": "Probation period", "kind": "text", "hint": "e.g. 6 months"},
    "reporting_to": {"label": "Reporting to", "kind": "text"},
    "accept_by": {"label": "Accept by", "kind": "date", "hint": "Last date to accept the offer"},
    "batch_start": {"label": "Batch start date", "kind": "date", "required": True},
    "schedule": {"label": "Class schedule", "kind": "text", "hint": "e.g. Monday to Friday, 7–9 PM IST"},
    "fee_total": {"label": "Total course fee", "kind": "money"},
    "fee_paid": {"label": "Fee received", "kind": "money"},
    "fee_balance": {"label": "Balance due", "kind": "money"},
    "hours": {"label": "Hours of training", "kind": "text"},
    "grade": {"label": "Grade / result", "kind": "text", "hint": "Optional, e.g. A, Distinction"},
    "achievement": {
        "label": "Recognised for",
        "kind": "longtext",
        "required": True,
        "hint": "e.g. outstanding performance in the capstone project",
    },
    "event": {"label": "Event / workshop", "kind": "text", "required": True},
    "event_date": {
        "label": "Event date(s)",
        "kind": "text",
        "required": True,
        "hint": "e.g. 12–13 December 2026",
    },
    "relationship": {
        "label": "How we know the student",
        "kind": "text",
        "required": True,
        "hint": "e.g. intern in our Full Stack team",
    },
    "strengths": {
        "label": "Strengths and work (one or two paragraphs)",
        "kind": "longtext",
        "required": True,
    },
    "skills": {
        "label": "Key strengths (one per line)",
        "kind": "longtext",
        "hint": "Short items — printed as a checklist (at most 8).",
    },
    "addressee": {
        "label": "Addressed to",
        "kind": "text",
        "hint": "Leave empty for “To whom it may concern”",
    },
    "score_assess": {"label": "Assessment score", "kind": "text", "hint": "Optional, e.g. 38/40"},
    "score_project": {"label": "Capstone / project score", "kind": "text", "hint": "Optional, e.g. 52/60"},
    "project_title": {"label": "Capstone project title", "kind": "text", "hint": "Optional"},
    "cert_skills": {
        "label": "Skills covered (one per line)",
        "kind": "longtext",
        "hint": "Optional, 4–6 short items. Printed on the certificate (at most 6).",
    },
    "merit": {
        "label": "Merit tier",
        "kind": "select",
        "options": ["Distinction", "Merit", "Completed"],
        "hint": "Optional. Only when it was earned.",
    },
    "cohort_size": {
        "label": "Learners certified in this batch",
        "kind": "text",
        "hint": "Optional number, e.g. 38",
    },
    "batch": {"label": "Batch", "kind": "text", "hint": "Optional, e.g. NG-07 or December 2026"},
    "citation": {
        "label": "Citation (specific)",
        "kind": "longtext",
        "hint": "Optional, one line. Never “for active participation”.",
    },
    "achievements": {
        "label": "Quantified achievements (one per line)",
        "kind": "longtext",
        "hint": "2–3 items with numbers. Printed as a list (at most 5).",
    },
    "ranking": {
        "label": "Cohort ranking (only if true)",
        "kind": "text",
        "hint": "Optional, e.g. top 3 of 42 interns in the 2026 cohort.",
    },
}

# --------------------------------------------------------------------------- document types
# layout: "letter" (A4 portrait, letterhead) | "certificate" (A4 landscape, number + QR)
DOC_TYPES: dict[str, dict[str, Any]] = {
    "offer_internship": {
        "label": "Internship offer letter",
        "short": "Internship offer",
        "layout": "letter",
        "prefix": "OL",
        "heading": "Internship Offer",
        "subject": "Offer of internship: {{role}}",
        "fields": [
            "role",
            "start_date",
            "end_date",
            "duration",
            "mode",
            "location",
            "work_hours",
            "intern_stipend",
            "reporting_to",
            "accept_by",
            "responsibilities",
            "course_year",
            "roll_no",
            "no_fee",
            "minor",
        ],
        "paragraphs": [
            "Dear {{first_name}},",
            "We are pleased to offer you an internship with {{company}} as {{role_phrase}}. This letter sets out the terms of your internship.",
            "Your internship will run{{period_phrase}}, a period of {{duration}}. It will be conducted {{mode_phrase}}{{location_phrase}}.{{work_hours_sentence}}{{reporting_phrase}}",
            "{{stipend_sentence}}",
            "During the internship you will work on live projects under the guidance of our team. When you complete it successfully, meeting the attendance and work requirements, you will receive an internship certificate stating your role, period and hours, which you may submit to your college for academic credit where your college allows it.",
            "To accept this offer, sign the acceptance form at the end of this letter and return a scanned copy by replying to the offer email{{accept_by_phrase}}.",
            "We look forward to working with you and wish you a rewarding internship.",
        ],
    },
    "offer_employment": {
        "label": "Employment offer letter",
        "short": "Employment offer",
        "layout": "letter",
        "prefix": "EO",
        "heading": "Offer of Employment",
        "subject": "Offer of employment: {{position}}",
        "fields": [
            "position",
            "department",
            "joining_date",
            "compensation",
            "location",
            "mode",
            "probation",
            "reporting_to",
            "accept_by",
        ],
        "paragraphs": [
            "Dear {{first_name}},",
            "Following our discussions, we are pleased to offer you the position of {{position}}{{department_phrase}} at {{company}}.",
            "Your date of joining will be {{joining_date}}. You will work {{mode_phrase}}{{location_phrase}}.{{reporting_phrase}}",
            "Your total annual compensation (CTC) will be {{compensation}}. {{probation_sentence}}",
            "This offer is subject to verification of the documents and information you have provided, and to the terms of the appointment letter you will receive on joining. You will be expected to keep confidential all information about our business and clients.",
            "{{accept_sentence}}",
            "We are delighted to have you join us and look forward to working together.",
        ],
    },
    "offer_course": {
        "label": "Course admission letter",
        "short": "Admission letter",
        "layout": "letter",
        "prefix": "AL",
        "heading": "Admission Letter",
        "subject": "Admission confirmed: {{program}}",
        "fields": [
            "program",
            "batch_start",
            "duration",
            "mode",
            "schedule",
            "fee_total",
            "fee_paid",
            "fee_balance",
        ],
        "paragraphs": [
            "Dear {{first_name}},",
            "We are pleased to confirm your admission to {{program}} at {{company}}.",
            "Your batch begins on {{batch_start}}. The program runs for {{duration}} and will be conducted {{mode_phrase}}.{{schedule_sentence}}",
            "{{fee_sentence}}",
            "Your learning-portal access is linked to your registered email address, {{email}}. Class links, study material, assignments and announcements will be shared there and by email.",
            "Please keep this letter for your records. If you have any questions, reply to the email that came with this letter{{email_us_phrase}}.",
            "We look forward to having you in the batch.",
        ],
    },
    "cert_completion": {
        "label": "Course / internship completion certificate",
        "short": "Completion certificate",
        "layout": "certificate",
        "prefix": "CC",
        "kind": "Course Completion",
        "title": "Certificate of Completion",
        "subtitle": "of Completion",
        "subject": "Your certificate of completion: {{program}}",
        "fields": [
            "program",
            "start_date",
            "end_date",
            "hours",
            "grade",
            "score_assess",
            "score_project",
            "project_title",
            "cert_skills",
            "merit",
            "batch",
            "cohort_size",
        ],
        "paragraphs": [
            "This is to certify that",
            "{{name}}",
            "has successfully completed {{program}}{{period_phrase}}{{hours_phrase}}{{grade_phrase}}.",
        ],
    },
    "cert_internship": {
        "label": "Internship completion certificate",
        "short": "Internship certificate",
        "layout": "certificate",
        "prefix": "IC",
        "kind": "Internship",
        "title": "Internship Certificate",
        "subtitle": "of Internship",
        "subject": "Your internship certificate: {{role}}",
        "fields": [
            "role",
            "start_date",
            "end_date",
            "hours",
            "grade",
            "project_title",
            "cert_skills",
            "merit",
        ],
        "paragraphs": [
            "This is to certify that",
            "{{name}}",
            "has successfully completed an internship as {{role_phrase}}{{period_phrase}}{{grade_phrase}}.",
        ],
    },
    "cert_appreciation": {
        "label": "Certificate of appreciation",
        "short": "Appreciation certificate",
        "layout": "certificate",
        "prefix": "CA",
        "kind": "Appreciation",
        "title": "Certificate of Appreciation",
        "subtitle": "of Appreciation",
        "subject": "A certificate of appreciation for you",
        "fields": ["program", "achievement", "citation"],
        "paragraphs": [
            "This certificate is presented to",
            "{{name}}",
            "in appreciation of {{achievement}}{{program_phrase}}.",
        ],
    },
    "cert_participation": {
        "label": "Certificate of participation",
        "short": "Participation certificate",
        "layout": "certificate",
        "prefix": "CP",
        "kind": "Participation",
        "title": "Certificate of Participation",
        "subtitle": "of Participation",
        "subject": "Your certificate of participation: {{event}}",
        "fields": ["event", "event_date"],
        "paragraphs": [
            "This is to certify that",
            "{{name}}",
            "participated in {{event}} held on {{event_date}}.",
        ],
    },
    "lor": {
        "label": "Letter of recommendation",
        "short": "Recommendation (LOR)",
        "layout": "letter",
        "prefix": "LR",
        "heading": "Letter of Recommendation",
        "subject": "Letter of recommendation for {{name}}",
        "fields": [
            "addressee",
            "relationship",
            "program",
            "start_date",
            "end_date",
            "strengths",
            "achievements",
            "skills",
            "ranking",
        ],
        "paragraphs": [
            "{{salutation}}",
            "It is my pleasure to recommend {{name}}, who was with {{company}} as {{relationship}}{{period_phrase}}{{program_phrase}}.",
            "{{strengths}}",
            "{{ranking_sentence}}",
            "Based on this experience, I recommend {{first_name}} without reservation for further studies or a professional role. I am confident that {{first_name}} will be an asset to any organisation.",
            "{{contact_sentence}}",
        ],
    },
}
DOC_KEYS: tuple[str, ...] = tuple(DOC_TYPES)
PREFIXES: dict[str, str] = {k: v["prefix"] for k, v in DOC_TYPES.items()}
TYPE_BY_PREFIX: dict[str, str] = {v: k for k, v in PREFIXES.items()}


def is_certificate(doc_type: str) -> bool:
    return DOC_TYPES.get(doc_type, {}).get("layout") == "certificate"


def field_def(key: str) -> dict[str, Any]:
    return FIELDS.get(key, {"label": key, "kind": "text"})


# Extra sections of offer / admission letters (owners can edit them per type).
#   hero: congratulations line; benefits: "What you'll gain"; terms: numbered T&C; next: next steps;
#   accept: print the acceptance slip.
LETTER_SECTIONS: dict[str, dict[str, Any]] = {
    "offer_internship": {
        "hero": "Congratulations, {{first_name}}! Welcome to {{company}}.",
        "benefits": [
            "Hands-on work on real projects with guidance from our team",
            "Regular reviews and feedback on your work",
            "Internship certificate with your role, period and hours, on successful completion",
            "Letter of recommendation for outstanding performance, at the company's discretion",
        ],
        "terms": [
            "This offer is based on the information and documents you provided. It may be withdrawn if any of it is found to be incorrect.",
            "This internship is a training and learning engagement, not employment. It carries no salary or benefits other than any stipend stated in this letter, and it does not guarantee a job offer; any pre-placement offer is at the sole discretion of {{company}}, based on your performance.",
            "You will follow the working days and hours agreed with your reporting manager. Leave needs their prior approval; unapproved absence for more than three consecutive working days may lead to the internship being ended.",
            "You will keep confidential all information, code, data and material of {{company}} and its clients, during and after the internship.",
            "Work you create during the internship, including code, documents and designs, belongs to {{company}} unless agreed otherwise in writing. You may describe your role and contribution in your résumé and portfolio without disclosing confidential material.",
            "At the end of the internship you will return all company material and delete any company data you hold; your access to company systems will be withdrawn.",
            "You will follow our code of conduct, IT-use and anti-harassment (POSH) policies. Any concern or grievance can be raised in confidence {{grievance_phrase}}.",
            "Either side may end the internship with fifteen days' written notice; {{company}} may end it immediately for misconduct or breach of confidentiality. The internship certificate is issued only when the internship is completed successfully.",
            "{{no_fee_term}}",
            "{{guardian_term}}",
            "This offer lapses if it is not accepted{{lapse_phrase}}.",
        ],
        "next": [
            "If your college needs a no-objection certificate or its own internship form, send it to us before your start date.",
            "Keep a government photo ID and your college ID ready for verification on your first day.",
            "Joining instructions will be emailed to {{email}}.",
        ],
        "accept": True,
    },
    "offer_employment": {
        "hero": "Congratulations, {{first_name}}! We are delighted to welcome you to {{company}}.",
        "benefits": [],
        "terms": [
            "This offer is subject to satisfactory verification of your documents, qualifications and previous employment.",
            "You will keep confidential all information about the business, clients and employees of {{company}}, during and after your employment.",
            "Work created in the course of your employment belongs to {{company}}.",
            "Detailed terms, including leave, notice period and policies, will be set out in your appointment letter on joining.",
            "This offer lapses if it is not accepted{{lapse_phrase}}.",
        ],
        "next": [
            "Return the signed acceptance form by replying to the offer email{{accept_by_phrase}}.",
            "On your joining date, bring originals and copies of your educational certificates, previous employment documents, a government photo ID, PAN and recent passport-size photographs.",
        ],
        "accept": True,
    },
    "offer_course": {
        "hero": "Congratulations, {{first_name}}! Your seat is confirmed.",
        "benefits": [
            "Live, instructor-led sessions with hands-on practice",
            "Projects, assignments and feedback through the learning portal",
            "Course completion certificate on meeting the completion requirements",
        ],
        "terms": [
            "Your admission is for the batch and program stated above.",
            "Course access is given to your registered email address ({{email}}) and is personal; please don't share it.",
            "The completion certificate is issued when the attendance, assignments and project requirements of the program are met.",
            "Any balance fee must be paid by the dates communicated to you to keep your access active.",
        ],
        "next": [
            "Watch your email for the class schedule and learning-portal access.",
            "{{reg_no_sentence}}",
        ],
        "accept": False,
    },
}

# --------------------------------------------------------------------------- emails
# attach: the document type whose PDF is attached, or None. Body: paragraphs separated by blank lines.
EMAIL_TEMPLATES: dict[str, dict[str, Any]] = {
    "offer_internship": {
        "label": "Internship offer",
        "attach": "offer_internship",
        "subject": "Your internship offer from {{company}}",
        "body": "Dear {{first_name}},\n\nCongratulations! Please find attached your offer letter for the {{role}} internship at {{company}}.\n\nTo accept the offer, reply to this email{{accept_by_phrase}}.\n\nWe look forward to working with you.",
    },
    "offer_employment": {
        "label": "Employment offer",
        "attach": "offer_employment",
        "subject": "Your offer of employment from {{company}}",
        "body": "Dear {{first_name}},\n\nWe are pleased to offer you the position of {{position}} at {{company}}. Your offer letter is attached.\n\nTo accept the offer, reply to this email{{accept_by_phrase}}.\n\nWe look forward to welcoming you.",
    },
    "offer_course": {
        "label": "Course admission",
        "attach": "offer_course",
        "subject": "Admission confirmed: {{program}}",
        "body": "Dear {{first_name}},\n\nYour admission to {{program}} is confirmed. Your admission letter is attached.\n\nYour batch begins on {{batch_start}}. Your learning-portal access is linked to this email address ({{email}}).\n\nWelcome to {{company}}!",
    },
    "cert_completion": {
        "label": "Completion certificate",
        "attach": "cert_completion",
        "subject": "Your certificate of completion: {{program}}",
        "body": "Dear {{first_name}},\n\nCongratulations on completing {{program}}! Your certificate is attached.\n\nCertificate number: {{cert_no}}\nAnyone can verify it at {{verify_url}}.\n\nWe wish you every success.",
    },
    "cert_internship": {
        "label": "Internship certificate",
        "attach": "cert_internship",
        "subject": "Your internship certificate from {{company}}",
        "body": "Dear {{first_name}},\n\nThank you for your work as {{role_phrase}}. Your internship certificate is attached.\n\nCertificate number: {{cert_no}}\nAnyone can verify it at {{verify_url}}.\n\nWe wish you every success.",
    },
    "cert_appreciation": {
        "label": "Appreciation certificate",
        "attach": "cert_appreciation",
        "subject": "A certificate of appreciation from {{company}}",
        "body": "Dear {{first_name}},\n\nWe are delighted to recognise you {{achievement_phrase}}. Your certificate of appreciation is attached.\n\nCertificate number: {{cert_no}}\nVerify it at {{verify_url}}.\n\nKeep up the excellent work!",
    },
    "cert_participation": {
        "label": "Participation certificate",
        "attach": "cert_participation",
        "subject": "Your certificate of participation: {{event}}",
        "body": "Dear {{first_name}},\n\nThank you for participating in {{event}}. Your certificate of participation is attached.\n\nCertificate number: {{cert_no}}\nVerify it at {{verify_url}}.",
    },
    "lor": {
        "label": "Letter of recommendation",
        "attach": "lor",
        "subject": "Your letter of recommendation from {{company}}",
        "body": "Dear {{first_name}},\n\nAs requested, please find attached your letter of recommendation.\n\nWe wish you the very best for the road ahead.",
    },
    "credentials": {
        "label": "Learning-portal access",
        "attach": None,
        "subject": "Your {{company}} learning-portal access",
        "body": "Dear {{first_name}},\n\nYour access to the {{company}} learning portal is ready for {{program}}.\n\nPortal: {{portal_url}}\nSign in with: {{email}}\n\nUse this same email address to sign in (with Google, or create a password the first time). Never share your password with anyone.\n\nSee you in class!",
    },
    "payment_verified": {
        "label": "Payment received",
        "attach": None,
        "subject": "Payment received: {{program}}",
        "body": "Dear {{first_name}},\n\nWe have received and verified your payment of {{amount}} for {{program}} (registration {{reg_no}}).\n\nTotal fee: {{fee_total}}\nVerified so far: {{fee_paid}}\nBalance: {{fee_balance}}\n\nThank you!",
    },
    "registration_received": {
        "label": "Registration received",
        "attach": None,
        "subject": "We received your registration: {{program}}",
        "body": "Dear {{first_name}},\n\nThank you for registering for {{program}}. Your registration number is {{reg_no}}.\n\nOur team will verify your payment in our bank account and confirm your admission by email.\n\nIf you have any questions, reply to this email.",
    },
    "general": {
        "label": "General message",
        "attach": None,
        "subject": "",
        "body": "Dear {{first_name}},\n\n\n\nRegards,\n{{signatory}}\n{{company}}",
    },
}
EMAIL_KEYS: tuple[str, ...] = tuple(EMAIL_TEMPLATES)

# --------------------------------------------------------------------------- settings
SETTINGS_TEXT_LIMITS: dict[str, int] = {
    "company": 120,
    "legal_name": 160,
    "tagline": 120,
    "address": 300,
    "phone": 40,
    "email": 160,
    "website": 120,
    "signatory": 80,
    "designation": 80,
    "signatory_email": 160,
    "signatory_phone": 40,
    "signatory2": 80,
    "designation2": 80,
    "portal_url": 200,
}
# signature: the Authorised Signatory's (the only signature printed); seal: company stamp beside it
# on letters; logo_left / logo_right: optional top-row logos of the certificate template and the
# letterhead (empty by default; only logos the company may use, e.g. its own accreditations);
# signature2: kept for compatibility, not printed (one signatory).
IMAGE_SLOTS: tuple[str, ...] = ("signature", "seal", "signature2", "logo_left", "logo_right")
DEFAULT_TAGLINE = "Debug your career. Deploy your dreams."


def clean_settings(x: dict[str, Any] | None = None) -> dict[str, Any]:
    """Letterhead + signatory (owners edit). Empty values are simply left out of the documents.
    Image slots are kept as stored (``<slot>_key`` / ``<slot>_sha256``; set by the upload API)."""
    x = dict(x or {})
    out: dict[str, Any] = {}
    for k, n in SETTINGS_TEXT_LIMITS.items():
        out[k] = (
            " ".join(str(x.get(k) or "").split())[:n] if k != "address" else str(x.get(k) or "").strip()[:n]
        )
    out["company"] = out["company"] or "Tech Drona"
    out["tagline"] = out["tagline"] or DEFAULT_TAGLINE
    lines = x.get("reg_lines") or []
    if isinstance(lines, str):
        lines = lines.split("\n")
    out["reg_lines"] = [str(s).strip()[:120] for s in lines if str(s).strip()][:4]
    # automatic admission letter when a learner is enrolled (paid / manual / batch enrolments)
    out["auto_admission_letter"] = x.get("auto_admission_letter") is not False
    # faint Tech Drona mark behind every document and certificate page (on unless switched off)
    out["watermark"] = x.get("watermark") is not False
    for slot in IMAGE_SLOTS:
        key, sha = x.get(f"{slot}_key"), x.get(f"{slot}_sha256")
        out[f"{slot}_key"] = key if isinstance(key, str) and key else None
        out[f"{slot}_sha256"] = (
            sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha or "") else None
        )
    return out


def settings_problem(st: dict[str, Any]) -> str:
    """What must be set before documents can be issued ("" when ready)."""
    if not st.get("signatory") or not st.get("designation"):
        return "Add the signatory's name and designation in Documents → Settings."
    return ""


# --------------------------------------------------------------------------- placeholders
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
UNPAID = re.compile(r"unpaid|no stipend|^nil$|^none$", re.I)


def long_date(d: Any) -> str:
    """``2026-12-05`` (or a date) -> ``5 December 2026``. Anything else is returned as typed."""
    if isinstance(d, date):
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    m = _ISO.match(str(d or ""))
    if not m or not 1 <= int(m[2]) <= 12:
        return str(d or "")
    return f"{int(m[3])} {MONTHS[int(m[2]) - 1]} {m[1]}"


def short_date(d: Any) -> str:
    m = _ISO.match(str(d or ""))
    if not m or not 1 <= int(m[2]) <= 12:
        return str(d or "")
    return f"{int(m[3])} {MONTHS[int(m[2]) - 1][:3]} {m[1]}"


def first_name(n: str | None) -> str:
    parts = str(n or "").split()
    return parts[0] if parts else ""


def article(text: str | None) -> str:
    """ "a" or "an" by sound: an Intern, an ML Engineer, a UX Designer, a Full Stack Intern."""
    w = (re.split(r"[\s/-]+", str(text or "").strip()) or [""])[0]
    letters = re.sub(r"[^A-Za-z]", "", w)
    if len(letters) >= 2 and letters.isupper():  # acronyms are read letter by letter
        return "an" if re.match(r"^[AEFHILMNORSX]", w) else "a"
    if re.match(r"^(uni|use|usu|uti|eu|one$|once)", w, re.I):
        return "a"
    if re.match(r"^(hour|honou?r|heir)", w, re.I):
        return "an"
    return "an" if re.match(r"^[aeiou]", w, re.I) else "a"


def line_items(text: Any, limit: int = 8) -> list[str]:
    """Free text "one per line" (or with bullets) as a short list."""
    out = []
    for t in re.split(r"\r?\n|•", str(text or "")):
        t = re.sub(r"^\s*(?:[-*–]|\d+[.)])\s*", "", t).strip()
        if t:
            out.append(t)
    return out[:limit]


def _t(v: Any) -> str:
    return str(v if v is not None else "").strip()


def placeholder_values(
    *,
    doc_type: str,
    recipient: dict[str, Any],
    fields: dict[str, Any],
    settings: dict[str, Any],
    ref_no: str = "",
    cert_no: str = "",
    issue_date: Any = "",
    site_url: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Every placeholder value for one document / email. Phrases (``{{..._phrase}}``,
    ``{{..._sentence}}``) are built here so the wording reads naturally when details are empty."""
    f, st, r = fields or {}, settings or clean_settings({}), recipient or {}
    name = _t(r.get("name"))
    number = cert_no or ref_no

    def d(k: str) -> str:
        return long_date(f.get(k))

    v: dict[str, str] = {
        "name": name, "first_name": first_name(name), "email": _t(r.get("email")),
        "college": _t(r.get("college")), "reg_no": _t(r.get("reg_no")),
        "company": st.get("company") or "Tech Drona", "company_email": st.get("email") or "",
        "signatory": st.get("signatory") or "", "designation": st.get("designation") or "",
        "date": long_date(issue_date), "ref_no": ref_no, "cert_no": number,
        "verify_url": f"{site_url}/verify/{number}" if number else "",
        "portal_url": st.get("portal_url") or f"{site_url}/app",
    }  # fmt: skip
    for k, fd in FIELDS.items():
        v[k] = d(k) if fd["kind"] == "date" else _t(f.get(k))
    v.update({k: _t(x) for k, x in (extra or {}).items()})
    mode = _t(f.get("mode"))
    mode_word = {
        "Online": "online",
        "On-site": "on-site",
        "Hybrid": "in hybrid mode (online and on-site)",
    }.get(mode, mode.lower())
    v["mode_phrase"] = mode_word or "as communicated to you"
    v["location_phrase"] = (
        f" at {_t(f.get('location'))}" if _t(f.get("location")) and mode != "Online" else ""
    )
    v["reporting_phrase"] = (
        f" You will report to {_t(f.get('reporting_to'))}." if _t(f.get("reporting_to")) else ""
    )
    v["department_phrase"] = f" in our {_t(f.get('department'))} team" if _t(f.get("department")) else ""
    stip = _t(f.get("intern_stipend") or f.get("stipend"))
    v["stipend"] = stip
    v["stipend_sentence"] = (
        ""
        if not stip
        else "This is an unpaid internship: no stipend or salary is payable."
        if UNPAID.search(stip)
        else f"You will receive a stipend of {stip}, subject to deduction of tax at source where applicable."
    )
    wh = _t(f.get("work_hours")).rstrip(".")
    v["work_hours_sentence"] = f" Working days and hours: {wh}." if wh else ""
    v["grievance_phrase"] = (
        f"by writing to {st['email']}"
        if st.get("email")
        else "with your reporting manager or the signatory of this letter"
    )
    v["no_fee_term"] = (
        f"{v['company']} does not charge any fee for this internship, for this letter or for the certificate. "
        "Do not pay anyone who asks for money in our name; report it to us."
        if f.get("no_fee") == "Yes"
        else ""
    )
    v["guardian_term"] = (
        "As you are under 18, this offer is valid only when your parent or guardian also signs the acceptance form."
        if f.get("minor") == "Yes"
        else ""
    )
    v["lapse_phrase"] = (
        f" on or before {d('accept_by')}"
        if _t(f.get("accept_by"))
        else " within seven days of the date of this letter"
    )
    v["probation_sentence"] = (
        f"You will be on probation for {_t(f.get('probation'))} from your date of joining."
        if _t(f.get("probation"))
        else ""
    )
    v["accept_by_phrase"] = f" on or before {d('accept_by')}" if _t(f.get("accept_by")) else ""
    v["accept_sentence"] = (
        "To accept this offer, sign the acceptance form at the end of this letter and return a scanned copy by "
        f"replying to the offer email{v['accept_by_phrase']}."
    )
    v["schedule_sentence"] = f" Classes are held {_t(f.get('schedule'))}." if _t(f.get("schedule")) else ""
    fee_total, fee_paid, fee_bal = _t(f.get("fee_total")), _t(f.get("fee_paid")), _t(f.get("fee_balance"))
    fee = ""
    if fee_total:
        fee = f"Total course fee: {fee_total}."
        if fee_paid:
            fee += f" Received: {fee_paid}."
        if fee_bal and not re.fullmatch(r"(₹|Rs\.?\s*)?0(\.0+)?", fee_bal):
            fee += f" Balance due: {fee_bal}."
    v["fee_sentence"] = fee
    sd, ed = _t(f.get("start_date")), _t(f.get("end_date"))
    v["period_phrase"] = (
        f" from {d('start_date')} to {d('end_date')}"
        if sd and ed
        else (f" from {d('start_date')}" if sd else "")
    )
    v["hours_phrase"] = f", comprising {_t(f.get('hours'))}" if _t(f.get("hours")) else ""
    g = _t(f.get("grade"))
    if not g:
        v["grade_phrase"] = ""
    elif re.match(r"^with\b", g, re.I):
        v["grade_phrase"] = f", {g}"
    elif re.match(r"^grade\b", g, re.I) or re.search(
        r"\b(distinction|merit|honou?rs|first class|second class|credit)\b", g, re.I
    ):
        v["grade_phrase"] = f", with {g}"
    else:
        v["grade_phrase"] = f", with grade {g}"
    prog = _t(f.get("program"))
    v["program_phrase"] = (f" in {prog}" if doc_type == "lor" else f" during {prog}") if prog else ""
    v["achievement_phrase"] = f"for {_t(f.get('achievement'))}" if _t(f.get("achievement")) else ""
    to = re.sub(r"[,:]+$", "", _t(f.get("addressee")))
    if not to:
        v["salutation"] = "To whom it may concern,"
    elif re.match(r"^(dear|to)\b", to, re.I):
        v["salutation"] = f"{to},"
    else:
        bare = re.sub(r"^the\s+", "", to, flags=re.I)
        v["salutation"] = f"Dear {bare},"
    role = _t(f.get("role"))
    v["role_phrase"] = f"{article(role)} {role}" if role else ""
    v["email_us_phrase"] = f" or write to us at {st['email']}" if st.get("email") else ""
    c_mail = st.get("signatory_email") or st.get("email") or ""
    c_phone = st.get("signatory_phone") or st.get("phone") or ""
    v["contact_sentence"] = (
        f"Please feel free to contact me at {' or on '.join(x for x in (c_mail, c_phone) if x)} for any further information."
        if c_mail or c_phone
        else ""
    )
    rk = re.sub(
        r"^(ranked\s+)?(in\s+)?(the\s+)?", "", re.sub(r"[.\s]+$", "", _t(f.get("ranking"))), flags=re.I
    )
    who = first_name(name) or "the candidate"
    if not rk:
        v["ranking_sentence"] = ""
    elif re.match(r"^top\b", rk, re.I):
        v["ranking_sentence"] = f"In our assessment, {who} ranked in the {rk[0].lower()}{rk[1:]}."
    else:
        v["ranking_sentence"] = f"In our assessment, {who} ranked {rk}."
    v["reg_no_sentence"] = (
        f"Keep your registration number {v['reg_no']} for all communication with us." if v["reg_no"] else ""
    )
    return v


_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def fill(text: Any, values: dict[str, str]) -> str:
    """Replace ``{{key}}`` with values (unknown keys become ""); collapse doubled spaces."""
    s = _TOKEN.sub(lambda m: values.get(m.group(1), ""), str(text or ""))
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" +([.,])", r"\1", s)
    return s.strip()


def _keep(p: str) -> bool:
    return bool(p) and not re.fullmatch(r"[.,;\s]*", p)


def doc_paragraphs(
    doc_type: str, values: dict[str, str], override: dict[str, Any] | None = None
) -> list[str]:
    src = (override or {}).get("paragraphs") or DOC_TYPES[doc_type]["paragraphs"]
    return [p for p in (fill(x, values) for x in src) if _keep(p)]


def letter_sections(
    doc_type: str, values: dict[str, str], override: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    base = LETTER_SECTIONS.get(doc_type)
    if not base:
        return None
    s = {**base, **((override or {}).get("sections") or {})}

    def lst(a: Any) -> list[str]:
        return [x for x in (fill(i, values) for i in (a if isinstance(a, list) else [])) if _keep(x)]

    return {
        "hero": fill(s.get("hero"), values),
        "benefits": lst(s.get("benefits")),
        "terms": lst(s.get("terms")),
        "next": lst(s.get("next")),
        "accept": s.get("accept") is not False,
    }


def email_parts(key: str, values: dict[str, str], override: dict[str, Any] | None = None) -> dict[str, Any]:
    t = {**EMAIL_TEMPLATES[key], **{k: v for k, v in (override or {}).items() if k in ("subject", "body")}}
    paras = [fill(p, values) for p in re.split(r"\n\s*\n", str(t.get("body") or ""))]
    return {
        "subject": fill(t.get("subject"), values),
        "paragraphs": [p for p in paras if p],
        "attach": EMAIL_TEMPLATES[key].get("attach"),
    }


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def missing_fields(doc_type: str, fields: dict[str, Any], recipient: dict[str, Any]) -> list[str]:
    out = []
    if not _t(recipient.get("name")):
        out.append("Student name")
    email = _t(recipient.get("email"))
    if not email:
        out.append("Student email")
    elif not EMAIL_RE.match(email):
        out.append("Valid student email")
    for k in DOC_TYPES[doc_type]["fields"]:
        if FIELDS.get(k, {}).get("required") and not _t(fields.get(k)):
            out.append(FIELDS[k]["label"])
    return out


def clean_fields(doc_type: str, fields: dict[str, Any] | None) -> dict[str, str]:
    """Only the type's fields, as trimmed strings (longtext keeps its newlines); dates must be ISO;
    selects must be one of the options."""
    out: dict[str, str] = {}
    for k in DOC_TYPES[doc_type]["fields"]:
        raw = (fields or {}).get(k)
        if raw is None:
            continue
        fd = field_def(k)
        val = str(raw).strip()[: 4000 if fd["kind"] == "longtext" else 300]
        if fd["kind"] != "longtext":
            val = " ".join(val.split())
        if not val:
            continue
        if fd["kind"] == "date" and not _ISO.match(val):
            raise ValueError(f"{fd['label']}: use a date (YYYY-MM-DD).")
        if fd["kind"] == "select" and val not in fd["options"]:
            raise ValueError(f"{fd['label']}: choose one of {', '.join(fd['options'])}.")
        out[k] = val
    return out


EMPHASIS_FIELD = {
    "cert_completion": "program",
    "cert_internship": "role",
    "cert_appreciation": "achievement",
    "cert_participation": "event",
}


def render_extras(doc_type: str, fields: dict[str, Any], recipient: dict[str, Any]) -> dict[str, Any]:
    """What the PDF shows besides the paragraphs, computed from the saved fields (a re-render of an
    issued document looks exactly like the original). Empty values are dropped."""
    f = fields or {}

    def hl(pairs: Iterable[tuple[str, Any]]) -> list[dict[str, str]]:
        return [{"label": a, "value": _t(b)} for a, b in pairs if _t(b)]

    def span(a: Any, b: Any) -> str:
        return f"{long_date(a)} to {long_date(b)}" if a and b else long_date(a)

    if doc_type == "offer_internship":
        stip = _t(f.get("intern_stipend") or f.get("stipend"))
        mode = _t(f.get("mode")) + (
            f" · {_t(f.get('location'))}" if _t(f.get("location")) and f.get("mode") != "Online" else ""
        )
        return {
            "highlights": hl(
                [
                    ("Role", f.get("role")),
                    ("Mentor / reporting to", f.get("reporting_to")),
                    ("Period", span(f.get("start_date"), f.get("end_date"))),
                    ("Duration", f.get("duration")),
                    ("Working hours", f.get("work_hours")),
                    ("Mode", mode),
                    ("Stipend", "Unpaid internship" if UNPAID.search(stip or "-") and stip else stip),
                    ("Fee payable", "Nil" if f.get("no_fee") == "Yes" else ""),
                    ("Accept by", long_date(f.get("accept_by"))),
                ]
            ),
            "lists": [("Your responsibilities", line_items(f.get("responsibilities")))],
            "to_lines": [
                x
                for x in (
                    _t(f.get("course_year")),
                    f"Roll no. {_t(f.get('roll_no'))}" if _t(f.get("roll_no")) else "",
                )
                if x
            ],
            "guardian": f.get("minor") == "Yes",
        }
    if doc_type == "lor":
        period = (
            f"{long_date(f.get('start_date'))} – {long_date(f.get('end_date'))}"
            if f.get("start_date") and f.get("end_date")
            else long_date(f.get("start_date"))
        )
        return {
            "highlights": hl(
                [
                    ("Association", f.get("relationship")),
                    ("Period", period),
                    ("Program", f.get("program")),
                    ("College", recipient.get("college")),
                    ("Cohort standing", f.get("ranking")),
                ]
            ),
            "lists": [
                ("Key strengths", line_items(f.get("skills"))),
                ("Achievements", line_items(f.get("achievements"), 5)),
            ],
        }
    if doc_type == "offer_employment":
        return {
            "highlights": hl(
                [
                    ("Position", f.get("position")),
                    ("Department", f.get("department")),
                    ("Date of joining", long_date(f.get("joining_date"))),
                    ("CTC", f.get("compensation")),
                    ("Location", f.get("location")),
                    ("Probation", f.get("probation")),
                    ("Reporting to", f.get("reporting_to")),
                    ("Accept by", long_date(f.get("accept_by"))),
                ]
            )
        }
    if doc_type == "offer_course":
        return {
            "highlights": hl(
                [
                    ("Program", f.get("program")),
                    ("Batch starts", long_date(f.get("batch_start"))),
                    ("Duration", f.get("duration")),
                    ("Mode", f.get("mode")),
                    ("Schedule", f.get("schedule")),
                    ("Registration no.", recipient.get("reg_no")),
                ]
            )
        }
    if is_certificate(doc_type):
        n = re.sub(r"^(one of|1 of)\s*", "", _t(f.get("cohort_size")), flags=re.I)
        cohort = (f"{_t(f.get('batch'))} · " if _t(f.get("batch")) and n else "") + (
            (f"{n} certified" if n.isdigit() else n) if n else _t(f.get("batch"))
        )
        period = (
            f"{short_date(f.get('start_date'))} – {short_date(f.get('end_date'))}"
            if f.get("start_date") and f.get("end_date")
            else ""
        )
        cells = hl(
            [
                ("Held on", f.get("event_date")),
                ("Period", period),
                ("Hours", f.get("hours")),
                ("Assessments", f.get("score_assess")),
                ("Capstone", f.get("score_project")),
                ("Grade", f.get("grade")),
                ("Cohort" if n else "Batch", cohort),
            ]
        )
        merit = _t(f.get("merit"))
        return {
            "emphasis": _t(f.get(EMPHASIS_FIELD[doc_type])),
            "context": _t(f.get("program")) if doc_type == "cert_appreciation" else "",
            "evidence": cells[:4],
            "project": _t(f.get("project_title")),
            "skills": line_items(f.get("cert_skills"), 6),
            "merit": merit.capitalize() if merit.lower() in ("distinction", "merit") else "",
            "citation": re.sub(r"\s*\n\s*", " ", _t(f.get("citation"))),
            # the certificate's details sentence ("from ... to ..., comprising ..., with grade ...")
            "start": long_date(f.get("start_date")) if _t(f.get("start_date")) else "",
            "end": long_date(f.get("end_date")) if _t(f.get("end_date")) else "",
            "hours": _t(f.get("hours")),
            "grade": _t(f.get("grade")),
            "held_on": _t(f.get("event_date")),
        }
    return {}


def public_details(doc_type: str, fields: dict[str, Any]) -> dict[str, str]:
    """What the public verify page may show (never a letter's text, contact details or fees)."""
    f = fields or {}
    if doc_type == "lor":
        return {}
    out = {
        "program": _t(f.get("program") or f.get("role") or f.get("position") or f.get("event")),
        "start_date": _t(f.get("start_date") or f.get("batch_start") or f.get("joining_date")),
        "end_date": _t(f.get("end_date")),
        "hours": _t(f.get("hours")),
        "duration": _t(f.get("duration")),
        "mode": _t(f.get("mode")),
        "grade": _t(f.get("grade")),
        "project": _t(f.get("project_title")),
        "skills": "\n".join(line_items(f.get("cert_skills"), 6)),
        "event_date": _t(f.get("event_date")),
    }
    return {k: v for k, v in out.items() if v}


_LEFTOVER = re.compile(
    r"\{\{[^{}]*\}\}|\{\{|\}\}|\(([A-Z][A-Z0-9]*_[A-Z0-9_]*)\)|\[([A-Z][A-Z0-9]*_[A-Z0-9_]*)\]|<<[^<>\n]*>>"
    r"|\[(?:your|student|candidate|company|course|insert|name)\b[^\]\n]*\]",
    re.I,
)


def leftover_tokens(*values: Any) -> list[str]:
    """Template tokens still present in final text ({{name}}, (USER_NAME), [COURSE_NAME], <<x>>,
    [Student name]) anywhere in strings, lists or dicts. Issuing refuses such text."""
    out: list[str] = []

    def walk(v: Any, depth: int = 0) -> None:
        if v is None or depth > 4:
            return
        if isinstance(v, str):
            for m in _LEFTOVER.finditer(v):
                tok = m.group(0)
                if tok.startswith("(") and not re.fullmatch(r"\([A-Z0-9_]+\)", tok):
                    continue
                if tok not in out:
                    out.append(tok)
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x, depth + 1)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x, depth + 1)

    for v in values:
        walk(v)
    return out


# --------------------------------------------------------------------------- reference numbers
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REF_RE = re.compile(r"^TD-(OL|EO|AL|CC|IC|CA|CP|LR)-(\d{4})-([A-HJ-NP-Z2-9]{6})$")


def new_ref_no(doc_type: str, year: int, rnd: Callable[[int], int] | None = None) -> str:
    """``TD-<prefix>-<year>-<6 chars>`` (32-letter alphabet without I/O/0/1)."""
    pick = rnd or secrets.randbelow
    tail = "".join(ALPHABET[pick(len(ALPHABET))] for _ in range(6))
    return f"TD-{DOC_TYPES[doc_type]['prefix']}-{year:04d}-{tail}"


PREVIEW_TAIL = "DRAFT"  # 5 letters: never a REF_RE match, so the verify page always says not found


def preview_ref(doc_type: str, year: int) -> str:
    """The placeholder reference of a preview (``TD-OL-2026-DRAFT``); never stored or verifiable."""
    return f"TD-{DOC_TYPES[doc_type]['prefix']}-{year:04d}-{PREVIEW_TAIL}"


def normalise_ref(code: str) -> str:
    """``td/al/2026/7k3qx9`` / ``TD AL 2026 7K3QX9`` / ``TD-AL-2026-7K3QX9`` -> canonical form."""
    return re.sub(r"[\s/_.-]+", "-", str(code or "").strip().upper()).strip("-")


def is_doc_ref(code: str) -> bool:
    return bool(REF_RE.match(normalise_ref(code)))


def types_catalogue() -> list[dict[str, Any]]:
    """The type picker + per-type form (admin UI)."""
    out = []
    for key, t in DOC_TYPES.items():
        out.append(
            {
                "key": key,
                "label": t["label"],
                "short": t["short"],
                "layout": t["layout"],
                "prefix": t["prefix"],
                "fields": [{"key": k, **field_def(k)} for k in t["fields"]],
                "paragraphs": list(t["paragraphs"]),
                "sections": LETTER_SECTIONS.get(key),
                "email_key": key if key in EMAIL_TEMPLATES else None,
            }
        )
    return out
