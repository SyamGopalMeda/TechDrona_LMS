import { DEVICE_POLICY_DEFAULTS, REFUND_RULE_SUMMARY } from "./legal";
import type { ContentDoc } from "./types";

/**
 * PUB-019 help-centre articles. Sources: account-unblock-workflow.md (§4 SLAs, appeals),
 * analytics-event-schema.md (§3.1 parameters, §3.12 disclosure), privacy-and-data-retention.md
 * (§5 rights), product-requirements.md (FR-COM-008, FR-SUP-001). The grievance officer is not
 * named yet (implementation-roadmap E10): the page says so instead of inventing a contact.
 */

export const GRIEVANCE: ContentDoc = {
  slug: "grievance",
  title: "Grievance officer and complaints",
  summary: "How to raise a complaint about your data, a restriction or our service, and how fast we answer.",
  draft: true,
  sections: [
    {
      id: "officer",
      heading: "Grievance officer",
      paragraphs: [
        "The name and contact details of our grievance officer and Data Protection Officer will be published on this page after legal review. Until then, use the in-app routes below; every grievance raised there is tracked with a deadline.",
      ],
    },
    {
      id: "how",
      heading: "How to raise a grievance",
      items: [
        "About your personal data (access, correction, deletion or a complaint): sign in and go to Settings → Privacy.",
        "About a restricted account: use the review request on the restriction screen. A rejected request can be appealed once within 14 days to a different reviewer.",
        "About anything else (payments, content, tests, certificates): sign in and open a support ticket.",
      ],
      links: [
        { href: "/app/settings/privacy", label: "Privacy settings" },
        { href: "/unblock-request", label: "Request a review of a restriction" },
        { href: "/app/support/new", label: "Open a support ticket" },
      ],
    },
    {
      id: "timelines",
      heading: "How fast we answer",
      items: [
        "We acknowledge a grievance within 48 hours.",
        "We aim to resolve it within 30 days.",
        "Restriction reviews have their own, shorter targets (see “If your account is restricted”).",
        "If you are not satisfied with the outcome, you can complain to the Data Protection Board of India once the grievance process is complete.",
      ],
      links: [{ href: "/help/account-restricted", label: "If your account is restricted" }],
    },
  ],
};

export const ACCOUNT_RESTRICTED: ContentDoc = {
  slug: "account-restricted",
  title: "If your account is restricted",
  summary: "What a restriction means, how to ask for a review and how long it takes.",
  draft: false,
  sections: [
    {
      id: "what",
      heading: "What happened",
      paragraphs: [
        "If our checks suggest an account is being shared or has been taken over, we may show a notice, ask you to verify a device, or pause paid access for a while. A person reviews every restriction you contest, and every decision comes with a reason.",
      ],
    },
    {
      id: "review",
      heading: "Ask for a review",
      paragraphs: ["Use “Request a review” from the restriction screen. Tell us what happened in your own words. You get a case reference to track the request."],
      links: [{ href: "/unblock-request", label: "Request a review" }],
    },
    {
      id: "timing",
      heading: "How long it takes",
      table: {
        caption: "Review targets",
        head: ["", "Temporary restriction (L3)", "Suspension (L4)"],
        rows: [
          ["First response from a person", "24 hours", "48 hours"],
          ["Decision", "72 hours", "5 days"],
        ],
      },
      paragraphs: ["No case stays open for more than 30 days. If we ask you for more information, the clock pauses until you reply."],
    },
    {
      id: "appeal",
      heading: "If the review is rejected",
      paragraphs: ["You will see the reason. You can appeal once within 14 days; a different reviewer decides the appeal. You can also contact the grievance officer."],
      links: [{ href: "/help/grievance", label: "Grievance officer" }],
    },
  ],
};

