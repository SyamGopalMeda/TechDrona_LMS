# Enrollment capacity of the Tech Drona college database and allocation of 400 confirmed enrollments by 31 Dec 2026

Reference date: 3 Nov 2026. The horizon is 4 Nov to 31 Dec 2026, which is 58 days or 8.29 weeks. Every figure below was computed by a read-only node script (`node:sqlite` `DatabaseSync`, `{readOnly:true}`) over the live DB. Seed files were cross-checked: the recomputed eligible estimate matched the DB `eligible_estimate` on all 578 numbered relevant branches (0 mismatches). The script is in the session scratchpad at `C:\Users\SYAM\AppData\Local\Temp\claude\c--Users-SYAM-Downloads-colleges-data-main-colleges-data-main\ed62faac-3ba3-484b-9f39-ef305ecac048\scratchpad\cap.mjs`. The full allocation table is saved next to these notes as `allocation_400.csv`: 578 branch rows across 107 colleges, columns for the full and focus-30 allocations, and both sums verified at 400.

Source shorthands used below:
- [DB] = [portal/data/techdrona.db](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/portal/data/techdrona.db) (tables colleges, branches, exams, districts, cities, settings, people, targets, enrollments)
- [CONTRACT] = [portal/CONTRACT.md](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/portal/CONTRACT.md)
- [BRANCHES] = [portal/data/seed/branches.json](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/portal/data/seed/branches.json)
- [EXAMCSV] = [BTech exam status 3-1 4-1 Nov 2026.csv](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/BTech%20exam%20status%203-1%204-1%20Nov%202026.csv) (same 256 rows as the DB `exams` table / exams.json)
- [TIERS] = [BTech colleges NAAC tiers Excel.md](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/BTech%20colleges%20NAAC%20tiers%20Excel.md)
- [PLACE] = [BTech colleges placements 2024 to 2026.md](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/BTech%20colleges%20placements%202024%20to%202026.md)
- [CSV400] = [allocation_400.csv](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/research_notes/Path%20to%20400%20enrollments%202026/allocation_400.csv) (output of this analysis)

Unless marked "verified", every student count is an **estimate**. 93.9% of the eligible pool rests on estimated intakes (see Q1).

## Q1. How big is the relevant student pool, and where is it?

### Takeaway
113 colleges are operational. They have 613 relevant branches (IT-core, IT-allied and circuit), and 578 of those carry a number. Those branches hold about **80,055 eligible final-year (4-1) students (estimated)** out of 87,975 final-year students. Only **4,920 (6.1%) rest on verified intake**. The pre-final (3-1) proxy is the same 80,055, because the data holds a single intake per branch. Guntur district alone has **26,184 (32.7%)** of the eligible pool.

### Cited Findings
- Colleges by status: 170 in total, **113 operational**, 49 possibly_closed, 7 pending (NVRCET, Sunflower CET, SFT JNTUK, VRS & YRN CET, MAMWEC, SAU, ACET) and 1 closed. All 113 operational colleges are flagged `targeted=1`. — [DB]
- The tier file lists 128 institutions as active for 2026-27 (8 Tier 1, 32 Tier 2, 88 Tier 3) — [TIERS]. The DB's later op_status review keeps only 113 as operational: Tier 1 8, Tier 2 32, Tier 3 72, untiered 1. — [DB]
- Autonomy among the 113 operational colleges: Yes 65, No 44, Unclear 3, blank 1. — [DB]
- Branches: 808 in total. 807 of them belong to operational colleges: it_core 149, it_allied 270, circuit 194 (**613 relevant**), core 180 and other 14 (194 non-relevant). — [DB]
- Estimate rules: final_year = intake_2023_24, else intake_per_year. eligible = final_year × relevance factor (it_core 1, it_allied 1, circuit 0.6, core 0.15, other 0.15). These factors are stored in `settings.relevance_factors`. — [CONTRACT], [DB]
- Relevant-branch totals in operational colleges (estimated): final-year students **87,975**, eligible **80,055**.
  - it_core: 149 branches, 31,695 final-year, 31,695 eligible.
  - it_allied: 270 branches, 36,480 final-year, 36,480 eligible.
  - circuit: 194 branches, 19,800 final-year, 11,880 eligible.
  - The non-relevant core/other branches add only 1,317 eligible (194 branches × 0.15 factor), so the DB grand total is 81,372.
  - — [DB]
