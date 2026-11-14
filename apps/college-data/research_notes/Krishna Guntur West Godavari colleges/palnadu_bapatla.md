# Palnadu and Bapatla districts: B.Tech colleges (verified 7 Nov 2026)

Scope: all 22 portal DB rows with `district_id IN ('palnadu','bapatla')`. Outputs: `palnadu_bapatla_colleges.csv` (22 rows) and `palnadu_bapatla_branches.csv` (107 rows). The schema is in `SCHEMA.md`. The DB was read only and nothing in it was changed.

## Summary

| Finding | Count | Colleges |
|---|---|---|
| active | 16 | c35 UCEN, c36 NEC, c38 AMR, c39 Eswar, c40 MAMW, c42 TEC, c43 LITAM, c44 SNIT, c46 NIE, c47 NIST, c48 BEC, c49 BWEC, c50 CAE, c51 CFST, c52 CECC, c53 SACET |
| possibly_closed | 4 | c37 NIT Narasaraopet, c41 Sai Tirumala NVR, c45 SCREC, c54 Amara |
| unverified | 1 | c58 VRS & YRN (in the 2025 list according to the DB, absent from the 2026 list) |
| merged_renamed | 1 | c59, a duplicate of c40 (MAMW) |

**Missing colleges: none found.** I filtered the official AP EAPCET-2026 counselling data (CAP API, 399 institutes) by place and address. Every engineering college located in Palnadu (Narasaraopet, Sattenapalli/Kantepudi/Dhulipalla, Macherla) or Bapatla (Bapatla, Chirala) is already in the DB. VNRCE Ponnur (c56) is correctly placed in Guntur. Pharmacy-only institutes were excluded.

## Main sources (all fetched 2026-11-07)

- CAP API, the 2026 counselling list with convener seats, left-over seats, contacts and AO mobiles: https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details
  - "Derived" intake means CAP convener seats divided by 0.8, which is the method the DB uses. It is unreliable: for TEC, the AICTE 2026-27 EoA gives CSE 600 where CAP-derived gives 480, and IT 120 where CAP-derived gives 60.
  - `left_over_seats` has been read as seats still unfilled after counselling. That is my interpretation and has not been confirmed. Ranges from 12 of 960 (BEC) to 309 of 312 (SNIT).
- AICTE EoA PDFs hosted by the colleges:
  - NEC: 2023-24 and 2025-26
  - TEC: 2023-24 and 2026-27
  - BWEC: 2023-24 and 2026-27
  - Eswar: 2024-25 and 2026-27
  - CECC: 2025-26
  - URLs are in the CSVs. The AICTE facilities portal refused TLS connections, so the AICTE-hosted copies could not be fetched.
- NIRF DCS PDFs from college sites:
  - NEC 2026
  - TEC 2025
  - SACET (2023-24 data)
  - BWEC (2024-25 data)
  - AMR (2024-25 data)
  - Eswar (2022-23 data)
  - nirfindia.org returned 403.
