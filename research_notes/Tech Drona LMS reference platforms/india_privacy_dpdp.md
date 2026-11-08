# Indian Privacy & Data-Protection Requirements for "Tech Drona" (Edtech / Placement-Prep LMS) — current as of 3 Nov 2026

> Labels used throughout: **[STATUTE]** = Act text; **[RULES]** = DPDP Rules 2025 / official notifications / directions; **[COMMENTARY]** = law-firm, vendor or press analysis; **[OPEN]** = unresolved question for qualified Indian counsel. Many fetches used secondary reproductions of the Gazette text (dpdpa.com, MYND DPDP wiki) because the official PIB/MeitY PDFs were not machine-readable. Verify exact wording against the Gazette before relying on it. This is research, not legal advice.

## 1. Status and phased commencement of the DPDP Act 2023 and DPDP Rules 2025

### Takeaway
The DPDP Rules 2025 were notified on 13/14 Nov 2025. As of Nov 2026, the substantive Data Fiduciary obligations (notice, consent, security, breach, children, rights, retention) are **not yet in force**. They are computed to start on **13 May 2027** (AZB gives 12 May 2027). Consent-manager registration (Rule 4 and s.6(9)) starts on about 13 Nov 2026. A proposal to shorten the 18 months to 12 months was reported but never notified. Treat May 2027 as the hard deadline and build to it now.