- Intake basis behind the 80,055 eligible students: verified **4,920 (6.1%)** and estimated **75,135 (93.9%)**. 35 relevant branches are pending (no number).
  - Verified intake exists only at KL University (3,174, from the 2023-24 BoM approval), SAHE (1,068), Amrita Amaravati (480) and NIT AP (198).
  - 644 estimated branches are "derived from official CAP 2026 convener seats", which is a 2026-27 intake used as a proxy for the 2023 batch. Another 9 are "aggregator figure, year unspecified, low confidence".
  - — [DB], [BRANCHES]
- `intake_2023_24` is populated for only 9 branches, all at KL University (3,510 in total, equal to the NIRF total). For every other branch the final-year figure is the 2026-27 intake. — [DB], [BRANCHES]
- Eligible students by district (operational colleges with eligible > 0). The 3-1 proxy is identical in every district.

| District | Colleges | Relevant branches | Eligible 4-1 (est.) | of which verified | Share |
|---|---|---|---|---|---|
| Guntur | 26 | 152 | 26,184 | 3,654 | 32.7% |
| Kakinada | 11 | 56 | 10,206 | 0 | 12.7% |
| NTR | 16 | 94 | 9,765 | 0 | 12.2% |
| West Godavari | 9 | 62 | 7,854 | 198 | 9.8% |
| Krishna | 11 | 54 | 6,024 | 1,068 | 7.5% |
| East Godavari | 7 | 34 | 5,778 | 0 | 7.2% |
| Palnadu | 10 | 55 | 5,406 | 0 | 6.8% |
| Eluru | 6 | 29 | 3,120 | 0 | 3.9% |
| Dr. B.R. Ambedkar Konaseema | 5 | 26 | 3,066 | 0 | 3.8% |
| Bapatla | 4 | 25 | 2,388 | 0 | 3.0% |
| Polavaram | 2 | 6 | 264 | 0 | 0.3% |
| **Total** | **107** | **593 rows (578 numbered)** | **80,055** | **4,920** | 100% |

— [DB]. The branch column counts all relevant branches in these 107 colleges, including pending ones. Polavaram is a district id in the DB's 27-row districts table, beyond the contract's 26 ids.
- Concentration: the top 10 colleges hold 23,460 eligible students (29.3%), the top 20 hold 35,022 (43.7%), the top 30 hold 44,742 (55.9%) and the top 50 hold 60,090 (75.1%). — [DB]
- Leading towns by eligible students:
  - Surampalem (Kakinada, 2 colleges): 5,382
  - Rajanagaram (East Godavari, 3 colleges): 4,416
  - Narasaraopet (Palnadu, 6 colleges): 4,134
  - Bhimavaram (West Godavari, 4 colleges): 3,870
  - Mothadaka (Guntur, 1 college): 3,600
  - Vaddeswaram (Guntur, 1 college): 3,174
  - Vadlamudi (Guntur, 2 colleges): 2,850
  - Chowdavaram (Guntur, 2 colleges): 2,604
  - — [DB]
- Eligible students by department family (estimated):

| Department family | Branches | Eligible |
|---|---|---|
| CSE | 103 | 28,485 |
| AI / AI-ML (CSE-AIML, AI-ML, CSE-AI) | 115 | 21,420 |
| AI-DS / Data Science | 96 | 11,550 |
| ECE & allied (×0.6) | 112 | 9,351 |
| IT | 38 | 3,420 |
| EEE (×0.6) | 72 | 2,529 |
| Cyber Security / Blockchain | 21 | 1,860 |
| IoT | 11 | 720 |
| Other CSE-allied | 10 | 720 |

— [DB]
- The largest single branches are KL CSE 2,580 (verified), Aditya University AI-ML 1,320 (estimated), Aditya University CSE 1,320 (estimated), VFSTR CSE 1,200 (estimated) and Chalapathi University CSE 1,140 (estimated). — [DB]

### Inferences
- The 80,055 figure is an upper-bound style estimate. It assumes 2026-27 sanctioned or derived intake equals the number of 2023-batch students still enrolled in 4-1. Attrition, lateral entry and seat-fill below sanction are not modelled, so the true pool is probably smaller.
- The 3-1 cohort cannot be sized separately with this data: both proxies use the same intake field. Read "pre-final 3-1 = 80,055" as "same order of magnitude, unverified".
- Six of the 107 operational colleges contribute 0 eligible students only because their relevant intakes are pending, not because they lack relevant branches. SRM AP and VVIT University are among them (see Q6).

