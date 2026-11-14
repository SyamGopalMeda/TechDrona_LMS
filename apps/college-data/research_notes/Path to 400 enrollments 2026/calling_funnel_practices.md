# Calling Programme and Enrollment Funnel Practices (for ~113 AP engineering colleges, 400 enrollments by 31 Dec 2026)

Research date: 3 Nov 2026. Note: many benchmark figures are from vendor blogs (JustCall, Kixie, Prospeo, Gong, Belkins, Cognism, LeadSquared). They are flagged as vendor material. Nearly all sales benchmarks come from US/EU B2B SaaS SDR teams, not Indian institutional or ed-tech calling. Use them as rough bounds only.

## 1. Call disposition taxonomy and mapping to contact validity

### Takeaway
CRMs come with a small default outcome list. HubSpot's defaults are Connected, Busy, No answer, Left live message, Left voicemail and Wrong number. LeadSquared expects you to define your own disposition dropdown and attach mandatory follow-up actions to each value. Vendor guidance suggests keeping roughly 10–15 codes. Each code should map to one contact-validity state and one next action.

### Cited Findings
- HubSpot's default call outcomes are Busy, Connected, Left live message, Left voicemail, No answer and Wrong number. Each has a fixed internal GUID, e.g. Wrong number = 17b47fee-58de-441e-a44c-c6300d46f273. — [HubSpot Developers: Calls API](https://developers.hubspot.com/docs/api/crm/calls)
- HubSpot users have asked in the Ideas forum for customisable outcome lists and for a way to make Call Outcome a required field. This suggests that neither was fully available by default at the time. — [HubSpot Community: Customize Call Outcome options](https://community.hubspot.com/t5/HubSpot-Ideas/Customize-Call-Outcome-options/idc-p/290573); [Make Call Outcome required](https://community.hubspot.com/t/make-call-outcome-required/7905)
- LeadSquared's Generic Telephony Connector has you create a custom dropdown field (e.g. "Disposition") holding the disposition values. Once a call is disposed you can trigger actions, which can be made mandatory: create a task, create a custom activity, or update a lead field. — [LeadSquared Help: Generic Telephony Connector](https://help.leadsquared.com/?p=6889)
- In LeadSquared, Call Disposition lets a rep take a specific action when a call ends, e.g. schedule a follow-up call task. Calls without a submitted disposition form show a pending-disposition icon. — [LeadSquared Help: Telephony Feature Guide](https://help.leadsquared.com/?p=21640)
- Aircall treats a number as "wrong" when it is invalid or doesn't exist. When syncing to HubSpot, it logs those calls as Wrong number / No answer / None. — [Aircall support](https://support.aircall.io/en-gb/articles/10375355061277)
- Vendor guidance (Prospeo, vendor blog) recommends about 10–15 codes. Too few lose detail; too many make agents code inconsistently. — [Prospeo: What is call disposition](https://prospeo.io/s/what-is-call-disposition)
- Disposition codes are commonly used to drive retry timing, nurture routing, suppression and do-not-call flags. — [Outsource Accelerator glossary](https://www.outsourceaccelerator.com/glossary/call-disposition) (glossary, secondary)
- I found no official LeadSquared article that maps call outcomes directly to lead-stage changes. That mapping appears to need a workflow/automation rule. — [LeadSquared Help: Telephony Feature Guide](https://help.leadsquared.com/?p=21640) (absence noted)

### Inferences
- Suggested taxonomy for this programme. It is built from the HubSpot defaults plus Indian telecom realities and is my synthesis, not a vendor standard:
  | Code | Contact validity | Next action |
  |---|---|---|
  | Connected – Interested (right person) | Working, verified | Log stage = Interested; book meeting/visit; send info within 24h |
  | Connected – Callback requested (date/time) | Working, verified | Task at requested slot |
  | Connected – Not decision-maker / referred to X | Working, verified (wrong role) | Capture referred contact; new contact record |
  | Connected – Not interested (reason) | Working, verified | Close for 60–90 days; reason pick-list |
  | Connected – Do not call | Working | Suppress permanently (consent/DND) |
  | No answer (rings) | Unverified (count attempt) | Retry per cadence |
  | Busy | Probably working | Retry same day after 1–2h |
  | Switched off / not reachable | Unverified | Retry next day, different time slot |
  | Wrong number (reached, wrong person) | Non-working for this contact | Mark invalid; source an alternative |
  | Invalid / does not exist / out of service | Non-working | Mark invalid; source an alternative |
  | Left message (with office/receptionist) | Working (office line) | Retry in 1–2 days |
- Store contact validity as a property of the phone number (Working / Non-working / Unverified), separate from the call outcome. Then "contact validity rate" can be computed per number and per college.
- "Switched off" and "not reachable" are common Indian mobile network announcements and are not in US CRM defaults. Add them as custom values.

### Gaps
- I couldn't retrieve LeadSquared's or Zoho's actual default disposition lists. LeadSquared appears to have no fixed default list.
- I found no Salesforce default list (Salesforce uses a configurable "Call Result" field on tasks). Not verified in this session.

## 2. Call cadence, attempts and timing

### Takeaway
The evidence on attempts spans about 3–8 attempts, mostly from older or vendor sources. A defensible rule is about 6 attempts over about 10–14 working days, at varied time slots, before marking a contact "unreachable". Mid-morning (10–11am) and late afternoon look best; lunch looks worst. None of this data is India- or college-office-specific.

### Cited Findings
- Cognism's 2025 report, as summarised by a roundup, says about 3 attempts is optimal, with about 93% of conversations happening by the third call. — [Mystrika cold-calling stats roundup](https://blog.mystrika.com/cold-calling-statistics/) (secondary; Cognism is a vendor)
- InsideSales (vendor) says research points to 6–8 call attempts to reach a decision-maker. — [InsideSales](https://www.insidesales.com/?p=5358)
- A Leads360 analysis found that leads first reached after 7 or more attempts were 45% less likely to convert, and suggested stopping at 6 phone attempts (older study). — [CustomerThink](https://customerthink.com/?p=50152)
- Weidert found profitability peaked at 10 call attempts overall and at 6 for small businesses (older). — [Weidert](https://www.weidert.com/blog/effectively-prospect-leads-using-these-metrics)
- Belkins (vendor; 175,000+ dials, 2025) found a 9.9% connect rate per dial, rising to 24.5% per prospect after about 3 attempts. 19% of non-booking outcomes asked for a follow-up. — [JustCall: Auto dialer benchmarks 2026](https://justcall.io/blog/auto-dialer-benchmarks-2026.html) (vendor compilation)
- Best-time studies on the same page: Cognism (200k+ calls) found 10–11am best. ZoomInfo (1.4M+ calls) found 10–11am, with a second peak at 4–5pm. Belkins found 3–4pm best. Saleshandy (7,699 calls) found 3–5pm best. All agree the lunch hour performs worst. Tuesday/Wednesday tend to be best and Friday worst. — [JustCall: Auto dialer benchmarks 2026](https://justcall.io/blog/auto-dialer-benchmarks-2026.html)

### Inferences
- Proposed cadence for TPO/principal/HoD contacts (synthesis): Day 1 at two slots (10:00–11:30, 15:00–16:30). Then Day 2, 4, 7 and 10, rotating slots. A WhatsApp/email touch after attempt 2 and again after attempt 4. Mark "Unreachable – this number" after 6 no-connects and switch to an alternate number or the college main line. Mark the college "Unreachable" only when every known number is exhausted.
- Avoid known blackout windows in AP engineering colleges: semester exams, placement drive days, and festival holidays. Check each college's academic calendar. This is not sourced and should be validated by the team.
- Follow-up SLA proposal (synthesis, not sourced): callback requests honoured within ±30 min of the requested slot. "Interested" contacts get collateral the same day and a next-step call within 2 working days.

### Gaps
- I found no published data on best times to reach college offices or TPOs in India. Generic US B2B timing may not transfer, because college office hours are typically about 9:30–16:30 and lunch is around 13:00–14:00. Collect your own connect-rate-by-hour data in the first 2 weeks.
- I found no 2024 Orum or Gong primary study on attempt counts.

## 3. Prioritisation scoring (fit × intent × reachability)

### Takeaway
The standard B2B approach is a 2×2 fit × engagement matrix: high-fit/high-engagement goes to sales now, high-fit/low-engagement goes to nurture, low-fit/high-engagement gets qualified, low/low is deprioritised. HubSpot supports separate fit (property-based) and engagement (event-based) scores. Adding reachability (a working contact exists) as a gating multiplier fits a cold institutional list.

### Cited Findings
- Vendor and consultancy sources describe the fit × engagement 2×2: high/high routes to sales immediately, high fit + low engagement goes to nurture, low fit + high engagement goes to educate/qualify, low/low is disqualified or deprioritised. — [Pedowitz Group](https://www.pedowitzgroup.com/how-do-you-define-fit-vs.-engagement-scoring); [Prospeo: Lead qualification matrix](https://prospeo.io/s/lead-qualification-matrix) (vendor)
- HubSpot distinguishes property-based fit scores from event-based engagement scores. On some tiers, users build two separate properties and combine them in lists or reports. — [Glitter guide to HubSpot lead scoring](https://www.glitter.io/guides/understanding-lead-scoring-in-hubspot-engagement-fit-and-combined-approaches) (third party; verify on knowledge.hubspot.com)
- Salesforce Einstein Lead Scoring ranks leads from historical lead-field data and past conversions. Salesforce does not natively build a two-axis matrix. — [MassMailer: Lead scoring in Salesforce](https://massmailer.io/?p=118342) (third party)
- Account-level scoring playbooks for B2B use firmographic fit plus engagement signals at the account (not individual) level. — [Abmatic: Account scoring playbook](https://abmatic.ai/blog/account-scoring-playbook-for-b2b-teams) (vendor)

### Inferences
- For colleges, score the account (the college), not the person. Suggested inputs (synthesis):
  - **Fit (0–50):** total intake / number of B.Tech seats and relevant branches (CSE/IT/ECE), autonomy/NAAC/NBA status, district proximity to the team, past relationship.
  - **Intent (0–30):** most recent disposition (Interested = high), meeting held, MoU or permission letter, ambassador recruited, first registrations received.
  - **Reachability (multiplier 0 / 0.5 / 1):** no working number = 0, only office line = 0.5, verified TPO or HoD mobile = 1.
  - Priority = (Fit + Intent) × Reachability. Then tier A/B/C: call A daily, B per cadence, C monthly.
- With only 113 accounts, a simple transparent points table beats predictive scoring. There is too little conversion history to train on.

### Gaps
- I found no published ed-tech-specific institutional scoring model, and no evidence on which college attributes predict student enrollment yield.

## 4. Funnel stage definitions and anti-double-counting rules

### Takeaway
Ed-tech and admissions CRMs (LeadSquared) model a stage sequence: enquiry → counselling/follow-up → application → documents → decision → fee payment → enrolment. Double counting is avoided by keeping one lead record per student, deduplicated on a unique, standardised phone (and/or email) field, with stage held as a single field that moves forward. Separate institutional and student funnels.

### Cited Findings
- LeadSquared (vendor) describes the admissions pipeline as enquiry, application, counsellor follow-up, document submission, admissions decision, fee payment and enrolment. Another of its pages uses Inquiry → Counseling → Tour → Application → Enrolled. — [LeadSquared: Admissions funnel guide](https://www.leadsquared.com/industries/education/admissions-funnel-guide/); [LeadSquared: Student enrolment management system](https://www.leadsquared.com/education/student-enrollment-management-system/)
- LeadSquared lets you mark the phone/mobile field as unique to prevent new duplicates. Existing duplicates must be cleaned first (export/re-import). The "Phone Control" field type standardises number format and makes the country code mandatory. The duplicate report can filter on company, email, phone or mobile and merge records. — [LeadSquared Help: How to avoid creating duplicate leads](https://help.leadsquared.com/avoid-creating-duplicate-leads/); [LeadSquared: Duplicate lead report](https://www.leadsquared.com/duplicate-lead-report)
- LeadSquared has separate Opportunity duplicate detection for the same lead showing interest in the same opportunity type from multiple sources. That is a model for "one student, multiple sources/ambassadors". — [LeadSquared Help: Opportunity duplicate detection](https://help.leadsquared.com/duplicate-detections/)
- Vendor material recommends reporting enquiries by source, applications by stage, stage-to-stage conversion and counsellor productivity. — [LeadSquared: Student enrolment management system](https://www.leadsquared.com/education/student-enrollment-management-system/) (vendor)

### Inferences
- Proposed student stages (synthesis; define each by an observable event):
  1. Lead: a contact captured with a valid phone.
  2. Interested: positive call/WhatsApp response.
  3. Registered: account or form created.
  4. Applied: application submitted.
  5. Confirmed / Enrolled: payment received or seat confirmed. **This is the only stage that counts toward the 400.**
  6. Dropped / Refunded: terminal stage. Subtract from Enrolled; do not delete.
- Anti-double-count rules:
  - One record per student keyed on a normalised 10-digit mobile (strip +91/0/spaces), with email as a secondary key.
  - Stage is one field holding the highest stage reached, with a date stamp per stage. Count stage reached by date, not stage-entry events.
  - Count Enrolled net of refunds.
  - Attribution is a separate field (first-touch college + ambassador). Ties are resolved by a written rule (e.g. first verified referral wins). The enrollment counts once in totals even if credited in an ambassador leaderboard.
  - Institutional funnel (college: Not contacted → Contacted → Interested → Meeting → Partnered/Active) is tracked on the account record and never summed with student counts.

### Gaps
- I found no independent (non-vendor) benchmark for ed-tech stage-to-stage conversion rates in India.

## 5. KPIs, dashboard and run-rate forecasting

### Takeaway
Core activity KPIs:
- dials/day/caller
- connect rate per dial and per contact
- conversations/day
- contact validity rate
- stage conversion rates

Pace is tracked with a burn-up chart: cumulative enrolled against a straight target line to 400 by 31 Dec. The projected completion date is remaining ÷ recent run-rate.

### Cited Findings
- Bridge Group 2025 (351 B2B companies, via a vendor compilation): the median SDR makes 44 dials/day (56 for the top quartile of phone-centric teams) within 112 total activities. It has 4.1 quality conversations/day (top quartile 4.6), and ramp time is 3.0 months. — [JustCall: Auto dialer benchmarks 2026](https://justcall.io/blog/auto-dialer-benchmarks-2026.html); [Kixie](https://www.kixie.com/sales-blog/how-much-time-sdrs-spend-prospecting/) (both vendors citing Bridge Group; primary report not accessed)
- Bridge Group figure via Revenue.io: 49 dials/day without dialing software versus 77 with it. — [Revenue.io](https://www.revenue.io/blog/why-sales-call-connection-rates-are-dropping) (vendor)
- Connect-rate benchmarks vary widely:
  - Gong: 5.4% per dial on average, 13.3% for the top quartile, 19 vs 8 dials per connect.
  - Belkins: 9.9% per dial.
  - Orum (2021): 4.6–5.5%.
  - Saleshandy (verified mobiles, small sample): 44.6%.
  — [JustCall compilation](https://justcall.io/blog/auto-dialer-benchmarks-2026.html) (all vendors; conflicting)
- A LeadSquared customer testimonial claims counsellors handle 75–100 calls/day, up from 30–40 before adoption. This is self-reported vendor marketing. — [LeadSquared: Student enrolment management system](https://www.leadsquared.com/education/student-enrollment-management-system/)
- Burn-up method:
  - Pace is the slope of the completed line, and the target line shows the steady pace needed to hit the deadline. — [Zenhub: Release burnup](https://support.zenhub.com/article/release-burnup); [Allstacks](https://allstacks.atlassian.net/wiki/x/joAxyw)
  - Projected date = today + remaining ÷ completion rate, flagging the gap against the committed date. — [ScrumDesk FlowAnalyzer BC-05](https://flowanalyzer.scrumdesk.com/rules/BC-05)
  - Best/average/worst forecast cones come from min/avg/max historic velocity. — [Atlassian blog](https://www.atlassian.com/blog/archives/burnup-reports-agile-teams-guest-blog/amp); [Aha!](https://www.aha.io/blog/introducing-the-burnup-chart-to-track-the-impact-of-scope-creep)

### Inferences
- Dashboard (synthesis):
  - **Activity:** dials, connects and conversations per caller per day.
  - **Data quality:** contact validity rate = working numbers ÷ numbers attempted at least once; % of colleges with a verified decision-maker.
  - **Institutional funnel:** count of colleges per stage.
  - **Student funnel:** count per highest stage reached, with conversion between adjacent stages.
  - **Pace:**
    - Required run-rate = (400 − net enrolled) ÷ working weeks left to 31 Dec.
    - Actual run-rate = net enrolled in the trailing 2–4 weeks ÷ weeks.
    - Projected total by 31 Dec = net enrolled + actual run-rate × weeks left.
    - Projected completion date = today + (400 − net enrolled) ÷ actual run-rate.
  - Show best/worst cones using the min/max weekly rate.
- Arithmetic example (from the brief's figures only): from 3 Nov 2026 there are about 8.4 weeks to 31 Dec. If net enrolled were E, the required rate would be (400 − E)/8.4 per week. Plug in actual E from the portal; no figure is assumed here.
- Report connect rate both per dial and per contact (after N attempts). The Belkins figures show these differ by more than 2×.

### Gaps
- I couldn't access the primary Bridge Group report. I found no India telecalling connect-rate benchmark and no ed-tech-specific India KPI benchmark.

## 6. Team sizing rules of thumb

### Takeaway
I found no sourced rules for colleges per outreach lead or ambassadors per college/department. The only quantitative anchors are US SDR dial volumes (median 44/day, about 49–77 depending on dialer) and a vendor ed-tech testimonial (75–100 calls/day).

### Cited Findings
- Median SDR: 44 dials/day, 112 total activities/day, 4.1 quality conversations/day. — [JustCall citing Bridge Group 2025](https://justcall.io/blog/auto-dialer-benchmarks-2026.html)
- 49 dials/day manual versus 77 with dialer software. — [Revenue.io citing Bridge Group](https://www.revenue.io/blog/why-sales-call-connection-rates-are-dropping)
- Ed-tech counsellor claim of 75–100 calls/day (vendor testimonial). — [LeadSquared](https://www.leadsquared.com/education/student-enrollment-management-system/)

### Inferences
- For 113 colleges with a cadence of about 6 attempts × 2–3 contacts per college, the first full pass is about 113 × 15 ≈ 1,700 dials. At about 40–50 manual dials per caller per day, that is roughly 35–40 caller-days. This is calculated from the cited dial rates, not a published rule.
- Ambassador ratios must be set empirically. Start with 1 per partnered college, add per department once a college produces registrations, and track enrollments per ambassador.

### Gaps
- I found no sourced benchmark for colleges per outreach lead, ambassadors per college, or campus-ambassador yield in Indian ed-tech.

## 7. Compliance: DPDP Act 2023 / DPDP Rules 2025 and TRAI TCCCPR

### Takeaway
- **DPDP:** The Rules were notified on 14 Nov 2025 with an 18-month phased compliance window, so most data-fiduciary obligations bite around mid-May 2027. Building consent notices, purpose limitation, erasure handling and security into the student-data process now is low-cost and avoids rework. Student data (names, phones) is personal data. A TPO's official contact is still personal data of that individual.
- **TRAI:** The Feb 2025 TCCCPR amendments push promotional calls to the 140 series and service/transactional calls to the 1600 series. They restrict telemarketing from ordinary 10-digit numbers and tighten penalties for repeat violations.
- Promotional calls to students from personal mobiles are the highest-risk practice. Whether one-to-one B2B calls to college officials count as "commercial communication" under TCCCPR is not clearly answered in sources found.

### Cited Findings
- **DPDP**
  - The DPDP Rules 2025 were notified on 14 November 2025. The Act was enacted on 11 August 2023. — [PIB backgrounder, 17 Nov 2025](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)
  - The Rules introduce "an eighteen-month period for phased compliance". Every Data Fiduciary must issue a separate, clear consent notice explaining the specific purpose. Consent may be withdrawn at any time. Fiduciaries must display contact details for data queries. Rights requests (access, correction, erasure) must be answered within 90 days. Breaches must be notified to affected individuals without delay. — [PIB backgrounder](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)
  - Penalties: up to ₹250 crore for failure to maintain reasonable security safeguards. Up to ₹200 crore each for failing to notify breaches and for violating children's-data obligations. Up to ₹50 crore for other violations. — [PIB backgrounder](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)
  - Data Protection Board provisions took effect immediately. Secondary sources place consent-manager registration from about 14 Nov 2026 and the remaining substantive obligations at about 13/14 May 2027. — [AZB & Partners](https://www.azbpartners.com/bank/update-indias-digital-personal-data-protection-framework-comes-into-effect/); [Deccan Herald](https://www.deccanherald.com/amp/story/india%2Fcentre-notifies-dpdp-rules-implementation-planned-in-phases-spread-over-12-18-months-3798465) (secondary; verify against the Gazette)
  - The notification date is reported as both 13 Nov and 14 Nov 2025 across sources. The PIB says 14 Nov. — [PIB](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf); [DSK Legal](https://dsklegal.com/?p=26455)
- **TRAI**
  - The amendments to TCCCPR 2018 were announced on 12 Feb 2025 (TRAI PR No. 11/2025): 140 series for promotional calls, 1600 series for transactional/service calls, and senders restricted from using ordinary 10-digit numbers for telemarketing. — [Saraf & Partners](https://sarafpartners.com/?p=31162); [Storyboard18](https://www.storyboard18.com/how-it-works/trai-tightens-rules-against-spam-introduces-provision-of-stricter-penalties-56616.htm)
  - Penalties for senders found guilty of repeated violations: first violation bars outgoing services on all the sender's telecom resources for 15 days; subsequent violations disconnect all telecom resources across all providers for 1 year and blacklist the sender. — [Saraf & Partners](https://sarafpartners.com/?p=31162)
  - Complaint rules: consumers can complain within 7 days (up from 3). Access providers resolve within 5 days (down from 30). Action can trigger on 5 complaints in 10 days. — [Saraf & Partners](https://sarafpartners.com/?p=31162)
  - On 10 July 2026, TRAI clarified (PR No. 91/2026) that the 140 series is exclusively for promotional calls by businesses from any sector, and entities must register with telecom service providers to use it. Calls from 1600-series numbers cannot be tagged, blocked or filtered. The 1600 series is mandated initially for BFSI regulated entities' service/transaction calls. — [Telangana Today (IANS)](https://telanganatoday.com/trai-clarifies-rules-for-1600-and-140-number-series-to-prevent-misinformation); [SCC Online](https://www.scconline.com/blog/post/2026/07/18/trai-clarifies-1600-and-140-series-number-framework/); [TRAI PR 91/2026 (scanned PDF, text not extractable)](https://trai.gov.in/sites/default/files/2026-07/PR_No91of2026.pdf)

### Inferences
- **Calling institutions (TPO/principal/HoD):** these are relationship/B2B calls to identifiable officials. Low risk if made one-to-one, respectful of "do not call" requests, and not mass auto-dialled. Still log a lawful purpose and minimise the data kept: name, role, official number.
- **Calling students:** bulk promotional calls from personal 10-digit numbers risk UCC complaints and disconnection of the caller's SIM under the 2025 penalty regime. Safer routes:
  - Contact students only after opt-in, e.g. a registration form with a DPDP-style notice and consent checkbox, or an ambassador-collected opt-in.
  - Use a registered 140-series or principal-entity setup if doing promotional outreach at scale.
  - Honour DND/opt-outs, and keep a suppression list tied to the "Do not call" disposition.
- **Children's data:** under DPDP a "child" is under 18. Most B.Tech students are 18+, but some first-years may be 17. Capture date of birth or age confirmation at registration and route minors to a parental-consent path. The age threshold comes from the Act and was not re-verified in this session.

### Gaps
- I could not extract text from TRAI PR 91/2026 (scanned PDF) or the Feb 2025 amendment text. Specifics are from secondary legal and news summaries.
- I found no authoritative statement on whether one-to-one B2B calls to institutional officials, or calls by a small team from personal mobiles, are "commercial communication" under TCCCPR. Get legal advice if scaling.
- TCCCPR calling-hour limits were not confirmed in sources found this session.
- I found no sector-specific 1600/140 mandate for education.
