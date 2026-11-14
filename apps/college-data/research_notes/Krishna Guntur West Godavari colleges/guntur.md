# Guntur district (portal `district_id = 'guntur'`): B.Tech college verification, 7 Nov 2026

Scope: the 39 colleges in the portal DB with `district_id = 'guntur'` (the new Guntur district; Palnadu and Bapatla colleges are covered by other researchers). I also checked whether any functioning B.Tech college in the district is missing from the DB.

Files:
- `guntur_colleges.csv`: 39 rows, one per DB college
- `guntur_branches.csv`: 212 rows, one per college × branch

Both follow `SCHEMA.md`. The DB was read only and nothing in the portal was edited.

## Summary

| Status (this pass) | Colleges |
|---|---|
| active | 28 |
| merged_renamed | 1: c11 CITY, now c7 Chalapathi University |
| possibly_closed | 8: c16, c20, c22, c28, c34, c55, c57, c60 |
| unverified | 2: c21 NVRCET (in the 2025 list, no 2026 intake) and c61 Saveetha Amaravati |
| **Total** | **39** |

**Missing colleges: none found, so no extra rows were added.**
- I filtered the official AP EAPCET-2026 counselling list (cap.apcfss.in API, 399 institutions) to `district_id = GUNTUR` and kept only institutions with B.Tech seats.
- After removing Palnadu and Bapatla towns, every remaining college maps to an existing DB row: ANCUSF, CIET, CITYPU, GVRS, HIND, KHIT, KITG, KITS, MLEW, MPLG, NRIT, PIIT, PITT, PITW, RVIT, RVJC, SMGG, SRMUPU, STMW, UNIV, VITAPU, VLIT, VNIW, VNRC and VVITPU.
- KL, VFSTR and Amrita (deemed universities outside EAPCET) are already in the DB.
- The WebSearch budget ran out during the run, so I could not do a separate AICTE or JNTUK/ANU affiliation-list sweep for very new institutions. Example: the BITS Pilani Amaravati campus, whose status was not checked.