### Gaps
- No batch-specific (2023 or 2024 admission) intake or actual-strength data exists outside KL University.
- There is no seat-fill or attrition factor. NIRF graduate counts in [PLACE] cover only 19 colleges and were not linked to the branch table.

## Q2. Top 30 colleges by eligible students: profile and exam windows

### Takeaway
The top 30 hold 44,742 eligible students (55.9%). The four largest are Aditya University, Chalapathi, KL and GGU, all university-status and each above 2,800 eligible. For 71 of the 107 colleges with eligible students, the 4-1 end-sem window is known, and it clusters on **16–27 Nov** (JNTUK timetable, 54 colleges ending 27 Nov). Outreach to most final-years therefore reopens from **28 Nov**. Thirteen of the top 30, mostly deemed and private universities, have **no known 4-1 dates**.

### Cited Findings
Table columns:
- Eligible = 4-1 eligible students (estimated, except KL, SAHE and Amrita which are verified).
- 4-1 end-sem = the strict-date window in the DB.
- Open from = the day after the 4-1 end-sem ends. The contract's `outreach_from` is computed the same way.
- NAAC = the first token of the DB `naac` field. Most grades are aggregator-reported (see Q6).

| # | S.No | College | District / town | Tier | NAAC (reported) | Auto. | Eligible | Rel. br. | 4-1 end-sem | 4-1 evidence | 4-1 mid | Open from |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 106 | Aditya University | Kakinada / Surampalem | T2 | A++ | No | 4,140 | 5 | 2 Nov–21 Nov | Unverified (calendar) | 26–31 Oct | 22 Nov |
| 2 | 7 | Chalapathi University | Guntur / Mothadaka | T3 | — | No | 3,600 | 6 | unknown (No Current Exams Found) | Unverified | — | — |
| 3 | 1 | KL University | Guntur / Vaddeswaram | T1 | A++ | No | 3,174 (verified) | 6 | unknown (No Current Exams Found) | Unverified | — | — |
| 4 | 116 | GGU | East Godavari / Rajanagaram | T2 | A++ | No | 2,868 | 7 | unknown | Unverified | — | — |
| 5 | 4 | VIT-AP | Guntur / Inavolu | T1 | — | No | 2,064 | 11 | unknown | Unverified | — | — |
| 6 | 36 | NEC | Palnadu / Narasaraopet | T2 | A+ / A | Yes | 1,836 | 8 | 11–23 Nov | Officially confirmed | 26–31 Oct | 24 Nov |
| 7 | 2 | VFSTR | Guntur / Vadlamudi | T1 | A+ | No | 1,482 (4 branches pending) | 4 | "before 9 Dec (inferred)" | Unverified | — | — |
| 8 | 147 | SRKR | West Godavari / Bhimavaram | T2 | A+ | Yes | 1,476 | 10 | 24 Nov–5 Dec | Officially confirmed | 6–18 Nov | 6 Dec |
| 9 | 155 | SCET | West Godavari / Narsapur | T2 | A | Yes | 1,416 | 8 | 3–13 Nov | Officially confirmed | — | 14 Nov |
| 10 | 13 | KHIT | Guntur / Chowdavaram | T2 | A | Yes | 1,404 | 6 | unknown | Unverified | — | — |
| 11 | 32 | VLITS | Guntur / Vadlamudi | T2 | A+ | Yes | 1,368 | 7 | unknown | Unverified | — | — |
| 12 | 12 | KITS Guntur | Guntur / Vinjanampadu | T2 | A | Yes | 1,284 | 6 | unknown | Unverified | — | — |
| 13 | 107 | Pragati | Kakinada / Surampalem | T2 | A | Yes | 1,242 | 8 | unknown | Unverified | — | — |
| 14 | 82 | SRGEC | Krishna / Gudlavalleru | T2 | A+ | Yes | 1,236 | 7 | 16–28 Nov | Officially confirmed | 2–7 Nov | 29 Nov |
| 15 | 9 | RVR&JC | Guntur / Chowdavaram | T2 | A+ | Yes | 1,200 | 8 | 12–23 Nov | Officially confirmed | — | 24 Nov |
| 16 | 80 | SAHE | Krishna / Kanuru | T2 | — | No | 1,068 (verified) | 6 | "Upcoming", no dates | Officially confirmed (no dates) | — | — |
| 17 | 62 | LBRCE | NTR / Mylavaram | T2 | A | Yes | 1,056 | 6 | 16–28 Nov | Officially confirmed | 2–7 Nov | 29 Nov |
| 18 | 10 | CIET | Guntur / Lam | T2 | A | Yes | 1,044 | 8 | 12–28 Nov | Unverified (calendar) | 2–7 Nov | 29 Nov |
| 19 | 19 | MLWEC | Guntur / Pulladigunta | T2 | A+ | Yes | 1,032 | 4 | unknown | Unverified | — | — |
| 20 | 120 | ISTS | East Godavari / Rajanagaram | T3 | — | Yes | 1,032 | 6 | unknown | Unverified | — | — |
| 21 | 42 | TEC | Palnadu / Narasaraopet | T2 | A+ | Yes | 1,026 | 6 | unknown | Unverified | — | — |
| 22 | 153 | SVEC | West Godavari / Pedatadepalli | T2 | A | Yes | 1,014 | 8 | unknown | Unverified | — | — |
| 23 | 65 | MVR | NTR / Paritala | T3 | — | Yes | 1,008 | 6 | unknown | Unverified | — | — |
| 24 | 23 | NRIIT | Guntur / Visadala | T2 | A+ | Yes | 1,002 | 7 | unknown | Unverified | — | — |
| 25 | 152 | SITE | West Godavari / Tadepalligudem | T2 | A | Yes | 960 | 8 | 21 Nov–3 Dec | Officially confirmed | 9–14 Nov | 4 Dec |
| 26 | 156 | CRR | Eluru / Eluru | T3 | B / A | Yes | 960 | 6 | 16–27 Nov | JNTUK timetable | 9–14 Nov | 28 Nov |
| 27 | 33 | VNITSW | Guntur / Pedapalakaluru | T3 | — | Yes | 948 | 6 | 16–27 Nov | JNTUK timetable | 9–14 Nov | 28 Nov |
| 28 | 48 | BEC | Bapatla / Bapatla | T2 | A+ | Yes | 936 | 7 | 1–11 Dec | Officially confirmed | 16–21 Nov | 12 Dec |
| 29 | 125 | VSM | Konaseema / Ramachandrapuram | T3 | — | Yes | 936 | 5 | unknown | Unverified | — | — |
| 30 | 70 | Vikas CET | NTR / Nunna | T3 | — | Yes | 930 | 6 | 16–27 Nov | JNTUK timetable | 9–14 Nov | 28 Nov |

