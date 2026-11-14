# Decisions log: Krishna / Guntur / West Godavari consolidation (7 Nov 2026)

This log records every merge, de-duplication and figure choice made while building `master_colleges.csv`, `master_branches.csv` and the tracker workbook (`reports/Krishna Guntur West Godavari colleges tracker.xlsx`). The portal DB was only read, never written.

## 1. Scope

**In scope, by portal district id:**
- Old Krishna: `krishna` + `ntr`.
- Old Guntur: `guntur` + `palnadu` + `bapatla`.
- Old West Godavari: `west-godavari` + `eluru`.

**Out of scope.** The `polavaram` rows c127 Lenora and c128 Dr Paul Raj's were never in these old districts. They stay in `master_colleges.csv` with `scope_in=no` and are not counted.

**Pre-2022 districts differ for some in-scope colleges.** The workbook shows both groupings.
- c52 CECC, c53 SACET and c58 VRS&YRN were in Prakasam.
- c94 NRIIT, c95 SSIET and c96 RGUKT were in Krishna.
- c154 WISE was in old West Godavari but is now in East Godavari. It is not in these notes and is not counted. It is also absent from blueprint Table A. QA (7 Nov 2026) added it to `master_colleges.csv` as `scope_in=gap`, with an indicative target only.

**One college missing from the DB was added:** Akkineni Nageswara Rao CET, Gudivada (id `new-ANRG`, EAPCET code ANRG). It opened in 2025, so it has no final-year batch.

## 2. Duplicates and merges

No college is counted twice. Each duplicate row is kept, but its numbers are counted under the row shown.

| Row | Counted under | Evidence |
|---|---|---|
| c103 | c87 | Sri Viveka IT is the old EAPCET code VIVK of Lingayas, and Lingayas's registered society is Sri Viveka Education Society. Sources are an aggregator and the society name, so confidence is medium. |
| c59 | c40 | Duplicate DB row of MAM Women's Engineering College (EAPCET code MAMW). The rename from Krishnaveni EC for Women is confirmed in MAMW's mandatory disclosure. |
| c98 | c74 | An AICTE letter dated 05-09-2011 renamed Prasad Institute of Technology & Sciences to Mandava Institute of Engineering & Technology. |
| c73 | c72 | Likely duplicate: the JNTUK list has a single GDMM entry, per the DB note. Both are possibly closed, so neither is counted. |
| c11 | c7 | Chalapathi Institute of Technology became Chalapathi University (same AICTE permanent id 1-4822221). Its 2023 batch (720, of which IT 540) is counted once, under c7. |

### NRIIT: two distinct colleges, each counted once

The DB ids, towns, websites, approvals and intake series all differ:

| | c23 NRI Institute of Technology, Guntur | c94 NRI Institute of Technology, Agiripalli |
|---|---|---|
| Location | Visadala/Perecherla, Guntur district | Pothavarappadu, Agiripalli mandal, Eluru district (old Krishna) |
| Website | nriit.ac.in | nriit.edu.in, which now redirects to rvrnriuniversity.edu.in |
| Admissions | EAPCET (code NRIT) | NRIUCET, not EAPCET |
| 2023-24 intake | AICTE EoA 600 (IT 450); NIRF 2026 says 660 | 1,200 (NIRF IR-E-C-17942) |
| Counted | 600 | 1,200 |

This settles the social sweep's open question about whether NRIIT might be a different entity in the DB: it is.

### Branch-level duplicates

- **VWU (c149):** the DB lists CSE(AI&ML) twice (CSE-AIML and CSE-AIML-SVECW, 120 each). The research CSV keeps one row, and DB-derived sums de-duplicate by branch name. Current IT intake used is 660, not 780.
- **NRIIT Agiripalli (c94):** 'Artificial Intelligence and Machine Learning' and 'CSE (AI and Machine Learning)' are both listed, neither with an intake. The second row is marked `exclude` in `master_branches.csv`.
- **ANUCET (c8):** Space Science is listed twice. The blank row is excluded.
- A branch row counts only if its college is active and in scope (see the `final_decision` column in `master_branches.csv`).

## 3. Status decisions

- **Active and counted: 88.** Includes c89 YJR DMS, which is active under its new name, and the new ANR CET.
- **Possibly closed: 30.** Not in the EAPCET-2026 list, and no B.Tech activity was found. None is marked closed, because no official closure order was found.
- **Unverified: 4** (c21 NVRCET, c58 VRS&YRN, c61 Saveetha Amaravati, c76 Nova CET). Excluded from targets until a phone or field check is done.
- **Duplicate or merged: 5** (see section 2).

## 4. Final-year pools and conflicts

### Rule

