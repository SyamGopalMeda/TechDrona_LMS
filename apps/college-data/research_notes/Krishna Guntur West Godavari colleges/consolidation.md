# Consolidation: B.Tech colleges of old Krishna, Guntur and West Godavari districts (Tech Drona, 7 Nov 2026)

Outputs:
- `master_colleges.csv` and `master_branches.csv` in this folder.
- `decisions_log.md`, which records every merge, conflict and rule.
- The workbook `reports/Krishna Guntur West Godavari colleges tracker.xlsx`.

All targets are planning figures based on the playbook's assumed conversion rates. The portal still records 0 people and 0 enrollments.

## Counts

| Item | Colleges |
|---|---|
| Researched rows (128 DB rows + 1 missing college) | 129 |
| Out of scope (polavaram c127, c128) | 2 |
| In scope | 127 |
| Active (counted) | 88 |
| ...targeted for 2026 | 81 |
| ...on Hold (no 2026 target) | 7 |
| Possibly closed | 30 |
| Merged / duplicate | 5 |
| Unverified status | 4 |

## Final-year pools (active, in-scope colleges)

| Pool | Verified | Estimated | Unavailable (colleges) |
|---|---|---|---|
| All-branch final-year (2023 entry) | 41,216 (52 colleges) | 17,896 (34 colleges) | 2 |
| IT-related final-year (F) | 16,401 (42 colleges) | 21,701 (43 colleges) | 3 |

- 43% of the IT pool is verified.
- KL University's 2,940 is in the estimated column.
- Estimated pools carry the 0.85 haircut, and a further 0.6 at fill-risk colleges.

## Top 25 colleges by priority

Targets are individually paid enrollments by 31 Dec 2026.

