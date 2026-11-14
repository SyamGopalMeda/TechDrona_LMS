# College-wise paid-enrollment targets (Table A) for Tech Drona's 400-by-31-Dec-2026 goal

Reference date: 3 Nov 2026. Deadline: 31 Dec 2026.

Inputs:
- The portal DB [portal/data/techdrona.db](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/portal/data/techdrona.db), opened read-only with `node:sqlite`. Only operational colleges were used: 113 operational, 107 of them with eligible students greater than 0.
- Earlier notes in [Path to 400 enrollments 2026](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/research_notes/Path%20to%20400%20enrollments%202026/), cited below as [CAP] = capacity_and_allocation.md, [BENCH] = benchmarks_channels.md, [CGK] = contacts_guntur_krishna.md and [CGOD] = contacts_godavari.md.
- 15 official-source spot checks done by web search and fetch on 3 Nov 2026.

Output: [table_a_college_targets.csv](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/research_notes/Ambassador%20blueprint%20for%20400%20enrollments/table_a_college_targets.csv). It has 69 rows.

**Column sums, re-checked by an independent Python parse of the saved CSV:**

| Column | Sum |
|---|---|
| eligible | 54,242 |
| min | **400** |
| avg | **663** |
| max | **1,061** |
| ambassadors_min_needed | **191** |