— [DB], [EXAMCSV], [TIERS]
- 4-1 exam status across the 107 colleges, with the eligible students each status covers:
  - "Upcoming" per the official JNTUK timetable (affiliation-based): 52 colleges, 22,155 eligible.
  - "Upcoming", officially confirmed: 10 colleges, 9,402.
  - "In Progress", officially confirmed: 5 colleges, 5,112.
  - "Unverified (calendar-planned)": 6 colleges, 7,890.
  - "Unverified": 4 colleges, 4,170.
  - "No Current Exams Found / Unverified": 28 colleges, 30,804.
  - "Conflicting": 1 college, 192.
  - No exam row: 1 college, 330.
  - — [DB]
- Known 4-1 end-sem windows cover 71 colleges and **42,843 eligible (53.5%)**. The other 36 colleges, with 37,212 eligible (46.5%), have no strict-date 4-1 window. — [DB]
- Distribution of 4-1 end-sem end dates (colleges, eligible):
  - 4 Nov: 1 college, 480
  - 13 Nov: 1, 1,416
  - 18 Nov: 1, 192
  - 21 Nov: 1, 4,140
  - 23 Nov: 2, 3,036
  - 26 Nov: 2, 918
  - **27 Nov: 54, 23,667**
  - 28 Nov: 6, 5,622
  - 3 Dec: 1, 960
  - 5 Dec: 1, 1,476
  - 11 Dec: 1, 936
  - — [DB]
- The JNTUK revised timetable dated 29 Oct 2026 sets 4-1 Mid-II for 9–14 Nov and 4-1 end-sem for 16–27 Nov. 3-1 runs a day later: Mid-II 9–13 Nov, end-sem 17–26 Nov. Several autonomous colleges' 3-1 windows run into December: SITE 30 Nov–12 Dec, Vikas 30 Nov–9 Dec. — [EXAMCSV], [DB]
- Only 12 of the top 30 have a known 3-1 window. — [DB]

### Inferences
- For the JNTUK-affiliated bulk, the practical outreach calendar has three phases:
  - Now to 8 Nov: a brief open window.
  - 9–27 Nov: Mid-II, then end-sem. This is roughly three blocked weeks.
  - 28 Nov to 31 Dec: an open window of about 34 days.
