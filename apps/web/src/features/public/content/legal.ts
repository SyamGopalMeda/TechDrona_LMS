import type { ContentDoc } from "./types";

/**
 * PUB-018 policy texts, structured from the product rules. Sources per section are named in
 * the comments; no clause goes beyond what those documents decide. Open points stay open and
 * say so (for example the grievance officer is named only after counsel review, E10).
 */

/** Published device-policy defaults (blueprint-brief §1 "Device policy"; sitemap PUB-018). */
export const DEVICE_POLICY_DEFAULTS = {
  maxTrustedDevices: 3,
  maxConcurrentSessions: 2,
  maxVideoStreams: 1,
  maxReplacementsPer30Days: 2,
  trustedInactivityExpiryDays: 90,
} as const;

/** FR-COM-008 / OPD-01: one refund rule, same wording in Terms, product page and checkout. */
export const REFUND_RULE_SUMMARY =
  "Full refund within 7 days of purchase if less than 20% of the content has been consumed and no certificate has been issued. This includes discounted purchases.";

export const TERMS: ContentDoc = {
  slug: "terms",
  title: "Terms of use",
  summary: "The rules for using Tech Drona: one account per person, published device limits, fair review of restrictions, and one refund rule.",
  draft: true,
  sections: [
    {
      id: "account",
      heading: "1. Your account is for one person",
      paragraphs: [
        "A Tech Drona account is a single-user licence. Do not share your password, sessions or paid access with anyone else.",
        "You need an email address or an Indian mobile number and a date of birth to create an account. We use your date of birth to apply the right privacy protections.",
      ],
      // product-requirements D3/D4; privacy §1 "single-user licence"
    },
    {
      id: "minors",
      heading: "2. Learners under 18",
      paragraphs: [
        "If you are under 18 and sign up yourself, a parent or guardian must agree before you can start. We send them a link to approve or decline.",
        "If Tech Drona enrols you in a training batch, the same guardian approval applies before you can start.",
        "Accounts for learners under 18 never receive marketing and are never scored for account sharing.",
      ],
      // privacy §4 minors flow and minor mode
    },
    {
      id: "devices",
      heading: "3. Devices, sessions and video",
      paragraphs: [
        `By default an account may have up to ${DEVICE_POLICY_DEFAULTS.maxTrustedDevices} trusted devices, ${DEVICE_POLICY_DEFAULTS.maxConcurrentSessions} signed-in sessions at the same time and ${DEVICE_POLICY_DEFAULTS.maxVideoStreams} video playing at a time. Each browser profile counts as a device.`,
        "Signing in on a new device needs a one-time code. The full rules are in the device policy.",
      ],
      links: [{ href: "/legal/device-policy", label: "Device policy" }],
      // blueprint-brief §1 device policy; PO-02 / CCP-S7
    },
    {
      id: "restrictions",
      heading: "4. Account protection and restrictions",
      paragraphs: [
        "If our checks suggest that an account is being shared or taken over, we may ask you to verify yourself or apply a temporary restriction. A person reviews every restriction that you contest, and every decision comes with a reason.",
        "You can ask for a review from the restriction screen, and you can appeal a rejection once within 14 days to a different reviewer.",
      ],
      links: [
        { href: "/help/account-restricted", label: "If your account is restricted" },
        { href: "/unblock-request", label: "Request a review" },
      ],
      // account-unblock-workflow principle, §4
    },
    {
      id: "payments",
      heading: "5. Prices, payments and refunds",
      paragraphs: [
        "Prices are shown in Indian rupees and include 18% GST. The price shown on the pricing page is the price you pay at checkout. A GST invoice is issued for every paid order.",
        `Refunds: ${REFUND_RULE_SUMMARY}`,
        "Subscriptions renew automatically until you cancel. You can cancel in one click from Billing. Only the first payment of a subscription can be refunded under the rule above; renewals are not refundable but can be cancelled.",
      ],
      links: [{ href: "/legal/refund-policy", label: "Refund policy" }],
      // FR-COM-008, FR-COM-009, product-requirements D3
    },
    {
      id: "assessments",
      heading: "6. Tests and certificates",
      paragraphs: [
        "Proctored tests record integrity events such as tab switches, leaving full screen and paste events. You are told before the test starts. Flags are reviewed by a person before any decision.",
        "Certificates can be verified publicly with their code. A certificate may be revoked, for example after a confirmed integrity violation; the verification page then shows the revocation date without the reason.",
      ],
      links: [{ href: "/verify", label: "Verify a certificate" }],
      // privacy D15; FR-LRN-007
    },
    {
      id: "privacy",
      heading: "7. Your data",
      paragraphs: ["How we use your data, how long we keep it and how to exercise your rights is described in the privacy notice."],
      links: [{ href: "/legal/privacy", label: "Privacy notice" }],
    },
    {
      id: "contact",
      heading: "8. Questions and complaints",
      paragraphs: ["Contact support from the help centre. Complaints follow the grievance process described there."],
      links: [
        { href: "/help", label: "Help centre" },
        { href: "/help/grievance", label: "Grievance officer" },
      ],
    },
  ],
};

