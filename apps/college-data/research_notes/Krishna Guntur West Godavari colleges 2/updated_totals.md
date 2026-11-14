# Updated totals v2: Krishna / Guntur / West Godavari B.Tech colleges (7 Nov 2026)

For the report writer. Source of truth: `master_colleges_v2.csv`, `master_branches_v2.csv` (this folder) and
`reports/Krishna Guntur West Godavari colleges 2 tracker.xlsx`. Rules and every change are in `decisions_log_v2.md`.
The v1 files in `Krishna Guntur West Godavari colleges/` are unchanged. All targets are planning figures built on assumed conversion rates; the portal still records 0 people and 0 enrollments.

## Headline

| Item | v2 | v1 |
|---|---|---|
| Paid enrollments by 31 Dec 2026 (min / avg / max) | **377 / 655 / 1,143** | 363 / 637 / 1,113 |
| Share of company-wide 400 | 94.2% / 163.8% / 285.8% | 91% / 159% / 278% |
| Gap of the minimum to 400 | 23 short | 37 short |
| Colleges counted (active, in scope) / targeted / Hold | 89 / 84 / 5 | 88 / 81 / 7 |
| Priority P1 / P2 / P3 / Hold | 24 / 35 / 25 / 5 | 24 / 36 / 21 / 7 |
| 400-per-college test GREEN / AMBER / RED | 0 / 31 / 58 | 0 / 30 / 58 |
| Ambassadors to recruit / standby | 299 / 95 | 290 / 91 |
| Buffered minimum (sum of ceil(1.2 × min)) | 491 | 475 |
| College Leads | 64 (44 own: 22 with ≥4 ambassadors + 22 unpaired floor colleges; 40 colleges share 20) | 62 |
| District/City Leads | 12 (Old Krishna 3, Old Guntur 6, Old West Godavari 3) | 12 |
| Programme Manager / Payments & Data Verifier | 1 / 1 | 1 / 1 |
| MoU pipeline Jan 2027+ (30/50/80% of IT 2nd+3rd years) | 28,135 / 46,909 / 75,030 | 28,422 / 47,388 / 75,794 |

**Access-rule fix (coordinator request, 7 Nov 2026):** before the fix these v2 numbers were 386 / 674 / 1,178, 302 ambassadors, 95 standby, 64 College Leads, RAG 0/31/58, P1 25 / P2 35 / P3 24 / Hold 5. The fix stops negated role text ("no TPO published", "no CDC phone/email published") counting as a TPO line; it lowered x from 1.0 to 0.8 at 13 colleges.

No college reaches 400 on voluntary sign-ups; the largest voluntary average is KL University's 49 (VFSTR next at 28).

## Status counts (all 130 rows)

| Status | Count | Colleges |
|---|---|---|
| active (counted) | 89 | 88 v1 colleges + c154 WISE |
| winding_down (enrolled students, no 2026 intake; not targeted) | 6 | c20 (45), c21 (123), c28 (100), c37 (110), c41 (100), c167 (59) — figures are JNTUK Apr-2026 exam candidates across II–IV years; final-year cohorts are small |
| listed_no_admissions | 1 | c76 Nova CET (on 2026 seat matrix, 0 allotted) |
| possibly_closed | 21 | 7 with residual backlog only (c45, c72, c86, c93, c161, c168, c169) + 14 with no trace |
| pharmacy_only (no B.Tech) | 4 | c22, c57, c79, c165 |
| unverified | 1 | c61 Saveetha Amaravati |
| duplicate_merged | 5 | c103→c87, c59→c40, c98→c74, c73→c72, c11→c7 |
| out_of_scope | 3 | c127, c128 (Polavaram) + c58 VRS & YRN (old Prakasam; also winding down) |
| **total** | **130** | |

## Final-year pools (active, in-scope colleges)

| Pool | Verified | Estimated | Unavailable | % verified | v1 |
|---|---|---|---|---|---|
| All-branch final-year | 46,215 (53 colleges) | 14,549 (35) | 1 (SRM AP) | 76% | 41,216 / 17,896 (70%) |
| IT final-year (F) | 20,470 (44) | 19,692 (44) | 1 (SRM AP) | **51%** | 16,401 / 21,701 (43%) |