- The biggest pools (Aditya, Chalapathi, KL, GGU, VIT-AP, VFSTR) are the least certain on dates. Verifying their exam calendars is the highest-value data task.

### Gaps
- There are no 2026 4-1 dates for KL, Chalapathi, GGU, VIT-AP, VFSTR (inferred "before 9 Dec" only), SAHE, Pragati, KHIT, VLITS and 12 other top-30 colleges.
- Mid and internal windows for deemed and private universities are "ERP-only" per the KL note. — [DB]

## Q3. Required penetration and number of colleges to activate under conversion scenarios

### Takeaway
400 confirmed enrollments is **0.50% of the full 80,055 estimated pool**, 0.89% of the top 30 and 1.14% of the top 20. Conversion rates are scenario inputs, not data, and the college count they imply swings widely:
- at 0.5% of eligible students, essentially all 107 colleges are needed;
- at 1%, the top 25 (172 relevant branches);
- at 2%, the top 8;
- at 3%, the top 4.

### Cited Findings
- Penetration (400 ÷ eligible pool, colleges ranked by eligible):

| Scope | Eligible pool | Penetration needed |
|---|---|---|
| Top 20 | 35,022 | 1.14% |
| Top 30 | 44,742 | 0.89% |
| Top 50 | 60,090 | 0.67% |
| All 107 with eligible > 0 | 80,055 | 0.50% |

— [DB]
- Activation needed under scenario conversion rates (eligible → confirmed; these are **assumptions**, and no benchmark was supplied):

| Scenario conversion | Pool needed | Colleges needed (largest first) | Their pool | Relevant branches in them |
|---|---|---|---|---|
| 0.5% | 80,000 | 107 (all) | 80,055 | 578 |
| 1% | 40,000 | 25 | 40,032 | 172 |
| 2% | 20,000 | 8 | 20,640 | 57 |
| 3% | 13,333 | 4 | 13,782 | 24 |
| 5% | 8,000 | 3 | 10,914 | 17 |

— computed from [DB]
- The portal's own thresholds:
  - `settings.min_conversion` = 0.05 (enrolled ÷ reached); at that rate, 400 enrollments need ≥ 8,000 students *reached*.
  - The `low_outreach` diagnosis triggers if reached < 3 × target × elapsed fraction, which means a reach floor of 1,200 by the deadline.
  - `unrealistic_target` triggers if target > 0.5 × eligible.
  - These are configured thresholds, not observed benchmarks. — [CONTRACT], [DB]

### Inferences
- At the planned ~0.5–1.5% per-college penetration, no allocation comes close to the 50% "unrealistic" threshold. The binding constraint is reach and conversion, not pool size.
- If true conversion is below 0.5%, the 400 target cannot be met within the estimated pool, even with every operational college activated and before any attrition discount.

### Gaps
- There is no observed conversion, reach or enrollment history: the `enrollments`, `activities`, `people` and `targets` tables all have 0 rows. — [DB]

## Q4. Proposed allocation of 400 by district, city, college and department

### Takeaway
Weighting eligible students by tier and exam-free days gives Guntur 138 enrollments, Kakinada 49, NTR 44, West Godavari 43, Krishna 30, Palnadu 28 and East Godavari 27. By department, CSE gets 168 and AI/AI-ML 108. The full spread activates all 107 colleges, but 54 of them get only 1–2 enrollments each. A **focus-30 alternative** puts all 400 into the 30 highest-priority colleges, at 0.68–1.46% per-college penetration.

### Method (reproducible; [CSV400])
1. Pool: relevant branches (is_relevant = 1) in operational colleges with eligible_estimate > 0. That is 578 branches in 107 colleges.
2. College weight = eligible × tier weight × exam-availability factor.
   - **Tier weights are a scenario assumption:** Tier 1 = 1.2, Tier 2 = 1.0, Tier 3 or untiered = 0.8.
   - **Availability** = share of the 58 horizon days *not* inside the college's 4-1 end-sem window or parsed 4-1 mid window, computed from [DB] exam rows.
   - Colleges with no known 4-1 window (36) get the median of the known colleges, **0.69 (40 of 58 days)**. This is an imputation.