export const HOW_WE_MEASURE_TIME: ContentDoc = {
  slug: "how-we-measure-time",
  title: "How we measure time",
  summary: "Every “time spent” figure is an estimate. This is exactly how we estimate it (method tm-1.0).",
  draft: false,
  sections: [
    {
      id: "rule",
      heading: "When time counts",
      items: [
        "A page earns active time only while it is visible and you have used the keyboard, mouse or touch recently, or while a video is playing.",
        "A hidden tab never earns active time. Audio from a video in a hidden tab counts as video playback, not active learning.",
        "After your last input, time keeps counting only up to an idle limit for that kind of page; then the page is idle.",
        "Two tabs open at the same time are not counted twice.",
      ],
    },
    {
      id: "params",
      heading: "The numbers we use",
      table: {
        caption: "Time measurement parameters (method tm-1.0)",
        head: ["Setting", "Value"],
        rows: [
          ["Activity sample while you are active", "every 15 seconds"],
          ["Idle limit: reading a lesson", "180 seconds"],
          ["Idle limit: practice", "240 seconds"],
          ["Idle limit: coding", "180 seconds"],
          ["Idle limit: timed test", "300 seconds"],
          ["Idle limit: video page when the video is not playing", "90 seconds"],
          ["Most credit for one practice question view", "10 minutes"],
          ["Most credit for a video per day", "1.25 × its length"],
          ["Most credit for one coding problem per day", "120 minutes"],
        ],
      },
      paragraphs: ["If we change any of these, the method version changes and reports never mix numbers computed with different versions."],
    },
  ],
};

export const DEVICE_LIMITS: ContentDoc = {
  slug: "device-limits",
  title: "Devices, sessions and video limits",
  summary: "How many devices and sessions you can use, and what to do when you hit a limit.",
  draft: false,
  sections: [
    {
      id: "numbers",
      heading: "The limits",
      items: [
        `Up to ${DEVICE_POLICY_DEFAULTS.maxTrustedDevices} trusted devices (each browser profile is a device).`,
        `Up to ${DEVICE_POLICY_DEFAULTS.maxConcurrentSessions} signed-in sessions at the same time.`,
        `${DEVICE_POLICY_DEFAULTS.maxVideoStreams} video playing at a time.`,
        `You can replace up to ${DEVICE_POLICY_DEFAULTS.maxReplacementsPer30Days} devices yourself every 30 days.`,
      ],
      links: [{ href: "/legal/device-policy", label: "Full device policy" }],
    },
    {
      id: "fix",
      heading: "When you hit a limit",
      items: [
        "Remove a device you no longer use in Settings → Devices.",
        "When there are too many sessions, choose which session to sign out at sign-in.",
        "If you need more replacements than allowed, open a support ticket.",
      ],
      links: [
        { href: "/app/settings/devices", label: "Devices" },
        { href: "/app/support/new", label: "Open a support ticket" },
      ],
    },
  ],
};

export const REFUNDS: ContentDoc = {
  slug: "refunds",
  title: "Refunds",
  summary: "Who can get a refund, and how to ask for one.",
  draft: false,
  sections: [
    { id: "rule", heading: "The rule", paragraphs: [REFUND_RULE_SUMMARY] },
    {
      id: "how",
      heading: "How to ask",
      paragraphs: ["Request a refund from Billing in the app. The finance team decides within 5 business days and refunds go back to the original payment method."],
      links: [
        { href: "/app/billing", label: "Billing" },
        { href: "/legal/refund-policy", label: "Refund policy" },
      ],
    },
  ],
};

export const CERTIFICATES: ContentDoc = {
  slug: "certificates",
  title: "Certificates and verification",
  summary: "How employers can check that a Tech Drona certificate is genuine.",
  draft: false,
  sections: [
    {
      id: "verify",
      heading: "Verify a certificate",
      paragraphs: ["Every certificate has a code of 10–16 letters and digits. Anyone can enter it on the verification page to see the learner's name, the course and the issue date. A revoked certificate shows the revocation date."],
      links: [{ href: "/verify", label: "Verify a certificate" }],
    },
    {
      id: "mine",
      heading: "Your certificates",
      paragraphs: ["Signed-in learners find their certificates under Certificates in the app."],
      links: [{ href: "/app/certificates", label: "My certificates" }],
    },
  ],
};

export const HELP_ARTICLES: ContentDoc[] = [ACCOUNT_RESTRICTED, DEVICE_LIMITS, REFUNDS, CERTIFICATES, HOW_WE_MEASURE_TIME, GRIEVANCE];

export function findHelpArticle(slug: string): ContentDoc | null {
  return HELP_ARTICLES.find((a) => a.slug === slug) ?? null;
}
