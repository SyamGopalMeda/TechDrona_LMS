# Student strength gap-closing: Krishna / Guntur / West Godavari B.Tech colleges (7 Nov 2026)

Companion files in this folder: `strength_updates.csv` (68 rows) and `branch_updates.csv` (36 rows).
- Every verified number in them carries a URL.
- Every estimate states its method.
- PDFs were downloaded with curl and read with PyMuPDF.
- nirfindia.org and facilities.aicte-india.org refused scripted access (HTTP 403 and TLS reset respectively), so only college-hosted copies were usable.

## Q1. Hold and unknown colleges: SRM AP, VIT-AP, VVIT University, RGUKT Nuzvid, KHIT, KITS, KITS Akshar, SMCE, PITM, PITW, VNRCE

### Takeaway
Hard numbers were found for VIT-AP, VVIT, SMCE and PITW. KITS, KHIT, KITS Akshar, VNRCE and PITM only have 2026 seat counts and fill rates from the official EAPCET CAP list.

**VIT-AP (actual admitted, 2023 entry)**
- B.Tech 3,492, of which IT 3,025.
- With its 5-year integrated CSE/SE students, IT is 3,597.
- This is far above the tracker's estimate of 2,142 / 1,581.

**VVIT:** 2023-24 sanctioned intake is 1,740.

**SMCE**
- 2023-24 sanctioned intake: 540 (IT 480).
- Actually admitted: only 393 (IT 363).

**SRM AP:** remains a gap.