export const PRIVACY: ContentDoc = {
  slug: "privacy",
  title: "Privacy notice",
  summary: "What personal data Tech Drona collects, why, how long it is kept, and how you can see, correct or delete it.",
  draft: true,
  sections: [
    {
      id: "who",
      heading: "1. Who is responsible",
      paragraphs: [
        "When you sign up yourself, Tech Drona decides how your data is used (we are the Data Fiduciary).",
        "This also applies when Tech Drona enrols you in one of its training batches: Tech Drona is responsible for your batch, learning, security and billing records.",
      ],
      // privacy §1
    },
    {
      id: "data",
      heading: "2. What we collect and why",
      table: {
        caption: "Data we collect, why we need it and how long we keep it",
        head: ["Data", "Why", "How long"],
        rows: [
          ["Account details: name, email, phone, password (stored only as a secure hash), date of birth", "Create and secure your account; apply age protections", "While your account exists, then 30 days"],
          ["Profile and education: institution (optional), branch, graduation year, target companies", "Personalised placement preparation", "While your account exists"],
          ["Consent records", "Prove what you agreed to and when you withdrew", "While your account exists, then 3 years"],
          ["Sign-in and access logs: time, IP address, network type, state-level location, browser and device", "Keep accounts secure; investigate incidents (a legal obligation)", "13 months"],
          ["Devices you sign in on", "Device limits, new-device codes, remembered devices", "Up to 180 days after last use"],
          ["Account-sharing checks (adults who consent)", "Enforce the single-user licence and protect accounts", "180 days, or with a case while it is open"],
          ["Learning activity: enrolments, progress, attempts, scores, code, certificates", "Deliver courses, tests and certificates", "While your account exists; test attempts 3 years after the course ends"],
          ["Time-on-task signals (heartbeats while a page is visible)", "Show your progress and time spent", "Raw signals 35–90 days; summaries 13–24 months, then pseudonymised"],
          ["Payments, invoices and refunds (never your full card number)", "Payments, refunds and GST", "Invoices and GST records 72 months"],
          ["Support tickets and message logs", "Help you and send service messages", "Message logs 1 year; tickets 3 years"],
          ["Test integrity events (proctored tests only)", "Review the fairness of an assessment", "The attempt's life plus 1 year"],
        ],
      },
      // privacy §2 D1–D15 rewritten in plain language
    },
    {
      id: "never",
      heading: "3. What we never collect",
      items: [
        "GPS or precise location",
        "Aadhaar, PAN or other government ID numbers",
        "Your contact lists, hardware or advertising IDs",
        "Webcam or screen recordings",
        "Card numbers",
        "Caste, religion, health or disability details (an accommodation such as extra time is recorded only as a flag, never as a diagnosis)",
      ],
      // privacy §2 "Never collected"
    },
    {
      id: "choices",
      heading: "4. Your choices",
      paragraphs: [
        "The account and learning service is required to use Tech Drona. Everything else is a separate choice that is off unless you turn it on: personalised recommendations, product news by email or SMS, and product analytics. Account-sharing checks are needed for adult paid plans.",
        "You can withdraw any optional choice in Settings → Privacy, as easily as you gave it. Withdrawals take effect within 24 hours.",
      ],
      links: [{ href: "/app/settings/privacy", label: "Privacy settings (sign-in needed)" }],
      // privacy §3.2
    },
    {
      id: "minors",
      heading: "5. Learners under 18",
      items: [
        "A parent or guardian must agree before a learner under 18 who signs up directly can start.",
        "No account-sharing scoring, no device fingerprinting, no marketing and no personalised upsell.",
        "Learning data is used only to deliver learning.",
        "A missing date of birth is treated as under 18.",
      ],
      // privacy §4
    },
    {
      id: "rights",
      heading: "6. Your rights",
      table: {
        caption: "Your rights and how to use them",
        head: ["Right", "How", "Our target"],
        rows: [
          ["Get a copy of your data", "Settings → Privacy: request an export", "Within 72 hours"],
          ["Correct your data", "Edit your profile; ask support for locked fields such as date of birth", "7 days"],
          ["Delete your account", "Settings → Privacy: request deletion (7-day cooling-off period)", "Within 30 days after the cooling-off period"],
          ["Complain", "Grievance officer (see the help centre)", "Acknowledge in 48 hours, resolve within 30 days"],
        ],
      },
      paragraphs: [
        "Some records must be kept even after deletion: access logs (13 months), GST invoices (72 months) and open security cases. We tell you exactly what remains and why.",
        "If you are not satisfied with our answer to a grievance, you can complain to the Data Protection Board of India after the grievance process.",
      ],
      // privacy §5
    },
    {
      id: "where",
      heading: "7. Where your data is stored and who helps us",
      paragraphs: ["Your data and logs are stored in India (Mumbai region). A few service providers process limited data for us:"],
      items: [
        "Video delivery: your user ID, name and masked phone number appear as a watermark on videos.",
        "Code execution: source code and test inputs only, keyed by random IDs (no personal details).",
        "Email and SMS delivery in India.",
        "Password breach check: only the first 5 characters of a one-way hash of your password are sent.",
      ],
      // privacy §10
    },
    {
      id: "contact",
      heading: "8. Contact",
      paragraphs: ["The Data Protection Officer and grievance officer contact details will be published in the help centre after legal review."],
      links: [{ href: "/help/grievance", label: "Grievance officer" }],
    },
  ],
};