**Verified final-year (2023-24 entry) intake**
- I found it for 16 colleges, totalling 15,300 sanctioned seats.
- That total includes KL at 3,510 and VFSTR at 2,580. Both figures are all-UG totals from NIRF.
- Of the 15,300, 5,400 are IT-related seats, verified branch-wise at 12 colleges (KL's IT split is estimated and is not in this figure).
- For most colleges, the DB's 2026-27-derived figures overstate the final-year batch.

## Biggest discrepancies vs the DB

These matter for outreach sizing.

| College | DB figure (proxy) | Official 2023-24 intake (final year) | Source |
|---|---|---|---|
| c7 Chalapathi University (ex-CITY) | branch sum 3,840 | **720** (IT 540); current AICTE 2026-27 is 1,560 | CITY AICTE EoA 2023-24 / 2026-27 |
| c32 VLITS | 1,710 | **960** (IT 540); 2026-27 is 1,920 | AICTE EoA; NIRF 2026 |
| c9 RVR&JC | 1,620 | **1,380** | NIRF 2026 |
| c10 CIET | 1,170 | **780** (IT 510) | AICTE EoA; NIRF 2025 |
| c15 RVIT | 840 | **510** (IT 360); 2025-26 is 870 | AICTE EoA |
| c33 VNITSW | 1,020 | **600** (IT 420); 2024-25 is 780 | AICTE EoA; NIRF 2026 |
| c23 NRIIT | 1,050 | **600** by EoA, 660 by NIRF | AICTE EoA; NIRF 2026 |
| c19 MLWEC | 1,080 | **900** (IT 630); 2025-26 is 1,230 | AICTE EoA; NIRF 2026 |
| c6 Amrita Amaravati | 480 (treated as verified final-year) | **360** | AICTE letters 2023-24 to 2025-26 |
| c8 ANUCET | null | **480** | NIRF 2026 |
| c29 / c30 St. Mary's | total null | **780 / 480** | AICTE EoA |
| c18 HCET / c31 UCET | 300 / 480 | **270 / 390** | AICTE EoA |

Other DB issues:
- **c11 CITY** is marked `closed`. It is better described as **merged/renamed**: AICTE still issues the EoA in CITY's name (same permanent id, 1-4822221), while EAPCET 2026 lists the campus as Chalapathi University (CITYPU). Count its students only once, under c7.
- **Wrong or dead websites:**
  - c8 www.anu.ac.in is dead. The official site is nagarjunauniversity.ac.in.
  - c14's CAP website, gecg.in, is a placeholder page.
  - kitsguntur.ac.in and kitsakshar.ac.in return HTTP 403.
  - c26 PITW and c56 VNRCE have no working site.
- **DB contact fields copied from the CAP list but absent from the college sites:** c13 KHIT email, c32 VLITS phone, c30 STMW phone and c17 GVRS phone.
- **Branch mismatches between the DB, AICTE and 2026 convener seats:**
  - c19 MLWEC: the 2026-27 EoA lists AI&DS and CSE-DS without intake figures, yet the 2026 CAP list still has 192 AI&DS seats.
  - c31 UCET: AICTE 2025-26 has AIML 120, but there is no 2026 convener row for it.
  - c8 ANU: the DB has AIML and DS rows that are not in the 2026 convener list, plus duplicate Space Science rows.
  - c23 NRIIT: the DB's AI&DS and Quantum Computing rows are not in AICTE 2025-26. They appear only in the 2026 CAP list.
- **c4 VIT-AP DB branch numbers** (for example CSE-AIML 1,080) are derived, not official, and should be treated with caution.

## Gaps (no official intake or strength found this pass)

| Colleges | Why |
|---|---|
| c3 SRM AP, c4 VIT-AP, c5 VVIT University | Private universities. Convener seats are only a share of intake. No NIRF DCS was located. VVIT's NIRF PDF on vvitguntur.com returned 404, and that domain is spam-compromised. |
| c12 KITS Guntur, c14 KITS Akshar | Sites return HTTP 403. There is still no verified contact line for either college. |
| c13 KHIT | No EoA or NIRF document on the site. |
| c27 SMCE | React site; no EoA or NIRF document found. |
| c24 PITM | Only 2020-22 EoAs are posted. |
| c26 PITW, c56 VNRCE | No working website. |

Other gaps:
- Final-year figures for c17 GVR&S and c25 PITS are **estimated**: their 2025-26 and 2026-27 intake (360 and 540) is used as a proxy.
- The VFSTR and KL branch-wise 2023-24 splits are unverified. KL's DB split comes from a scanned BoM PDF.
- Total actual student strength (NIRF) was found for only 10 colleges.
- Student clubs and fest dates are thin. Official pages yielded only a few items:
  - Qiskit Fall Fest 2026 at KL, SRM AP and VNITSW
  - RVIT BuildX Buildathon (4–8 Aug 2026) and its 2K26 Tech Fest
  - KHIT Tech Fest 2026
  - UCET Fest 2026
  - MLWEC hackathon and IEEE items
  - VLITS IEEE/ASME mention

  Upcoming (Dec 2026 to Mar 2027) fest dates were not found.
- c21 NVRCET and c61 Saveetha Amaravati need a phone or field check.

## Method

1. **Official list.** I pulled the EAPCET-2026 counselling list from https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details. It gives convener seats only, but a listing is proof that the college is admitting for 2026-27.
2. **AICTE EoA PDFs** came from each college's own approval page. I parsed them with `pdftotext -raw` and a small parser, and checked the totals against NIRF where both exist (CITY 720, VLITS 960, CIET 780, MLWEC 900, VNIW 600 all match).
3. **NIRF DCS PDFs** came from the college sites. The intake columns run newest year first: the value on the "UG [4 Years]" line is the latest year, and the "Academic Year" line holds the earlier years.
4. **Contacts** were reused from `Path to 400 enrollments 2026/contacts_guntur_krishna.json`. These are official pages as seen on 3 Nov 2026, and I did not re-test them. Only institutional or staff roles are recorded.
5. **Social links** were taken only where the college's homepage links to them.

## Source list (main)

- EAPCET-2026 counselling list: https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details
- KL NIRF 2026: https://www.kluniversity.in/NIRF/ENGINEERING-2026.pdf
- VFSTR NIRF 2025: https://www.vignan.ac.in/nirf/NIRF%202025%20Engineering%20DCS.pdf
- RVR&JC NIRF 2026: https://rvrjcce.ac.in/files/nirf/Engineering_2026.pdf
- ANUCET NIRF 2026: https://www.nagarjunauniversity.ac.in/assets/notifications/ucet.pdf
- CIET:
  - NIRF 2025: https://chalapathiengg.ac.in/wp-content/themes/ciet/files/NIRF_Engineering-2025.pdf
  - Compiled EoAs: https://chalapathiengg.ac.in/wp-content/themes/ciet/files/2025/AICTE.pdf
- CITY / Chalapathi University:
  - EoA 2023-24: https://city.ac.in/Files/AICTE%20EOA/EOA-Report--2023-24.PDF
  - EoA 2025-26: https://city.ac.in/Files/AICTE%20EOA/EOA%20Report%202025-2026.pdf
  - EoA 2026-27: https://city.ac.in/Files/AICTE%20EOA/EOA%20Report%2026-27.PDF
  - NIRF 2025: https://city.ac.in/Files/nirf-e-2025.pdf
- VLITS:
  - EoA 2023-24: https://www.vignanlara.org/approvals/aicte/EOA_Report_2023-24.PDF
  - EoA 2026-27: https://www.vignanlara.org/approvals/aicte/EOA_Report_2026-27.PDF
  - NIRF 2026: https://www.vignanlara.org/NIRF/DCS%20Report%20NIRF%202026.pdf
- VNITSW:
  - EoA 2024-25: https://www.vignannirula.org/aicteapprovals/AICTE%20approval%2024-25%20pdf.pdf
  - NIRF 2026: https://www.vignannirula.org/nirf.pdf
- MLWEC:
  - EoA 2024-25: http://mlewguntur.com/EOA%202024-2025.pdf
  - EoA 2025-26: http://mlewguntur.com/MLEW%20EOA%20Report%202025-26.pdf
  - EoA 2026-27: http://mlewguntur.com/EOA%202026-2027.PDF
  - NIRF 2026: http://mlewguntur.com/Engineering-NIRF%202026.pdf
- NRIIT:
  - EoA 2023-24: https://nriit.ac.in/assets/pdf/EOA%20Report%202023-24.pdf
  - EoA 2025-26: https://nriit.ac.in/assets/pdf/EOA%20Report%202025-26.pdf
  - NIRF 2026: http://nriit.ac.in/assets/pdf/NIRF%20DCS%20Engineering%202025-26-.pdf
- RVIT EoAs (Google Drive files linked from https://rvit.edu.in/approvals.php):
  - EoA 2023-24: https://drive.google.com/file/d/1gwu4f8dukvKPFfCEHtVTNfUQ5vo_eHzt
  - EoA 2025-26: https://drive.google.com/file/d/1UQyOuCPts3cRKFNc2gleOoGxGqkqR4Dl
  - Buildathon page: https://rvit.edu.in/buildathon.php
- HCET:
  - EoA 2023-24: https://www.hinduengg.com/hinduenggnew/public/Admincss/New-Uploads/AICTE-EOA/EOA%20Report%202023-24.PDF
  - EoA 2025-26: https://www.hinduengg.com/hinduenggnew/public/Admincss/New-Uploads/AICTE-EOA/2X-%20EOA%20AICTE%20-%202025-26.PDF
- UCET:
  - EoA 2023-24: https://ucet.edu.in/wp-content/uploads/2024/08/EOA-2023-24.pdf
  - EoA 2025-26: https://ucet.edu.in/wp-content/uploads/2025/12/EOA-Report-2025-26.pdf
- St. Mary's Chebrolu (SMGG):
  - EoA 2023-24: https://stmarysguntur.com/wp-content/uploads/2023/06/EOA-Report-2023-24.pdf
  - EoA 2024-25: https://stmarysguntur.com/wp-content/uploads/5.-SMGIG-EOA-2024-25.pdf
- St. Mary's Budampadu (STMW):
  - AICTE approval 2023-24: http://stmaryswomens.com/wp-content/uploads/2023/11/SMWEC-AICTE-Approval-2023-24.pdf
  - AICTE approval 2024-25: http://stmaryswomens.com/wp-content/uploads/2024/12/SMWEC-AICTE-Approval-2024-25.pdf
- GVR&S EoA 2026-27: https://gvrs.ac.in/assets/Images/EOA%20Report%202026-2027.pdf
- PITS EoA 2025-26: https://pitt.ac.in/uploads/legacy-pdfs/EOA-Report-2025-26.pdf
- Amrita Amaravati AICTE letters: https://webfiles.amrita.edu/2026/03/aicte-approval-letter-amaravati-2022-25.pdf

The downloaded PDFs and the parser scripts (`eoa_parse.py`, `build_guntur.py` and `build_part2_body.py`) are in the session scratchpad: C:\Users\SYAM\AppData\Local\Temp\claude\96bc413f2bb7cb1e\ed62faac-3ba3-484b-9f39-ef305ecac048\scratchpad