### Cited Findings
**VIT-AP: students admitted in 2023 (2023-24 annual report)** ([VIT-AP Annual Report 2023-24](https://universitywebsitbucket.s3.ap-south-1.amazonaws.com/Annual+Reports/Annual+Report_2023-24.pdf))

| Programme | 2023 intake | Page |
|---|---|---|
| B.Tech CSE (all specialisations) | 2,798 | 53 |
| CSE-Business Systems | 227 | 53 |
| ECE | 373 | 74 |
| Mechanical | 94 | 88 |
| 5-yr integrated M.Tech Software Engineering | 288 | 53 |
| Integrated M.Tech with Virtusa | 284 | 53 |

- **B.Tech intake by entry year:** 2020: 1,394 | 2021: 2,868 | 2022: 3,326 | 2023: 3,492 ([same report](https://universitywebsitbucket.s3.ap-south-1.amazonaws.com/Annual+Reports/Annual+Report_2023-24.pdf)).
- **Hostel residents in 2023-24, men + women:** 1st year 3,253 / 2nd 3,032 / 3rd 1,936 / 4th 116 ([same report, p301-303](https://universitywebsitbucket.s3.ap-south-1.amazonaws.com/Annual+Reports/Annual+Report_2023-24.pdf)).
- **2024 graduates:** 1,524 students in total, 517 placed ([same report, p47](https://universitywebsitbucket.s3.ap-south-1.amazonaws.com/Annual+Reports/Annual+Report_2023-24.pdf)).

**VVIT (Nambur), from its NIRF 2025 data**
- **UG sanctioned intake:** 2023-24: 1,740; 2022-23: 1,620; 2021-22: 1,440; 2020-21: 1,260.
- **UG strength:** 6,060 ([VVIT NIRF 2025](https://www.vvitguntur.com/images/documents/NIRF/NIRF-VVIT-2025.pdf)).
- Caution: 6,060 is exactly the sum of the four sanctioned years, so it may be seats rather than a head-count.
- **2020-21 cohort:** 1,235 admitted of 1,260 seats.

**SMCE (Sri Mittapalli)**
- **NIRF 2026:** UG sanctioned 2023-24 = 540 (2024-25 = 810); UG strength 1,922 ([SMCE NIRF 2026](https://www.smce.ac.in/pdfs/FINAL-REPORT-ENGG-2026.pdf)).
- **Mandatory Disclosure (Nov 2025)** ([SMCE Mandatory Disclosure](https://www.smce.ac.in/pdfs/mandatory-disclosure.pdf)):

  | Branch | Sanctioned 2023-24 | Admitted 2023-24 |
  |---|---|---|
  | CSE | 240 | 176 |
  | IT | 60 | 28 |
  | CSE(AI) | 120 | 109 |
  | CSE(DS) | 60 | 50 |
  | ECE | 60 | 30 |
  | **Total** | **540** | **393** |

- **Admitted in other years:** 2024-25: 796 of 810; 2025-26: 340 of 930 (same source).

**PITW**
- AICTE EoA 2026-27 approves CSE 120 + ECE 60 = 180 seats for both 2025-26 and 2026-27 ([PITW EoA](https://pitw.ac.in/aicte-eoa.pdf)).
- It was not possible to find the 2023-24 EoA.

**PITM**
- The latest EoA on its site is for 2021-22: CSE 60, AI&DS 60, ECE 120, EEE 60, Civil 60, Mech 60, a total of 420 ([PITM EoA 2021-22](https://pitmgnt.ac.in/assets/documents/AICTE-EOA-2021-22.pdf)).

**EAPCET CAP 2026 convener seats and seats left over** ([APSCHE CAP API](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details))

| College | Convener seats | Left over | Share filled |
|---|---|---|---|
| KITS (code KITS) | 1,104 (IT 912) | 6 | about 99% |
| KHIT | 1,248 (IT 1,008) | 557 | 55% |
| KITS Akshar (KITG) | 672 (IT 576) | 147 | 78% |
| SMCE (MPLG) | 744 | 646 | 13% |
| PITM (PIIT) | 288 | 215 | 25% |
| PITW | 144 | 118 | 18% |
| VNRCE (VNRC) | 360 | 358 | 2 seats filled |

- **Check on the 0.8 convener share:** PITW's 144 convener seats ÷ 0.8 = 180, which matches its EoA.

**RGUKT Nuzvid**
- RGUKT allots 1,000 general seats + 100 EWS seats to each campus ([Deccan Chronicle, July 2024](https://deccanchronicle.com/southern-states/andhra-pradesh/4400-students-selected-for-rgukt-in-ap-1809741)).
- The same 4,400-seat structure (1,000 + 100 per campus) was reported for 2020-21 (search snippet only; I did not open the article).

### Inferences
**Current intake estimates (CAP 2026 convener seats ÷ 0.8):** these are estimates, not 2023-24 figures.

| College | Total | IT |
|---|---|---|
| KITS | 1,380 | 1,140 |
| KHIT | 1,560 | 1,260 |
| KITS Akshar | 840 | 720 |
| VNRCE | 450 | 240 |
| PITM | 360 | 210 |

**Batch sizes**
- VNRCE's real batch is probably close to zero.
- SMCE's 2026 entry batch is under about 150.
- **VVIT IT final-year, estimated:** about 1,044 (1,740 × the tracker's median verified IT share of 0.60).
- **RGUKT Nuzvid E4 2026-27 batch (2021 PUC entry), estimated:** about 1,100 before attrition.
- **VIT-AP:**
  - It is the second-largest single IT pool in the tracker, after KL.
  - Replacing the estimated 1,581 IT pool with the verified 3,025 adds about 1,444 students to the IT pool. With the integrated students it adds about 2,016.

### Gaps
- **SRM AP:** no figures at all.
  - srmap.edu.in exposes no NIRF, AQAR or annual-report PDFs without JavaScript; /naac/, /iqac/ and /aqar/ return 404.
  - nirfindia.org returns 403.
  - SRM AP is not in the CAP list.
- **No 2023-24 intake for KITS, KHIT or KITS Akshar.**
  - The KITS and KITS Akshar sites sit behind a Cloudflare challenge.
  - KHIT's new site carries no NIRF or EoA PDFs.
- **No 2023-24 figure for VNRCE or PITM.**
- **No branch split for VVIT 2023-24 or RGUKT.**
- **No 2021 RGUKT seat document:** the 2021 notification I fetched gives no per-campus seats.

## Q2. Colleges with a verified total but no verified IT split

### Takeaway
VITB is resolved by its 2023-24 EoA: 1,140 seats, IT 780.
- This conflicts with NIRF's 1,020; the tracker's rule is to prefer the EoA.

No 2023-24 branch split could be found for VFSTR, RVR&JC, SRKR, Sri Vasavi, NRIIT Agiripalli, St. Ann's, ANUCET, AM Reddy, NIT AP, Nimra or KL. Their IT pools stay estimated.

### Cited Findings
**Vishnu Institute of Technology (VITB), AICTE EoA 2023-24** ([Vishnu EoA 2023-24](https://vishnu.edu.in/Docs/AICTE/EOA_Report_202324_VIT.pdf))

| Branch | 2023-24 seats |
|---|---|
| CSE | 240 |
| IT | 240 |
| CSBS | 60 |
| CSE(AI&DS) | 120 |
| CSE(AI&ML) | 120 |
| ECE | 180 |
| EEE | 60 |
| Civil | 60 |
| Mechanical | 60 |
| **Total** | **1,140 (IT 780)** |

- The EoA's 2022-23 column totals 1,020.
- NIRF 2026 instead says 2023-24 = 1,020 and 2024-25 = 1,140 ([VITB NIRF 2026](https://vishnu.edu.in/Docs/NIRF/IR_O-C-18099-NIRF-2026-VITB.pdf)).

**NIRF fill on the latest cohort NIRF reports** (the cohort that has already graduated)

| College | Cohort | Admitted / seats | Source |
|---|---|---|---|
| SRKR | 2021-22 | 1,739 / 1,740 | [SRKR NIRF 2026](https://www.srkrec.ac.in/assets/documents/mandates/NIRF_2026_engineering.pdf) |
| Sri Vasavi | 2021-22 | 960 / 960 | [SVEC NIRF 2026](https://srivasaviengg.ac.in/uploads/nirf/Engg%20Submitted%20Data%20SRI%20VASAVI%20ENGINEERING%20COLLEGE20260226-.pdf) |
| RVR&JC | 2021-22 | 1,091 / 1,140 | [RVR NIRF 2026](https://rvrjcce.ac.in/files/nirf/Engineering_2026.pdf) |
| NRIIT Agiripalli | 2021-22 | 899 / 1,020 | [NRIIT NIRF 2026](https://nriit.edu.in/wp-content/uploads/2026/04/NRI-Institute-of-Technology20260402.pdf) |
| St. Ann's | 2020-21 | 611 / 840 | [SACET NIRF](https://sacet.ac.in/wp-content/uploads/ST-ANNS-COLLEGE-OF-ENGINEERING-AND-TECHNOLOGY__Engineering.pdf) |
| ANUCET | 2021-22 | 321 / 300 | [ANUCET NIRF 2026](https://www.nagarjunauniversity.ac.in/assets/notifications/ucet.pdf) |
| AM Reddy | 2021-22 | 152 / 330 | [AMRMCET NIRF](https://amreddyengineering.ac.in/assets/pdfs/nirf/nirf-2024-25.pdf) |
| VFSTR | 2020-21 | 1,602 / 1,830 | [VFSTR NIRF 2025](https://www.vignan.ac.in/nirf/NIRF%202025%20Engineering%20DCS.pdf) |

**CAP 2026 IT share of convener seats** ([CAP API](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details))

| College | IT seats / convener seats |
|---|---|
| SRKR | 624 / 1,104 |
| Sri Vasavi | 480 / 864 |
| RVR&JC | 816 / 1,248 |
| AM Reddy | 264 / 408 |

These are current shares, not 2023-24.

### Inferences
- **VITB:** applying the EoA rule gives a final-year pool of 1,140 and an IT pool of 780. The previous figures were 1,020 and 698 (estimated).
- **Colleges still without a split:** current-share estimates remain the best available. They are probably similar to the tracker's existing method.
- **SRKR and Sri Vasavi fill completely:** NIRF admitted equals intake, and CAP 2026 had almost no seats left over, so sanctioned seats are a good proxy for the actual batch.

### Gaps
- **No 2023-24 EoA or branch-wise intake was found** for: c1 KL, c2 VFSTR, c9 RVR&JC, c147 SRKR, c153 Sri Vasavi, c94 NRIIT Agiripalli, c53 St. Ann's, c8 ANUCET, c38 AM Reddy, c146 NIT AP and c75 Nimra.
- **Why the AICTE route failed:** the AICTE dashboard API, which would give the branch split for every AICTE college, was unreachable (TLS reset).
- **KL and VFSTR are deemed universities** and do not file AICTE EoAs.

## Q3. NEC Narasaraopet: AICTE EoA 1,500 vs NIRF 960

### Takeaway
The 2023-24 EoA's 1,500 is correct; NIRF's 960 is not credible. An NBA filing confirms the EoA at branch level. NEC's NIRF entries look formulaic.

### Cited Findings
**AICTE EoA 2023-24** ([NEC EoA 2023-24](https://www.nrtec.in/wp-content/uploads/2023/09/AICTE-2023-24-1.pdf))

| Branch | 2023-24 seats |
|---|---|
| CSE | 420 |
| CSE(AI) | 120 |
| CSE(AIML) | 120 |
| CSE(CS) | 60 |
| CSE(DS) | 60 |
| AI&ML | 60 |
| IT | 120 |
| ECE | 360 |
| EEE | 60 |
| Civil | 60 |
| Mechanical | 60 |
| **Total** | **1,500 (IT 960)** |

The EoA's 2022-23 column totals 1,020.

**NIRF 2026** ([NEC NIRF 2026](https://www.nrtec.in/wp-content/uploads/2026/04/Engineering-2026-submitted.pdf))
- UG sanctioned intake is 960 for every year from 2021-22 to 2024-25.
- Admitted equals intake in every cohort.
- UG strength is 3,840, which is exactly 4 × 960.

**NBA filing for CSE(AI), 2026** ([NEC NBA CSE-AI DCS 2026](https://www.nrtec.in/wp-content/uploads/2026/08/NBA-CSE-AI-DCS-2026.pdf)), Table B3.1
- **Sanctioned intake:** 60 → 60 → 120 → 180 → 300 (2021-22 to 2025-26).
- **2023-24:** 104 admitted + 12 supernumerary, against 120 seats.

**CAP 2026:** NEC does not appear at all in the CAP list ([CAP API](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details)). I searched it for "NARAS".

### Inferences
- **Sanctioned batch:** keep 1,500 (IT 960) as the 2023 sanctioned batch.
- **Actual batch, estimated (low confidence):** about 1,300 (IT about 835). Method: apply the CSE(AI) regular-admission fill of 87% (104 of 120) to every branch.
- **Change from the blueprint:** the blueprint's 960 should not be revived.

### Gaps
- No NEC-wide figure for students admitted in 2023-24 was found.
- It is unclear why NEC is missing from CAP 2026: it may admit through another route or may have changed status. This should be checked.

## Q4. MIET, Nimra and other colleges: students actually admitted vs seats sanctioned

### Takeaway
**NIRF limits**
- NIRF never reports students admitted in 2023-24.
- Its "admitted in first year" column covers only the cohort that has already graduated: 2021-22 in NIRF 2026, 2020-21 in NIRF 2025.
- Real 2023-24 admissions were found only in mandatory disclosures (SMCE, Usha Rama, SRGEC, CRR, MAMW), in NEC's NBA filing, and in VIT-AP's annual report.

**MIET and Nimra fill only a third to half of their seats.** Estimated actual batches:

| College | Actual batch, estimated | Sanctioned |
|---|---|---|
| MIET | about 110 (range 100-165) | 315 |
| Nimra | about 100-130 | 360 |

### Cited Findings
**MIET (NIRF 2025)** ([MIET NIRF 2025](https://mandava.ac.in/wp-content/uploads/2025/01/MANDAVA-INSTITUTE-OF-ENGINEERING-AND-TECHNOLOGY20250109-Engineering.pdf))
- Admitted / seats: 2018-19: 111 / 420; 2019-20: 93 / 285; 2020-21: 164 / 315.
- UG strength: 436.

**Nimra (NIRF 2026)** ([Nimra NIRF 2026](https://nimracet.in/images/downloads/nirf/nirf-2026.pdf))
- Admitted / seats: 2019-20: 42 / 300; 2020-21: 53 / 270; 2021-22: 97 / 270.
- UG strength: 408.

**CAP 2026 fill** ([CAP API](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details))
- MIET: 145 of 204 convener seats left over.
- Nimra: 56 of 84 left over.

**Real 2023-24 admissions from mandatory disclosures**

| College | Admitted 2023-24 | Sanctioned | Source |
|---|---|---|---|
| Usha Rama | 542 (IT 321) | 540 (IT 300) | [Usha Rama MD](https://cdn.usharama.edu.in/documents/mandatory-disclosure.pdf) |
| SRGEC (UG) | 1,318 (Category A 955 + Category B 363) | 1,380 (EoA) or 1,500 (NIRF) | [SRGEC MD 2026](https://gecgudlavalleru.ac.in/images/admin/pdf/1707315874_Mandatory%20Disclosure%202026%20final.pdf) |
| CRR | 1,039 (category-wise total; management quota 232) | 1,050 | [CRR MD 2025-26](https://sircrrengg.ac.in/images/MANDATORYDISCLOSURE/MANDATORY_DISCLOSURE_2025-26.pdf) |
| MAMW | 111 (all CSE) | — | [MAMW MD](https://www.mamw.org/files/mandatory-disclosures.pdf) |
| SMCE | 393 | 540 | Q1 above |

Usha Rama's admitted branch split: CSE 131, IT 63, AI&ML 64, AI&DS 63, ECE 188, EEE 23, ME 10.

**Latest-cohort fill for the top-20 colleges by IT pool**

- **Full rows are in `strength_updates.csv`** (field `nirf_latest_cohort_fill`).

| Fill band | College | Admitted / seats | Cohort |
|---|---|---|---|
| About 100% | KL | 3,060 / 3,060 | 2021-22 |
| | SRKR | 1,739 / 1,740 | 2021-22 |
| | SRGEC | 1,219 / 1,260 | 2021-22 |
| | Swarnandhra | 822 / 840 | 2021-22 |
| | Sri Vasavi | 960 / 960 | 2021-22 |
| | RVR&JC | 1,091 / 1,140 | 2021-22 |
| | VITB | 1,039 / 900 | 2021-22 |
| | Malineni Women's | 388 / 360 | 2021-22 |
| | LBRCE | 841 / 900 | 2020-21 |
| | CRR | 764 / 810 | 2020-21 |
| About 80-90% | NRIIT Agiripalli | 899 / 1,020 | 2021-22 |
| | VFSTR | 1,602 / 1,830 | 2020-21 |
| | Chalapathi University | 482 / 540 | 2021-22 |
| | MIC | 581 / 720 | 2021-22 |
| About 70% | Vignan's Lara | 546 / 780 | 2021-22 |
| | St. Ann's | 611 / 840 | 2020-21 |
| | DIET | 414 / 570 | 2020-21 |

Sources: [KL](https://www.kluniversity.in/NIRF/ENGINEERING-2026.pdf), [SRKR](https://www.srkrec.ac.in/assets/documents/mandates/NIRF_2026_engineering.pdf), [SRGEC](https://gecgudlavalleru.ac.in/images/admin/pdf/1775620595_NIRT%202026%20-%20Engineering.pdf), [Swarnandhra](https://www.swarnandhra.ac.in/data/nirfdata2021/nirf2026.pdf), [Sri Vasavi](https://srivasaviengg.ac.in/uploads/nirf/Engg%20Submitted%20Data%20SRI%20VASAVI%20ENGINEERING%20COLLEGE20260226-.pdf), [RVR&JC](https://rvrjcce.ac.in/files/nirf/Engineering_2026.pdf), [VITB](https://vishnu.edu.in/Docs/NIRF/IR_O-C-18099-NIRF-2026-VITB.pdf), [Malineni Women's](http://mlewguntur.com/Engineering-NIRF%202026.pdf), [LBRCE](https://www.lbrce.ac.in/iqac/nirf/2025/NIRF_2025_Engg_Submitted.pdf), [CRR](https://sircrrengg.ac.in/images/crr/NIRFCRRE25.pdf), [NRIIT](https://nriit.edu.in/wp-content/uploads/2026/04/NRI-Institute-of-Technology20260402.pdf), [VFSTR](https://www.vignan.ac.in/nirf/NIRF%202025%20Engineering%20DCS.pdf), [Chalapathi University](https://city.ac.in/Files/nirf-e-2025.pdf), [MIC](https://www.mictech.edu.in/images/pdfs/NIRF-2026.pdf), [Vignan's Lara](https://www.vignanlara.org/NIRF/DCS%20Report%20NIRF%202026.pdf), [St. Ann's](https://sacet.ac.in/wp-content/uploads/ST-ANNS-COLLEGE-OF-ENGINEERING-AND-TECHNOLOGY__Engineering.pdf), [DIET](https://diet.ac.in/wp-content/uploads/2025/02/NIRF-2025_DHANEKULA-INSTITUTE-OF-ENGINEERING-TECHNOLOGY20250107.pdf).

**CAP 2026 fill for the other top-20 colleges** ([CAP API](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details))

| College | Convener seats | Left over |
|---|---|---|
| MVR | 672 | 398 |
| St. Mary's Guntur | 546 | 205 |
| Swarnandhra | 1,104 | 265 |
| Sasi | 840 | 5 |
| Bapatla EC | 912 | 12 |
| SRGEC | 1,104 | 4 |
| CRR | 912 | 6 |

### Inferences
**Suspect NIRF figures.** The entries below should be treated as seats, not head-count:

| College | NIRF strength | What it equals |
|---|---|---|
| NEC | 3,840 | Exactly 4 × 960 |
| VVIT | 6,060 | Exactly the sum of the four sanctioned years |
| PVPSIT | 2,940 | Exactly the sum of the four sanctioned years |
| KL | 13,487 | Within 13 seats of the sanctioned sum |

**How to estimate a real batch:** multiply the sanctioned 2023-24 seats by the college's latest NIRF fill, or use its 2026 CAP fill as a sign of trend.

**Colleges where real batches are much smaller than sanctioned**

| College | Measure |
|---|---|
| AM Reddy | 46% filled (NIRF) |
| MIET | 52% filled (NIRF), 29% (CAP 2026) |
| Nimra | 36% filled (NIRF), 33% (CAP 2026) |
| VITW | 71% filled (NIRF) |
| VGI | 64% filled (NIRF) |
| SMCE | 73% filled in 2023-24 (mandatory disclosure) |
| MVR | 41% filled (CAP 2026) |

The tracker should apply these fills as haircuts.

### Gaps
- **Real 2023-24 admissions** were not found for most top-20 colleges: KL, VFSTR, SRKR, RVR&JC, Swarnandhra, NRIIT Agiripalli, VITB, Sri Vasavi, KITS, KHIT and MVR.
- **Where they would be:** in each college's AICTE-format mandatory disclosure, which was not posted or not found for these colleges.
- **Not yet checked:** NBA SARs, the other source that gives branch-level admissions, were checked only for NEC.