| Rank | College | District | P | Score | IT pool F (basis) | Min | Avg | Max | 400 test | Ambassadors |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | c36 Narasaraopeta Engineering College (NEC) | Palnadu | P1 | 93.6 | 960 (ver) | 11 | 19 | 30 | AMBER | 6 |
| 2 | c1 KL University (Koneru Lakshmaiah Education Found | Guntur | P1 | 92.0 | 2940 (est) | 24 | 49 | 96 | AMBER | 12 |
| 3 | c2 Vignan's Foundation for Science, Technology & Re | Guntur | P1 | 91.0 | 1802 (est) | 13 | 28 | 55 | AMBER | 7 |
| 4 | c147 S.R.K.R. Engineering College (Sagi Rama Krishnam | West Godavari | P1 | 91.0 | 1260 (est) | 13 | 21 | 34 | AMBER | 7 |
| 5 | c82 Seshadri Rao Gudlavalleru Engineering College (S | Krishna | P1 | 89.5 | 900 (ver) | 9 | 16 | 25 | AMBER | 5 |
| 6 | c9 RVR & JC College of Engineering | Guntur | P1 | 87.4 | 869 (est) | 9 | 15 | 25 | AMBER | 5 |
| 7 | c155 Swarnandhra College of Engineering & Technology | West Godavari | P1 | 87.3 | 780 (ver) | 9 | 15 | 25 | AMBER | 5 |
| 8 | c4 VIT-AP University | Guntur | P1 | 87.0 | 1581 (est) | 13 | 28 | 54 | AMBER | 7 |
| 9 | c13 Kallam Haranadhareddy Institute of Technology (K | Guntur | P1 | 85.0 | 1071 (est) | 11 | 19 | 30 | AMBER | 6 |
| 10 | c62 Lakireddy Bali Reddy College of Engineering (LBR | NTR | P1 | 81.0 | 600 (ver) | 7 | 11 | 18 | AMBER | 4 |
| 11 | c81 Prasad V Potluri Siddhartha Institute of Technol | Krishna | P1 | 76.7 | 420 (ver) | 4 | 7 | 12 | AMBER | 3 |
| 12 | c157 Ramachandra College of Engineering | Eluru | P1 | 75.9 | 540 (ver) | 6 | 9 | 15 | AMBER | 4 |
| 13 | c27 Sri Mittapalli College of Engineering | Guntur | P1 | 75.0 | 714 (est) | 7 | 12 | 20 | AMBER | 4 |
| 14 | c15 RV Institute of Technology (formerly Chebrolu En | Guntur | P1 | 74.6 | 360 (ver) | 5 | 8 | 12 | AMBER | 3 |
| 15 | c153 Sri Vasavi Engineering College | West Godavari | P1 | 74.1 | 631 (est) | 7 | 11 | 18 | AMBER | 4 |
| 16 | c148 Vishnu Institute of Technology (VITB) | West Godavari | P1 | 73.4 | 698 (est) | 7 | 12 | 20 | AMBER | 4 |
| 17 | c152 Sasi Institute of Technology & Engineering | West Godavari | P1 | 71.2 | 663 (est) | 7 | 12 | 19 | AMBER | 4 |
| 18 | c10 Chalapathi Institute of Engineering & Technology | Guntur | P1 | 70.8 | 510 (ver) | 5 | 8 | 13 | AMBER | 3 |
| 19 | c80 Siddhartha Academy of Higher Education (formerly | Krishna | P1 | 69.0 | 600 (ver) | 5 | 11 | 21 | AMBER | 3 |
| 20 | c149 Vishnu Women's University (formerly Shri Vishnu  | West Godavari | P1 | 68.6 | 561 (est) | 5 | 10 | 18 | RED | 3 |
| 21 | c6 Amrita Vishwa Vidyapeetham, Amaravati campus | Guntur | P1 | 68.6 | 360 (ver) | 2 | 5 | 10 | AMBER | 3 |
| 22 | c156 Sir C R Reddy College of Engineering | Eluru | P1 | 66.0 | 600 (ver) | 6 | 10 | 19 | RED | 4 |
| 23 | c32 Vignan's Lara Institute of Technology & Science | Guntur | P1 | 65.9 | 540 (ver) | 7 | 12 | 19 | AMBER | 4 |
| 24 | c42 Tirumala Engineering College | Palnadu | P1 | 65.8 | 480 (ver) | 6 | 11 | 17 | AMBER | 4 |
| 25 | c12 KKR & KSR Institute of Technology & Sciences | Guntur | P2 | 64.9 | 969 (est) | 6 | 10 | 17 | AMBER | 4 |

## District totals (active colleges)

| Old district | New district | Colleges | IT pool F | Min | Avg | Max | College Leads | Ambassadors | Standby |
|---|---|---|---|---|---|---|---|---|---|
| Old Krishna | Krishna | 12 | 3,740 | 37 | 63 | 108 | 8 | 35 | 12 |
| Old Krishna | NTR | 15 | 5,249 | 51 | 90 | 159 | 10 | 47 | 15 |
| **Old Krishna** | **total** | **27** | **8,989** | **88** | **153** | **267** | **18** | **82** | **27** |
| Old Guntur | Guntur | 28 | 17,124 | 148 | 275 | 497 | 23 | 105 | 32 |
| Old Guntur | Palnadu | 10 | 2,683 | 33 | 51 | 81 | 6 | 34 | 11 |
| Old Guntur | Bapatla | 6 | 1,434 | 13 | 22 | 38 | 2 | 12 | 4 |
| **Old Guntur** | **total** | **44** | **21,241** | **194** | **348** | **616** | **31** | **151** | **47** |
| Old West Godavari | West Godavari | 9 | 5,287 | 56 | 94 | 154 | 8 | 36 | 11 |
| Old West Godavari | Eluru | 8 | 2,585 | 25 | 42 | 76 | 5 | 21 | 6 |
| **Old West Godavari** | **total** | **17** | **7,872** | **81** | **136** | **230** | **13** | **57** | **17** |
| **All** | | **88** | **38,102** | **363** | **637** | **1113** | **62** | **290** | **91** |

The same totals grouped by pre-2022 district:

| Pre-2022 district | Colleges | Min | Avg | Max |
|---|---|---|---|---|
| Guntur | 42 | 188 | 338 | 598 |
| West Godavari | 14 | 73 | 121 | 201 |
| Krishna | 30 | 96 | 168 | 296 |
| Prakasam | 2 | 6 | 10 | 18 |

## How much of the company-wide 400 these districts can carry

**This area alone carries min 363 / avg 637 / max 1113**, which is 91% / 159% / 278% of 400.
- It cannot guarantee 400 by 31 Dec 2026: the minimum is 37 short.
- 400 falls inside its average-to-max range.

**Compared with the blueprint.** Table A has 52 colleges in these districts, totalling 317 / 527 / 841 (min / avg / max) with 151 active ambassadors needed. This tracker's minimum is 46 higher.
- **Why it is higher:** it adds IT 3rd- and 2nd-years at 50%, uses verified 2023-24 pools, and covers more colleges.
- **Where pools shrank:** some verified figures replaced larger DB proxies. Examples: SRGEC 1,380 instead of 1,500, and VLITS 960 instead of 1,710.
- **Corrections to the blueprint (QA, 7 Nov 2026):**
  - NEC: the blueprint used 960 from NIRF 2026. The AICTE EoA 2023-24 gives 1,500 in total, of which 960 is IT, and that figure is now used. NEC's target rises from 6 / 10 / 17 to 11 / 19 / 30.
  - Chalapathi University: 626 (an assumption) is replaced by 720, verified on CITY's NIRF 2025.
  - LBRCE: 898 (estimated) is replaced by 1,080, of which 600 is IT (AICTE EoA 2023-24).
  - Amrita Amaravati: 480 is replaced by 360.
  - Vikas CET: 791 (estimated) is replaced by 480, of which 270 is IT (AICTE EoA 2023-24).

**Rest of the 400.** Table A puts 83 of the 400 minimum in Godavari colleges outside this scope. If those rows hold, the combined minimum rises to about 446.

**Institutional MoU pipeline (Jan 2027 onward, not counted in 2026).** At 30% / 50% / 80% of IT 2nd- and 3rd-years, it comes to 28,422 / 47,388 / 75,794 seats. This is an upper bound on cohort size, not a forecast, and it needs signed MoUs and purchase orders.

## "400 per college" test

- **GREEN: 0.** No college reaches 400 on voluntary sign-ups. The largest voluntary average is KL University's 49.
- **AMBER: 30 colleges.** These are type (a)/(b) colleges with roughly 800+ IT students. 400 is reachable only through an institutional MoU from Jan 2027, and whether management is open to one has not been checked.
- **RED: 58 colleges**, including the 7 on Hold.

Priority levels: P1 24, P2 36, P3 21, Hold 7.

## Staffing totals

| Role | Count | Notes |
|---|---|---|
| College Leads | 62 | 43 colleges have their own lead: 23 with 4 or more ambassadors, plus 20 floor-size colleges that have no same-town partner. 38 small colleges share 19 leads in same-town pairs. KL University has 12 ambassadors, more than a lead's span of 7, so its lead runs 2 ambassador_leads. |
| Ambassadors (recruit) | 290 | Buffered minimum 475. At 2.5 paid per recruit they would produce about 725. About 145 are expected to stay active (assumed a = 0.5). |
| Standby ambassadors | 91 | |
| District/City Leads | 12 | Krishna 3, Guntur 6, West Godavari 3; about 6 College Leads each |
| Program Manager | 1 | |
| Payments & Data Verifier | 1 | |

Each ambassador's personal target is 3 / 5 / 15 paid (minimum / standard / stretch).

## Quality issues

### Duplicates

1. Duplicate and merged rows are excluded from counts: c103 (counted as c87), c59 (as c40), c98 (as c74), c73 (as c72) and c11 (as c7).
2. NRIIT c23 and c94 are two distinct colleges, and each is counted once.
3. Duplicate branch rows were found and excluded: VWU AI&ML in the DB, c94 AI&ML, and c8 Space Science.

### DB data

4. The DB uses 2026-27 intake as a stand-in for the final-year batch, which overstates many colleges:

| College | DB figure | Verified final-year |
|---|---|---|
| NEC | 2,100 | 1,500 |
| VLITS | 1,710 | 960 |
| Chalapathi University | 3,840 | 720 |
| RVIT | 840 | 510 |
| MAMW | 360 | 111 (actually admitted) |

5. Corrections the DB needs. None were made, because the portal was read-only for this work:
   - Add ANR CET, Gudivada.
   - Rename c40 to MAM Women's, and c44 to SNIT (not VRIT).
   - Fix the c89 name (YJR DMS), the c94 website and the c149 email.
   - Mark c11 as merged into c7, and c103 as merged into c87.

### Missing data

6. **No intake data** for SRM AP, VVIT University or RGUKT Nuzvid. All three are on Hold, with large upside if intake is obtained.
7. **No branch-wise IT split** for several verified totals (c2, c8, c9, c38, c53, c94, c146, c147, c148, c153), so their IT pools are estimated. NIT AP's IT pool rests on a 2019 FAQ and has low confidence.
8. **Contacts:** 5 active colleges have no verified contact line (c12, c14, c8, c26, c56). Another 22 have only an office, principal or admissions line.
9. **Exam windows:** 4-1 dates are unknown for 32 active colleges. Most known JNTUK-pattern windows end 26-28 Nov. SRKR (5 Dec), Sasi (3 Dec) and BEC (11 Dec) run later.
10. **Social data:**
    - Follower counts are blank, because the pages need a login.
    - 2027 fest dates are not yet published.
    - Colleges outside the 45-college social sweep were scored from district-CSV fields only.
11. **Unchecked closures:** the 30 possibly-closed and 4 unverified colleges were not checked against the JNTUK/ANU affiliation lists or AICTE closure lists, because the search budget ran out. c154 WISE (old West Godavari, now East Godavari) is outside these notes and is also missing from blueprint Table A. QA (7 Nov 2026) added it to `master_colleges.csv` as `scope_in=gap` with an indicative 2 / 2 / 2 target and 3 ambassadors. It is not in the totals. If it is activated, the totals become 365 / 639 / 1,115, with 293 ambassadors and 92 standby.

### Fill and timing risks

12. **Fill-risk colleges (9):** c74, c75, c52, c88, c44, c85, c43, c47, c90. MIET and Nimra keep their verified sanctioned pools under the rule, but their real batches are far smaller.
13. **APSCHE 360-hour internship from 16 Nov 2026:** this rests on a secondary source only. It competes for students' time, but is also an opening for Tech Drona to host internships.