Scripts used (scratchpad): `pool.cjs` extracts the data from the DB, `adj.cjs` applies the corrections, `targets.cjs` scores the colleges and `final.cjs` writes the CSV and roll-ups. All four are in `C:\Users\SYAM\AppData\Local\Temp\claude\96bc413f2bb7cb1e\ed62faac-3ba3-484b-9f39-ef305ecac048\scratchpad\`.

Labels used for every figure:
- **verified**: from an official source such as AICTE EoA, NIRF DCS or a DB verified intake.
- **verified-scaled**: the official 2023-24 college total was used to scale the DB branch figures.
- **verified-total**: the official 2023-24 total equals the DB total, but the branch split is unverified.
- **estimated**: the DB figure, built from the 2026-27 EAPCET-derived intake, with a 0.85 haircut.
- **assumption**: no data. These figures are judgement calls.

## Q1. Which colleges give the highest potential for the least outreach effort?

### Takeaway
The best ratio of return to effort is in **18 P1 colleges**. Each has a large IT/CSE-allied 2023 batch, a verified TPO line in the DB, and most sit in a multi-college cluster or have a known exam window.

The 18 P1 colleges are:
- KL University, VFSTR, VLITS, RVR&JC and KHIT (Guntur: the Vaddeswaram, Vadlamudi and Chowdavaram clusters)
- SRKR, SVECW/VWU, SCET and SITE (West Godavari)
- SRGEC and SAHE (Krishna)
- LBRCE, Vikas CET and MVR (NTR)
- NEC and TEC (Narasaraopet)
- MLWEC (Guntur)
- ISTS (Rajanagaram)

Together they carry **156 min / 258 avg / 413 max** of the 400. The largest DB pools are Aditya University, Chalapathi University, GGU and VIT-AP. All four turned out to be either much smaller for the final-year batch than the DB says, or unverified, or without a TPO contact. None of them is P1.

### Cited Findings
- Scoring rule (an assumption, chosen for transparency). Score = adjusted eligible × contact factor × exam factor × cluster factor:
  - Contact factor: verified TPO in the DB `contacts` table = 1.0; another verified line only = 0.85; no verified line = 0.6.
  - Exam factor: 4-1 end-sem known and ending on or before 28 Nov = 1.0; ending on or before 11 Dec = 0.9; dates unknown = 0.85.
  - Cluster factor: ≥2 operational colleges in the same town = 1.05.
  - GGU's score is also halved, because only 3rd-years are available there.
  - Priority: **P1** = score ≥ 750 and a verified TPO. **P2** = score ≥ 500. **P3** = the rest. GGU and Chalapathi University are forced to P3 because their pools are assumptions.
  - Sources: [DB] contacts and exams tables.
- Priority totals in Table A:

| Priority | Colleges | Eligible (adj.) | Min | Avg | Max | Ambassadors (min plan) |
|---|---|---|---|---|---|---|
| P1 | 18 | 20,605 | 156 | 258 | 413 | 71 |
| P2 | 24 | 18,809 | 142 | 236 | 376 | 65 |
| P3 | 27 | 14,828 | 102 | 169 | 272 | 55 |
| **Total** | **69** | **54,242** | **400** | **663** | **1,061** | **191** |

- Contact status across the 69 colleges (DB `contacts`, basis = verified):

| Contact status | Colleges | Min | Avg |
|---|---|---|---|
| Verified TPO | 39 | 242 | 402 |
| Office, admissions or principal line only | 27 | 139 | 229 |
| No verified line at all | 3 (KITS Guntur, BEC, KITS Akshar) | 19 | 32 |

  The DB has 0 verified contacts for KITS Guntur (c12) and Bapatla Engineering College (c48). This matches [CGK]: kitsguntur.ac.in returned HTTP 403, and becbapatla.ac.in refused connections four times.
- Exam windows across the 69 colleges (DB `exams`, 4-1 rows):

| 4-1 window | Colleges | Min |
|---|---|---|
| End-sem known, open on or before 29 Nov (mostly the JNTUK window 16–27 Nov, open from 28 Nov) | 38 | 175 |
| Open only in December: SITE from 4 Dec, SRKR from 6 Dec, BEC from 12 Dec | 3 | 23 |
| 4-1 dates unknown (KL, VFSTR, VIT-AP, KHIT, VLITS, Pragati, SAHE, GGU, Chalapathi U and others) | 28 | 202 |

  The colleges with unknown dates carry 202 of the 400. VFSTR has only "before 2026-12-09 (inferred)". Aditya's 4-1 end-sem is calendar-planned for 2–21 Nov, so it is open from 22 Nov. Amrita Amaravati's ended 4 Nov.
- The densest clusters by minimum target:

| Town | Colleges | Min / avg / max |
|---|---|---|
| Bhimavaram | 4 (SRKR, VITB, SVECW, DNR) | 26 / 44 / 71 |
| Vaddeswaram | 1 (KL) | 24 / 40 / 63 |
| Vadlamudi | 2 (VFSTR, VLITS) | 20 / 34 / 53 |
| Rajanagaram | 3 (GGU, ISTS, GIET EC) | 19 / 31 / 51 |
| Chowdavaram | 2 (RVR&JC, KHIT) | 18 / 30 / 48 |
| Narasaraopet | 4 | 18 / 29 / 47 |

  Source: computed from [DB].

### Inferences
- The least-effort first wave covers the eight P1 colleges with both a verified TPO and a known end-of-exam date. Their open-from dates are:
  - SCET: 14 Nov
  - RVR&JC and NEC: 24 Nov
  - Vikas CET and SVECW: 28 Nov
  - SRGEC and LBRCE: 29 Nov
  - SRKR: 6 Dec
- KL, VFSTR, VLITS and KHIT have verified TPOs but unknown exam dates. The first TPO call to each should also confirm the exam calendar.
- VIT-AP (1,754 adjusted eligible) has no verified TPO, only a named CDC head and the admissions line [CGK]. Pragati has no TPO line either. Both are high-yield P2 colleges that need in-person visits.

### Gaps
- There are no 2026 4-1 dates for 28 of the 69 colleges.
- None of the 69 colleges' contacts has been tested yet: all are `status = untested` in the DB.
- No distance or travel-time data was used. "Cluster" means only that the colleges share a town.

## Q2. Conversion band and each college's min / avg / max

### Takeaway
The planning band is **min 0.75% / avg 1.25% / max 2.0% of adjusted eligible students**. It is an assumption, built from benchmark components. The rates are halved for GGU, where only pre-final-year (3rd-year) students are available. Each college's figure is that rate × adjusted eligible, rounded to the nearest whole number.

The example band in the brief (0.4% / 0.9% / 1.6%) cannot meet the 400 minimum anywhere in the DB (see Q3).

### Cited Findings
- No conversion or ambassador history exists. The `enrollments`, `people`, `targets` and `activities` tables have 0 rows — [CAP].
- Benchmarks available in [BENCH]:
  - About 1% of cold or first-time inquiries convert to enrollment (Meritto 2026 index, mostly higher-education admissions).
  - 5–12% of live webinar attendees buy, and warm-audience attendee-to-sale is 5–15% (vendor figures: acceleroi, ruzuku).
  - Organic ed-tech leads convert at 2–3% (AskWonder, dated blog).
  - Free-to-paid conversion is 2–5% for general learning (productgrowth.in, blog).
  - There is no benchmark for converting campus seminar attendees to paid IT courses in Andhra Pradesh or Telangana.
- How the band was built (**assumption**). Each rate = share of eligible students who attend a TPO/HOD-approved session × attendee-to-paid rate:
  - min: 15% × 5% = **0.75%**. The 5% is the bottom of the vendor 5–12% range.
  - avg: 20% × 6.25% = **1.25%**. This is close to Meritto's roughly 1%, with an uplift for the workshop channel.
  - max: 25% × 8% = **2.0%**. This is the lower end of the 2–3% organic-lead range.
  - The attendance shares (15–25%) are unsourced judgement.
- Seat fill: VFSTR's NIRF 2025 DCS shows that 81–88% of sanctioned seats were actually filled (1,654 of 2,040, 1,715 of 2,040 and 1,602 of 1,830) — [VFSTR NIRF 2025 Engg DCS](https://www.vignan.ac.in/nirf/NIRF%202025%20Engineering%20DCS.pdf). The pool here stays on a sanctioned-seat basis, so the band implicitly absorbs a roughly 15% fill gap.
- Ambassador productivity is the brief's assumption: min 1, avg 2.5, max 5 paid enrollments per ambassador over about 8 weeks. [BENCH] has no published average. Its inference is that a median ambassador makes 0–2 per month, a small top tier makes 5–15, and plausibly half make nothing. IMAV Learning Academy requires 3 confirmed enrollments a month for an ambassador to stay active. The brief's 1 / 2.5 / 5 over 8 weeks (about 0.5 / 1.25 / 2.5 per month) is consistent with that inference, so I kept it, labelled as an assumption.
- `ambassadors_min_needed` = max(1, ceil(min ÷ 2.5)), meaning the number needed to deliver the minimum at average productivity. Totals across the 69 colleges:
  - 191 at 2.5 per ambassador
  - 107 at 5 per ambassador, with a floor of 1 per college
  - 400 at 1 per ambassador
- Table A, ranked by score. Each row gives min / avg / max, ambassadors needed, priority, when outreach can start, and contact status. The full rows, with branches and notes, are in the CSV.

| # | College | District / town | Adj. eligible (provenance) | Min / avg / max | Amb. | Pri. | Open from | Contact |
|---|---|---|---|---|---|---|---|---|
| 1 | KL University | Guntur / Vaddeswaram | 3174 (verified) | 24 / 40 / 63 | 10 | P1 | unknown | TPO |
| 2 | SRKR | West Godavari / Bhimavaram | 1476 (verified-total) | 11 / 18 / 30 | 5 | P1 | 6 Dec | TPO |
| 3 | VFSTR | Guntur / Vadlamudi | 1482 (verified-total) | 11 / 19 / 30 | 5 | P1 | unknown | TPO |
| 4 | VIT-AP | Guntur / Inavolu | 1754 (estimated) | 13 / 22 / 35 | 6 | P2 | unknown | line |
| 5 | RVR&JC | Guntur / Chowdavaram | 1200 (verified-total) | 9 / 15 / 24 | 4 | P1 | 24 Nov | TPO |
| 6 | SRGEC | Krishna / Gudlavalleru | 1236 (verified-total) | 9 / 15 / 25 | 4 | P1 | 29 Nov | TPO |
| 7 | KHIT | Guntur / Chowdavaram | 1193 (estimated) | 9 / 15 / 24 | 4 | P1 | unknown | TPO |
| 8 | VLITS | Guntur / Vadlamudi | 1163 (estimated) | 9 / 15 / 23 | 4 | P1 | unknown | TPO |
| 9 | SCET | West Godavari / Narsapur | 1001 (verified-scaled) | 8 / 13 / 20 | 4 | P1 | 14 Nov | TPO |
| 10 | SAHE | Krishna / Kanuru | 1068 (verified) | 8 / 13 / 21 | 4 | P1 | unknown | TPO |
| 11 | GGU (3rd-year only) | East Godavari / Rajanagaram | 2438 (assumption) | 9 / 15 / 24 | 4 | P3 | unknown | line |
| 12 | LBRCE | NTR / Mylavaram | 898 (est.) | 7 / 11 / 18 | 3 | P1 | 29 Nov | TPO |
| 13 | NEC | Palnadu / Narasaraopet | 839 (verified-scaled) | 6 / 10 / 17 | 3 | P1 | 24 Nov | TPO |
| 14 | Pragati | Kakinada / Surampalem | 1139 (verified-scaled) | 9 / 14 / 23 | 4 | P2 | unknown | line |
| 15 | Vikas CET | NTR / Nunna | 791 (est.) | 6 / 10 / 16 | 3 | P1 | 28 Nov | TPO |
| 16 | VWU / SVECW | West Godavari / Bhimavaram | 785 (est.) | 6 / 10 / 16 | 3 | P1 | 28 Nov | TPO |
| 17 | MLWEC | Guntur / Pulladigunta | 877 (est.) | 7 / 11 / 18 | 3 | P1 | unknown | TPO |
| 18 | ISTS | East Godavari / Rajanagaram | 877 (est.) | 7 / 11 / 18 | 3 | P1 | unknown | TPO |
| 19 | TEC | Palnadu / Narasaraopet | 872 (est.) | 7 / 11 / 17 | 3 | P1 | unknown | TPO |
| 20 | SITE | West Godavari / Tadepalligudem | 816 (est.) | 6 / 10 / 16 | 3 | P1 | 4 Dec | TPO |
| 21 | MVR | NTR / Paritala | 857 (est.) | 6 / 11 / 17 | 3 | P1 | unknown | TPO |
| 22 | SVEC | West Godavari / Pedatadepalli | 862 (est.) | 6 / 11 / 17 | 3 | P2 | unknown | TPO |
| 23 | CRR | Eluru / Eluru | 816 (est.) | 6 / 10 / 16 | 3 | P2 | 28 Nov | line |
| 24 | RVIT | Guntur / Chebrolu | 673 (est.) | 5 / 8 / 13 | 2 | P2 | 29 Nov | TPO |
| 25 | VITB | West Godavari / Bhimavaram | 785 (est.) | 6 / 10 / 16 | 3 | P2 | 29 Nov | line |
| 26 | VNITSW | Guntur / Pedapalakaluru | 806 (est.) | 6 / 10 / 16 | 3 | P2 | 28 Nov | line |
| 27 | SMGG | Guntur / Chebrolu | 643 (est.) | 5 / 8 / 13 | 2 | P2 | 28 Nov | TPO |
| 28 | Amrita Sai | NTR / Paritala | 740 (est.) | 6 / 9 / 15 | 3 | P2 | unknown | TPO |
| 29 | PCE | Kakinada / Patavala | 653 (est.) | 5 / 8 / 13 | 2 | P2 | 28 Nov | TPO |
| 30 | SMCE | Guntur / Tummalapalem | 760 (est.) | 6 / 10 / 15 | 3 | P2 | unknown | TPO |
| 31 | SACET | Bapatla / Chirala | 612 (est.) | 5 / 8 / 12 | 2 | P2 | 27 Nov | TPO |
| 32 | Aditya University | Kakinada / Surampalem | 720 (verified) | 5 / 9 / 14 | 2 | P2 | 22 Nov | line |
| 33 | NRIIT | Guntur / Visadala | 852 (est.) | 6 / 11 / 17 | 3 | P2 | unknown | line |
| 34 | VSM | Konaseema / Ramachandrapuram | 796 (est.) | 6 / 10 / 16 | 3 | P2 | unknown | line |
| 35 | CIET | Guntur / Lam | 696 (verified-scaled) | 5 / 9 / 14 | 2 | P2 | 29 Nov | line |
| 36 | KIET | Kakinada / Korangi | 663 (est.) | 5 / 8 / 13 | 2 | P2 | 28 Nov | line |
| 37 | KIET-II | Kakinada / Korangi | 663 (est.) | 5 / 8 / 13 | 2 | P2 | 28 Nov | line |
| 38 | MIC | NTR / Kanchikacherla | 785 (est.) | 6 / 10 / 16 | 3 | P2 | unknown | line |
| 39 | SRKIT | NTR / Enikepadu | 632 (est.) | 5 / 8 / 13 | 2 | P2 | unknown | TPO |
| 40 | RCE | Eluru / Eluru | 632 (est.) | 5 / 8 / 13 | 2 | P2 | unknown | TPO |
| 41 | KITS Guntur | Guntur / Vinjanampadu | 1091 (est.) | 8 / 14 / 22 | 4 | P2 | unknown | none |
| 42 | RKCE | NTR / Kethanakonda | 536 (est.) | 4 / 7 / 11 | 2 | P2 | 28 Nov | TPO |
| 43 | PVPSIT | Krishna / Kanuru | 500 (est.) | 4 / 6 / 10 | 2 | P2 | 28 Nov | TPO |
| 44 | DNR | West Godavari / Bhimavaram | 464 (est.) | 3 / 6 / 9 | 2 | P3 | 28 Nov | TPO |
| 45 | BVCITS | Konaseema / Batlapalem | 485 (est.) | 4 / 6 / 10 | 2 | P3 | 29 Nov | TPO |
| 46 | PSCMR | NTR / Vijayawada | 602 (est.) | 5 / 8 / 12 | 2 | P3 | unknown | line |
| 47 | Chalapathi University | Guntur / Mothadaka | 626 (assumption) | 5 / 8 / 13 | 2 | P3 | unknown | line |
| 48 | BEC | Bapatla / Bapatla | 796 (est.) | 6 / 10 / 16 | 3 | P3 | 12 Dec | none |
| 49 | BVCEC | Konaseema / Odalarevu | 530 (est.) | 4 / 7 / 11 | 2 | P3 | unknown | TPO |
| 50 | SIET | Konaseema / Cheyyeru | 612 (est.) | 5 / 8 / 12 | 2 | P3 | unknown | line |
| 51 | VITW | NTR / Enikepadu | 418 (est.) | 3 / 5 / 8 | 2 | P3 | 28 Nov | TPO |
| 52 | RIET | East Godavari / Bhoopalapatnam | 434 (est.) | 3 / 5 / 9 | 2 | P3 | 28 Nov | TPO |
| 53 | VGI | NTR / Nunna | 485 (est.) | 4 / 6 / 10 | 2 | P3 | 28 Nov | line |
| 54 | KITS Divili | Kakinada / Divili | 485 (est.) | 4 / 6 / 10 | 2 | P3 | 28 Nov | line |
| 55 | KIET-W | Kakinada / Korangi | 459 (est.) | 3 / 6 / 9 | 2 | P3 | 28 Nov | line |
| 56 | DIET | Krishna / Ganguru | 566 (est.) | 4 / 7 / 11 | 2 | P3 | unknown | line |
| 57 | Amrita Amaravati | Guntur / Kuragallu | 480 (verified) | 4 / 6 / 10 | 2 | P3 | 5 Nov | line |
| 58 | SMWEC | Guntur / Budampadu | 388 (est.) | 3 / 5 / 8 | 2 | P3 | 28 Nov | TPO |
| 59 | KITS Akshar | Guntur / Yanamadala | 673 (est.) | 5 / 8 / 13 | 2 | P3 | 28 Nov | none |
| 60 | URCE | Krishna / Telaprolu | 464 (est.) | 3 / 6 / 9 | 2 | P3 | unknown | TPO |
| 61 | Ideal | Kakinada / Kakinada | 439 (est.) | 3 / 5 / 9 | 2 | P3 | 28 Nov | line |
| 62 | GIET EC | East Godavari / Rajanagaram | 439 (est.) | 3 / 5 / 9 | 2 | P3 | 28 Nov | line |
| 63 | ECET | Eluru / Duggirala | 434 (est.) | 3 / 5 / 9 | 2 | P3 | 28 Nov | line |
| 64 | ALIET | NTR / Vijayawada | 398 (est.) | 3 / 5 / 8 | 2 | P3 | 28 Nov | line |
| 65 | ECE Narasaraopet | Palnadu / Narasaraopet | 316 (est.) | 2 / 4 / 6 | 1 | P3 | 28 Nov | TPO |
| 66 | AMRMCET | Palnadu / Narasaraopet | 357 (est.) | 3 / 4 / 7 | 2 | P3 | 28 Nov | line |
| 67 | CEC Chirala | Bapatla / Chirala | 357 (est.) | 3 / 4 / 7 | 2 | P3 | 28 Nov | line |
| 68 | UCET | Guntur / Dokiparru | 316 (est.) | 2 / 4 / 6 | 1 | P3 | 28 Nov | TPO |
| 69 | BVCR | East Godavari / Palacharla | 367 (est.) | 3 / 5 / 7 | 2 | P3 | unknown | TPO |
| | **Total** | | **54,242** | **400 / 663 / 1,061** | **191** | | | |

### Inferences
- The avg band is not a forecast: it rests on two unsourced inputs, the attendance share and the attendee-to-paid rate. The first two weeks of real workshops should replace it. At that point, re-run the allocation using measured attendee-to-paid rates.
- Rounding to whole numbers costs nothing at the total level: the rounded min values sum to exactly 400.

### Gaps
- No AP/Telangana-specific conversion benchmark exists, and none exists for campus-seminar-to-paid conversion on short IT courses [BENCH].
- No ambassador-yield data exists for Indian ed-tech [BENCH].

## Q3. Does the minimum sum reach 400? How many colleges are needed, and which close the gap?

### Takeaway
**At the 0.75% floor, 69 colleges are needed to reach a minimum of 400.** The focus-30 set (re-ranked) reaches only **238 min / 393 avg / 629 max**, so the focus set cannot make 400 its minimum: 400 there sits at roughly its average outcome.

Colleges ranked 31–69 close the gap of 162. They are mostly P2 and P3 colleges in the JNTUK cluster, which open on 28–29 Nov. The 38 operational colleges left outside Table A add a reserve of only 68 min / 110 avg.

Under the brief's example band (0.4% / 0.9% / 1.6%), **all 107 operational colleges together give only 250 min**. That is 319 even on the uncorrected DB pool. So **400 is not reachable as a floor at 0.4% with any set of colleges in the DB.**

### Cited Findings (all computed from [DB] with the corrections in Q4)
- Corrected eligible pool: **63,332** across 107 colleges, against 80,055 in [CAP]. The fall comes from the official-source corrections and the 0.85 haircut on unverified intakes.
- Cumulative totals by score rank:

| Colleges (by rank) | Adj. eligible | Min (0.75%) | Avg (1.25%) | Max (2.0%) |
|---|---|---|---|---|
| Top 10 | 14,747 | 111 | 185 | 295 |
| Top 20 | 25,079 | 181 | 298 | 478 |
| Top 30 | 32,674 | 238 | 393 | 629 |
| Top 45 | 42,801 | 314 | 521 | 832 |
| **Top 69 (Table A)** | **54,242** | **400** | **663** | **1,061** |
| Reserve (other 38) | 9,090 | 68 | 110 | 182 |

- Brief's band (0.4% / 0.9% / 1.6%), min / avg / max:
  - All 107 colleges: 250 / 559 / 997
  - Table A's 69: 214 / 478 / 853
  - Top 30: 127 / 284 / 505
- Pool sizes needed for a 400 minimum: about 53,300 adjusted eligible at 0.75%, and about 100,000 at 0.4%. The second figure is larger than the whole DB.
- District roll-up for Table A:

| District | Colleges | Adj. eligible | Min | Avg | Max | Ambassadors |
|---|---|---|---|---|---|---|
| Guntur | 19 | 18,847 | 142 | 238 | 377 | 64 |
| NTR | 11 | 7,142 | 55 | 90 | 144 | 27 |
| West Godavari | 7 | 6,189 | 46 | 78 | 124 | 23 |
| Kakinada | 8 | 5,221 | 39 | 64 | 104 | 18 |
| Krishna | 5 | 3,834 | 28 | 47 | 76 | 14 |
| East Godavari | 5 | 4,555 | 25 | 41 | 67 | 13 |
| Dr. B.R. Ambedkar Konaseema | 4 | 2,423 | 19 | 31 | 49 | 9 |
| Palnadu | 4 | 2,384 | 18 | 29 | 47 | 9 |
| Eluru | 3 | 1,882 | 14 | 23 | 38 | 7 |
| Bapatla | 3 | 1,765 | 14 | 22 | 35 | 7 |
| **Total** | **69** | **54,242** | **400** | **663** | **1,061** | **191** |

  Guntur's minimum is 142, against 193 in the earlier focus-30 plan [CAP]. The difference comes from three corrections: Aditya, CIET and Chalapathi University are much smaller, and the plan is spread across more colleges.
- City roll-up for Table A. The first 23 towns are listed in full; the remaining 25 single-college towns are grouped in the last row.

| Town (district) | Colleges | Adj. eligible | Min | Avg | Max |
|---|---|---|---|---|---|
| Bhimavaram (West Godavari) | 4 | 3,510 | 26 | 44 | 71 |
| Vaddeswaram (Guntur) | 1 | 3,174 | 24 | 40 | 63 |
| Vadlamudi (Guntur) | 2 | 2,645 | 20 | 34 | 53 |
| Rajanagaram (East Godavari) | 3 | 3,754 | 19 | 31 | 51 |
| Chowdavaram (Guntur) | 2 | 2,393 | 18 | 30 | 48 |
| Narasaraopet (Palnadu) | 4 | 2,384 | 18 | 29 | 47 |
| Surampalem (Kakinada) | 2 | 1,859 | 14 | 23 | 37 |
| Inavolu (Guntur) | 1 | 1,754 | 13 | 22 | 35 |
| Korangi (Kakinada) | 3 | 1,785 | 13 | 22 | 35 |
| Paritala (NTR) | 2 | 1,597 | 12 | 20 | 32 |
| Kanuru (Krishna) | 2 | 1,568 | 12 | 19 | 31 |
| Eluru (Eluru) | 2 | 1,448 | 11 | 18 | 29 |
| Nunna (NTR) | 2 | 1,276 | 10 | 16 | 26 |
| Chebrolu (Guntur) | 2 | 1,316 | 10 | 16 | 26 |
| Gudlavalleru (Krishna) | 1 | 1,236 | 9 | 15 | 25 |
| Vinjanampadu (Guntur) | 1 | 1,091 | 8 | 14 | 22 |
| Narsapur (West Godavari) | 1 | 1,001 | 8 | 13 | 20 |
| Enikepadu (NTR) | 2 | 1,050 | 8 | 13 | 21 |
| Vijayawada (NTR) | 2 | 1,000 | 8 | 13 | 20 |
| Chirala (Bapatla) | 2 | 969 | 8 | 12 | 19 |
| Mylavaram (NTR) | 1 | 898 | 7 | 11 | 18 |
| Pulladigunta (Guntur) | 1 | 877 | 7 | 11 | 18 |
| Pedatadepalli (West Godavari) | 1 | 862 | 6 | 11 | 17 |
| 25 other towns, 1 college each* | 25 | 14,795 | 111 | 186 | 297 |
| **Total (48 towns)** | **69** | **54,242** | **400** | **663** | **1,061** |

  \*Visadala, Tadepalligudem, Pedapalakaluru, Tummalapalem, Ramachandrapuram, Kanchikacherla, Bapatla, Lam, Patavala, Mothadaka, Cheyyeru, Yanamadala, Kethanakonda, Odalarevu, Ganguru, Batlapalem, Divili, Kuragallu, Telaprolu, Bhoopalapatnam, Budampadu, Kakinada, Duggirala, Palacharla and Dokiparru.

  The ambassador column is in the CSV-derived run output only (it sums to 191).
- Reserve colleges outside Table A, best first: MAMWEC, LIMAT, SVIST, SVIET, BIET, VKR VNB AGK, PITS, GVR&S, SNIT, PITM, SSIET, Nova CET, NIE Macherla, Adarsh and CIST, at 2–3 min each.

### Inferences
- The minimum sums to exactly 400 with no buffer. Two Table A rows are themselves assumptions: GGU (9) and Chalapathi University (5). Without them the minimum is 386, and the top three reserve colleges (MAMWEC, LIMAT, SVIST) would be needed to restore 400.
- A practical reading: commit P1+P2 (42 colleges, 298 min / 494 avg). Treat P3 (27 colleges) as the gap-closing layer, and activate it from 28 Nov when the JNTUK window opens. 400 is then the expected (avg) outcome of P1+P2, with P3 as insurance.
- Under the brief's 0.4% floor, the 400 goal has to be treated as a stretch target. Under that floor, the realistic minimum across the entire DB is about 250.

### Gaps
- The conversion band is unvalidated. If real attendee-to-paid rates are below 5%, even 69 colleges will not reach a 400 minimum.

## Q4. Spot-check of student strength for the top ~15 colleges against official sources

### Takeaway
Fifteen large colleges were checked against official sources.

- **The DB matches** for 2023-24 (the current final-year batch) at **VFSTR, SRKR and SRGEC**, and for 2024-25 at RVR&JC.
- **The DB overstates** the final-year batch at **Aditya, NEC, SCET, CIET and Pragati**. The DB uses 2026-27 intake as its proxy, and these colleges have grown their intake sharply since 2023.
- **Chalapathi University and GGU** are new universities. Chalapathi was converted from CITY, and GGU's first B.Tech intake was in 2024. Their DB figures do not describe a 2023 final-year batch.

**Correction to the brief:** VFSTR's verified 2023-24 figure is **2,580**, not 1,830. The 1,830 is the 2022-23 intake, a batch that has already graduated.

### Cited Findings
- **VFSTR (c2)**: NIRF 2025 Engineering DCS gives UG 4-year sanctioned intake of **2,580 (2023-24)**, 1,830 (2022-23) and 1,800 (2021-22). Seats filled were 1,602–1,715 a year — [VFSTR NIRF 2025 DCS](https://www.vignan.ac.in/nirf/NIRF%202025%20Engineering%20DCS.pdf). The DB total of 2,580 is therefore correct for the final-year batch.
  - The figure covers all UG 4-year programmes, possibly including non-B.Tech ones.
  - The relevant-branch eligible stays at the DB's 1,482. This is likely an undercount, because 4 CSE-allied branches (AIML, CS, BS, DS) are still pending in the DB.
  - The earlier "1,830 vs 2,580" flag ([CGK], citing NIRF 2024) compared the wrong year.
- **Aditya University (c106)**: The AICTE EoA 2024-25 for Aditya Engineering College lists "intake approved for 2023-24":
  - CSE 180, AI&ML 180, CSE (DS) 60, IT 120
  - ECE 240, EEE 60
  - This gives **720 eligible**, against the DB's 4,140 (the 2026-27 university intake) — [AICTE EoA 2024-25 on adityauniversity.in](https://www.adityauniversity.in/public/frontend/assets/pdf/2024-25.pdf).
  - The DB notes that senior batches still carry the AEC letterhead. Aditya's target falls from 37 (focus-30) to 5 / 9 / 14.
- **NEC (c36)**: The NIRF 2026 Engineering submission gives UG sanctioned intake of **960 for 2023-24** (and 960 for 2024-25), against the DB total of 2,100 — [NEC NIRF 2026 Engg](https://www.nrtec.in/wp-content/uploads/2026/04/Engineering-2026-submitted.pdf). The NIRF 2025 Overall gives the same 960 — [NEC NIRF 2025 Overall](https://nrtec.in/wp-content/uploads/2025/02/NIRF-Overall-Submitted-2025.pdf). Adjusted eligible: 1,836 × 960/2100 = 839.
- **SRGEC (c82)**: NIRF 2026 gives UG **1,500 for 2023-24**, equal to the DB total of 1,500 — [SRGEC NIRF 2026 Engg](https://gecgudlavalleru.ac.in/images/admin/pdf/1775620595_NIRT%202026%20-%20Engineering.pdf).
- **SRKR (c147)**: The NIRF 2025 engineering submission gives UG **1,860 for 2023-24**, equal to the DB — [SRKR NIRF 2025 Engg](https://srkrec.edu.in/files/mandates/NIRF_2025_engineering.pdf). This came from a search-result extract. A direct fetch returned HTML, not the PDF.
- **SCET / Swarnandhra (c155)**: The college's NIRF 2026 and SDG 2025 sheets give UG **1,230 for 2023-24** (1,650 for 2024-25), against the DB's 1,740 — [Swarnandhra NIRF 2026](https://www.swarnandhra.ac.in/data/nirfdata2021/nirf2026.pdf); [SDG 2025](https://www.swarnandhra.ac.in/data/sdgdata/sdg2025.pdf). This came from a search-result extract. Adjusted eligible: 1,001.
- **Pragati (c107)**: The college's NIRF 2025 Overall gives UG **1,320 for 2023-24**, against the DB's 1,440 — [Pragati NIRF 2025 Overall](https://pragati.ac.in/wp-content/uploads/2025/02/Overall.pdf). This came from a search-result extract. Adjusted eligible: 1,139.
- **CIET (c10)**: NIRF 2025 DCS gives UG sanctioned **780 for 2023-24**, against the DB's 1,170 ([CGK], citing chalapathiengg.ac.in NIRF_Engineering-2025.pdf). Adjusted eligible: 696.
- **KL University (c1)**: verified. The DB holds `intake_2023_24` = 3,510 from the BoM approval, and NIRF 2026 also shows 3,510 for 2024-25 ([CGK]; [DB]).
- **RVR&JC (c9)**: NIRF 2026 gives 1,620 for 2024-25, equal to the DB. The 2023-24 column was not re-checked ([CGK]).
- **VLITS (c32)**: conflicting. The intake page gives 2,100 (undated) against the DB's 1,710 ([CGK]). No NIRF figure was found this pass. The DB figure was kept, with the standard haircut.
- **Chalapathi University (c7)**: The DB op-status note says the 2026 EAPCET list carries CITYPU "Chalapathi University" at the same campus that admitted students in 2025 as Chalapathi Institute of Technology (CITY, S.No 11, now `closed` in the DB). So the final-years are CITY's 2023 batch, and its size is unknown. A web search found no official source for the university's establishment.
  - Pool used: 3,600 × 0.174, an **assumption** borrowed from Aditya's converted-university ratio of 720 / 4,140. This gives 626.
- **GGU (c116)**: The DB note reads "first B.Tech batch admitted 2024". The exam report found that GGU's final-year students sit under GIET Engineering College (c117) ([report](file:///C:/Users/SYAM/Downloads/colleges_data-main/colleges_data-main/reports/Path%20to%20400%20enrollments%202026.md)).
  - Action taken: GGU is re-targeted to 3-1 (3rd-year) students, at half the conversion rates, and moved to P3. GIET EC (c117, 4-1 end-sem 16–27 Nov, open from 28 Nov) is kept in Table A.
  - Moving GGU's whole former 25 to GIET is not supported: GIET EC's estimated pool is only 439, which gives 3 / 5 / 9.
- **VIT-AP, KHIT, KITS Guntur**: no official 2023-24 intake was found. NIRF searches returned only VIT Vellore files [search: VIT-AP NIRF]. KHIT has no intake table on its disclosure page. KITS Guntur's site blocks access with HTTP 403 [CGK]. These stay at the DB figure × 0.85.
- **Growth haircut (assumption)**: the official 2023-24 total divided by the DB 2026-27 total, for the seven colleges checked, was:

| College | 2023-24 / 2026-27 |
|---|---|
| NEC | 0.46 |
| CIET | 0.67 |
| SCET | 0.71 |
| Pragati | 0.92 |
| SRKR | 1.0 |
| SRGEC | 1.0 |
| VFSTR | 1.0 |

  The mean is 0.82 and the median 0.92. Aditya was excluded as a university-conversion outlier (0.17). I applied **0.85** to every college without an official check.
- Bapatla Engineering College (c48) and KITS Guntur (c12) have **no verified contact line** in the DB (verified contacts = 0). [CGK] has only low-confidence lines: BEC 9849409947 / 08643-224244 from an unreachable site, and KITS 0863-2286666 from a 2022 job advert. Both are kept in the table:
  - KITS Guntur: P2, 8 / 14 / 22
  - BEC: P3, 6 / 10 / 16, and its exams run 1–11 Dec
  - Both need a visit or a general-line call before their targets count.

### Inferences
- The DB's 2026-27 intake proxy overstates final-year cohorts most at fast-growing colleges and converted universities, which are also the colleges at the top of the earlier focus-30 list. The earlier plan had about 87 of 400 riding on Aditya, Chalapathi U and GGU (37 + 25 + 25) [CAP]. After correction, those three carry 19 min, with GGU's 9 counting only 3rd-years.
- Every "estimated" row (55 of 69) still rests on a DB figure × 0.85.

### Gaps
- 2023-24 official intake was not found for VIT-AP, KHIT, KITS Guntur, VLITS (conflicting), Chalapathi U's CITY batch, MLWEC, ISTS or TEC.
- GGU's 2024 intake is unverified.
- No figures for actual enrolled strength (as opposed to sanctioned seats) were checked, except VFSTR's seats-filled data.
- SRKR, SCET and Pragati were read from search-result extracts of official PDFs, not from full-document fetches.
