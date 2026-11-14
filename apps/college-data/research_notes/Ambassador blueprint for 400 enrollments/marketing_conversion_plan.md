# Marketing and student-conversion plan: Tech Drona paid IT courses, coastal AP B.Tech students, campus-ambassador network (3 Nov - 31 Dec 2026, target 400 paid)

Research date: 3 Nov 2026. These notes build on `research_notes/Path to 400 enrollments 2026/benchmarks_channels.md`, `calling_funnel_practices.md` and `reports/Path to 400 enrollments 2026.md`. Sources from those notes are re-cited where they are reused, not re-fetched. Every figure is tagged:

- **[SOURCED]** has an inline citation.
- **[ASSUMPTION]** is a planning figure built by me from the sourced ranges. It is not a measured fact.
- Source quality: [OFFICIAL], [INDEPENDENT/LARGE-SAMPLE], [VENDOR], [BLOG], [ANECDOTAL], [UNOFFICIAL-MIRROR].

DB facts below come from a **read-only** query of `portal/data/techdrona.db` (`exams` table: 256 rows, 3-1 and 4-1 for 128 colleges, `is_demo = 0`). The `enrollments`, `people`, `activities` and `courses` tables are all empty, so there is no conversion history and no course or price record in the portal.

## Q1. Realistic conversion benchmarks by stage and by channel (webinar/workshop, WhatsApp lead, referral)

### Takeaway
There is no independent, India-specific benchmark for short IT-course sales to engineering students. The only large-sample Indian figure is Meritto's index: about **1% lead-to-enrollment**, 0.74% for first-time inquirers and 3% for re-inquired leads. Workshop or webinar to paid is put at **3-8%** of registrants and **5-12%** of live attendees, but only by vendors and blogs. Referral figures of 8-15% are unverified vendor claims. Plan on roughly **5% of live attendees, 1-3% of opted-in WhatsApp leads and 5-10% of referred leads**. Recalibrate after the first two weeks of real data.