3. Largest-remainder rounding apportions 400 to colleges, so the sum is exactly 400. This is the same method as the portal's `/api/targets/allocate` ([CONTRACT]).
4. Each college's target is then split across its relevant branches pro rata to branch eligible, again by largest remainder. District and city figures are roll-ups.
5. For comparison, an unweighted allocation (eligible only) is in column `college_target_unweighted`. The focus-30 version takes the top 30 colleges by weight and re-apportions 400 among them (`focus30_*` columns).

### Cited Findings (all computed from [DB]; output in [CSV400])
- Allocation by district (full, 107 colleges):

| District | Eligible | Weighted target | Unweighted target | Colleges | Focus-30 target (colleges) |
|---|---|---|---|---|---|
| Guntur | 26,184 | **138** | 130 | 26 | 193 (14) |
| Kakinada | 10,206 | **49** | 51 | 11 | 48 (2) |
| NTR | 9,765 | **44** | 48 | 16 | 10 (1) |
| West Godavari | 7,854 | **43** | 40 | 9 | 60 (6) |
| Krishna | 6,024 | **30** | 29 | 11 | 21 (2) |
| Palnadu | 5,406 | **28** | 28 | 10 | 27 (2) |
| East Godavari | 5,778 | **27** | 28 | 7 | 32 (2) |
| Eluru | 3,120 | **14** | 16 | 6 | 0 |
| Konaseema | 3,066 | **14** | 16 | 5 | 0 |
| Bapatla | 2,388 | **11** | 12 | 4 | 9 (1) |
| Polavaram | 264 | **2** | 2 | 2 | 0 |
| **Total** | 80,055 | **400** | 400 | 107 | 400 (30) |

- Allocation by town (top 15 of 73 towns, full weighted allocation):
  - Surampalem 29
  - Narasaraopet 23
  - Rajanagaram 21
  - Bhimavaram 21
  - Vaddeswaram 20
  - Vadlamudi 16
  - Mothadaka 15
  - Chowdavaram 14
  - Inavolu 13
  - Kanuru 10
  - Narsapur 9
  - Eluru 9
  - Paritala 8
  - Korangi 8
  - Vinjanampadu 7
- Allocation by tier:
  - Weighted: Tier 1 51 (7 colleges, 7,974 eligible), Tier 2 198 (31 colleges, 36,600), Tier 3 150 (68 colleges, 35,151), untiered 1.
  - Unweighted: 39, 182, 177 and 2.
- Allocation by department family, full allocation (eligible in brackets) and focus-30:

| Department family | Full | Eligible | Focus-30 |
|---|---|---|---|
| CSE | 168 | 28,485 | 147 |
| AI / AI-ML | 108 | 21,420 | 110 |
| AI-DS / Data Science | 54 | 11,550 | 57 |
| ECE & allied | 42 | 9,351 | 40 |
| IT | 14 | 3,420 | 17 |
| EEE | 5 | 2,529 | 8 |
| Cyber Security | 5 | 1,860 | 13 |
| IoT | 2 | 720 | 2 |
| Other CSE-allied | 2 | 720 | 6 |

- Distribution of college targets in the full allocation:

| College target | Colleges | Enrollments |
|---|---|---|
| >20 | 1 (Aditya University, 22) | 22 |
| 11–20 | 5 | 74 |
| 6–10 | 13 | 91 |
| 3–5 | 34 | 132 |
| 1–2 | 54 | 81 |

  293 branches receive ≥1 enrollment.
- Weighted priority ranking (top 30) with targets in the form full / focus-30:

| # | College | Target | # | College | Target | # | College | Target |
|---|---|---|---|---|---|---|---|---|
| 1 | Aditya Univ | 22 / 37 | 11 | VLITS | 7 / 12 | 21 | SVEC | 5 / 9 |
| 2 | KL Univ | 20 / 34 | 12 | KITS Guntur | 7 / 11 | 22 | NRIIT (S.No 23) | 5 / 9 |
| 3 | Chalapathi | 15 / 25 | 13 | SRGEC | 7 / 11 | 23 | CIET | 5 / 9 |
| 4 | GGU | 15 / 25 | 14 | Pragati | 7 / 11 | 24 | BEC | 5 / 9 |
| 5 | VIT-AP | 13 / 22 | 15 | SRKR | 7 / 11 | 25 | SITE | 5 / 8 |
| 6 | NEC | 11 / 18 | 16 | LBRCE | 6 / 10 | 26 | VITB | 5 / 8 |
| 7 | VFSTR | 9 / 16 | 17 | SAHE | 6 / 10 | 27 | SMCE | 5 / 8 |
| 8 | SCET | 9 / 15 | 18 | VWU/SVECW | 6 / 9 | 28 | ISTS | 4 / 7 |
| 9 | KHIT | 7 / 12 | 19 | MLWEC | 6 / 9 | 29 | Amrita Amaravati | 4 / 7 |
| 10 | RVR&JC | 7 / 12 | 20 | TEC | 5 / 9 | 30 | RVIT | 4 / 7 |

  Colleges ranked 31–40 are MVR, KITS Akshar, CRR, PCE, VNITSW, VSM, Vikas CET, RCE, MIC and Amrita Sai, each with 4 in the full allocation.