- MAMW AICTE mandatory disclosure (https://www.mamw.org/files/mandatory-disclosures.pdf). It gives students actually admitted by branch for 2023-24 to 2025-26.
- Contacts are reused from `research_notes/Path to 400 enrollments 2026/contacts_guntur_krishna.md`, which took them from official pages on 2026-11-03. They are supplemented with institutional numbers listed on the CAP portal.

## Biggest DB discrepancies

1. **NEC (c36): use 1,500 for the final year, not 2,100 and not 960.**
   - The DB's 2,100 is the AICTE 2025-26 intake.
   - The AICTE 2023-24 EoA gives 1,500, of which 960 are IT branches.
   - NIRF-2026 DCS states a sanctioned intake of 960 for every year from 2021-22 to 2024-25, which contradicts AICTE.
   - NIRF total UG students: 3,840 (2024-25).
2. **TEC (c42):**
   - AICTE 2026-27 intake is 1,335; the DB has 1,125.
   - The DB understates CSE by 120 and IT by 60, and is missing Civil (30).
   - Final year is 810 (AICTE 2023-24 = NIRF), of which 480 are IT.
3. **AMR (c38):**
   - The DB has 510. NIRF gives a sanctioned intake of 270 for 2023-24 and 2024-25.
   - Total UG students are only 638.
4. **SACET (c53):** the DB has 960. NIRF 2023-24 gives 840, and total UG students are 3,300.
5. **MAMW (c40):**
   - The rename is confirmed. AICTE approval was originally issued to St. Joseph's Educational Society, Krishnaveni Premises.
   - The 2023 batch is only **111 admitted students, all CSE**, against the DB's 360.
   - c59 is a duplicate of this row.
6. **c44 VRIT:** the 2026 counselling list names it Sri Nalanda Institute of Engineering & Technology (SNIT, Kantepudi, ngi.ac.in). Only 3 of 312 convener seats were filled in 2026.
7. **JNTUK UCEN (c35):** the college site gives 66 per branch (330 total); the DB has 60 per branch (300).
8. **ANGRAU CAE and CFST (c50, c51):** the DB intake is null. ANGRAU gives 60 each. Neither college has an IT branch.
9. **Eswar (c39):** the 2026-27 intake of 510 matches the DB. The 2023 batch (540) included CS&Design (60) and Agricultural Engineering (30), both since discontinued and missing from the DB branches. Eswar is autonomous from 2025-26.

## Activity and fill signals (2026 counselling, convener seats left over)

- Well filled:
  - BEC: 12 of 960
  - UCEN: 7 of 330
  - ANGRAU colleges: 0
  - SACET: 153 of 672+
  - TEC: 252 of 900
- Weak:
  - NEC: 514 of 1,632
  - NIE: 128 of 240
  - MAMW: 233 of 288
  - AMR: 316 of 408
  - Eswar: 325 of 408
- Near-empty:
  - LITAM: 266 of 312
  - NIST: 270 of 288
  - CECC: 408 of 432
  - SNIT: 309 of 312

At the near-empty colleges, real student strength is probably far below sanctioned intake. Their final-year figures are marked "estimated / low".

## Outreach leads found

- **NEC:** Agent-X 2026 AI Hackathon (Oct 2026), HYPERLOOP hackathon for first-years, a Robotics+AI workshop, and Instagram nrtec.
- **BWEC:** MSME Hackathon announcement and an IETE Bapatla Sub-Centre on campus (Dec 2025). 20 students were placed at Transenergy (Oct 2026).
- **SACET:** ServiceNow and Power BI AI/ML six-day workshops (Apr 2026).
- **AMR:** CODE CRUSADE 24-hour hackathon (2025).
- **Eswar:** LLM workshop (Aug 2026).
- **UCEN:** IEEE and IETE student branches.
- **TEC:** IEEE activity.
- No upcoming fest dates were found for any college.

## Gaps

- **BEC Bapatla:**
  - becbapatla.ac.in refused connections again (ECONNREFUSED).
  - There is still no verified TPO name or line. The best official line is the CAP-listed AO mobile 9440730035 with 08643-224244 and bec_principal@yahoo.com.
  - No NIRF or EoA was obtainable, so the final-year figure is left blank.
- **Web search quota ran out** partway through. These could not be searched:
  - AICTE or JNTUK closure orders for the four possibly_closed colleges and for VRS & YRN
  - JNTUK/ANU affiliation lists for 2025-26 and 2026-27
  - NIRF/EoA for LITAM, SNIT, NIE, NIST and BEC

  A follow-up run should check the JNTUK affiliated-colleges list and the AICTE approved-institute dashboard. The dashboard needs a browser, because curl gets a TLS reset.
- **Branch-wise 2023-24 intake:** not available for SACET, AMR, BEC, LITAM, SNIT, NIE or NIST.
- **Official LinkedIn:** none found for any college.
- **Total UG students:** missing for UCEN, MAMW, LITAM, SNIT, NIE, NIST, BEC, CAE, CFST and CECC.