Total IT pool 40,162 (v1 38,102). Verified now covers actual 2023-24 admissions at 6 colleges (VIT-AP, SMCE, Usha Rama, SRGEC, CRR, MAMW) and sanctioned 2023-24 seats elsewhere. The largest estimated pools are KL (2,940), VFSTR (1,802), SRKR (1,260), KITS (1,134) and VVIT (1,044).

## District table (active, in-scope)

| Old district | New district | Colleges | Targeted | IT pool F (verified) | Min | Avg | Max | College Leads | Ambassadors | Standby | District/City Leads |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Old Krishna | Krishna | 12 | 11 | 3,761 (2,661) | 37 | 63 | 109 | 8 | 35 | 12 |  |
| Old Krishna | NTR | 15 | 15 | 5,022 (3,750) | 49 | 86 | 150 | 10 | 47 | 15 |  |
| **Old Krishna** | **total** | **27** | 26 | 8,783 (6,411) | **86** | **149** | **259** | 18 | 82 | 27 | 3 |
| Old Guntur | Guntur | 28 | 27 | 18,540 (8,788) | 160 | 293 | 530 | 24 | 109 | 34 |  |
| Old Guntur | Palnadu | 10 | 10 | 2,683 (1,851) | 33 | 51 | 80 | 6 | 34 | 11 |  |
| Old Guntur | Bapatla | 6 | 4 | 1,434 (180) | 13 | 21 | 36 | 2 | 12 | 4 |  |
| **Old Guntur** | **total** | **44** | 41 | 22,657 (10,819) | **206** | **365** | **646** | 32 | 155 | 49 | 6 |
| Old West Godavari | West Godavari | 9 | 9 | 5,369 (1,860) | 57 | 94 | 153 | 8 | 36 | 11 |  |
| Old West Godavari | Eluru | 8 | 7 | 3,245 (1,380) | 26 | 45 | 83 | 5 | 23 | 7 |  |
| Old West Godavari | East Godavari | 1 | 1 | 108 (0) | 2 | 2 | 2 | 1 | 3 | 1 |  |
| **Old West Godavari** | **total** | **18** | 17 | 8,722 (3,240) | **85** | **141** | **238** | 14 | 62 | 19 | 3 |
| **All** | **** | **89** | 84 | 40,162 (20,470) | **377** | **655** | **1143** | 64 | 299 | 95 | 12 |

| Pre-2022 district | Colleges | Min | Avg | Max | v1 (min / avg / max) |
|---|---|---|---|---|---|
| Guntur | 42 | 200 | 356 | 629 | 188 / 338 / 598 |
| Krishna | 30 | 98 | 171 | 301 | 96 / 168 / 296 |
| West Godavari | 15 | 73 | 119 | 196 | 73 / 121 / 201 |
| Prakasam | 2 | 6 | 9 | 17 | 6 / 10 / 18 |

## Top 25 by priority

Lead offer codes: (a) GenAI/full-stack capstone or hackathon bootcamp; (b) "Ninja → Digital" placement upgrade; (c) entry aptitude + coding module; (d) women's college (as b or c by size). Full text per college is in the workbook's Priority list.