- The focus-30 set holds a pool of 43,974 eligible. Penetration is 0.91% overall, ranging from 0.68% (ISTS) to 1.46% (Amrita Amaravati). — [CSV400]

### Inferences
- The full spread is mathematically fair but operationally thin. 54 colleges carrying 1–2 enrollments each (81 in total) would each still need a lead. The focus-30 plan concentrates 400 where 55% of the pool sits and needs about a quarter of the leads.
- A hybrid is defensible: focus-30 as the committed plan, with the 77 other colleges as an opportunistic reserve.
- Tier weights shift 27 enrollments from Tier 3 to Tier 1/2 compared with the unweighted plan. The ranking at the top is robust to the weights, because the top 5 are the largest pools either way.

### Gaps
- Tier weights and the availability imputation are judgement inputs. Placement outcomes ([PLACE]: medians and placement rates for only 48 of 128 colleges) were not used as a weight because coverage is too thin.
- There are no price, course-fit or prior-relationship signals to weight colleges.

## Q5. College leads, ambassadors and weekly pace (with exam impact)

### Takeaway
- **Full plan:** 107 college leads and 293 branch ambassadors (1 per branch with a target), which works out to 1.37 enrollments per ambassador.
- **Focus-30 plan:** 30 leads and 167 ambassadors, which works out to 2.4 enrollments per ambassador. Alternatively 103 ambassadors at 1 per 500 eligible (3.9 each).

The flat pace is 48.3 enrollments/week. Exams block roughly 30% of college-days for the allocated students, so the pace actually needed on open days is about **69/week**. The exam-adjusted schedule reaches only ~105–115 by 24 Nov, and about 60% of the target must come from 2–31 Dec.

### Cited Findings (computed from [DB]; staffing ratios are **scenario assumptions**)
- Leads: 1 per activated college gives 107 (full) or 30 (focus-30). All 113 operational colleges currently have no lead: `people` has 0 rows. — [DB]
- Ambassador scenarios:

| Rule | Full plan: ambassadors | Full plan: enrollments/amb. | Focus-30: ambassadors | Focus-30: enrollments/amb. |
|---|---|---|---|---|
| 1 per branch with a target | 293 | 1.37 | 167 | 2.40 |
| 1 per relevant branch (all) | 578 | 0.69 | 203 | 1.97 |
| 1 per 250 eligible (min 1/college) | 374 | 1.07 | 191 | 2.09 |
| 1 per 500 eligible | 212 | 1.89 | 103 | 3.88 |
| 1 per 1,000 eligible | 140 | 2.86 | — | — |

- Pace:
  - Flat: 400 ÷ 8.29 weeks = **48.3 per week** (about 6.9 per day).
  - Allocation-weighted open days per college = **40.7 of 58**, which gives an effective **68.8 per open week**.
- Share of the eligible pool inside a known 4-1 end-sem window, by week. A further 46.5% has an unknown window in every week.

| Week | In 4-1 end-sem | In 4-1 mid (not end-sem) | Allocated enrollments in blocked colleges (pro rata days) | Exam-adjusted schedule, full (cumulative) | Focus-30 (cumulative) |
|---|---|---|---|---|---|
| 4–10 Nov | 7.0% | 14.7% | 87 | 44 (44) | 41 (41) |
| 11–17 Nov | 21.1% | 18.7% | 153 | 32 (76) | 38 (78) |
| 18–24 Nov | **44.9%** | 0.9% | 177 | 29 (105) | 37 (115) |
| 25 Nov–1 Dec | 20.2% | 0% | 77 | 45 (150) | 47 (162) |
| 2–8 Dec | 2.6% | 0% | 10 | 57 (207) | 53 (216) |
| 9–15 Dec | 0.5% | 0% | 2 | 59 (265) | 56 (271) |
| 16–22 Dec | 0% | 0% | 0 | 59 (324) | 56 (328) |
| 23–29 Dec | 0% | 0% | 0 | 59 (383) | 56 (384) |
| 30–31 Dec | 0% | 0% | 0 | 17 (400) | 16 (400) |

  The exam-adjusted schedule spreads each college's target evenly over its own open days. Colleges with unknown windows are spread evenly over all 58 days, which understates their exam dip. — [DB]