### Cited Findings
- Meritto Enrollment Index 2026 [VENDOR, 4.3 crore inquiries, mostly institutional admissions] — [The Wire/PTI](https://m.thewire.in/article/ptiprnews/ai-led-discovery-converts-6x-better-than-digital-reveals-merittos-enrollment-index-2026):
  - lead-to-enrollment 1.06% overall
  - first-time inquirers 0.74%, re-inquired leads 3.00%
  - digital average 0.94%
  - same-day response converts at 2x a one-week response
  - aggregator/publisher leads give high volume but few enrollments
- Webinar or workshop to sale is 3-8% "when content is useful and the offer well-priced", with a worked example at ₹2,999. [VENDOR/BLOG] — [inqrise.in](https://inqrise.in/blog/online-coaching-platform-marketing-india/)
- Webinar registrant show-up is 30-40%, and 5-12% of live attendees buy. For warm audiences, attendee-to-sale is 5-15% and registrant-to-sale 3-8%. [VENDOR, not India] — [acceleroi](https://www.acceleroi.com/blog/unlocking-success-exploring-the-average-conversion-rate-for-online-courses); [ruzuku](https://www.ruzuku.com/learn/articles/webinar-launch-blueprint)
- Free-to-paid conversion is 2-5% for general learning and 8-15% for exam prep, with the gap attributed to deadline pressure. [BLOG] — [productgrowth.in](https://productgrowth.in/insights/edtech/free-to-paid/)
- Indian ed-tech average conversion is about 2-3%. [VENDOR] — [WebEngage, via search](https://webengage.com/?p=41665)
- Referral claims, all unverified:
  - Education referral programmes show "8-15% conversion for referred prospects", attributed to McKinsey. I found no primary source. [VENDOR, unverified]
  - Online course platforms get 25-40% of new enrolments from referrals, and coding bootcamps 35-50%. No source is given. [VENDOR, unverified]
  - Source for both: [GrowSurf](https://growsurf.com/statistics/education-referral-statistics/)
- A vendor case study reports calls attempted → enrolled of 18% for an Indian ed-tech platform after process changes. [VENDOR, unverified] — [Vertex Global Services](https://vertexglobalservices.com/from-inquiry-to-enrollment-a-case-study-on-enhancing-conversion-rates-for-indias-top-edtech-platform/)
- One ed-tech GTM write-up says conversion is "trust-first, trial-second" and needs multi-week engagement before payment. [BLOG] — [upGrowth](https://upgrowth.in/edtech-gtm-strategy-frameworks-execution/)

### Inferences
**Stage definitions.** These follow the earlier report, and only the last stage counts toward the 400 [ASSUMPTION]:

| Stage | Event |
|---|---|
| Reach | Saw the session, post or message |
| Lead | Consented mobile captured |
| Counselled | A 1:1 call or chat of 5 minutes or more completed |
| Interested | Says yes to the batch, or asks about fee or schedule |
| Registered | Form plus seat request, or a token amount paid |
| Paid/Confirmed | Full fee, or first EMI instalment, received and not refunded within the refund window |

**Per-channel planning rates [ASSUMPTION; built to be consistent with the SOURCED ranges above].** "Lead → Paid" is the product of the stage rates.

| Channel | Reach → Lead | Lead → Counselled | Counselled → Interested | Interested → Registered | Registered → Paid | Lead → Paid (product) | Anchor |
|---|---|---|---|---|---|---|---|
| TPO/HOD-approved in-college workshop (live attendee = reach) | 60-80% fill the opt-in form | 60-70% | 35-50% | 45-60% | 55-70% | about 6-9% of leads, **about 4-7% of attendees** | 5-12% of attendees (acceleroi); 3-8% (inqrise) |
| Online webinar (registrant = reach) | 30-40% attend | 50-60% of attendees | 30-40% | 40-50% | 50-60% | **about 1-3% of registrants** | 3-8% of registrants, show-up 30-40% (acceleroi) |
| Ambassador 1:1 peer referral (warm) | n/a | 70-80% | 40-50% | 50-60% | 60-70% | **about 8-15%**; plan on 8% | Meritto 3% re-inquiry; GrowSurf 8-15% (unverified) |
| Paid-student referral ("bring a friend") | n/a | 80% | 45-55% | 55-65% | 65-75% | **about 10-15%**; plan on 10% | as above |
| WhatsApp group/community post (opted-in member = reach) | 2-5% reply or click to the form | 50-60% | 25-35% | 35-45% | 50-60% | **about 1-3% of leads** | Meritto 0.74-1.06% for first-time/digital |
| Instagram reel or college page | 0.3-1% DM or form | 40-50% | 20-30% | 35-45% | 50% | **about 0.5-1.5% of leads** | Meritto digital 0.94% |
| Hackathon or club event (participant = reach) | 40-60% opt in | 40-50% | 20-30% | 35-45% | 50% | **about 1.5-3% of leads** | Meritto: aggregator/event leads low-intent |

Notes on the table:
- The webinar row is the product of its stage rates applied to registrants: 0.35 × 0.55 × 0.35 × 0.45 × 0.55 ≈ 1.7% of registrants.
- The registrant-to-paid figure is below the vendor 3-8% on purpose. The audience is price-sensitive students, not warm buyers.

**Volume implied for 400 [ASSUMPTION: channel mix]:**

| Channel | Target paid | Rate used | Volume needed |
|---|---|---|---|
| In-college workshops | 210 | 5% of attendees | about 4,200 attendees, about 45-60 sessions of 70-90 students |
| Ambassador peer 1:1 | 70 | 8% | about 875 warm leads |
| Paid-student referrals | 60 | 10% | about 600 referred leads, i.e. about 1 in 5 paid students referring 3 friends |
| WhatsApp communities and broadcasts | 35 | 2% | about 1,750 opted-in leads |
| Online webinars (exam-week and holiday catch-up) | 15 | 1.7% | about 900 registrants |
| Instagram, Telegram, hackathons, clubs | 10 | 1% | about 1,000 leads |
| **Total** | **400** | | |

**Lag.** Most students need 3-10 days from first workshop to payment. Exams, waiting for parents and month-end allowances all slow it. A workshop held in week N mostly pays in weeks N and N+1 [ASSUMPTION; upGrowth's "multi-week engagement" supports a lag but gives no figure].

### Gaps
- No India-specific, independent figure for workshop attendee → paid, WhatsApp lead → paid or referral → paid for short IT courses. GrowSurf's 8-15% referral figure has no traceable primary source.
- No source separates "interested" from "registered" from "confirmed" for this product type. The stage rates above are synthetic and must be replaced with Tech Drona's week 1-3 data.
- No AP or Telugu-state conversion data.

## Q2. Which channels work for coastal-AP engineering students, and what rules constrain them

### Takeaway
The evidence supports this order:
1. **In-person, TPO/HOD-approved workshops** framed around placements
2. **peer and ambassador referrals**
3. **WhatsApp as the opted-in follow-up layer** (Communities announcement groups, 1:1 chats)
4. Instagram/Telegram for awareness and social proof

Telugu works as a **bilingual add-on** for explanations, parent messages and reels, not as the teaching medium. Placement anxiety is the strongest documented motivator. Four rules shape execution:
- WhatsApp's own policy requires opt-in and honouring opt-outs.
- TRAI's 2025 TCCCPR changes push promotional calls and SMS onto registered 140-series and DLT-registered channels.
- CCPA's November 2024 coaching guidelines ban "100% job guarantee" style claims.
- No AICTE/UGC rule specifically bars short-course promotion on campus (none found), but the colleges themselves act as gatekeepers.

### Cited Findings
**Demand and motivation**
- Unstop Talent Report 2025 found 83% of engineering graduates without a job or internship offer (survey of 30,000+ Gen-Z respondents and 700 HR leaders). [VENDOR survey, large] — [Business Today](https://businesstoday.in/jobs/story/83-engineering-46-b-school-grads-remain-without-a-job-internship-offer-unstop-report-468828-2025-03-21)
- The 2026 edition (37,000+ students, Jan-Feb 2026) reports about 85% of engineering students still without jobs. 92% of engineering students cite live projects as the most effective upskilling method, yet many get little exposure to them. [VENDOR survey, large] — [Outlook Business](https://www.outlookbusiness.com/corporate/jobs-are-there-but-most-students-arent-getting-them-heres-why)
- A BridgeLabz survey (about 1,000 engineering candidates) found 35.48% worried about timely placements. [VENDOR survey] — [People Matters](https://www.peoplematters.in/news/campus-recruitment/more-than-one-third-of-engineering-graduates-worried-about-placements-survey-26016)
- B.Tech students report paying for outside skill courses because syllabi are outdated. [ANECDOTAL journalism, 11 Jun 2026] — [Careers360](https://news.careers360.com/btech-courses-civil-mechanical-cse-it-engineering-students-pay-online-skill-education-syllabus-faculty-aicte-jobs-industry-gap-nep)

**Platforms**
- In small Indian student surveys, WhatsApp (87.4%) and Instagram (89.7%) are the most-used apps among undergraduates, at about 2-3 hours a day of social media. [ACADEMIC, small/unclear sample; search snippet] — [Shanlax journal](https://www.shanlaxjournals.in/journals/index.php/sijash/article/view/9795)
- An older Tamil Nadu study found 91.6% of respondents prefer WhatsApp for communication. [ACADEMIC, 2019, older] — [VVV College journal](https://journals.vvvcollege.org/assets/journalsnew/april2019/2019article9.pdf)
- WhatsApp limits: regular groups hold up to 1,024 members. Communities are reported at a 2,000-member total across up to 100 sub-groups plus the announcement group; one older page says 5,000, so the sources conflict. [VENDOR guides citing WhatsApp Help Center] — [GSMArena (1,024)](https://www.gsmarena.com/whatsapp_unveils_communities_feature_raises_group_limit_to_1024_participants-news-56392.php); [getkanal 2026](https://getkanal.com/blog/whatsapp-communities-guide)

**Telugu content and regional language**
- Resorcio reported about 18% of its footfall from Telugu-speaking states, the highest of any linguistic region. [VENDOR press] — [Sakshi Post](https://www.sakshipost.com/news/tech/resorcio-expands-its-footprint-telugu-content-155633)
- Regional-language B.Tech had a slow start. NRI Institute of Technology (AP) filled about 50% of its regional-language seats, and the industry "still needs English". [JOURNALISM] — [Careers360](https://news.careers360.com/btech-computer-science-engineering-mechanical-electrical-aicte-regional-language-hindi-aktu-karnataka-andhra-uttar-pradesh/amp)
- Skillfloor launched free tech courses in five Indian languages including Telugu (2026). [VENDOR press] — [Skillfloor](https://skillfloor.com/blog/press-release/skillfloor-opens-free-tech-courses-in-five-indian-languages-to-expand-access-for-regional-learners)

**Parent influence**
- An opinion piece says most students pursue engineering "due to parental pressure". [OPINION/ANECDOTAL] — [Deccan Herald](https://www.deccanherald.com/content/111328/engineered-future.html)
- I found no survey quantifying parents' role in paying for upskilling courses.

**WhatsApp Business policy** [OFFICIAL] — [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/)
- "You may only contact people on WhatsApp if (a) they have given you their mobile phone number … and (b) you have received opt-in permission from the recipient."
- "You must respect all requests (either on or off WhatsApp) … to block, discontinue, or otherwise opt out."
- Do not "spam, or surprise people".
- Outside the 24-hour window, use only approved Message Templates.
- Negative feedback (blocks and reports) can lead WhatsApp to "limit the amount of messages a business can send" or remove access.

**WhatsApp API pricing**
- Per delivered template message in India: marketing ₹0.8631, utility and authentication ₹0.115 (vendor-reported Meta rate card, 2026). Bulk discounts do not apply to marketing. [VENDOR citing Meta] — [Monty Mobile](https://montymobile.com/blogs/whatsapp-business-api-pricing-in-india-inr-rates-gst-and-the-2026-currency-migration-deadline); [Meta pricing docs](https://developers.facebook.com/docs/whatsapp/pricing)
- One vendor quotes about ₹1.09, which conflicts with the rate card. It is likely a BSP markup.

**TRAI TCCCPR (Feb 2025 amendments)**
- 140 series for promotional calls and 1600 series for service and transactional calls.
- Telemarketing from ordinary 10-digit numbers is restricted.
- A first repeat-violation bars outgoing services for 15 days. Further violations bring disconnection across all providers for one year and a blacklist. Action can trigger on 5 complaints in 10 days.
- [LEGAL COMMENTARY] — [Saraf & Partners](https://sarafpartners.com/?p=31162)
- TRAI's July 2026 clarification makes the 140 series exclusive to promotional calls, with registration required. [PRESS/LEGAL] — [SCC Online](https://www.scconline.com/blog/post/2026/07/18/trai-clarifies-1600-and-140-number-series-to-prevent-misinformation/)

**DLT and SMS**
- Since 2025, telcos append -P, -S, -T and -G suffixes to SMS headers by category.
- One vendor says "Service Explicit" templates migrate into the Promotional category from 10 Mar 2026.
- Consent templates must be registered and linked before consent-based messages can be sent.
- [VENDOR explainers] — [Storyboard18](https://www.storyboard18.com/amp/how-it-works/why-your-sms-now-looks-like-a-code-trais-new-message-format-explained-70270.htm); [Fast2SMS](https://www.fast2sms.com/help/?p=16132); [Plivo](https://www.plivo.com/docs/sms/concepts/dlt-registration-process)

**CCPA coaching-advertisement guidelines** (final, 13 Nov 2024) [OFFICIAL via press] — [Careers360/PTI](https://news.careers360.com/centre-issues-coaching-centres-guidelines-jee-neet-upsc-cuet-2025-crack-down-on-misleading-ads/amp)
- They prohibit false claims of "100% selection" or "100 per cent job security".
- They also prohibit misrepresenting fees, refund policies, faculty and course duration.
- Names, photos and testimonials of successful candidates need written consent obtained after selection.
- "Coaching" covers academic support, education, guidance, study programmes and tuition.
- Penalties fall under the Consumer Protection Act 2019.

**UGC/AICTE**
- The 2022 notices warned institutions against "franchise" tie-ups with ed-tech firms for degree or diploma programmes. [PRESS] — [Daily Excelsior](https://www.dailyexcelsior.com/?p=1272891)
- A law-firm reading cites UGC rules that advertisements must not suggest enrollment "will provide the student a temporary or permanent job". [LEGAL] — [Nishith Desai](https://nishithdesai.com/research-and-articles/hotline/education-sector-hotline/decoding-the-ugc-and-aictes-notices-on-franchising-and-mis-advertising-for-online-degree-programmes-5190)
- An AICTE chairman said ed-tech may support classes but not run franchise degrees. [PRESS] — [CollegeDekho](https://www.collegedekho.com/amp/news/aicte-chairman-ed-tech-companies-must-not-delve-outside-their-domain-23756/)
- I found no 2023-26 AICTE/UGC circular that specifically regulates non-degree course promotion on campus.

**DPDP** (from the earlier notes)
- The Rules were notified 14 Nov 2025 with 18-month phased compliance. Consent, notice and children's-data rules bite around May 2027. [OFFICIAL] — [PIB](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf)

### Inferences
**Channel playbook [ASSUMPTION unless cited].**

1. **Workshops (primary, about 50% of target).**
   - The pitch to the TPO/HOD is a free 90-minute "Placement-ready in 30 days: [stack] + live project" session. It ties to the 92% "live projects" finding (Unstop 2026).
   - The college gets an attendance certificate and an optional mock-test for students.
   - Format: 60 minutes of value (a live build), then 15 minutes on the course, the offer and the deadline. Finish with a QR opt-in form carrying a DPDP-style notice and a separate WhatsApp marketing opt-in checkbox, per WhatsApp's "separate opt-in by category" best practice.
   - Counsellors call every form-filler the same day or next day, since Meritto shows 2x conversion for same-day response.
   - Ask for a slot timed to 28 Nov-12 Dec, when DB exam windows close (Q4).
2. **Ambassador peer selling.**
   - One ambassador per branch-section. Each runs a branch WhatsApp sub-group within a Tech Drona Community, but only for students who opted in at a workshop or via a form.
   - Pay per confirmed payment (₹150-1,000 market band from the earlier notes) plus a session-organising fee.
   - Ambassadors must not mass-add classmates to groups. That risks blocks and reports, which WhatsApp says can throttle the business.
3. **Referrals.**
   - "Bring a friend" gives both students ₹200-500 off, or cashback after the referred student pays.
   - Add a 3-friend group price (see Q3).
   - Trigger the ask at the payment confirmation screen and on day 3 of the course, when satisfaction is highest [ASSUMPTION].
4. **WhatsApp.**
   - Use the free WhatsApp Business app for 1:1 counselling chats.
   - Use a Community announcement channel for batch updates.
   - Use the API with approved templates only for opted-in broadcast reminders. Budget about ₹0.86 per marketing message: 5,000 leads × 6 reminders ≈ ₹26,000.
   - Use utility templates (about ₹0.115) for payment receipts and batch confirmations.
5. **Instagram.**
   - Twice-weekly reels in Telugu-English mix, e.g. "3 projects that got a Guntur student shortlisted", with written consent per CCPA. Also "exam-over, now what?" content timed to 27-28 Nov.
   - Collaborate with college fest and club pages only with the student admins' agreement.
   - Instagram's role is social proof and retargeting, not primary acquisition.
6. **Telegram.**
   - A free resource channel (notes, interview question banks) as a lead magnet. Telegram leads convert like other digital leads, about 1%.
7. **Clubs, IEEE/CSI chapters, hackathons.**
   - Offer a free mini-hackathon or "build-a-thon" judged by the Tech Drona trainer, with prize scholarships of 50-100% off for the top 3. Every participant gets a time-boxed discount.
   - Treat these as volume and lower intent, per Meritto's aggregator finding.
8. **Parents.**
   - A one-page Telugu PDF or voice note for students to forward. It covers what the course is, the fee and EMI, the refund policy, trainer credentials and a no-guarantee placement-support statement.
   - Hold a 15-minute parent call on request, and a Sunday Telugu Zoom for parents in weeks 4-7.
   - This is a plausible lever: engineering choice is parent-influenced (Deccan Herald, opinion), and fee payment for students usually involves family. It is unquantified.
9. **Telugu.**
   - Use Telugu for hooks, explanations, parent material and counselling calls. Keep technical terms, certificates and course content in English, per the "industry still needs English" finding.

**Compliance rules for the ambassador network [ASSUMPTION, from cited rules].**
- No calls or SMS to students who have not opted in.
- No bought, scraped or college-roster lists.
- Promotional SMS only via a DLT-registered header and template.
- Scaled outbound promotional calling only from a registered 140-series number. Counsellors call opted-in leads 1:1.
- A suppression list for opt-outs.
- No "100% placement" or "guaranteed job" wording anywhere, including ambassador WhatsApp forwards. Use "placement support" with a stated scope.
- Testimonials only with written consent.
- Written TPO/principal permission for every on-campus session. Avoid any arrangement that looks like the college co-branding a credential, given the UGC/AICTE franchise warnings.

### Gaps
- No numeric channel comparison for AP engineering students. No AP-specific social-media usage study.
- No survey on parents' role in paying for upskilling courses in AP.
- No AICTE/UGC/APSCHE/JNTUK circular found on commercial promotion inside campuses; the rules are gatekept college by college. Ask each TPO for the college's own policy.
- Exact Meta India marketing rate and Community limits were confirmed only via vendor pages citing Meta and the Help Center. Verify in the Meta Business Manager rate card.

## Q3. Price sensitivity, guarantees, certificates, EMI; counselling and payment conversion

### Takeaway
Observed student prices for short skill courses cluster at **₹3,000-5,000**, with longer programmes at ₹35,000-40,000. Free NPTEL plus a ₹1,000 exam fee anchors the low end. No AP willingness-to-pay study exists. The only EMI uplift figure, 20-30% for premium courses, is unsourced. EMI matters mainly above about ₹10,000. "Placement guarantee" claims are legally risky under the CCPA 2024 guidelines. A transparent placement-support scope, a refund window and an industry-recognised project or certificate are the safe substitutes.

### Cited Findings
- Student-reported prices (Maharashtra/Karnataka): Apna College ₹5,000; a 4-month Agentic AI certificate ₹3,000; a 10-week DS/ML course ₹3,000; 6-month programmes ₹35,000-40,000. [ANECDOTAL journalism] — [Careers360](https://news.careers360.com/btech-courses-civil-mechanical-cse-it-engineering-students-pay-online-skill-education-syllabus-faculty-aicte-jobs-industry-gap-nep)
- NPTEL courses are free, with a certification exam fee of about ₹1,000. [JOURNALISM] — [Careers360](https://news.careers360.com/btech-engineering-online-courses-nptel-swayam-research-phd-ai-data-science-ml-iot-iit-kharagpur-madras-job-placement-abc-aicte-ugc/amp)
- EMI:
  - "EMI options for premium courses increase conversion 20-30%", with no method given. [BLOG, unsourced] — [productgrowth.in](https://productgrowth.in/insights/edtech/edtech-monetization-models-india/)
  - Fibe, a lender, reports 72% of respondents willing to take EMI for ed-tech upskilling. [VENDOR survey, conflicted] — [The Statesman tag page](https://www.thestatesman.com/tag/fibe-report)
- No-cost EMI is typically funded by the merchant through an interest-equivalent discount. ICICI's ed-tech offer gives the cardholder an "instant discount equal to interest charged". [OFFICIAL bank offer page] — [ICICI](https://www.icici.bank.in/offers/byju-offer)
- CCPA final guidelines (13 Nov 2024) ban false "100% job security" or selection claims and misrepresenting fees or refunds. [OFFICIAL via press] — [Careers360](https://news.careers360.com/centre-issues-coaching-centres-guidelines-jee-neet-upsc-cuet-2025-crack-down-on-misleading-ads/amp)
- Deadline pressure raises free-to-paid from 2-5% to 8-15% (exam-prep analogy). [BLOG] — [productgrowth.in](https://productgrowth.in/insights/edtech/free-to-paid/)
- Market ambassador commissions are ₹150-1,000 per confirmed enrollment, with some paying only after the full fee is paid. [OPERATOR listings] — [Jobaaj/IMAV](https://www.jobaaj.com/job/imav-learning-academy-campus-ambassador-commission-based-india-0-to-1-years-1245242); [origennt](https://origennt.com/campus-ambassador.html); [Career Craft](https://careercraftinstitute.in/campus-ambassador/)

### Inferences
**Pricing ladder [ASSUMPTION].** The Tech Drona course and price are not in the DB (`courses` is empty), so confirm them first.
- If the list price is at most ₹5,000: early-bird about 20% off until 30 Nov ("pay now, start after exams").
- Group-of-3 price: about 15% off each, with the trio paying together.
- Ambassador-referral code: about ₹300 off.
- Split payment: 2 UPI instalments, 50% now and 50% at week 3.
- No lender EMI below about ₹10,000. Credit checks and paperwork cost more conversion than they add.
- If the list price is above ₹10,000: add no-cost EMI through a card or NBFC partner (Tech Drona absorbs the interest) or a 3-part in-house instalment. Expect conversion toward the low end of the Q1 ranges.

**Placement messaging.** Use "placement support":
- resume review
- 2 mock interviews
- a curated job/referral board
- a demo-day project

State the limits in writing. Never promise "guaranteed placement" or "100% placement" (CCPA). A refund window (e.g. full refund within 7 days of batch start) reduces risk for parents. Count refunds against the 400.

**Certificates.** A Tech Drona certificate plus a GitHub-hosted capstone is more credible than a logo certificate. Any partner-brand certificate must be accurately described (CCPA prohibits misrepresentation).

**Counselling script (10-15 minutes, Telugu or English as the student prefers) [ASSUMPTION]:**
1. Status: year, branch, exam end date, placement status.
2. Goal: target role or company.
3. Gap: what interviewers ask that the student can't yet show.
4. Fit: map the course modules and project to that gap.
5. Logistics: batch date (post-exam), timings, offline or online.
6. Fee and options: early-bird, group, instalment.
7. Parent check: offer the Telugu parent PDF and a parent call.
8. Close: UPI link now, or a token of ₹500 to hold the seat, with the balance before batch start.

Log the disposition the same day.

**Payment conversion mechanics [ASSUMPTION].**
- Use a UPI payment link or QR with auto-receipt, plus a WhatsApp utility template for confirmation (₹0.115 per message).
- Make the token-to-full window 7 days. Chase on days 1, 3 and 6, then release the seat.
- An enrollment counts as confirmed only on full fee, or first instalment plus a signed instalment consent, net of refunds.
- Send a confirmation pack within 1 hour: receipt, batch WhatsApp community link, orientation date, refund policy.

### Gaps
- No AP or Telugu-state willingness-to-pay data.
- No independent study of EMI, early-bird or group-discount lift in Indian ed-tech.
- No data on how placement-support claims or certificates affect conversion.
- I found no source on UPI's share of student ed-tech payments, so it is not quantified here.
- Tech Drona's actual course list and prices are not recorded in the portal DB.

## Q4. Week-by-week execution calendar, 3 Nov - 31 Dec 2026, and validation of the milestones

### Takeaway
The DB confirms that the bulk of target colleges sit end-semester exams until **26 Nov (3-1) and 27 Nov (4-1)**. **Lab externals are undated**, so selling in November is pre-selling only. The earlier milestones need adjusting:
- 30 by 24 Nov is a **stretch**. Plan for 20-25, coming mostly from early-exam colleges and "pay now, start after exams" early-bird.
- 145 by 8 Dec is **aggressive**. Plan for about 125-135, given a 3-10 day payment lag after workshops in the week of 30 Nov.
- 305 by 22 Dec is **achievable but tight**.
- 400 by 31 Dec depends on a hard batch-start deadline (e.g. a 4 Jan batch) to pull about 95-100 payments into the Christmas week.

### Cited Findings
**DB exam data** (read-only query of `exams`, 256 rows):

| Semester | End-sem ends 24-30 Nov | Ends 11-23 Nov | Ends ≤10 Nov | Ends in Dec | No dates | 2027 |
|---|---|---|---|---|---|---|
| 4-1 | 76 rows (68 on 27 Nov, 6 on 28 Nov) | 5 | 1 | 4 | 41 | 1 |
| 3-1 | 66 rows (56 on 26 Nov, 9 on 28 Nov) | 5 | 1 | 2 | 52 | 2 |

- JNTUK rows: Mid-II on 9-13 Nov (3-1) and 9-14 Nov (4-1), per the revised timetable of 29 Oct 2026. Lab externals are "postponed to after theory exams; no dates yet" (CoE notice, 29 Oct 2026).
- Early finishers: Amrita (4-1 ended 4 Nov, 3-1 ends 6 Nov) and Aditya EC (4-1, 2-21 Nov, Unverified). AKNU ends 17-18 Nov. Several autonomous colleges end on 21 or 23 Nov.
- December exams:
  - Bapatla EC 4-1, 1-11 Dec, with SEE practicals from 14 Dec
  - SRKR 4-1, 24 Nov-5 Dec
  - Sasi (SITE) 4-1, 21 Nov-3 Dec; 3-1, 30 Nov-12 Dec
  - Vikas CET 3-1, 30 Nov-9 Dec
  - Krishna University 3-1 from 2 Dec
  - **SAHE 4-1 from 12 Dec (end not recorded)**
  - ANGRAU Food Science 4-1, 14-22 Dec

  SAHE's 12 Dec date conflicts with treating SAHE as open through December.
- Large universities (KL/KLEF, VIT-AP, SRM AP, Chalapathi, GGU) show "No Current Exams Found", meaning dates are unknown.
- The JNTUK 2026-27 proposed calendars give 4-2 internship/project from 30 Nov, 2-1 end exams 23 Nov-5 Dec with 2-2 classes from 7 Dec, and 1-1 end exams 31 Dec 2026-13 Jan 2027. [UNOFFICIAL-MIRROR] — [jntufastupdates 4-1](https://www.jntufastupdates.com/jntuk-4-1-4-2-academic-calendar-2026-27/); [2-1](https://www.jntufastupdates.com/jntuk-2-1-2-2-academic-calendar-2026-27/); [1-1](https://www.jntufastupdates.com/jntuk-1-1-1-2-academic-calendar-2026-27/)
- Sankranti 2026: AP schools and colleges were off 10-18 Jan 2026 (9 days). [PRESS] — [Sakshi Post](https://www.sakshipost.com/news/andhrapradesh/ap-sankranti-holidays-2026-january-10-january-18-9-days-break-schools-colleges). For 2027, only unofficial calendars exist, putting Sankranti/Pongal around 14-15 Jan 2027. [UNOFFICIAL] — [officeholidays](https://www.officeholidays.com/countries/india/andhra-pradesh/2027); [calendarlabs](https://www.calendarlabs.com/andhra-pradesh-state-holidays-2027/)
- Same-day follow-up doubles conversion. [VENDOR, large sample] — [The Wire/PTI](https://m.thewire.in/article/ptiprnews/ai-led-discovery-converts-6x-better-than-digital-reveals-merittos-enrollment-index-2026)

### Inferences
**Calendar** [ASSUMPTION for every weekly target; dates from the DB and the sources above]. Weeks start Tuesday 3 Nov to match the brief's "weeks of 3 Nov … 29 Dec".

| Week | Academic context (DB/sourced) | Recruitment and training | Campaigns and workshops | Checkpoint | Weekly paid (cum.) |
|---|---|---|---|---|---|
| **1: 3-9 Nov** | Short open window before Mid-II (9 Nov). Amrita done. Cyclone closures in Guntur on 3 Nov | Hire 30 college leads. Open ambassador applications via TPO/club heads and Instagram. Finalise course, price ladder and refund policy. DLT header/templates and WhatsApp Business setup. Draft Telugu parent PDF | TPO/HOD calls to the focus-30 (cadence from the earlier report), asking for (a) a 15-minute pre-exam "intro + opt-in" slot this week if possible and (b) a 60-90 minute workshop slot 28 Nov-12 Dec. Amrita workshop. Launch the Telegram resource channel | 30 leads hired. ≥20 TPO conversations. Exam calendar confirmed for the 13 unknown top colleges | 3 (3) |
| **2: 10-16 Nov** | Mid-II (JNTUK 9-14 Nov). AKNU/autonomous end-sems start | Select about 170 ambassadors (one per branch-section). 2-hour online training: product, script, compliance do's and don'ts, referral codes, leaderboard | Ambassador opt-in drive: a "post-exam placement sprint" waitlist form, no hard selling during exams. Two reels a week. **Early-bird opens** ("pay ₹X now, batch starts after exams"). One evening webinar for 2nd/3rd-years (low priority) | ≥150 ambassadors onboarded. ≥1,000 waitlist opt-ins. ≥20 workshop slots booked | 5 (8) |
| **3: 17-23 Nov** | Peak end-sem (JNTUK 4-1 16-27 Nov, 3-1 17-26 Nov). Aditya/AKNU/some autonomous colleges finish 18-23 Nov | Ambassador check-in. Mark ambassadors with zero opt-ins as at-risk | Workshops at early finishers: Aditya, AKNU, autonomous colleges ending 21-23 Nov, Amrita follow-ups. Counsellors call the waitlist in Telugu/English, briefly, without disturbing exam prep. **Early-bird deadline reminder** | Slots booked for ≥25 of 30 colleges. Contact rate for opted-in leads measured | 14 (22) |
| **4: 24-30 Nov** | JNTUK end-sems end 26-27 Nov. Lab externals undated. 4-2 internship from 30 Nov (unofficial) | Ambassador "exam-over" kit: reel template, WhatsApp copy, parent PDF | **"Exams over: placement sprint" launch on 27-28 Nov**: reels and Community announcements. Workshops from 28 Nov (Saturday) at reopened colleges (NEC, RVR&JC, SRGEC, LBRCE, CIET per the earlier report). **Early-bird closes 30 Nov** | Checkpoint A (1 Dec): if fewer than 20 colleges have booked a session, activate the reserve colleges (ranks 31-40) and the 3-1 cohort | 28 (50) |
| **5: 1-7 Dec** | Workshop peak. Lab externals likely somewhere here (undated). SITE, SRKR, BEC (1-11 Dec), Vikas, Krishna Univ still examining | Weekly leaderboard. First commission payout (confirmed payments only) | 12-15 in-college workshops (target about 1,100 attendees). Same-day counselling calls. Group-of-3 offer. Parent Telugu Zoom on Sunday 6 Dec | Workshop yield measured (attendee → lead → paid). Re-forecast | 80 (130) |
| **6: 8-14 Dec** | 2-2 classes start 7 Dec (unofficial). SAHE 4-1 exams from 12 Dec. BEC SEE practicals from 14 Dec | Prune inactive ambassadors (zero opt-ins after 4 weeks) and backfill from top referrers | 12-15 workshops: SITE and SRKR now open, KL/VIT-AP/VFSTR if dates allow. **Referral wave 1**: paid students get a bring-a-friend code. Mini-hackathon at 2-3 colleges with IEEE/CSI chapters | Checkpoint B (15 Dec): if trailing 2-week rate × weeks left < remaining, stop opening new colleges and move counsellors to referrals and re-engaging Registered/Interested leads | 85 (215) |
| **7: 15-21 Dec** | Mostly open. ANGRAU and SAHE exams | Ambassador bonus sprint, e.g. double commission for ≥3 confirmations this week | 8-10 workshops, mainly catch-up colleges and second sessions at top performers. Referral wave 2. Second parent Zoom. "Batch closes 31 Dec" countdown | Run-rate ≥ 80/week? | 85 (300) |
| **8: 22-28 Dec** | Christmas (25 Dec). Students travelling; campus attendance thin | Ambassadors work 1:1 and home-town WhatsApp | No campus sessions. 2 online webinars ("last batch of 2026"). Counsellor blitz on every Registered/token-paid and Interested lead | Daily tracking of token → full conversion | 70 (370) |
| **9: 29-31 Dec** | 1-1 end exams start 31 Dec (unofficial) | Final payouts computed | **Hard deadline 31 Dec**: "seat-hold and early pricing end". Batch starts 4 Jan, ahead of Sankranti (about 14-15 Jan 2027) | Close at 400 net of refunds | 30 (400) |

**Milestone validation against the earlier plan:**

| Date | Earlier plan | This plan | Verdict |
|---|---|---|---|
| 24 Nov | 30 | about 22-25 | Stretch. Only about 7% of DB 4-1 rows end before 24 Nov, so most of the pool is mid-exam. |
| 1 Dec | (not set) | about 50-60 | New checkpoint |
| 8 Dec | 145 | about 125-135 | Revise down. First mass workshops are 28 Nov-5 Dec, with a 3-10 day pay lag. 145 is reachable only if early-bird pre-sales exceed about 40. |
| 15 Dec | (not set) | about 215-220 | New checkpoint |
| 22 Dec | 305 | about 300-305 | Keep |
| 31 Dec | 400 | 400 | Keep, conditional on a hard batch deadline and a strong token-to-full process |

**Resource check.** Weeks 5-7 need about 35-40 workshops reaching about 3,500-4,000 attendees, matching the about 4,200 attendees from Q1. That works out to about 1.2 workshops per focus college, so the 30 leads must each secure at least one slot, and the top 10 colleges two [ASSUMPTION].

**Monitoring cadence.**
- Daily: funnel counts by stage and channel, and payments.
- Weekly on Monday: burn-up against the milestone table, plus per-college and per-ambassador leaderboards.
- Formal checkpoints: A on 1 Dec and B on 15 Dec, as in the earlier report.

### Gaps
- Lab-external dates for JNTUK colleges are undated in the DB. They could take 2-5 days of the 30 Nov-12 Dec window.
- 41 of the 4-1 rows have no dates, including KL, VIT-AP, SRM AP, Chalapathi and GGU.
- The 4-2 internship start (30 Nov) and 1-1 exam dates come only from unofficial calendars.
- No official 2027 Sankranti dates.
- No data on how much Christmas week depresses conversion.

## Q5. Contingency plays for underperforming colleges or ambassadors

### Takeaway
Use leading-indicator triggers (slots booked, opt-ins, counselled leads) rather than waiting for paid counts. Pre-commit reserve colleges and reallocation rules. The earlier report's reserve list is ranks 31-40: MVR, KITS Akshar, CRR, PCE, VNITSW, VSM, Vikas CET, RCE, MIC and Amrita Sai. Re-engaged leads are the cheapest recovery pool: Meritto puts them at 3% vs 0.74% for first-timers.

### Cited Findings
- Re-inquired leads convert at 3.00% vs 0.74% for first-time inquirers, and make up 40% of enrollments from 14% of volume. [VENDOR, large sample] — [The Wire/PTI](https://m.thewire.in/article/ptiprnews/ai-led-discovery-converts-6x-better-than-digital-reveals-merittos-enrollment-index-2026)
- Internshala notes some ambassadors are "inactive from day 1". [OPERATOR, 2017] — [Internshala](https://internshala.com/blog/?p=15482)
- IMAV requires 3 confirmed enrollments a month to remain active. [OPERATOR] — [Jobaaj](https://www.jobaaj.com/job/imav-learning-academy-campus-ambassador-commission-based-india-0-to-1-years-1245242)
- The 2026 AP Sankranti break was 10-18 Jan, which is useful if the deadline has to slip into a January cohort. [PRESS] — [Sakshi Post](https://www.sakshipost.com/news/andhrapradesh/ap-sankranti-holidays-2026-january-10-january-18-9-days-break-schools-colleges)

### Inferences
These are playbook rules [ASSUMPTION].

| Trigger | Play |
|---|---|
| College has no workshop slot by 24 Nov | Escalate from TPO to principal/HOD with a placement-prep pitch: free mock test, resume clinic. Offer an off-campus session at a nearby venue or an online session pushed by ambassadors. If still nothing by 1 Dec, move its target to a reserve college in the same district. |
| Workshop attended but attendee → paid < 2% after 7 days | Re-run the counselling list with a senior counsellor in Telugu. Add a group-of-3 offer, a parent call and a 48-hour deadline. Check whether the pitch included a live project demo. |
| Ambassador with zero opt-ins after 2 weeks, or zero confirmations after 4 | Pause commissions and reassign their section to a top performer or a paid student turned referrer. Keep the certificate for those who stay active. |
| Ambassador fraud signals (self-referrals, fake numbers, mass-adding to groups) | Dedupe on normalised mobile (earlier report). Pay only after the refund window closes. Remove from the programme. A WhatsApp block/report spike risks throttling the business account. |
| College exam dates move (lab externals) | Swap that week's slot with a college that is open. Keep a 5-college "ready now" standby list from the DB. |
| Network-wide run-rate below plan at Checkpoint B (15 Dec) | Freeze new-college outreach. Put all counsellors on Registered, Interested and token-paid leads. Run referral double-reward. Run 2 online webinars for 2nd/3rd-years. Extend early pricing only to existing leads, not publicly. |
| Below 370 on 28 Dec | Offer a "January Sankranti batch" (starting after about 18 Jan) to those who cannot pay in December, and report it separately. Do not count it toward 31 Dec. Ask parents directly via the PDF and call. |
| Price objection dominant (>40% of "not interested" reasons) | Introduce a 2-instalment UPI split, or a lighter tier (e.g. a 4-week module at a lower price) as an entry offer that does not discount the flagship. |

### Gaps
- No published data on ambassador-programme recovery tactics or reactivation rates.
- The reserve colleges' exam dates and contacts were not re-verified in this session.