| Rank | College | District | P | IT pool F (basis) | Min | Avg | Max | 400 test | Amb. | Lead offer | 4-1 exams end |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | c36 Narasaraopeta Engineering College (NEC) | Palnadu | P1 | 960 (ver) | 11 | 19 | 30 | AMBER | 6 | (b) | 2026-11-23 |
| 2 | c1 KL University (Koneru Lakshmaiah Education … | Guntur | P1 | 2,940 (est) | 24 | 49 | 96 | AMBER | 12 | (a) | not published  |
| 3 | c2 Vignan's Foundation for Science, Technology… | Guntur | P1 | 1,802 (est) | 13 | 28 | 55 | AMBER | 7 | (a) | not found |
| 4 | c147 S.R.K.R. Engineering College (Sagi Rama Kri… | West Godavari | P1 | 1,260 (est) | 13 | 21 | 34 | AMBER | 7 | (b) | 2026-12-05 |
| 5 | c82 Seshadri Rao Gudlavalleru Engineering Colle… | Krishna | P1 | 900 (ver) | 9 | 16 | 25 | AMBER | 5 | (b) | 2026-11-28 |
| 6 | c9 RVR & JC College of Engineering | Guntur | P1 | 869 (est) | 9 | 15 | 25 | AMBER | 5 | (b) | 2026-11-23 |
| 7 | c155 Swarnandhra College of Engineering & Techno… | West Godavari | P1 | 780 (ver) | 9 | 15 | 25 | AMBER | 5 | (b) | 2026-11-13 |
| 8 | c4 VIT-AP University | Guntur | P1 | 3,025 (ver) | 18 | 36 | 71 | AMBER | 9 | (a) | not found |
| 9 | c62 Lakireddy Bali Reddy College of Engineering… | NTR | P1 | 600 (ver) | 7 | 11 | 18 | AMBER | 4 | (b) | 2026-11-28 |
| 10 | c148 Vishnu Institute of Technology (VITB) | West Godavari | P1 | 780 (ver) | 8 | 13 | 21 | AMBER | 4 | (b) | 2026-11-28 |
| 11 | c81 Prasad V Potluri Siddhartha Institute of Te… | Krishna | P1 | 420 (ver) | 4 | 7 | 12 | AMBER | 3 | (b) | 2026-11-27 |
| 12 | c157 Ramachandra College of Engineering | Eluru | P1 | 540 (ver) | 6 | 9 | 15 | AMBER | 4 | (b) | unknown (DB: N |
| 13 | c15 RV Institute of Technology (formerly Chebro… | Guntur | P1 | 360 (ver) | 5 | 8 | 12 | AMBER | 3 | (b) | 2026-11-28 |
| 14 | c153 Sri Vasavi Engineering College | West Godavari | P1 | 631 (est) | 7 | 11 | 18 | AMBER | 4 | (b) | unknown (DB: U |
| 15 | c12 KKR & KSR Institute of Technology & Sciences | Guntur | P1 | 1,134 (est) | 9 | 15 | 25 | AMBER | 5 | (b) | unknown (DB: N |
| 16 | c5 VVIT University (Vasireddy Venkatadri Inter… | Guntur | P1 | 1,044 (est) | 6 | 13 | 25 | AMBER | 4 | (b) | unknown (DB: N |
| 17 | c13 Kallam Haranadhareddy Institute of Technolo… | Guntur | P1 | 655 (est) | 8 | 13 | 22 | AMBER | 4 | (b) | unknown (DB: N |
| 18 | c152 Sasi Institute of Technology & Engineering | West Godavari | P1 | 663 (est) | 7 | 12 | 19 | AMBER | 4 | (b) | 2026-12-03 |
| 19 | c10 Chalapathi Institute of Engineering & Techn… | Guntur | P1 | 510 (ver) | 5 | 8 | 13 | AMBER | 3 | (b) | 2026-11-28 |
| 20 | c80 Siddhartha Academy of Higher Education (for… | Krishna | P1 | 600 (ver) | 5 | 11 | 21 | AMBER | 3 | (b) | unknown (DB: U |
| 21 | c149 Vishnu Women's University (formerly Shri Vi… | West Godavari | P1 | 561 (est) | 5 | 10 | 18 | RED | 3 | (d) | 2026-11-27 |
| 22 | c6 Amrita Vishwa Vidyapeetham, Amaravati campus | Guntur | P1 | 360 (ver) | 2 | 5 | 10 | AMBER | 3 | (a) | 2026-11-04 |
| 23 | c32 Vignan's Lara Institute of Technology & Sci… | Guntur | P1 | 540 (ver) | 7 | 12 | 19 | AMBER | 4 | (b) | unknown (DB: N |
| 24 | c42 Tirumala Engineering College | Palnadu | P1 | 480 (ver) | 6 | 11 | 17 | AMBER | 4 | (b) | unknown (DB: N |
| 25 | c94 NRI Institute of Technology, Agiripalli | Eluru | P2 | 720 (est) | 6 | 12 | 24 | AMBER | 4 | (b) | unknown (DB: U |

## 400-per-college test: AMBER colleges (31)

AMBER = 400 reachable only through an institutional MoU from Jan 2027 (V_max + 0.5 × (F + T + S) ≥ 400 and type a/b). Management openness is unverified for all.

| College | Type | IT pool F | Max | 0.5 × (F + T + S) |
|---|---|---|---|---|
| c36 Narasaraopeta Engineering College (NEC) | b | 960 | 30 | 1,978 |
| c1 KL University (Koneru Lakshmaiah Education Founda… | a | 2,940 | 96 | 4,292 |
| c2 Vignan's Foundation for Science, Technology & Res… | a | 1,802 | 55 | 2,168 |
| c147 S.R.K.R. Engineering College (Sagi Rama Krishnam … | b | 1,260 | 34 | 1,840 |
| c82 Seshadri Rao Gudlavalleru Engineering College (SR… | b | 900 | 25 | 1,429 |
| c9 RVR & JC College of Engineering | b | 869 | 25 | 1,414 |
| c155 Swarnandhra College of Engineering & Technology | b | 780 | 25 | 1,600 |
| c4 VIT-AP University | a | 3,025 | 71 | 3,298 |
| c62 Lakireddy Bali Reddy College of Engineering (LBRC… | b | 600 | 18 | 1,106 |
| c148 Vishnu Institute of Technology (VITB) | b | 780 | 21 | 1,139 |
| c81 Prasad V Potluri Siddhartha Institute of Technolo… | b | 420 | 12 | 671 |
| c157 Ramachandra College of Engineering | b | 540 | 15 | 846 |
| c15 RV Institute of Technology (formerly Chebrolu Eng… | b | 360 | 12 | 871 |
| c153 Sri Vasavi Engineering College | b | 631 | 18 | 1,064 |
| c12 KKR & KSR Institute of Technology & Sciences | b | 1,134 | 25 | 1,662 |
| c5 VVIT University (Vasireddy Venkatadri Internation… | a | 1,044 | 25 | 522 |
| c13 Kallam Haranadhareddy Institute of Technology (KH… | b | 655 | 22 | 1,537 |
| c152 Sasi Institute of Technology & Engineering | b | 663 | 19 | 1,080 |
| c10 Chalapathi Institute of Engineering & Technology … | b | 510 | 13 | 1,119 |
| c80 Siddhartha Academy of Higher Education (formerly … | a | 600 | 21 | 1,049 |
| c6 Amrita Vishwa Vidyapeetham, Amaravati campus | a | 360 | 10 | 641 |
| c32 Vignan's Lara Institute of Technology & Science | b | 540 | 19 | 1,422 |
| c42 Tirumala Engineering College | b | 480 | 17 | 1,277 |
| c94 NRI Institute of Technology, Agiripalli | a | 720 | 24 | 1,120 |
| c27 Sri Mittapalli College of Engineering | b | 363 | 11 | 666 |
| c150 DNR College of Engineering & Technology | b | 300 | 9 | 553 |
| c14 KITS Akshar Institute of Technology (formerly Gun… | b | 563 | 13 | 972 |
| c7 Chalapathi University | a | 540 | 20 | 1,595 |
| c48 Bapatla Engineering College | b | 612 | 14 | 997 |
| c23 NRI Institute of Technology, Guntur | b | 450 | 12 | 974 |
| c151 Bhimavaram Institute of Engineering & Technology … | b | 306 | 7 | 498 |

## Changes vs previous (v1 → v2) and why

Totals: min +14, avg +18, max +30; ambassadors +9; standby +4; College Leads +2; District/City Leads unchanged (12); AMBER +1 (c5); RED unchanged (c5 left RED, c154 joined).
Every college whose numbers moved:

| College | Min/Avg/Max v1 → v2 | Ambassadors | College Lead | Why |
|---|---|---|---|---|
| c4 VIT-AP | 13/28/54 → 18/36/71 | 7 → 9 (+1 standby) |  | IT pool 1,581 (estimated) → 3,025 verified ACTUAL admitted 2023 (Annual Report 2023-24); integrated M.Tech 572 excluded. Access-rule fix: role is 'Admissions office (no CDC phone/email published)', so x 1.0 → 0.8. |
| c5 VVIT University | 0/0/0 (Hold) → 6/13/25 | 0 → 4 (+1 standby) | +1 own lead | 2023-24 sanctioned 1,740 verified (NIRF 2025); IT 1,044 estimated (× 0.60 median share). Leaves Hold; P1, AMBER. |
| c96 RGUKT Nuzvid | 0/0/0 (Hold) → 4/7/13 | 0 → 3 (+1 standby) | +0.5 (shares with c95) | E4 batch ~1,100 estimated (1,000 + 100 EWS seats); IT 660 estimated (× 0.60). Leaves Hold; P2. |
| c95 Sri Sarathi | unchanged | unchanged | 1 → 0.5 | Now pairs with c96 in Nuzvid instead of having its own lead. |
| c12 KITS | 6/10/17 → 9/15/25 | 4 → 5 (+1 standby) |  | Pool = CAP-2026 intake × 99.5% fill (IT 1,134; was × 0.85 = 969). New office line + principal email: x 0.6 → 0.8. P2 → P1. |
| c13 KHIT | 11/19/30 → 8/13/22 | 6 → 4 (−1 standby) |  | Pool = CAP-2026 intake × 2026 fill (IT 52%): IT 655 (was 1,071). |
| c14 KITS Akshar | 4/6/10 → 5/8/13 | 3 → 3 |  | Pool × 78% fill (IT 563, was 612) but new office line + principal email: x 0.6 → 0.8. |
| c27 SMCE | 7/12/20 → 4/7/11 | 4 → 3 | stays own (no town partner) | IT pool 714 (estimated) → 363 verified ACTUAL admitted 2023-24; new CAP-2026 fill-risk flag (13% filled). P1 → P2. |
| c148 VITB | 7/12/20 → 8/13/21 | 4 → 4 |  | AICTE EoA 2023-24: 1,140 / IT 780 verified (was NIRF 1,020, IT 698 estimated). |
| c83 Usha Rama | 3/5/9 → 3/5/10 | 3 → 3 |  | IT pool 300 sanctioned → 321 ACTUAL admitted. |
| c8 ANUCET | 1/2/4 → 2/3/5 | 3 → 3 |  | New office line + principal email: x 0.6 → 0.8 (min floor of 2 now applies). |
| c26 PITW | 1/1/2 → 2/2/2 | 3 → 3 |  | Principal email added (x 0.6 → 0.8, floor applies); new fill-risk flag cuts IT pool 102 → 61. |
| c56 VNRCE | 1/2/3 → 2/2/2 | 3 → 3 |  | Pool × 2026 fill (2 of 360 seats): IT 204 → 1. New office line (x 0.8) so the floor of 2 applies. Phone-check before staffing. |
| c24 PITM | 2/3/5 → 2/2/2 | 3 → 3 |  | Pool × 25% fill: IT 230 → 53; new fill-risk flag. |
| c74 MIET | 2/2/3 → 2/2/2 | 3 → 3 |  | Sanctioned 315 / IT 120 → estimated actual batch ~110 / IT ~40. P2 → P3. |
| c75 Nimra | 2/3/5 → 2/2/2 | 3 → 3 |  | Sanctioned 360 / IT 216 → estimated actual ~115 / IT 69; access-rule fix x 1.0 → 0.8. P2 → P3. |
| c154 WISE | not counted → 2/2/2 | +3 (+1 standby) | +1 own lead | Now active and in scope (old West Godavari). 270 × 0.6 low-fill: IT 108 estimated; principal line only (x 0.8). |
| c82 SRGEC | unchanged | unchanged |  | Final-year total now ACTUAL 1,318; IT pool stays the verified sanctioned split 900, so the target does not move. |
| c156 Sir CRR | 6/10/19 → 4/8/15 | 4 → 3 | 1 → 0.5 (shares with c158) | Final-year total now ACTUAL 1,039 (IT 600 unchanged). Access-rule fix: principal line only, x 1.0 → 0.8. P1 → P2. |
| c158 Eluru CE | 3/6/10 → 2/4/8 | 3 → 3 | 0.5 (now shares with c156) | Access-rule fix: 'Principal (Head of Placements named, no contact)', x 1.0 → 0.8. |
| c159 Helapuri | unchanged 2/2/3 | unchanged | 0.5 → 1 (no partner left in Eluru) | Lead re-pairing after c156 dropped below 4 ambassadors. |
| c68 PSCMR | 4/8/14 → 3/6/11 | 3 → 3 |  | Access-rule fix: principal line only, x 1.0 → 0.8. |
| c151 Bhimavaram Inst. of Engg | 3/5/9 → 3/4/7 | 3 → 3 |  | Access-rule fix: info line only, x 1.0 → 0.8. |
| c71 VGI | 3/5/9 → 2/4/7 | 3 → 3 |  | Access-rule fix: principal line only, x 1.0 → 0.8. |
| c38 AM Reddy | 2/3/6 → 2/3/5 | 3 → 3 | re-paired with c35 | Access-rule fix, x 1.0 → 0.8. P2 → P3. |
| c49 Bapatla Women's | 2/3/6 → 2/3/5 | 3 → 3 |  | Access-rule fix, x 1.0 → 0.8. |
| c52 Chirala EC | 2/3/5 → 2/2/4 | 3 → 3 |  | Access-rule fix, x 1.0 → 0.8. |
| c90 KRUCET | unchanged 2/2/2 | unchanged |  | Access-rule fix, x 1.0 → 0.8 (already at the floor). |
| c36 NEC | unchanged 11/19/30 | unchanged |  | EoA 1,500 / IT 960 confirmed (NBA filing); flagged 'absent from CAP 2026 – verify'. |

Status-only changes (no effect on totals, none was counted before): 6 colleges reclassified possibly_closed/unverified → winding_down, c76 → listed_no_admissions, 4 → pharmacy_only, c58 → out_of_scope; c154 moved from `scope_in=gap` into the counted set.

## Open gaps

1. **Minimum still 23 short of 400**; 51% of the IT pool is verified. KL's 2,940 (largest pool) remains an estimated split.
2. **NEC (rank 1) is absent from the CAP 2026 list** — verify its 2026 admission route/status on the TPO call.
3. **SRM AP has no data** (Hold). KITS, KHIT, KITS Akshar, VNRCE and PITM pools use 2026 seats × 2026 fill as a proxy for 2023-24.
4. **VNRCE** pool is ~1 student, but the floor rule still sets 2/2/2 and 3 ambassadors; MIET, Nimra, WISE, PITW and PITM also sit at the floor. Phone-check batch sizes before staffing these.
5. **Access-rule fix applied (v2):** a role such as "Principal (no TPO published)" no longer counts as a TPO line. Before the fix v2 stood at 386 / 674 / 1,178 (302 ambassadors); after it, the figures above. 13 colleges moved from x 1.0 to 0.8 (c4, c156, c68, c151, c71, c158, c38, c49, c52, c75, c90, c154, new-ANRG).
6. **T/S understated** at VIT-AP (DB current IT intake 1,860 vs ~3,000+ admitted per year) and zero at VVIT/RGUKT, so the MoU pipeline is conservative.
7. **Contacts:** TPO/HOD-CSE lines still unverified for KITS, KITS Akshar, BEC, PITW, VNRCE and ANUCET (office line / principal email only; principal emails are on gmail/yahoo/rediffmail). Admissions-officer mobiles deliberately not used.
8. **Exams:** 4-1 end dates known for 58 of 89 active colleges; KL, VFSTR, VIT-AP, SRM AP, KHIT, KITS not published. JNTUK-pattern colleges finish theory 27 Nov; lab externals TBA.
9. **Closures:** no AICTE closure list could be checked; winding-down colleges need a phone check before any contact (c21 especially).
10. **APSCHE 360-hour internship** rests on one secondary source; APSCHE internships must be free to students.