### Cited Findings
- [RULES] Rules 1, 2 and 17–21 (Board) took effect on publication. Rule 4 (consent manager registration) takes effect after 1 year. Rules 3, 5–16, 22 and 23 take effect after 18 months — [Mondaq, "DPDP Rules 2025 notified"](https://www.mondaq.com/india/data-protection/1708164/digital-personal-data-protection-rules-2025-notified); [SS Rana](https://ssrana.in/articles/meity-notifies-final-digital-personal-data-protection-rules-2025/)
- [RULES] Act commencement notification G.S.R. 843(E), dated 13 Nov 2025:
  - In force immediately: ss.1(2), 2, 18–26, 35, 38–43, 44(1) and 44(3).
  - About 13 Nov 2026: s.6(9) and s.27(1)(d).
  - About 13 May 2027: ss.3–5, 6(1)–(8) and (10), 7–17, 27 (rest), 28–34, 36, 37 and **44(2)**. Section 44(2) is the provision that omits IT Act s.43A.
  - Source: [dpdprules.org commencement/proposal tracker, updated 27 Oct 2026](https://dpdprules.org/blog/dpdp-18-months-to-12-months-proposal); [ICAI Palakkad reproduction](https://palakkad.icai.org/detail/56514.aspx); [Taxmann](https://www.taxmann.com/post/blog/govt-notifies-commencement-dates-for-dpdp-act/)
- [COMMENTARY] AZB's timeline: 13 Nov 2025 for the immediate provisions, 12 Nov 2026 for consent managers, 12 May 2027 for everything else. Other sources say 13 May 2027 — [AZB Partners](https://www.azbpartners.com/?p=87799)
- [COMMENTARY] In Jan 2026, MeitY reportedly proposed cutting the window to 12 months, chiefly for SDF obligations, which would mean about 13 Nov 2026. Industry comments were reportedly due 4 Feb 2026 — [Business Standard](https://www.business-standard.com/technology/tech-news/meity-may-cut-compliance-timeline-for-key-dpdp-rules-to-12-months-126012201293_1.html); [Mondaq/SS Rana](https://www.mondaq.com/india/data-protection/1773554/meity-plans-to-cut-short-dpdp-compliance-timeline-and-notify-cross-border-restrictions-for-sdfs)
- [COMMENTARY] No amending instrument has been found. A Lok Sabha written answer on 12 Aug 2026 still referred to an "eighteen-month transition period". The December 2025 corrigenda reworded Rule 1(3)–(4) but did not change the periods — [dpdprules.org](https://dpdprules.org/blog/dpdp-18-months-to-12-months-proposal)
- [RULES] DPDP (Removal of Difficulties) Order 2026, S.O. 5458(E), dated 5 Oct 2026. It makes word-level fixes only: s.9(1) now reads "child or *of* a person with disability", and s.10(2)(c)(ii) changes "audit" to "data audit". It moves no deadline — [SCC Online](https://www.scconline.com/blog/post/2026/10/15/dpdp-removal-of-difficulties-order-2026/); [dpdprules.org](https://dpdprules.org/blog/dpdp-removal-of-difficulties-order-2026); [India Briefing](https://www.india-briefing.com/news/dpdp-removal-of-difficulties-order-2026-consent-data-audit-47274.html)
- [RULES] The Data Protection Board was established in law on 13 Nov 2025. MeitY's circular of 6 May 2026 invited applications for a Chairperson and 4 Members. Commentators say no appointments had been made as of mid-2026 — [LiveLaw, 1 Aug 2026](https://www.livelaw.in/articles/india-data-protection-board-established-law-543751); [SanSa Legal](https://www.sansalegal.com/post/data-protection-board-of-india-takes-shape-enforcement-architecture-under-the-dpdp-act-2023); [DSCI FAQ](https://www.dsci.in/files/content/documents/2026/faq-on-data-protection-board.pdf)

### Inferences
- Tech Drona has about 6 months, until about 13 May 2027, to finish its DPDP build. Launching with DPDP-compliant notice and consent avoids re-consenting users later.
- Until s.44(2) commences, **IT Act s.43A and the SPDI Rules 2011 most likely still apply**. They require a privacy policy, consent in writing for sensitive personal data such as passwords and financial or card information, and "reasonable security practices" such as ISO 27001.

### Gaps
- I could not search the Gazette directly. Check egazette.gov.in for any DPDP amendment notified after Oct 2026.
- The exact final day (12 vs 13 May 2027) differs between sources. [OPEN] Counsel should confirm it.
- Whether s.44(2) is already in force: the MYND wiki says it is, while the ICAI reproduction and dpdprules.org say it is not. The weight of sources says it is not — [MYND wiki](https://dpdp.myndsolution.com/wiki/act/section-44-amendments-to-certain-acts/)

## 2. Core Data Fiduciary obligations (notice, consent, legitimate uses, purpose and minimisation, security, breach, retention, rights, SDF)

### Takeaway
DPDP is **consent-centric with narrow "legitimate uses"**. Unlike the GDPR, there is no general "legitimate interests" basis. Rule 3 requires an itemised, standalone notice. Rule 6 sets minimum security controls and a **1-year log retention**. Rule 7 requires breach notice to individuals "without delay" and to the Board immediately, with a detailed report within **72 h**. Rule 8(3) sets a **minimum 1-year retention** of personal data, traffic data and logs. Rule 14 caps grievance responses at **90 days**. The Third Schedule's **3-year inactivity erasure applies only to large e-commerce, gaming and social-media fiduciaries, not edtech**.

### Cited Findings
**Notice (s.5 and Rule 3)**
- [RULES] The notice must be understandable on its own (standalone). It must be in clear, plain language and contain at least:
  - an **itemised description of the personal data**;
  - the **specified purpose(s)** and a specific description of the goods or services or uses enabled;
  - a link to the website or app;
  - the means to **withdraw consent, with ease comparable to giving it**;
  - the means to exercise rights;
  - the means to complain to the Board.
  - Source: [Rule 3 text, dpdpa.com](https://dpdpa.com/dpdparules/rule3.html)

**Consent (s.6)**
- [STATUTE] Consent must be free, specific, informed, unconditional and unambiguous, given by clear affirmative action, and limited to the data necessary for the specified purpose. It can be withdrawn. After withdrawal, the fiduciary and its processors must stop processing within a reasonable time — [DPDP Act 2023, MeitY PDF](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)
- [RULES] Consent Managers are registered with the Board under Rule 4 and the First Schedule. Using one is optional for fiduciaries. Registration opens about Nov 2026 — [AZB](https://www.azbpartners.com/?p=87799)

**Legitimate uses (s.7)**
- [STATUTE] There are nine exhaustive grounds:
  - (a) data the person voluntarily provided for a specified purpose, where they have not indicated they do not consent to its use;
  - (b)–(d) State subsidies and functions, and legal disclosure to the State;
  - (e) compliance with judgments and orders;
  - (f)–(h) medical emergency, epidemic, disaster or breakdown of public order;
  - (i) employment purposes.
  - There is **no fraud-prevention or "legitimate interests" ground** for a private B2C company — [s.7, dpdpa.com](https://dpdpa.com/dpdpa2023/chapter-2/section7.html)

**Purpose limitation and minimisation**
- [STATUTE] Consent is limited to data "necessary for the specified purpose" (s.6(1)). Under s.8(7), a fiduciary must erase data once the person withdraws consent or once it is reasonable to assume the purpose is no longer served, whichever is earlier, unless the law requires retention. Processors must erase too — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)

**Security (s.8(5) and Rule 6)**
- [RULES] The minimum controls are:
  - (a) encryption, obfuscation, masking or virtual tokens;
  - (b) access control over computer resources;
  - (c) **logs, monitoring and review of access** to detect, investigate and remediate unauthorised access;
  - (d) continuity measures such as backups;
  - (e) **retention of such logs and personal data for 1 year** for detection, investigation and remediation, unless another law requires otherwise;
  - (f) security clauses in contracts with Data Processors;
  - (g) technical and organisational measures.
  - Source: [Rule 6, dpdpa.com](https://dpdpa.com/dpdparules/rule6.html)

**Breach notification (s.8(6) and Rule 7)**
- [RULES] Each affected Data Principal must be told **"without delay"**, through their account or registered contact. The notice must cover the nature, extent and timing of the breach, likely consequences, mitigation, safety steps the person can take, and a contact.
- [RULES] The Board gets an initial notice without delay. A **detailed report follows within 72 hours** (extendable on written request), covering facts, causes, mitigation, findings about the person who caused the breach, preventive measures and the notices sent to individuals.
- [RULES] Notice is required for **every** personal data breach. There is no materiality threshold — [Rule 7, dpdpa.com](https://dpdpa.com/dpdparules/rule7.html)

**Retention and erasure (Rule 8 and Third Schedule)**
- [RULES] Under Rule 8(1)–(2), Third Schedule fiduciaries must erase data after a set period of user inactivity, with a **48-hour advance warning** to the user.
- [RULES] The Third Schedule covers only three classes:
  - **e-commerce entities with at least 2 crore registered users in India**;
  - **online gaming intermediaries with at least 50 lakh**;
  - **social media intermediaries with at least 2 crore**.
- [RULES] Their period is **3 years** from the user's last contact or from commencement, whichever is later. It does not apply to account access or virtual tokens such as wallets. **Edtech is not a listed class** — [Third Schedule, dpdpa.com](https://dpdpa.com/schedule/schedule3.html)
- [RULES] Under Rule 8(3), **every** fiduciary must keep personal data, associated traffic data and processing logs for **at least 1 year** from processing, for the Seventh Schedule purposes (State and investigative requests). After that it must erase them, unless another law requires longer. The official illustration says that after an e-book purchase, order, payment and delivery logs are kept for 1 year **even if the account is deleted** — [Rule 8, dpdpa.com](https://dpdpa.com/dpdparules/rule8.html)

**Rights and grievances (ss.11–14 and Rule 14)**
- [STATUTE] Data Principals have the rights to:
  - access a summary of their data, the processing activities and the recipients of shared data (s.11);
  - correction, completion, updating and erasure (s.12);
  - grievance redressal (s.13);
  - nominate someone to act for them (s.14).
- [STATUTE] Data Principals must exhaust the fiduciary's grievance process before approaching the Board — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)
- [RULES] Fiduciaries must prominently publish how to make requests and which identifier is needed. Grievances get a response "within a reasonable period **not exceeding ninety days**" — [Rule 14, dpdpa.com](https://dpdpa.com/dpdparules/rule14.html)
- [STATUTE] Under s.8(9)–(10), the fiduciary must publish the business contact of a DPO or other person who can answer questions, and must run an effective grievance mechanism — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)

**Significant Data Fiduciary (s.10 and Rule 13)**
- [STATUTE] SDF status is **notified by the Central Government** based on:
  - the volume and sensitivity of the data;
  - the risk to Data Principals;
  - the potential impact on sovereignty and integrity, electoral democracy, security of the State and public order.
- [STATUTE] SDFs must appoint an India-based DPO, an independent data auditor, and conduct a DPIA — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)
- [RULES] Under Rule 13, SDFs must:
  - carry out a **DPIA and audit every 12 months** and report significant observations to the Board;
  - do **due diligence that algorithmic software is not likely to pose a risk to Data Principals' rights**;
  - **localise** data the Central Government specifies on a committee's recommendation.
  - Source: [Rule 13, dpdpa.com](https://dpdpa.com/dpdparules/rule13.html)

### Inferences
- A startup LMS is very unlikely to be notified as an SDF early on. But Rule 13's algorithmic due-diligence standard is a sensible benchmark for the account-sharing model anyway.
- Because edtech is outside the Third Schedule, Tech Drona's retention is governed by s.8(7) purpose-exhaustion plus the Rule 6 and Rule 8(3) **1-year minimum**. Tech Drona sets its own maximums and must justify them.

### Gaps
- [OPEN] How Rule 6(e) and Rule 8(3) interact with s.8(7) erasure on request. The illustration suggests logs survive account deletion for 1 year. Confirm the scope of "logs" and "traffic data" with counsel.
- [OPEN] Whether an edtech that sells courses online is an "e-commerce entity" under the Consumer Protection Act. It only matters for the Third Schedule if Tech Drona ever reaches 2 crore users.

## 3. Children's data (under 18): verifiable parental consent, tracking ban, educational-institution exemption

### Takeaway
Under the Act, a "child" is anyone **under 18**. For a child, Tech Drona needs **verifiable parental consent** (s.9(1) and Rule 10). Section 9(3) **bans tracking, behavioural monitoring and targeted advertising** directed at children. The Fourth Schedule Part A exempts "educational institutions" only for tracking and behavioural monitoring for **their educational activities or the safety of enrolled children**. Whether a private edtech platform counts as an "educational institution" is **genuinely unresolved**. Treat it as an [OPEN] question and design conservatively.

### Cited Findings
- [STATUTE] s.9(1) requires verifiable consent of the parent or lawful guardian before processing a child's data. s.9(2) prohibits processing likely to cause any detrimental effect on a child's well-being. s.9(3) prohibits "tracking or behavioural monitoring of children or targeted advertising directed at children". s.9(4)–(5) let the government exempt classes or purposes — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)
- [RULES] Rule 10 requires technical and organisational measures for verifiable parental consent, plus due diligence that the parent is an **identifiable adult**. Verification can use:
  - reliable identity and age details the fiduciary already holds;
  - details the parent supplies voluntarily;
  - a **virtual token** from an authorised entity, for example via **DigiLocker**.
  - Source: [Rule 10, dpdpa.com](https://dpdpa.com/dpdparules/rule10.html)
- [RULES] Fourth Schedule Part A, item 3 lists "educational institution", with processing **"restricted to tracking and behavioural monitoring (a) for the educational activities of such institution; or (b) in the interests of safety of children enrolled with such institution"**. "Educational institution" means "an institution of learning that imparts education, including vocational education". "Educational activities" is **not defined** — [Fourth Schedule, dpdpa.com](https://dpdpa.com/schedule/schedule4.html)
- [RULES] Part B is purpose-based. It covers:
  - creating a user account **limited to email communication**;
  - keeping harmful information inaccessible to a child;
  - **confirming that a Data Principal is not a child** under the Rule 10 due-diligence obligations.
  - Source: [Fourth Schedule](https://dpdpa.com/schedule/schedule4.html)
- [COMMENTARY] The definition is vague. It is unclear whether it covers only schools or also **edtech companies and private tutors**. Part A and Part B may be read as independent or interconnected (Chitra Iyer, quoted) — [MediaNama, 17 Nov 2025](https://www.medianama.com/2025/11/223-dpdp-rules-tracking-children-parental-consent/)
- [COMMENTARY] SS Rana addresses coaching centres and platforms specifically and urges them to audit their compliance — [SS Rana](https://ssrana.in/articles/schools-coaching-centres-platforms-processing-childrens-data-are-you-compliant/). Tsaaro discusses edtech and behavioural-monitoring limits — [Tsaaro](https://tsaaro.com/blogs/safeguarding-minors-online-understanding-parental-consent-obligations-and-behavioural-monitoring-restrictions-under-the-dpdpa-and-dpdp-rules)
- [STATUTE] Breach of the s.9 child obligations carries a penalty of **up to ₹200 crore** (see section 7 below).

### Inferences
- Most college students are 18 or older. Some first-years, and any school-level users, may be 17.
- **Recommended age gate:** collect date of birth at signup; Part B covers age-confirmation processing. If the user is under 18, route them to parental consent under Rule 10, or allow them only through an institution-sponsored enrolment.
- **For confirmed minors, the conservative design is:**
  - no per-user behavioural profiling for account-sharing risk;
  - no marketing personalisation or retargeting pixels;
  - analytics only in aggregate or strictly for learning delivery, such as course progress the student and teacher need.
- **For institution (B2B) deployments:** Tech Drona processing on a college's instructions is arguably a **Data Processor** of that college. The college is plausibly an "educational institution" within Part A. That is the strongest route to rely on the "educational activities" exemption. Contract for it explicitly.
- **For direct-to-consumer minors:** a private edtech seller of placement-prep content is a weaker fit for "institution of learning". It may at most claim the vocational-education angle. [OPEN]
- Page-level time-on-task analytics used to deliver learning (progress, completion) may count as "educational activities". Using the same data for upsell targeting would not.

### Gaps
- [OPEN] Whether a private, online-only, for-profit edtech or placement-prep platform is an "educational institution". There is no MeitY FAQ or Board guidance yet; the Board is not yet staffed.
- [OPEN] Whether **fraud and security monitoring** (account-sharing detection) of a minor counts as "tracking or behavioural monitoring" under s.9(3). The term is undefined.
- [OPEN] Whether parental consent obtained under Rule 10 can **lift** the s.9(3) ban. On a plain reading it cannot: s.9(3) is a standalone prohibition, separate from consent.

## 4. Account-sharing detection, profiling and automated restrictions: lawful basis and transparency

### Takeaway
DPDP has no general fraud-prevention or legitimate-interest basis. For adults, account-sharing detection should rest on **consent obtained through the Rule 3 notice**, with the purpose itemised (for example "account security and enforcement of single-user licence"). Section 7(a) "voluntarily provided" may arguably support it. DPDP has **no GDPR-style Art. 22 right** against automated decisions. But fairness, notice specificity and the SDF algorithmic due-diligence standard point to providing explanation, human review and appeal.

### Cited Findings
- [STATUTE] s.7 lists the only consent-free grounds. None is "fraud prevention" or "security" for a private company. s.7(a) covers data voluntarily provided for a specified purpose where the person has not objected — [s.7](https://dpdpa.com/dpdpa2023/chapter-2/section7.html)
- [RULES] The notice must itemise each data element and each specified purpose, and withdrawal must be as easy as giving consent — [Rule 3](https://dpdpa.com/dpdparules/rule3.html)
- [RULES] Rule 6(c) *requires* logs, monitoring and review of access to personal data to detect unauthorised access. This is a security obligation, distinct from monitoring users' behaviour — [Rule 6](https://dpdpa.com/dpdparules/rule6.html)
- [RULES] SDFs must verify that algorithmic software is "not likely to pose a risk to the rights of Data Principals" — [Rule 13](https://dpdpa.com/dpdparules/rule13.html)
- [STATUTE] s.8(3) says that if personal data is used to make a decision affecting the Data Principal, the fiduciary must ensure its completeness, accuracy and consistency — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)

### Inferences
- **Section 8(3) is the closest DPDP hook for automated restriction decisions.** A risk score that triggers lockout is a decision affecting the person, so the input signals must be accurate. False positives from shared college NAT IPs or mobile carrier CGNAT are a real accuracy risk.
- **Recommended design for account-sharing detection:**
  - state the purpose explicitly in the notice and Terms;
  - rely on **contract plus consent**;
  - use graduated responses: step-up re-verification (OTP) before any suspension;
  - provide a human-review appeal channel through the grievance mechanism, with the Rule 14 90-day cap, though a far shorter response is advisable;
  - log the reasons for each decision so access and correction requests under ss.11–12 can be answered.
- **Withdrawal of consent:** a user could withdraw consent to sharing-detection. Withdrawal plausibly lets Tech Drona end the service, but s.6(4)–(6) and the "unconditional" consent requirement in s.6(1) create tension. If the processing is essential to a single-user licence, frame it as **necessary** for the service. [OPEN]
- **Security logs:** basic login, IP and device logging for access security is independently mandated by Rule 6 and Rule 8(3) and by CERT-In. It is the most defensible tier.

### Gaps
- [OPEN] Whether consent bundled into terms of service for anti-sharing detection is "specific" and "unconditional" enough. Counsel should advise on whether necessary-for-contract can be expressed within DPDP consent.
- I found no official guidance on automated decision-making under DPDP. The Board has issued none.

## 5. CERT-In Directions (28 Apr 2022)

### Takeaway
The CERT-In Directions were issued under IT Act s.70B(6) and have applied since 27 Jun 2022. They cover service providers, intermediaries, data centres, body corporates and government bodies, so an Indian edtech company is in scope as a body corporate. They require:
- reporting specified cyber incidents to CERT-In **within 6 hours** of noticing them;
- **180-day rolling ICT log retention**, required to be within Indian jurisdiction; the FAQs soften this;
- synchronising clocks to the **NIC or NPL NTP servers**, or to servers traceable to them.

### Cited Findings
- [RULES] Issued 28 Apr 2022, effective 27 Jun 2022. FAQs were issued 18 May 2022. The MSME timeline was extended by an order of 27 Jun 2022 — [Ankura](https://ankura.com/insights/everything-you-need-to-know-about-indias-new-guidelines-related-to-cyber-incident-reporting-by-cert-in/); [Khaitan Ergo](https://khaitanco.com/sites/default/files/2022-04/Ergo_30042022.pdf)
- [RULES] **6-hour reporting.** If full details are not available, report what is known within 6 hours and supplement later. The FAQs say the obligation overrides contractual confidentiality — [Ankura](https://ankura.com/insights/everything-you-need-to-know-about-indias-new-guidelines-related-to-cyber-incident-reporting-by-cert-in/); [AZB](https://www.azbpartners.com/bank/cert-in-directions/)
- [RULES] **180-day logs**, maintained within India. Sources conflict on the FAQ position: some say logs may be stored abroad if they can be produced to CERT-In, others say a copy must be kept in India — [ManageEngine](https://www.manageengine.com/log-management/cyber-security/cert-in-compliance-for-indian-enterprises.html); [Cyril Amarchand blog](https://corporate.cyrilamarchandblogs.com/2022/05/the-cert-in-cyber-security-directions-more-questions-than-answers/)
- [COMMENTARY] Critics argue the 180-day retention conflicts with storage limitation, and that 6 hours departs from global practice — [Cyril Amarchand](https://corporate.cyrilamarchandblogs.com/2022/05/the-cert-in-cyber-security-directions-more-questions-than-answers/)

### Inferences
- Tech Drona will run **two parallel incident clocks**: CERT-In within 6 h, and the DPDP Board without delay plus 72 h (from May 2027). Build one incident runbook covering both.
- The log retention floor is **max(180 days CERT-In, 1 year DPDP Rule 6(e) and 8(3)) = 1 year** for security and access logs.
- Host primary logs in an Indian cloud region to avoid the CERT-In localisation ambiguity.
- The VPN and VPS KYC provisions of the Directions do not apply to an LMS.

### Gaps
- The CERT-In primary text and FAQ PDF were not fetched in this session. Verify the incident categories (Annex I) and the FAQ wording on log location at cert-in.org.in.

## 6. Adjacent regimes: IT Act s.43A / SPDI, Intermediary Rules, RBI payment data, GST record retention, Consumer Protection (E-Commerce) and dark patterns

### Takeaway
- **SPDI Rules and s.43A** remain live until s.44(2) commences (about May 2027).
- **Card data** must not be stored by the merchant; the RBI card-on-file rules let the gateway or network tokenise it.
- **GST records** must be kept for **72 months from the due date of the annual return**, about 7–8 years from the start of the financial year, and longer if proceedings are pending.
- **Consumer protection:** the E-Commerce Rules 2020 require a grievance officer (acknowledge within 48 h, resolve within 1 month). The **Dark Patterns Guidelines 2023** ban subscription traps. The **E-Commerce Amendment Rules 2026** (in force 1 Jan 2027) add an annual dark-pattern self-audit and certificate.

### Cited Findings
- [STATUTE] DPDP s.44(2) omits IT Act s.43A and is in the 18-month commencement group — [dpdprules.org](https://dpdprules.org/blog/dpdp-18-months-to-12-months-proposal). Sources conflict; see [MYND wiki](https://dpdp.myndsolution.com/wiki/act/section-44-amendments-to-certain-acts/)
- [RULES] **RBI card-on-file rules:**
  - Merchants and other entities in the transaction chain (other than the card issuer and card network) may not store actual card data.
  - The deadline was extended to 30 Sep 2022, and the rules took effect 1 Oct 2022.
  - Merchants may keep the last 4 digits and the issuer name for reconciliation.
  - Tokenisation requires explicit consent with additional-factor authentication.
  - Sources: [RBI press release](https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=52188); [HDFC Bank](https://www.hdfc.bank.in/blogs/credit-cards/what-are-the-rbi-guidelines-on-tokenisation-in-india)
- [STATUTE] **CGST Act s.36:** keep accounts and records for **72 months from the due date of the annual return** for the year. If an appeal, revision or proceeding is pending, keep them for 1 year after final disposal or for the 72 months, whichever is later — [KnowYourGST s.36](https://www.knowyourgst.com/gstlaw/cgst-act/36-period-of-retention-of-accounts-36/)
- [RULES] **E-Commerce Rules 2020:** grievance officer details must be displayed, complaints acknowledged within **48 hours** and resolved within **1 month** — [ONDC legal handbook](https://www.ondc.org/legal-compliance-handbook/Gaming-Industry.1074724865.html)
- [RULES] **CCPA Dark Patterns Guidelines**, 30 Nov 2023 (CPA s.18): 13 specified patterns, including **subscription trap**, false urgency, basket sneaking, confirm shaming, drip pricing and interface interference — [K&S](https://ksandk.com/newsletter/safeguarding-consumer-rights-dark-patterns-guidelines-2023/); [Vikaspedia](https://en.vikaspedia.in/viewcontent/news/guidelines-for-prevention-and-regulation-of-dark-patterns-2023-issued?lgn=en)
- [RULES] **E-Commerce Amendment Rules 2026:** notified about 10 Sep 2026, in force **1 Jan 2027**. They require dark-pattern compliance, a yearly self-audit and a prominently displayed compliance certificate — [MoneyLife](https://www.moneylife.in/article/new-ecommerce-rules-to-rein-in-dark-patterns-misleading-listings-and-hidden-charges-from-1st-january/81643.html); [Inc42](https://inc42.com/buzz/govt-tightens-ecommerce-rules-ahead-of-the-festive-season/)

### Inferences
- **Subscription trap:** paid plans must offer one-click cancellation that is as easy as signup, disclose auto-renewal, and send a pre-renewal reminder.
- **SPDI Rules** (my understanding, not re-verified this session): they require a privacy policy, written consent for sensitive personal data, a grievance officer with a 1-month redress period, and "reasonable security practices" with ISO/IEC 27001 named as one standard.
- **Intermediary Rules 2021** apply only if Tech Drona hosts third-party user content such as forums or peer Q&A. That would add due-diligence duties and a Grievance Officer (acknowledge within 24 h, resolve within 15 days). Not verified this session; [OPEN].
- Tech Drona sells its own courses, so it is likely an "inventory e-commerce entity" when selling online. That makes the E-Commerce Rules grievance-officer duty relevant. [OPEN] Confirm with counsel.

### Gaps
- I did not fetch the primary SPDI Rules, the Intermediary Rules text or the E-Commerce Amendment Rules 2026 Gazette text. The figures above are partly secondary or from memory and must be verified.
- I did not verify any post-2022 RBI amendments, such as the 2025 PA-PG master directions.

## 7. DPDP penalties

### Takeaway
The Board imposes penalties after an inquiry (s.33). They are set per instance as fixed ceilings in the Schedule to the Act. The maximums are:
- **₹250 crore** for failing to take reasonable security safeguards;
- **₹200 crore** for failing to notify a breach;
- **₹200 crore** for breaching the children's obligations;
- **₹150 crore** for breaching SDF obligations;
- **₹50 crore** for other breaches;
- **₹10,000** for breaches of a Data Principal's own duties.

### Cited Findings
- [STATUTE] Schedule items: ₹250 cr (s.8(5)); ₹200 cr (s.8(6)); ₹200 cr (s.9); ₹150 cr (s.10); ₹10,000 (s.15); ₹50 cr residual. Per-instance framing — [DPDPA Schedule](https://dpdpa.com/theschedule.html); [EY POV](https://www.ey.com/content/dam/ey-unified-site/ey-com/en-in/pdf/2025/11/ey-india-dpdp-act-2023-and-rules-2025-pov.pdf); [Konfirmity](https://www.konfirmity.com/blog/dpdp-penalties)
- [COMMENTARY] Some sources claim a ₹500 crore cumulative cap. Critics say it has **no basis in the Act** — [MYND wiki Schedule](https://dpdp.myndsolution.com/wiki/act/schedule/)
- [STATUTE] In setting a penalty, the Board considers the nature, gravity and duration of the breach, mitigation, repetition and proportionality (s.33(2)). There is no criminal liability and no statutory compensation to Data Principals. Voluntary undertakings are possible under s.32 — [DPDP Act](https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf)

### Inferences
- The highest-exposure items for Tech Drona are security safeguards and children's data. Prioritise the Rule 6 controls and the age gate.

### Gaps
- No Board enforcement precedent exists yet. The Board is not staffed and the substantive provisions are not in force.

## 8. Practical data inventory and retention proposal (recommendation, not legal advice)

### Takeaway
Use **1 year as the floor** for security and access logs; this is the DPDP Rule 6(e) and 8(3) floor, which exceeds CERT-In's 180 days. Set purpose-bound maximums elsewhere. Erase or anonymise when the purpose ends (s.8(7)). Separate statutory tax records (GST: 72 months after the annual-return due date) from behavioural analytics, which should get the shortest retention.

### Cited Findings
- [RULES] 1-year minimum for logs and personal data (Rule 6(e)) and for traffic data and processing logs (Rule 8(3)) — [Rule 6](https://dpdpa.com/dpdparules/rule6.html); [Rule 8](https://dpdpa.com/dpdparules/rule8.html)
- [RULES] CERT-In: 180 days rolling, in India — [Ankura](https://ankura.com/insights/everything-you-need-to-know-about-indias-new-guidelines-related-to-cyber-incident-reporting-by-cert-in/)
- [STATUTE] CGST s.36: 72 months from the annual-return due date — [KnowYourGST](https://www.knowyourgst.com/gstlaw/cgst-act/36-period-of-retention-of-accounts-36/)

### Inferences — proposed retention schedule

All of these are proposals unless marked as a required floor.

| Data category | Purpose and basis | Proposed retention | Notes |
|---|---|---|---|
| Account profile (name, email, phone, DOB, college) | Service delivery (consent/contract) | Life of account + 30–90 days grace, then erase | Keep DOB or an age-verified flag to evidence the age gate |
| Parental-consent records (minors) | s.9 and Rule 10 evidence | Life of the child account + limitation period (about 3 years; [OPEN]) | Store a verification token or reference, not ID documents |
| Authentication and login logs (timestamp, success/failure, IP, user agent) | Rule 6 security; CERT-In | **1 year (required floor)**, then delete or aggregate | Hot storage 180 days in India; archive to 1 year; NTP-synced |
| Device identifiers or fingerprints | Session security and sharing detection | Rolling 90–180 days for scoring; raw data purged once 1-year log duty is met | Hash or salt; no cross-site tracking; **not for under-18 users** absent counsel sign-off |
| Page-level time-on-task analytics | Learning delivery and progress (consent) | Identifiable data 12–24 months or until course end + 1 year; then aggregate or anonymise | Do not reuse for ad targeting; minors: learning use only |
| Account-sharing risk scores and decisions | Licence enforcement (consent/contract); s.8(3) accuracy | Score inputs ≤ 180 days; decision and appeal records 1 year after closure (longer if disputed) | Human review; reasons logged; appeal through grievance channel |
| Security incident case files | Rule 7 and CERT-In; defence of claims | 3 years after closure (proposed) | Includes Board and CERT-In filings |
| Grievance and rights-request tickets | s.13 and Rule 14; E-Commerce Rules | 3 years (proposed) | Evidence of the 90-day / 1-month timelines |
| Payment transaction references (no card data) | Reconciliation; RBI rules | Per GST/tax period | Gateway token, last 4 digits, issuer only |
| Invoices and GST records | CGST s.36 | 72 months from annual-return due date (about 8 years) | Statutory; s.8(7) "unless law requires" exception applies |
| Marketing consent records | Consent proof | Until withdrawal + 1 year | Never for under-18 users (s.9(3)) |
| Institution (B2B) student data | Processor for the college | Per DPA with the college; return or delete at contract end | Strongest route to the "educational institution" exemption |

- **Notice and privacy policy:** itemise each row of the table as a data element and purpose (Rule 3). Provide a consent dashboard with withdrawal as easy as consent. Publish the DPO or contact person, the grievance process and the Board-complaint route.
- **Processor contracts** (cloud, analytics, payment gateway, email/SMS): include the Rule 6(f) security clauses, a 1-year log-retention duty and breach notice to Tech Drona within hours, so the CERT-In 6 h and Board 72 h clocks can be met.

### Gaps
- [OPEN] The limitation-period-based retentions (3 years) are proposals. Indian counsel should set them against the Limitation Act and consumer-forum limitation periods (2 years under CPA s.69).
- [OPEN] Whether to rely on the B2B "educational institution" route, and how to treat minors in the D2C channel. Get a qualified opinion before launching behavioural or sharing-detection features for under-18 users.