### Inferences
- The blocked weeks 9–27 Nov are best used for appointing leads and ambassadors and building interest lists. Confirmations should be planned for 28 Nov to about 22 Dec, which needs about 57–59 per week in that phase.
- Late-December holidays are not modelled. If the week of 23–29 Dec is weak, the 2–22 Dec weeks need to carry about 75–80 per week. This is an inference, not data.
- Under the full plan, about 1.4 enrollments per ambassador is a low per-person ask but a large coordination load: 400 people to recruit in a few weeks. Focus-30 trades a higher per-ambassador ask (2–4) for far fewer people to recruit and manage.

### Gaps
- There are no data on ambassador productivity, student availability around results or holidays, or the course-purchase lead time.
- The 36 colleges without a known 4-1 window (46.5% of the pool) make the weekly profile uncertain.

## Q6. Data gaps that limit this analysis

### Takeaway
The analysis rests on estimated intake for 93.9% of the pool, has no 4-1 exam dates for 46.5% of it, and has zero operational history (people, targets, enrollments, activities). Several Tier 1 institutions are missing branch intake entirely or partly.

### Cited Findings
- 35 relevant branches in operational colleges have pending intake.
  - **SRM AP** (Tier 1): 3 pending, 0 numbered.
  - **VVIT University** (Tier 2): 6 pending, 0 numbered.
  - VFSTR (Tier 1): 4 of 8 pending.
  - VIT-AP (Tier 1): 3 pending.
  - Amrita Amaravati (Tier 1): 2 pending.
  - UCEK (JNTUK UCE Kakinada, Tier 1): 5 pending.
  - SAHE: 1 pending.
  - NRIIT (S.No 94): 7 pending.
  - RGUKT Nuzvid: 4 pending.
  - The SRM AP notes say convener seats "do not follow a consistent 35% ratio", so the derived intake was withdrawn. — [DB]
- Six operational colleges contribute 0 eligible because of pending intake: SRM AP, VVIT University, CAE Bapatla, CFST Bapatla, NRIIT (94) and RGUKT Nuzvid. — [DB]
- Estimated intakes mostly come from 2026-27 CAP convener seats (644 branches) and aggregator figures (9 branches). They are not 2023-batch figures; only KL has `intake_2023_24`. — [DB], [BRANCHES]
- Exam dates:
  - 36 of 107 colleges, holding 37,212 eligible, have no strict-date 4-1 window.
  - 28 colleges are "No Current Exams Found" and 4 are "Unverified" with no dates. VFSTR, for example, has only "before 2026-12-09 (inferred)".
  - Free-text dates do not create windows in the portal. — [DB], [CONTRACT]
- Contacts for the 113 operational colleges: 110 have a phone, 100 an email, 98 a website. S.No 26, 29 and 35 have neither phone nor email. There are no named staff contacts, because `people` = 0. — [DB]
- Geo precision for the 113: 62 exact, 43 town, 8 district only. — [DB]
- NAAC: only 42 of the 113 have any NAAC entry. Of these, 29 are labelled aggregator and 13 official or college-site, and several are conflicting (e.g. "A++ (2026 adverts) / B++ (2023-24)"). The tier file says "only about a dozen grades come from official or college documents", and that NIRF 2026 had not been published as of 2 Nov 2026. — [DB], [TIERS]
- Placement data are disclosed by only 48 of 128 institutions — [PLACE]. They were not used in the weighting.
- Status mismatch: the tier file counts 128 active institutions — [TIERS]. The DB has 113 operational and 7 pending. Including the pending 7 would change the pool only if their branches were numbered, and they have 1 branch row with 5 eligible (non-relevant). — [DB]

### Inferences
- The highest-value fixes, in order:
  1. Verified 2023-batch strength for the top 10 colleges, which hold 29% of the pool.
  2. 4-1 exam dates for KL, Chalapathi, GGU, VIT-AP, VFSTR and Pragati.
  3. Branch intakes for SRM AP and VVIT University. Both are large Amaravati-belt universities now counted at zero, so the allocation under-weights them.

### Gaps
- There is no benchmark for conversion, ambassador productivity or attrition. All rates in Q3 and Q5 are scenarios.