export const REFUND_POLICY: ContentDoc = {
  slug: "refund-policy",
  title: "Refund policy",
  summary: "One refund rule, used word for word in these Terms, on product pages and at checkout. It includes discounted purchases.",
  draft: true,
  sections: [
    {
      id: "rule",
      heading: "The rule",
      paragraphs: [REFUND_RULE_SUMMARY],
      // FR-COM-008
    },
    {
      id: "products",
      heading: "How it applies to each kind of purchase",
      items: [
        "Subscriptions: only the first payment can be refunded under the rule. Renewals are not refundable, but you can cancel any time in one click.",
        "Placement packages: refundable minus the mentor sessions already used, at their listed unit price.",
        "Mock-test packs: refundable if no mock has been started.",
      ],
    },
    {
      id: "how",
      heading: "How to ask for a refund",
      items: [
        "Request a refund in the app from Billing.",
        "The finance team decides within 5 business days.",
        "Approved refunds go back to the original payment method. A credit note is issued against your GST invoice.",
        "An approved refund ends the access it paid for.",
      ],
      links: [{ href: "/app/billing", label: "Billing (sign-in needed)" }],
    },
  ],
};

export const DEVICE_POLICY: ContentDoc = {
  slug: "device-policy",
  title: "Device policy",
  summary: "The published numbers for devices, signed-in sessions and video streams on a learner account.",
  draft: true,
  sections: [
    {
      id: "numbers",
      heading: "The numbers",
      table: {
        caption: "Default limits for a learner account",
        head: ["Limit", "Default"],
        rows: [
          ["Trusted (registered) devices", String(DEVICE_POLICY_DEFAULTS.maxTrustedDevices)],
          ["Signed-in sessions at the same time", String(DEVICE_POLICY_DEFAULTS.maxConcurrentSessions)],
          ["Videos playing at the same time", String(DEVICE_POLICY_DEFAULTS.maxVideoStreams)],
          ["Device replacements you can make yourself", `${DEVICE_POLICY_DEFAULTS.maxReplacementsPer30Days} per 30 days`],
          ["A trusted device expires after", `${DEVICE_POLICY_DEFAULTS.trustedInactivityExpiryDays} days without use (does not use up a replacement)`],
        ],
      },
      // blueprint-brief §1 device policy
    },
    {
      id: "what-counts",
      heading: "What counts as a device",
      items: [
        "Each browser profile counts as a device. Two browsers on one laptop are two devices.",
        "Signing in on a new device needs a one-time code sent to your email or mobile.",
        "Verifying a device with a code does not allow using the account from two different networks at the same time.",
      ],
      // PO-02 / CCP-S7; CPR-PRD-11
    },
    {
      id: "limits",
      heading: "When you reach a limit",
      items: [
        "Too many sessions: you choose which session to sign out before continuing.",
        "A second video: playback is refused on the second device until the first one stops.",
        "Too many devices: remove a device in Settings → Devices.",
        "Tests: an attempt in progress belongs to one session. Another device sees a read-only view and can move the attempt after confirming (at most 2 moves per attempt).",
      ],
      links: [{ href: "/app/settings/devices", label: "Devices (sign-in needed)" }],
    },
  ],
};

export const LEGAL_DOCS = { terms: TERMS, privacy: PRIVACY, "refund-policy": REFUND_POLICY, "device-policy": DEVICE_POLICY } as const;
