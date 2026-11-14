# Management hierarchy, span of control, performance tracking and enrollment-fraud controls (Tech Drona ambassador network, coastal AP, 400 paid enrollments by 31 Dec 2026)

Labels used below: **[Sourced]** = backed by a cited source; **[Portal DB]** = read from `portal/data/techdrona.db` on 3 Nov 2026 (read-only query); **[Portal contract]** = from `portal/CONTRACT.md` or server code; **[Assumed]** = design choice or planning figure with no external source. Do not quote assumed figures as findings.

## Q1. What spans of control are typical for sales/field teams and volunteer/student networks?

### Takeaway
No single "right" span exists. Field sales and inexperienced reps sit at the low end (about 5–8 per manager). The wider 8–12 range fits inside sales, simple products and tenured reps. Emergency-management doctrine for temporary, fast-forming teams uses 3–7 (optimum 5). No source gives an ambassadors-per-coordinator ratio for campus programmes. Our recommendation is 1 College Lead to 4–6 ambassadors and 1 District/City Lead to 5–7 colleges. These are labelled assumptions, derived from the sourced ranges.

### Cited Findings
- The average first-line sales manager has 8.5 direct reports, but spans range from 2 to 38. Field sales models usually need lower spans than inside sales, and in-person inside-sales supervision supports 20%–80% more reps per manager. FLSMs spend on average 16% of their time coaching, against a best practice of 28%. — [Alexander Group](https://www.alexandergroup.com/insights/what-is-the-right-span-of-control-for-first-line-sales-managers-flsms/)
- Spans should be smaller when reps are recent graduates or less experienced, when the manager also carries a quota (player-coach), and when reps generate their own leads. Strong tools and well-defined processes allow larger spans. — [Alexander Group](https://www.alexandergroup.com/insights/what-is-the-right-span-of-control-for-first-line-sales-managers-flsms/)
- In the 2020 Redpoint GTM survey (507 respondents), the average span of control was 4.7 and the most common was 3. Teams with 7 or fewer reps had markedly better quota attainment: about 18% of teams with a span of 7 or less attained under 50% of quota, versus roughly double that for teams above 7. The author notes this is correlation, not causation. — [Tomasz Tunguz](https://www.tomtunguz.com/how-should-you-structure-your-sales-team-for-success/)
- FEMA's NIMS/ICS doctrine says a supervisor's span of control should be 3 to 7 subordinates, optimally no more than 5. The same doctrine notes that real incidents often need different ratios and that the fix is to add teams, divisions or groups. — [FEMA IS-200.c](https://emilms.fema.gov/_is0200c/groups/53.html); [FEMA IS-200.c Modular Organization](https://emilms.fema.gov/is_0200c/groups/55.html)
- Volunteer management: there is "no specific rule of thumb" for volunteer/staff ratios, and supervision needs rise with the intensity of volunteer duties. Quoted ratios range from 12:1 to 100:1 depending on the organisation. — [Energize Inc. (book excerpt)](https://www.energizeinc.com/a-z/book-excerpt/11739)
- A county HR review cites general best practice of 1:5 to 1:10 managers to staff, and says reliable research is hard to find. — [Multnomah County span of control report, Jan 2026](https://multco.us/file/span_of_control_final_report_january_2026/download)
- Campus ambassador practice: one guide suggests piloting with about 2–5 ambassadors per target campus. A campus-ambassador programme deck targets 5–8 per campus. — [Loop](https://loop.fans/blog/how-to-find-and-manage-campus-brand-ambassadors); [SlideShare campus ambassador programme](https://www.slideshare.net/slideshow/campus-ambassador-program-final/60291398)
- Makai describes a campus programme manager who handles regional onboarding, audits weekly reporting and runs milestone reviews. It also describes a decentralised model where one or two high-performing students own a university territory. — [Makai](https://www.makaiinc.com/resources/the-complete-guide-to-building-a-student-brand-ambassador-program); [Makai decision guide](https://www.makaiinc.com/resources/in-house-vs-outsourced-student-ambassador-programs-a-decision-guide)
- Indian edtech inside-sales job postings put team leads over 10+ counsellors (iKounselor) and 8–12 sales executives or academic counsellors (Vedantu, though that role covers the USA/Canada region). These are job ads, not benchmarks. — [iKounselor posting](https://jobs.weekday.works/team-lead-%25E2%2580%2593-academic-counselling-conversions-at-ikounselor-ed-tech-wkdys8accl); [Vedantu posting](https://jobs.weekday.works/sales-team-lead-at-vedantu-4415749973)

### Inferences
- Campus ambassadors are part-time, inexperienced students who generate their own leads, and the team is new and short-lived. Every Alexander Group factor points to a small span, so the low end of the field range applies.
- **[Assumed] Recommended spans:**
  - Central Program Manager (CPM): 5–7 District/City Leads, within the FEMA 3–7 range.
  - District/City Lead (DCL): 5–7 colleges, each represented by its College Lead.
  - College Lead (CL): 4–6 ambassadors, consistent with the 2–5 and 5–8 per-campus practice figures.
  - The portal's `ambassador_lead` role is only needed where a college has more than about 7 ambassadors.
- Spans of 8–12 (edtech counsellor teams) apply to full-time, co-located inside-sales staff. They should not be used for a dispersed, part-time student network.

### Gaps
- I found no peer-reviewed or industry benchmark for ambassadors per campus coordinator, or for campus-ambassador conversion rates in India. The ratios above are reasoned assumptions.
- I found no published span-of-control data for Indian FMCG or insurance field forces (for example, sales officers per area sales manager, or agents per development officer). The searches returned only job ads.

## Q2. How should District/City Leads be sized given geographic clustering? (Portal DB counts)

### Takeaway
The portal DB holds 170 colleges across 11 targeted districts. 113 of them are marked operational, and every operational college is flagged as targeted. The Guntur–Vijayawada–Amaravati corridor (Guntur, NTR, Krishna, Palnadu, Bapatla) has 71 operational colleges and about 62% of the estimated eligible students. The Godavari belt (Kakinada, East Godavari, West Godavari, Eluru, Konaseema, Polavaram) has 42 colleges and about 38%. For a 30–45-college programme, 6 DCLs fit the sourced span ranges: 4 in the corridor and 2 in the Godavari belt.

### Cited Findings (all [Portal DB], read-only query, 3 Nov 2026)
| District | Colleges in DB | Operational | Eligible estimate (relevant branches, operational colleges) | Main city clusters (operational) |
|---|---|---|---|---|
| Guntur | 39 | 28 | 26,184 | Vadlamudi 2, Chebrolu 2, Chowdavaram 2, Pulladigunta 2, Budampadu 2, Chintalapudi (Tenali) 2, plus 16 single-college locations (Namburu, Neerukonda, Vaddeswaram, Mothadaka, Lam, Guntur, etc.) |
| NTR | 25 | 16 | 9,765 | Vijayawada 2, Paritala 2, Nunna 2, Jupudi 2, Enikepadu 2, Mylavaram, Kanchikacherla, Jaggayyapeta, Tiruvuru, etc. |
| Krishna | 14 | 11 | 6,024 | Machilipatnam 2, Kanuru 2, Gudlavalleru, Gudivada, Ganguru, etc. |
| Palnadu | 15 | 10 | 5,406 | Narasaraopet 6, Macherla 2, Kantepudi, Dhulipalla |
| Bapatla | 7 | 6 | 2,388 | Bapatla 4, Chirala 2 |
| Kakinada | 20 | 11 | 10,206 | Korangi 3, Surampalem 2, Kakinada 2, etc. |
| West Godavari | 16 | 9 | 7,854 | Bhimavaram 4, Tadepalligudem 2, etc. |
| East Godavari | 14 | 7 | 5,778 | Rajanagaram 3, Rajamahendravaram, etc. |
| Eluru | 10 | 8 | 3,120 | Eluru 3, Nuzvid 2, etc. |
| Konaseema | 8 | 5 | 3,066 | Ramachandrapuram 2, etc. |
| Polavaram | 2 | 2 | 264 | (new district id in the DB; not in CONTRACT.md's fixed list) |
| **Total** | **170** | **113** | **80,055** | |

- "Eligible" is the portal's relevance-weighted final-year figure. Its basis is mostly `estimated` (intake × relevance factor: it_core/it_allied 1.0, circuit 0.6, core/other 0.15), not verified. — [Portal DB settings `relevance_factors`; CONTRACT.md branches schema]
- Corridor (Guntur + NTR + Krishna + Palnadu + Bapatla): 71 operational colleges, 49,767 estimated eligible (62%). Godavari belt: 42 operational colleges, 30,288 estimated eligible (38%). — [Portal DB]
- Current operational state: 0 people, 0 enrollments, 0 courses and 0 calls. There is 1 target row (state `ap` = 400, deadline 2026-12-31) and 434 college contacts. — [Portal DB]
- Span basis (CPM 3–7, optimum 5). — [FEMA IS-200.c](https://emilms.fema.gov/_is0200c/groups/53.html)

### Inferences
- **[Assumed] Allocation of a 36-college pilot** (inside the 30–45 band; pick colleges from the calling queue's high-priority tier). Split by eligible share: about 22 corridor and 14 Godavari colleges. 400 × 62% ≈ 248 corridor and ≈ 152 Godavari enrollments, if targets are set with `POST /api/targets/allocate method:'eligible'`.
- **[Assumed] Six DCL territories** (5–7 colleges each, built from the city clusters above so a lead can visit 2–3 campuses a day):
  1. Guntur South/Tenali: Vadlamudi, Chebrolu, Chowdavaram, Budampadu, Tenali, Ponnur.
  2. Amaravati/Mangalagiri: Namburu, Neerukonda, Vaddeswaram, Pedapalakaluru, Nagarjuna Nagar.
  3. Vijayawada/NTR + Krishna: Vijayawada, Nunna, Enikepadu, Kanuru, Paritala, Gudlavalleru, Machilipatnam.
  4. Palnadu + Bapatla: Narasaraopet (6 colleges in one town), Bapatla, Chirala.
  5. Kakinada–Rajahmundry: Korangi, Surampalem, Kakinada, Rajanagaram, Rajamahendravaram, Ramachandrapuram.
  6. West Godavari–Eluru: Bhimavaram, Tadepalligudem, Eluru, Nuzvid.
- With 6 DCLs the CPM span is 6, which falls in the FEMA 3–7 range. If the pilot grows to 45 colleges, use 7 DCLs (split Guntur further) rather than going above about 7 colleges per DCL.
- **Headcount [Assumed]:** 1 CPM + 6 DCLs + 36 College Leads + about 144–216 ambassadors (4–6 per college). Ambassador leads are needed only at large colleges such as the Guntur deemed universities.
- **Pace [Portal-derived arithmetic]:** 3 Nov–31 Dec is 59 days including today. 400 ÷ 59 ≈ 6.8 confirmed enrollments per day, or about 47 per week. That works out to about 11 per college over the sprint, or about 2–3 per ambassador.

### Gaps
- Drive times between clusters were not measured. Territory boundaries should be checked against real travel time.
- The new `polavaram` district slug exists in the DB but not in CONTRACT.md's fixed district list. The contract asks for any such slug to be reported.

## Q3. Responsibilities, KPIs, review cadence and escalation triggers per role

### Takeaway
Use a three-tier rhythm: a short daily huddle at college level, a weekly pipeline review at district level, and a weekly programme review run by the CPM. Hold everyone to funnel KPIs, with only gateway-confirmed payments counting. Escalation triggers should be numeric and written down in advance. The cadence pattern is sourced; the specific trigger thresholds are assumptions.

### Cited Findings
- Field sales operating rhythm: a 10–15 minute daily huddle before reps go out, a 30–45 minute weekly sync covering metrics, pipeline and short training, plus monthly and quarterly reviews. Sources disagree on whether metrics belong in the daily huddle. One argues daily stand-ups cost about 60 hours per rep a year. — [Spotio](https://spotio.com/blog/sales-meeting-agenda/); [Prospeo](https://prospeo.io/s/sales-operating-rhythm); [Sales Xceleration](https://salesxceleration.com/fractional-vp-of-sales-operating-cadence-weekly-meetings-monthly-reviews-quarterly-resets/)
- A forecast cadence of at least weekly is suggested for high-velocity or SMB-type sales. — [RevEngine](https://revengine.substack.com/p/setting-up-your-operating-cadences)
- A campus programme manager should audit weekly reporting and run milestone reviews. — [Makai](https://www.makaiinc.com/resources/the-complete-guide-to-building-a-student-brand-ambassador-program)
- The portal already defines pace as `expected_now = target × elapsed/total` and `on_track = enrolled ≥ 0.8 × expected_now`. It applies a diagnosis order of ambassador_gap → low_outreach (reached < 3 × target × elapsed fraction) → low_conversion (enrolled/reached < 5%) → unrealistic_target (> 50% of eligible) → behind_pace. — [Portal contract]
- Coaching time matters: managers average 16% of their time coaching against a 28% best practice. — [Alexander Group](https://www.alexandergroup.com/insights/what-is-the-right-span-of-control-for-first-line-sales-managers-flsms/)

### Inferences — role design [Assumed unless marked]
| Role | Count | Responsibilities | KPIs | Cadence | Escalates to |
|---|---|---|---|---|---|
| Central Program Manager | 1 | Owns the 400 target and course/pricing; sets and allocates targets; recruits DCLs; owns payment reconciliation, the fraud/attribution ruling and payouts | Confirmed vs pace (portal `target-dashboard`); projection date; DCL target %; refund/drop rate; duplicate/dispute count | Weekly 60-min programme review (Mon); daily 10-min dashboard check; fortnightly target re-allocation | Leadership |
| District/City Lead | 6 (5–7 colleges each) | Appoints and supports College Leads; campus visits; TPO/HOD relationships (portal calls/contacts); exam-window planning; first-line dispute resolution | District confirmed vs pace; % colleges with an active CL and ≥4 active ambassadors; lead→confirmed conversion; follow-ups overdue | Weekly 30–45-min pipeline review with each CL (one call per college); 2–3 campus visits/day; Friday report to CPM | CPM |
| College Lead | 1 per college (36) | Recruits and coaches 4–6 ambassadors; runs campus sessions; logs activities; keeps enrollment stages current; checks for duplicates before recording | College confirmed vs target; leads added/week; follow-ups done; stage aging; ambassadors active (≥1 activity in 7 days) | Daily 10-min huddle (WhatsApp or in person: one win, one blocker, one commitment); weekly review with DCL | DCL |
| Campus Ambassador | 4–6 per college | Generates leads in assigned branch/section; follows up; shares referral code/payment link; never collects cash | Leads, follow-ups, registered, confirmed (paid), conversion lead→paid, target % | Daily update; weekly 1:1 with CL | CL |

**Escalation triggers [Assumed thresholds; mapped to portal fields where possible]:**
- Ambassador with 0 new leads or 0 logged activities in 7 days → CL check-in within 48 h. If still 0 by day 14, set the ambassador `inactive` and reassign their leads.
- Ambassador with ≥10 leads and 0 confirmed after 14 days → CL coaching session (conversion problem).
- College below 50% of linear pace (stricter than the portal's 80% `on_track` line) for 7 consecutive days → DCL visit plus root-cause check using the portal diagnosis (ambassador_gap / low_outreach / low_conversion / unrealistic_target / exams).
- District below 80% of pace at the weekly review → CPM reallocates targets (`/api/targets/allocate`) or moves ambassadors and budget.
- Programme projection date (portal `projection.date`) after 31 Dec for 2 consecutive weeks → CPM escalation to leadership (pricing, offer or extra colleges).
- Any lead stuck in `registered` or `applied` for more than 5 days → follow-up created for the owner.
- Exams: colleges with `exams_soon`/`in_exams` are paused (no pace penalty) and targets shift to clear colleges.
- Fraud signals (see Q5) go straight to the CPM and bypass the DCL.

### Gaps
- No sourced lead→paid conversion benchmark for Indian B.Tech paid courses. The portal's 5% `min_conversion` default is a setting, not evidence.
- The specific trigger thresholds (7 days, 50%, 5 days) are not drawn from any source.

## Q4. Performance dashboard spec (college-wise, ambassador-wise) and what the portal already supports

### Takeaway
About 70% of the dashboard already exists in the portal: the target dashboard, funnel, leaderboard by level, the people list with target/enrolled/pct, attention, and timeseries. The main missing pieces are per-ambassador stage counts, an activity-recency flag, follow-up counts per lead, payment/referral data, a district-lead role and a refund state.

### Cited Findings (all [Portal contract] / [Portal DB])
- `/api/target-dashboard?scope=` returns target, confirmed, remaining, pct, days_left, required_daily/weekly, confirmed_last_14d, current pace, projection date/status, funnel, contacts, calls, pending calls, followups_due and `people[]`. `people[]` is only the **top 10** leads/ambassadors by confirmed, with target and in-pipeline count.
- `/api/people?role=&college=&district=` returns each person with target, reached, enrolled, remaining, pct, on_track and next_followup. There are no per-stage counts.
- `/api/leaderboard?level=district|city|college|branch|person` returns target/enrolled/pct. `/api/funnel?scope=` returns stage counts. `/api/timeseries` returns daily enrolled/reached. `/api/attention` covers behind pace, ambassador gaps, overdue follow-ups, no lead appointed and exams soon.
- Enrollment stages: lead, interested, registered, applied, confirmed, dropped. Only `confirmed` counts toward targets. One row per student, moved through stages by PATCH (no copies).
- `people.role` allows only `college_lead | ambassador_lead | ambassador`. Every person has a single `college_id`. `reports_to` allows a chain.
- `targets` supports scope state/district/city/college/branch/person, and allocation down to ambassadors.

### Inferences — dashboard spec [Assumed design]
**College-wise table** (one row per targeted college; filters district/city/DCL):
- Target, confirmed (paid), pct.
- Expected-by-today, gap to pace.
- Leads, interested, registered, applied (pending = sum of open stages), dropped/refunded.
- Lead→confirmed conversion.
- Active ambassadors / total.
- Days since last activity.
- Follow-ups open/overdue.
- Exam state.
- Diagnosis.
- Most of this maps to `/api/colleges` plus `/api/funnel?scope=college:<id>`.

**Ambassador-wise table** (filter by college/DCL):
- Target, confirmed, pct.
- Leads added (7d / total), follow-ups done (7d), stage counts, oldest open lead age.
- Conversion lead→paid.
- Last activity date.
- Duplicate/dispute flags.
- Refunds/clawbacks.

**Programme header:** the existing target-dashboard tiles (confirmed/400, required vs current weekly pace, projection date), the funnel, and the DCL leaderboard.

### Gaps (portal changes needed; no code was changed)
1. **No District/City Lead or Program Manager role.** The `people.role` CHECK lacks them, and `people` has no `district_id`, so a DCL cannot be scoped to a district. Workaround: create the DCL as a `college_lead` with `reports_to` and a district-scoped target, but rollups will misattribute it.
2. **No per-person stage counts** in `/api/people`, and `target-dashboard.people[]` is capped at the top 10. The full ambassador-wise funnel table needs a new endpoint or field.
3. **No "days since last activity" per person**, and `/api/attention` has no "ambassador idle 7 days" reason.
4. **No follow-up link to an enrollment.** `followups.scope_type` is only college/branch/person, so per-lead follow-up counts can't be computed.
5. **No refund state.** The contract text says "dropped/refunded", but the stage CHECK has only `dropped`, and there are no `refunded_on`/`refund_amount` fields.
6. **No payment fields:** no gateway payment/order id, payment status, paid-at timestamp or reconciliation flag. `amount_inr` is free entry.
7. **No referral-code field** on people or enrollments, and no attribution source (ambassador code, walk-in, website).
8. **No courses yet** (0 rows). Course-level dedup and pricing depend on courses being created.

## Q5. Controls against duplicate/false enrollments and double counting

### Takeaway
Make the payment gateway the only thing that can move a record to `confirmed`. Deduplicate on normalised mobile plus course, and attribute each student to the first-registered referral code with a fixed protection window. Hold ambassador payouts until the refund window has closed, and claw back afterwards from future payouts. The portal already blocks same-mobile/same-course duplicates and stage double counting. It has no payment or referral data, and any user can mark a record confirmed.

### Cited Findings
- Razorpay webhooks are delivered at least once, so the same event can arrive more than once. The `x-razorpay-event-id` header is unique per event and should be used for idempotent handling. Failed deliveries are retried with exponential backoff for 24 hours. Events may arrive out of order. Signatures should be verified. — [Razorpay webhook best practices](https://razorpay.com/docs/webhooks/best-practices/)
- Razorpay says to rely on webhooks for automation, to make an immediate API fetch when a time-sensitive webhook has not arrived, and not to use `callback_url` as a substitute for webhooks when tracking payment status. — [Razorpay webhooks](https://razorpay.com/docs/webhooks/)
- Webhook signatures are HMAC-SHA256 over the raw body with the webhook secret, which differs from the checkout signature. A scheduled reconciliation job should list gateway payments and compare them to the database to catch missed events. — [DEV Community: Razorpay webhooks done right](https://dev.to/buildbyravirai/razorpay-webhooks-done-right-2026-signature-verification-idempotency-and-reconciliation-a9m) (third-party, consistent with Razorpay docs)
- Referral fraud patterns include self-referrals, duplicate or fake accounts, rings and copied personal details. Controls include one signup per identifier, multi-dimension rate limits, delaying rewards until payment or a milestone, idempotent reward issuance, written terms, and graduated enforcement (void and warn first, then suspend). One vendor claims fraud takes 5–15% of referral budgets (vendor claim, unverified). — [Prefinery](https://www.prefinery.com/blog/referral-fraud-types-and-prevention/); [Track360](https://www.track360.io/learn/refer-a-friend-program-design/preventing-referral-fraud); [Gravitee](https://gravitee.io/corpus/gen-2445/referral-marketing/referral-fraud-detection-and-rate-limiting.html); [Viral Loops](https://viral-loops.com/blog/fraud-in-referral-programs/)
- Velocity thresholds need headroom: a genuine referrer may bring 2–5 friends in a burst. — [Track360](https://www.track360.io/learn/refer-a-friend-program-design/preventing-referral-fraud)
- Attribution conflicts: channel programmes mostly use a written first-to-register rule, with an exclusivity window (one source says 90–180 days in B2B). The rule should be written down before the first dispute. — [Track360 deal registration](https://track360.io/learn/b2b-partner-and-channel-program-management/deal-registration-and-channel-conflict); [Tray.ai](https://tray.ai/automate/partner-deal-registration/); [Magentrix](https://www.magentrix.com/glossary/deal-registration)
- Clawbacks: hold commission at least as long as the refund window. Name the triggers explicitly (refund, cancellation, non-payment). Recover from future payouts, capped (QuotaPath suggests 25–50% of variable pay per cycle). Record a reversal as a negative event in the period it occurs rather than rewriting history. — [QuotaPath](https://www.quotapath.com/blog/fair-clawback-policies/); [QuotaPath playbook](https://www.quotapath.com/resource/clawback-policy-playbook/); [Sales Cookie](https://blog.salescookie.com/2019/06/13/how-to-implement-claw-backs)
- What the portal already enforces [Portal contract + `server/server.js` lines 311–317, `db.js` line 46]:
  - A second enrollment with the same normalised mobile (or lower-case email) and the same course returns 409 with `existing_id`.
  - Stage moves PATCH the same row, so funnel counts cannot double count.
  - Only `confirmed` rows count toward targets.
  - Every write is audited.

### Inferences — control set [Assumed design]
1. **Single source of truth for "paid":** a record becomes `confirmed` only when it carries a gateway `payment_id` with status captured/paid and the amount matches the course price. Run a daily reconciliation that lists gateway payments for the day and matches them to enrollments. Unmatched payments and confirmed rows with no payment go to an exceptions list for the CPM. Store `x-razorpay-event-id` to make processing idempotent. Ambassadors never collect cash.
2. **Unique student key:** normalised +91 mobile plus course, with email and college roll number as secondary keys. Require the mobile at `lead` stage, because the current check is skipped when `student_contact` is null. A later "student" with the same roll number but a different phone is flagged for review.
3. **Referral codes:** one immutable code per ambassador, embedded in the payment link (for example as order notes). Attribution follows the code on the captured payment. If there is no code, attribution goes to the first-registered lead owner within a protection window. **[Assumed: 21 days]**, because the 90–180-day B2B window is too long for an 8-week sprint. Disputes are ruled by the DCL within 48 hours, with CPM appeal. No split credit, since the schema has one `person_id`.
4. **Refund window and clawback:** pay ambassador incentives only after the course refund window closes (for example, weekly payout of enrollments confirmed more than 7 days earlier; the window length is **[Assumed]** and must match the published refund policy). Refunds after payout are deducted from the next payout. Record refunds as `dropped`/`refunded` with a date, never by deleting the row.
5. **Red flags for CPM review [Assumed thresholds]:**
   - The same payer account or card paying for 3 or more students.
   - Several enrollments from one ambassador within minutes.
   - A student whose mobile matches an ambassador's or lead's own phone (self-referral).
   - Enrollments from colleges outside the ambassador's assigned college.
   - Spikes just before payout cut-off.
   - High refund rate per ambassador.
6. **Permissions:** today `X-User` is a free-text name with an optional shared passcode. Anyone can set `stage='confirmed'`. Until gateway integration exists, only the CPM (or a named finance user) should confirm enrollments, checked against the gateway export.

### Gaps
- Portal dedup is application-level only. There is no unique DB index on `(student_contact_norm, course_id)`, though writes are single-process.
- The `course_id` NULL check is treated as "course 0". A lead saved without a course and later saved with course X is not detected as a duplicate.
- Mobile-versus-email normalisation means the same student recorded once by phone and once by email will not match.
- No gateway, payment-reference, referral-code, refund or role-based permission fields exist (see Q4 gaps).
- The course refund policy and actual payment gateway (Razorpay assumed for illustration) were not specified. Payout and clawback windows must be set from them.
- I found no Indian-specific (for example, edtech or insurance agent) published data on campus referral fraud rates. Vendor fraud percentages are marketing claims.
