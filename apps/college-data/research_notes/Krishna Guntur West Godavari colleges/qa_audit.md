# QA audit: Krishna / Guntur / West Godavari B.Tech tracker (7 Nov 2026)

This is an independent audit of:
- `master_colleges.csv` and `master_branches.csv`
- `consolidation.md` and `decisions_log.md`
- the district CSV and markdown notes
- `reports/Krishna Guntur West Godavari colleges tracker.xlsx`

The portal DB `portal/data/techdrona.db` was opened read-only (`mode=ro`) and nothing was written to it. Backups of every file changed are in the session scratchpad: `...\scratchpad\backup\`.

**How the checks were made:**
- Every total was recomputed in Python from the master CSV.
- The workbook's formulas were evaluated manually in Python, because LibreOffice is not installed. The workbook has no cached values: it was written by openpyxl and has never been recalculated. Excel will calculate it when it is opened.
- Source PDFs were fetched and their text read with PyMuPDF.

## Pass / fail by check

| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Duplicates (colleges and branches) | **PASS** | See section 1. |
| 2 | Arithmetic: consolidation.md and xlsx totals, formulas | **PASS** (2 documentation gaps fixed) | Every total reproduces exactly. Formula ranges and SUMIFS criteria are correct, and there is no #REF. |
| 3 | Provenance of "verified" figures | **PASS** (16 of 16 spot-checks). Citation weakness fixed. | Every verified figure has a URL. 6 of the cited URLs are later-year EoAs that do not show 2023-24. |
| 4 | Fabrication and privacy | **PASS** after 1 fix | 9 of 10 contacts matched on the source page. One KRUCET number was removed. No student data was found. People, Leads and Enrollments have 0 data rows. |
| 5 | Status logic | **PASS** | Each of the 88 active colleges has EAPCET-2026, AICTE, NIRF or Oct-2026 dated evidence. Nothing is called "closed". |
| 6 | Consistency with the blueprint | **PASS**, with corrections listed | See section 6. |
| 7 | c154 WISE coverage gap | **FIXED (logged)** | Added as a `scope_in=gap` row with an indicative target, kept out of the totals. |

## 1. Duplicates

**College rows.** I checked shared website domains, name similarity above 0.75, EAPCET codes and towns.
- The only shared domains are c87/c103 (lingayas.edu.in) and c40/c59 (mamw.org). Both pairs are already merged.
- **c23 vs c94 NRIIT:** these are distinct colleges.

  | | c23 | c94 |
  |---|---|---|
  | Website | nriit.ac.in | nriit.edu.in |
  | Admission | EAPCET code NRIT | NRIUCET |
  | Town | Visadala | Agiripalli |
  | NIRF id | own filing (660) | IR-E-C-17942 (1,200) |

  Each is counted once.
- **c72/c73, c98/c74, c103/c87, c59/c40, c11/c7:** each duplicate has `status_final=duplicate` and empty pools. No branch rows are counted for them, and they are excluded from every total.
- **c7 Chalapathi University:** its 2023 batch of 720 (IT 540) is counted only under c7.
- **Look-alike pairs:** each was confirmed to be two different colleges.

  | Pair | Colleges | What distinguishes them |
  |---|---|---|
  | c70 / c71 | Vikas CET / VGI | AICTE permanent ids 1-4233034 and 1-5601571 differ; EAPCET codes VCTN and VGTN. Both have an identical 2023-24 mix of 480 (IT 270), confirmed on the two separate EoAs. |
  | c12 / c14 | KITS / KITS Akshar | EAPCET codes KITS and KITG |
  | c24 / c25 / c26 | Priyadarshini colleges | — |
  | c32 / c33 | Vignan's Lara / Vignan's Nirula | — |
  | c48 / c49 | Bapatla Engineering / Bapatla Women's | — |

**Branch rows.**
- There is no duplicate (college, normalised branch) row among counted rows.
- Three branch duplicates are already excluded: c8 Space Science, c94 CSE(AI&ML), and the DB-only duplicate of VWU AI&ML.
- None of the 653 counted branch rows belongs to an excluded college.

## 2. Arithmetic

All figures were recomputed from `master_colleges.csv` (active, in scope, 88 colleges). Each matches consolidation.md and the workbook.

| Item | Recomputed | Doc / xlsx |
|---|---|---|
| All-branch final-year pool, verified | 41,216 (52 colleges) | 41,216 (52) ✓ |
| All-branch final-year pool, estimated | 17,896 (34 colleges) | 17,896 (34) ✓ |
| All-branch final-year pool, unavailable | 2 colleges | 2 ✓ |
| IT pool F, verified | 16,401 (42 colleges) | 16,401 (42) ✓ |
| IT pool F, estimated | 21,701 (43 colleges) | 21,701 (43) ✓ |
| IT pool F, unavailable | 3 colleges | 3 ✓ |
| Verified share of the IT pool | 43.0% | 43% ✓ |
| Total IT pool F | 38,102 | 38,102 ✓ |
| Minimum / average / maximum | 363 / 637 / 1,113 | ✓ |
| Old Krishna: colleges, minimum / average / maximum | 27, 88 / 153 / 267 | ✓ |
| Old Krishna: Krishna district | 12 colleges, 37 / 63 / 108 | ✓ |
| Old Krishna: NTR district | 15 colleges, 51 / 90 / 159 | ✓ |
| Old Guntur: colleges, minimum / average / maximum | 44, 194 / 348 / 616 | ✓ |
| Old Guntur: Guntur district | 28 colleges, 148 / 275 / 497 | ✓ |
| Old Guntur: Palnadu district | 10 colleges, 33 / 51 / 81 | ✓ |
| Old Guntur: Bapatla district | 6 colleges, 13 / 22 / 38 | ✓ |
| Old West Godavari: colleges, minimum / average / maximum | 17, 81 / 136 / 230 | ✓ |
| Old West Godavari: West Godavari district | 9 colleges, 56 / 94 / 154 | ✓ |
| Old West Godavari: Eluru district | 8 colleges, 25 / 42 / 76 | ✓ |
| Pre-2022 Guntur (minimum / average / maximum) | 188 / 338 / 598 | ✓ |
| Pre-2022 Krishna | 96 / 168 / 296 | ✓ |
| Pre-2022 West Godavari | 73 / 121 / 201 | ✓ |
| Pre-2022 Prakasam | 6 / 10 / 18 | ✓ |
| Ambassadors: A = max(3, ceil(ceil(1.2·min)/2.5)) | 290; all 81 rows correct | ✓ |
| Standby: ceil(A/4) | 91 | ✓ |
| Buffered minimum | 475 | ✓ |
| College Leads | 62 (43 own leads + 38 colleges sharing 19) | ✓ |
| District/City Leads | 3 + 6 + 3 = 12 | ✓ |
| RAG ratings | GREEN 0, AMBER 30, RED 58 (re-derived from the rule) | ✓ |
| Priority levels | P1 24, P2 36, P3 21, Hold 7 | ✓ |
| MoU pipeline | 28,422 / 47,388 / 75,794 | ✓ |
| Share of the 400 | 91% / 159% / 278%; 37 short; 46 above Table A; 446 with the out-of-scope Godavari rows | ✓ |
| min ≤ avg ≤ max | holds for all 81 targeted colleges | ✓ |
| Target formula V_s (rF, rT, rS, k, x, floor) | reproduces all 243 values, with one exception (below) | ✓ |

The one exception: for c35, c85, c88, c90 and c146 the formula gives an average of 1, which was raised to the minimum floor of 2. This rule was undocumented and is now documented in decisions_log.md.

**Workbook checks:**
- The 'Priority & Targets' sheet matches master on 15 columns for all 88 rows. The only differences are blank vs NaN for the Hold rows c3, c5 and c96.
- The 'District rollup' COUNTIFS and SUMIFS formulas point at the correct columns (Q, Y, Z, AA, AE–AH, AK, AL) over rows 2–89.
- The criteria strings ("Old Krishna", "NTR" and so on) match the cell values exactly. A Python evaluation reproduces the table above.
- The Dashboard references 'Priority & Targets' rows 2–89 and Leads, Enrollments and People rows 2–1001. No #REF was found.

**Branch intake vs college totals (minor, not fixed):** the current-intake branch sums differ from the college's current intake for six colleges:
- c2 (1,890 vs 2,580)
- c156 (1,380 vs 1,200)
- c75 (120 vs 240)
- c8 (520 vs 480)
- c83 (720 vs 660)
- c153 (1,260 vs 1,320)

None of these figures feeds a pool. The 2023-24 branch sums equal the verified totals where branch data exists (for example c7 720/540, c40 111, c74 315/120 and c156 1,050/600).

**Documentation gap fixed:** 20 colleges at the floor of 3 ambassadors have their own lead, because they have no same-town partner. decisions_log.md implied that every floor college is paired. The rule is now documented, and the counts were unchanged.

## 3. Provenance spot-checks

All 54 rows marked verified have an `http` source URL. No figure needed to be downgraded. I fetched these PDFs and read the 2023-24 figure from each:

| College | Claimed | Source read | Result |
|---|---|---|---|
| c36 NEC | 1,500 (IT 960) | AICTE EoA 2023-24 (nrtec.in/…/2023/09/AICTE-2023-24-1.pdf): 1,500, IT 960. NIRF 2026 shows 960 for every year. | PASS. The conflict is real. The EoA is preferred per the rule. |
| c1 KL | 3,510 | NIRF 2026: 3,510 | PASS |
| c2 VFSTR | 2,580 | NIRF 2025: 2,580 | PASS |
| c147 SRKR | 1,860 | NIRF 2026: 1,860 | PASS |
| c82 SRGEC | 1,380 (IT 900) | Mandatory Disclosure 2026: branch seats for 2023-24 sum to 1,380 (IT 900); 2024-25 is 1,500 | PASS |
| c62 LBRCE | 1,080 (IT 600) | AICTE EoA 2023-24: 1,080 (IT 600) | PASS |
| c9 RVR&JC | 1,380 | NIRF 2026: 1,380 | PASS |
| c7 Chalapathi University | 720 | CITY NIRF 2025: 720 | PASS |
| c42 TEC | 810 (IT 480) | AICTE EoA 2023-24: 810 (IT 480) | PASS |
| c155 SCET | 1,230 | NIRF 2026: 1,230 | PASS |
| c156 CRR | 1,050 | NIRF 2025: 1,050 | PASS |
| c32 VLITS | 960 | NIRF 2026: 960 | PASS |
| c10 CIET | 780 | NIRF 2025: 780 | PASS |
| c94 NRIIT Agiripalli | 1,200 | NIRF 2026 IR-E-C-17942: 1,200 | PASS |
| c70 Vikas CET | 480 (IT 270) | AICTE EoA 2023-24, inside a compiled PDF: 480 (IT 270) | PASS |
| c71 VGI | 480 (IT 270) | AICTE EoA 2023-24: 480 (IT 270) | PASS |

None was unreachable. WebFetch could not read the PDF text, so each PDF was extracted locally.

**Weakness found and fixed.** For several colleges, `total_intake_source_url` points to a later-year EoA (2025-26 or 2026-27) that does not contain 2023-24 at all: NEC, LBRCE, CITY, TEC, SCET and CRR. The 2023-24 source appeared only in the notes or branch rows. I added a `qa_fy_source_check` column to `master_colleges.csv` giving the exact 2023-24 URL and figure for all 16 colleges checked.

## 4. Fabrication and privacy

**Contacts.**
- 185 of the 207 phone and email values in active master rows match the portal DB `contacts` or `colleges` tables, which carry their own sources.
- I fetched 10 cited contact pages:

  | Result | College | What was checked |
  |---|---|---|
  | Match | c1 KL | 08645-350200 x1409, placements@ |
  | Match | c36 NEC | 9885553622, placements@nrtec.in |
  | Match | c63 MIC | 4 values |
  | Match | c67 SRKIT | 7674098333 / 9849651651 |
  | Match | c69 VITW | the same TPO line, legitimately shared with SRKIT |
  | Match | c80 SAHE | — |
  | Match | c84 DIET | — |
  | Match | c153 SVEC | x319 |
  | Match | c157 RCE | 8247494424 |
  | **Partial** | c90 KRUCET | 9154281361 is on the page. 08672-259207 is in the DB. **08672-259208 is on neither, so it was removed.** |

**Student data.**
- I scanned all CSV and MD files and the workbook for student names and mobile numbers. The only 10-digit matches are inside social-media URL ids.
- Student coordinators are recorded as roles only.
- No student personal data was found.

**Workbook sheets.**
- People, Leads and Enrollments contain 0 non-formula values. They hold only formula columns (auto lookups and duplicate checks), which return "" or 0 on empty rows.
- The Dashboard's actuals (leads, confirmed, amount, ambassadors recorded) all evaluate to 0.

**Portal DB.** It has 0 people, 0 enrollments and 0 calls.

## 5. Status logic

- **Active colleges (88):** each has EAPCET-2026 CAP, AICTE EoA or NIRF evidence. The exceptions are c96 RGUKT, which has a fee circular dated 07-10-2026 and a fest in Oct 2026, and c146 NIT AP, which has dated Aug–Oct 2026 homepage events. Both count as recent dated activity, so this passes.
- **Possibly closed (30):** each is marked "possibly closed (not in EAPCET-2026 list / no B.Tech activity found)". None is labelled `closed`, and no closure order is claimed.
- **Unverified (4):** these are excluded from the targets.

## 6. Differences from the blueprint ("Ambassador blueprint for 400 enrollments.md")

The report should state these as corrections.

| College | Blueprint | Now | Basis |
|---|---|---|---|
| NEC c36 | 960 (NIRF 2026), 839 adjusted eligible; target 6 / 10 / 17 | 1,500 total, IT 960 (AICTE EoA 2023-24); target 11 / 19 / 30 | EoA preferred over NIRF. The blueprint's text also says the 960 is the "2023-24 sanctioned intake". |
| SRGEC c82 | 1,500 ("matches DB", NIRF 2026) | 1,380 total, IT 900 | The 1,500 intake starts in 2024-25 (Mandatory Disclosure). |
| Chalapathi University c7 | 626 (assumption); target 5 / 8 / 13 | 720 verified, IT 540; target 5 / 10 / 20 | CITY NIRF 2025 |
| VLITS c32 | 1,163 (estimated); target 9 / 15 / 23 | 960 verified, IT 540; target 7 / 12 / 19 | NIRF 2026 and EoA |
| LBRCE c62 | 898 (estimated) | 1,080 verified, IT 600 (target unchanged at 7 / 11 / 18) | AICTE EoA 2023-24 |
| Amrita Amaravati c6 | 480 | 360 verified | AICTE letter |
| Vikas CET c70 | 791 (estimated); target 6 / 10 / 16 | 480 verified, IT 270; target 3 / 6 / 11 | AICTE EoA 2023-24 |
| KL c1 | 3,174 eligible; target 24 / 40 / 63 | IT 2,940 (estimated split of the verified 3,510); target 24 / 49 / 96 | DB BoM split |
| RVR&JC c9 | 1,200 eligible | 1,380 total, IT 869 (estimated) | NIRF 2026 |
| SCET c155 | 1,001 (verified-scaled) | 1,230 total, IT 780 verified | NIRF / EoA |

**Totals.** The blueprint's 52 Table A rows inside these districts total 317 / 527 / 841 (min / avg / max), with 151 ambassadors (minimum needed). This was recomputed from `table_a_college_targets.csv`. The tracker's 363 / 637 / 1,113 adds 29 colleges that are not in Table A. The 17 Table A rows outside the area carry a minimum of 83.

## 7. c154 WISE

c154 is the West Godavari Institute of Science & Engineering at Nallajerla. Nallajerla was in old West Godavari and is now in East Godavari.
- **Status:** active. The portal DB records it in the official EAPCET-2026 list (code WISE, 24/07/2026). I did not re-fetch that list.
- **Not covered anywhere:** it is missing from the district notes and from blueprint Table A. The Gaps sheet line saying it was "covered by Godavari plan" was wrong and has been corrected.
- **Added to master** as `scope_in=gap`:
  - current intake 270 (DB value derived from CAP seats, estimated); IT 210
  - fill-risk (134 of 216 convener seats left over), so the 0.6 factor applies
  - F 107, T 120, S 122
  - type c, x 0.8 (principal line, verified in DB)
  - indicative target 2 / 2 / 2, 3 ambassadors, RED, P3
  - **Not in the totals.** If activated, the totals become 365 / 639 / 1,115, with 293 ambassadors, 92 standby and 62.5 College Leads.

## Fixes applied (before → after)

| File | Change |
|---|---|
| master_colleges.csv | New column `qa_fy_source_check`, filled for 16 colleges with the 2023-24 URL and figure; blank before. |
| master_colleges.csv | c90 `contact_phone`: "08672-259207; 08672-259208; +91-9154281361" → "08672-259207; +91-9154281361". The reason is noted in `notes`. |
| master_colleges.csv | New row c154 WISE (`scope_in=gap`, not counted). Rows go from 129 to 130. Anyone counting `status_final=active` must still filter `scope_in=yes` to get 88. |
| tracker.xlsx | Colleges sheet: c90 `contact_phone` and `notes` changed as above. |
| tracker.xlsx | Gaps & Decisions: the c154 row is rewritten ("covered by Godavari plan" → gap in both plans, with the indicative impact). |
| tracker.xlsx | Gaps & Decisions: 3 QA rows added (provenance spot-check, contact spot-check, blueprint corrections). No formulas or ranges were changed. |
| consolidation.md | Quality item 11 now describes c154 and its indicative impact. |
| consolidation.md | Blueprint comparison: a bullet list of corrections was added (NEC, Chalapathi University, LBRCE, Amrita, Vikas CET). |
| consolidation.md | Staffing: the 43 own leads are explained as 23 with A ≥ 4 plus 20 unpaired floor colleges. |
| decisions_log.md | Lead rule for unpaired floor colleges, and the avg-floor rule (5 colleges). |
| decisions_log.md | c154 scope note. |

The master_branches.csv and portal DB were not changed. The district CSVs were not changed either; they are source records.

## Unresolved issues, ranked by severity

1. **High: the minimum misses 400.** The minimum of 363 is below 400, and 43% of the IT pool is verified. KL's 2,940 IT split (the largest single pool) is estimated, from a scanned BoM PDF. For the 11 colleges with a verified total but no branch split (c2, c8, c9, c38, c53, c94, c146, c147, c148, c153, c75), the IT pool is estimated.
2. **High: actual batches may be far smaller.** MIET c74 and Nimra c75 keep their verified sanctioned pools, but NIRF shows only 436 and 408 UG students across all years. Their real batches are probably much smaller.
3. **Medium: unchecked closures.** The 30 possibly-closed and 4 unverified colleges have not been checked against the JNTUK/ANU affiliation lists or AICTE closure lists.
4. **Medium: Hold colleges with no intake.** SRM AP, VVIT University and RGUKT Nuzvid have no intake data and carry a large upside.
5. **Medium: the NEC conflict is unresolved at source.** AICTE says 1,500 and NIRF says 960. If 960 is right, NEC's target falls back towards the blueprint's 6 / 10 / 17, and the overall minimum drops by about 4–5. Confirm on the TPO call.
6. **Medium: c154 WISE has no owner.** Decide whether to activate it and assign it to a lead (indicative 2 / 2 / 2).
7. **Low: no cached values in the workbook.** It shows blanks in viewers that do not recalculate, such as some previews. Open and save it in Excel once.
8. **Low: branch sums differ from current intake** at six colleges (section 2). Pools are not affected.
9. **Low: Lists sheet.** The `role` list has no "Payments & Data Verifier" option, although staffing includes the role.
10. **Low: DB corrections pending.** These are already listed in consolidation item 5. The DB was read-only here.

## Final verified totals (unchanged by this audit)

| Item | Value |
|---|---|
| In-scope rows | 127 |
| Active, counted | 88 |
| Targeted | 81 |
| Hold | 7 |
| Possibly closed | 30 |
| Duplicate | 5 |
| Unverified | 4 |
| IT final-year pool F | 38,102 (16,401 verified / 21,701 estimated) |
| All-branch final-year pool | 59,112 (41,216 verified / 17,896 estimated) |
| Target min / avg / max | **363 / 637 / 1,113** |
| Old Krishna | 88 / 153 / 267 |
| Old Guntur | 194 / 348 / 616 |
| Old West Godavari | 81 / 136 / 230 |
| College Leads | 62 |
| Ambassadors (recruit) | 290 |
| Standby | 91 |
| District/City Leads | 12 |
| RAG | GREEN 0 / AMBER 30 / RED 58 |
| Priority | P1 24 / P2 36 / P3 21 / Hold 7 |
| With c154 WISE (if activated) | 365 / 639 / 1,115; 293 ambassadors; 92 standby |