- **Verified pool:** the final-year pool is the 2023-24 approved or sanctioned intake, when it was read on an AICTE EoA, NIRF filing or mandatory disclosure.
- **Estimated pool:** otherwise, current intake × 0.85, a haircut for growth since 2023. Current intake is taken from the research CSV total, then the DB total, then the sum of DB branches, in that order.
- **IT pool (F):** follows the same rule. Where the total is verified but no IT split is published, F = verified total × the college's current IT share of branch intake (estimated).
- **c94 NRIIT Agiripalli:** it has no branch intakes at all, so it uses the regional median IT share (0.60) of the 38 colleges with verified splits.
- **Source conflicts:** where AICTE and NIRF disagree, the AICTE EoA figure is used.

### Conflicts resolved

| College | Conflict | Figure used |
|---|---|---|
| c36 Narasaraopeta Engineering College (NEC) | NEC: AICTE EoA 2023-24 = 1,500 (IT 960) vs NIRF 2026 = 960 sanctioned. Rule: AICTE EoA preferred for approved intake -> total 1,500, IT 960. NIRF noted. | total 1500 (verified); IT 960 (verified) |
| c82 Seshadri Rao Gudlavalleru Engineering College | SRGEC: AICTE EoA + Mandatory Disclosure 2026 = 1,380 vs NIRF 2026 = 1,500 (1,500 starts 2024-25). Rule: EoA -> 1,380 (IT 900). Blueprint's 1,500 superseded. | total 1380 (verified); IT 900 (verified) |
| c69 Vijaya Institute of Technology for Women (VIT | VITW: AICTE EoA 2023-24 = 420 vs NIRF 2025 = 480. Rule: EoA -> 420 (IT 300). | total 420 (verified); IT 300 (verified) |
| c7 Chalapathi University | Chalapathi University: CITY EoA 2023-24 = 720 (IT 540), matches NIRF. Replaces the blueprint's 626 'assumption'. c11 CITY not counted separately. | total 720 (verified); IT 540 (verified) |
| c32 Vignan's Lara Institute of Technology & Scien | VLITS: EoA 2023-24 = 960 (IT 540) = NIRF 2026; DB 1,710 / 2026-27 1,920 are later-year intakes. | total 960 (verified); IT 540 (verified) |
| c9 RVR & JC College of Engineering | RVR&JC: NIRF 2026 2023-24 = 1,380 (DB 1,620 is 2024-25+). IT split unpublished -> IT = 1,380 x current IT share. | total 1380 (verified); IT 869 (estimated) |
| c23 NRI Institute of Technology, Guntur | NRIIT Guntur: EoA 2023-24 = 600 vs NIRF 660. Rule: EoA -> 600 (IT 450). | total 600 (verified); IT 450 (verified) |
| c40 MAM Women's Engineering College (formerly Kri | MAMW: sanctioned 360 but only 111 actually admitted in 2023-24 (all CSE, mandatory disclosure). Actual admitted used (verified). | total 111 (verified); IT 111 (verified) |
| c155 Swarnandhra College of Engineering & Technolo | SCET: 1,230 (EoA/NIRF 2023-24) vs DB 1,740/1,800 current. | total 1230 (verified); IT 780 (verified) |
| c6 Amrita Vishwa Vidyapeetham, Amaravati campus | Amrita Amaravati: AICTE letters 2023-24 = 360 vs DB 480 (later year). | total 360 (verified); IT 360 (verified) |
| Aditya University | Outside scope (Kakinada) | not counted here |

### Exceptions to the rule

- **KL University (c1):** the IT pool of 2,940 is the DB's 2023-24 branch split (from a scanned BoM PDF) of the verified 3,510 total. No growth haircut is applied, because the total has not grown since 2023-24. The basis is still marked estimated.
- **MAMW (c40):** actual admissions are used instead of sanctioned seats. That is 111 students in 2023-24, and 250 and 217 IT students in 2024-25 and 2025-26 (mandatory disclosure). Marked verified.
- **ANR CET and ISTS (c160):** F = 0, because neither has a final-year batch (opened 2025 and 2024).

## 5. Fill-risk flags (2026 counselling)

A college is flagged where the seats left over in the EAPCET-2026 list are close to its total convener seats.
- Estimated pools (F, T, S) at these colleges are multiplied by a further 0.6.
- Verified pools keep the rule value. The flag is still shown, and the priority score drops by 4 points.

| College | Evidence | F used | Treatment |
|---|---|---|---|
| c74 Mandava Institute of Engineering & Techn | MIET: 175 of 252 left over (CAP 2026); 436 UG students all years (NIRF 2025) | 120 (verified) | verified, flag only; real batch likely much smaller |
| c75 Nimra College of Engineering & Technolog | Nimra: 56 of 84 left over (CAP 2026); 408 UG students all years (NIRF 2026) | 216 (estimated) | x0.6 applied |
| c52 Chirala Engineering College | CECC: 408 of 432 left over (CAP 2026) | 169 (estimated) | x0.6 applied |
| c88 Paladugu Parvathi Devi College of Engine | PPD: left-over seats close to full convener count (krishna.md, CAP 2026) | 107 (estimated) | x0.6 applied |
| c44 Sri Nalanda Institute of Engineering & T | SNIT: 309 of 312 convener seats left over (CAP 2026) | 153 (estimated) | x0.6 applied |
| c85 Sri Chaitanya DJR College of Engineering | DJRCET: 287 of 288 left over (CAP 2026) | 92 (estimated) | x0.6 applied |
| c43 Loyola Institute of Technology & Managem | LITAM: 266 of 312 left over (CAP 2026) | 122 (estimated) | x0.6 applied |
| c47 Newton's Institute of Science & Technolo | NIST: 270 of 288 left over (CAP 2026) | 122 (estimated) | x0.6 applied |
| c90 Krishna University College of Engineerin | KRUCET: left-over seats close to full convener count (krishna.md, CAP 2026) | 61 (estimated) | x0.6 applied |

Notes on the table:
- **PPD (c88) and KRUCET (c90)** are added to the brief's list, because krishna.md reports almost all of their seats left over.
- **MIET (c74) and Nimra (c75)** have verified sanctioned totals. But NIRF shows only 436 and 408 UG students across all years, so their real batches are much smaller. Check this on the TPO call.
- **Nimra's IT pool** is still multiplied by 0.6, because its IT split is estimated.

## 6. Targets, the 400 test and staffing

All conversion rates, k, x, the 2.5 paid per recruited ambassador and the MoU coverage are assumptions taken from the playbook and the blueprint.

### Targets

Formula from the playbook:
- V_s = round(k_s × x × (rF·F + 0.5·rT·T + 0.5·rS·S)).
- T = current IT intake × 0.95 and S = current IT intake × 0.97. Both are estimates, counted at 50% for the 2026 window.
- V_min is at least 2 wherever F > 0 and the college has a contact line.
- Non-IT final-years (N) are not counted, because no course for them is offered yet.

**College type (sets k):**
- (a) Deemed or private universities: c1, c2, c3, c4, c5, c6, c7, c80, c94.
- (d) Women's colleges: c19, c26, c30, c33, c40, c49, c69, c149.
- (b) Other DB Tier 1 and Tier 2 colleges.
- (c) All the rest.

**Access factor (x):** 1.0 with a verified TPO/placement line, 0.8 with an office line only, 0.6 with no line.

### 400-per-college test

- **GREEN:** V_avg ≥ 400.
- **AMBER:** V_max + 0.5 × (F + T + S) ≥ 400, and the college is type (a) or (b). Reachable only through an institutional MoU from Jan 2027. Whether management is open to one has not been checked.
- **RED:** everything else.

**MoU pipeline:** I = 30% / 50% / 80% × (T + S). This is Jan 2027 onward and is not counted in 2026.

### Staffing

- **Ambassadors:** A = max(3, ceil(ceil(1.2 × min) / 2.5)). Standby = ceil(A / 4).
- **College Leads:** a college gets its own lead if A ≥ 4. Colleges at the floor of 3 are paired within the same town cluster and share one lead (counted 0.5 each). A floor-size college with no partner in its town gets its own lead. 20 colleges fall in this case. (QA note, 7 Nov 2026.)
- **Avg floor:** where the formula gives V_avg below the V_min floor of 2, V_avg is raised to V_min. This applies to 5 colleges: c35, c85, c88, c90 and c146. (QA note.)
- **District/City Leads:** ceil(College Leads / 6) per old district.

### Hold colleges (2026 target 0, no staffing)

- c3 SRM AP, c5 VVIT University and c96 RGUKT: no intake data.
- c50 CAE and c51 CFST: no IT branch.
- c160 ISTS and new-ANRG: no final-year batch.

### Priority score (0-100)

| Component | Max points |
|---|---|
| IT pool | 35 |
| Contact | 15 |
| Digital and community | 15 |
| Exam window | 10 |
| Fill and quality | 10 |
| Tier and NAAC | 15 |

- **Levels:** P1 ≥ 65, P2 45-64.9, P3 < 45.
- **Exam-window points** come from the 4-1 end-sem end date in the DB `exams` table: ends by 29 Nov = 10, by 6 Dec = 7, by 12 Dec = 4, later = 2, unknown = 5.
