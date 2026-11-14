# West Godavari + Eluru B.Tech colleges: verification notes (7 Nov 2026)

Scope: the 26 portal-DB colleges with `district_id IN ('west-godavari','eluru')`, plus a sweep for missing B.Tech colleges. Outputs in this folder:
- `west_godavari_colleges.csv`: 26 rows, 40 columns
- `west_godavari_branches.csv`: 138 rows

Both follow SCHEMA.md. The DB was read only, never written.

## Headline
- **18 active, 8 possibly_closed. No college was found missing from the DB.**
  - The 18 active colleges are in the official AP EAPCET-2026 list ([cap.apcfss.in API](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details), read 7 Nov 2026), except three that do not take EAPCET admissions: NIT AP (JoSAA), RGUKT Nuzvid (its own PUC+B.Tech) and NRIIT (a deemed university since Mar 2026 that admits through NRIUCET).
  - The 8 possibly_closed colleges: GVVR, both Akula Sreeramulu colleges, SVISIT, JITS (pharmacy only), Gayatri, Swarnandhra Inst. of Engg & Tech (Narsapur) and both Nova colleges. None is in EAPCET-2026, and no B.Tech activity was found for any of them. No official closure order was found either, so none is marked `closed`.
- **Verified final-year batch (2023-24 sanctioned intake): 9,770 seats across 11 colleges.**
  - SRKR 1,860, SCET 1,230, NRIIT 1,200, CRR 1,050, VITB 1,020, SVEC 1,020, RCE 900, DNR 540, NIT AP 530, SSIET 420. ISTSOC has 0 because it was established in 2024 and has no 2023 batch.
  - Sources are college-hosted NIRF 2025/2026 DCS PDFs and AICTE EoAs. Each URL is in the CSV.
- **Verified IT-related final-year: 2,460 at 5 colleges.** SCET 780, CRR 600, RCE 540, DNR 300, SSIET 240. Other colleges publish only totals.
- **NIRF total UG strength is available for 8 colleges, 37,118 students in all:**

| College | UG students |
|---|---|
| SRKR | 8,134 |
| NRIIT | 5,211 |
| SCET | 4,955 |
| SVEC | 4,687 |
| VITB | 4,488 |
| RCE | 3,720 |
| CRR | 3,670 (2023-24) |
| NIT AP | 2,253 |

  The year is 2024-25 except where marked.
- **Unavailable:**
  - No intake or strength data for Sasi, VWU/SVECW, BIET, ECET, HITS or RGUKT (beyond EAPCET seats).
  - Sasi's site (sasi.ac.in) is stuck in an infinite 301 redirect loop, so its NIRF, EoA and social pages could not be read.

## DB discrepancies to review
1. **SCET (c155):** AICTE EoA 2026-27 approves CSE at 600, against 540 in the DB, for a total of 1,800 vs 1,740. CSBS is approved at 0 (discontinued), but its 2023 batch of 60 is still in final year.
   - SCET is in Narsapur, West Godavari, not East Godavari as the brief said.
2. **CRR (c156):**
   - The DB has no IT branch, but the Mandatory Disclosure 2025-26 lists B.Tech IT with 180 seats for 2023-24 to 2025-26. IT is absent from EAPCET-2026, yet IT students in years 2–4 still exist.
   - The DB phone is the grievance helpline; the principal's line is 08812 230840.
3. **RCE (c157):** the 2026-27 branch mix (from EAPCET) differs from EoA 2025-26: CSE 120 vs 180, AI&DS and AI&ML 180 vs 120, Civil and Mech 30 vs 60. The total stays at 900.
4. **VITB (c148):** the DB matches EoA 2026-27 (1,140). The final-year batch is 1,020, not 1,140.
5. **NIT AP (c146):** the DB's 480 is an aggregator estimate. NIRF 2026 gives 530 for both 2023-24 and 2024-25. The DB branch rows come from a 2019 FAQ and add up to 540.
6. **NRIIT (c94):**
   - The DB total is null; NIRF gives 1,320 for 2024-25 and 1,200 for 2023-24.
   - The website has moved to rvrnriuniversity.edu.in, and nriit.edu.in now only shows a banner.
   - The two AI&ML branch rows may be duplicates.
7. **ISTSOC (c160):**
   - The DB total is null; AICTE 2026-27 gives 480.
   - The off-campus site is istsoffcampus.co, not ists.ac.in.
   - It was established in 2024, so it has no final-year students.
8. **VWU/SVECW (c149):**
   - The DB total is null.
   - CSE(AI&ML) appears twice in the DB: one row is the VISW college programme, the other is the VISWPU university programme (42 convener seats).
   - The email should be info@vwu.edu.in.
9. **RGUKT Nuzvid (c96):** the DB's 1,100 is the PUC entry intake, not a B.Tech branch intake. The site lists an IT HOD, but the DB has no IT branch.
10. **Smaller corrections:**
    - DNR's DB phone is the fax; the office line is 08816221237.
    - ECET's EAPCET email is ecet2008@yahoo.co.in, while the DB has yahoomail.co.in.
    - BIET's EAPCET contact is 8816230366 / info@bietbvrm.ac.in.

## Method and caveats
- **Branch intakes in the DB are derived:** EAPCET-2026 convener seats ÷ 0.8 (÷ 0.7 for SVECW). In the branches CSV they are marked `medium` unless an AICTE EoA, Mandatory Disclosure or official admissions page confirms them (`high`).
- **CRR's Mandatory Disclosure seat counts include the 10% EWS seats.** Base intake was taken as seats ÷ 1.1; the result matches NIRF.
- **Contacts:** most come from `../Path to 400 enrollments 2026/contacts_godavari.md` (read 3 Nov 2026). New ones:
  - Swarnandhra IT HOD: ithod@swarnandhra.ac.in, +91 99637 44990.
  - CRR HOD-ECE: 9392511629, from the Mandatory Disclosure.
  - NRIU admissions lines.
  - EAPCET-listed office lines.
  
  Only institutional contacts are included; there is no student personal data.
- **Social accounts:** taken only when linked from the official site.
  - VITB, DNR, BIET and ECET have placeholder icons with no links.
  - Sri Vasavi links only its GDG on Campus Instagram.
- **Not completed:** the web-search budget ran out, so the JNTUK 2025-26 affiliation list and AICTE closure lists were not checked. A follow-up should confirm c161–c169 closures there.

## Outreach pointers (dated where published)
- **SRKR:** JAITRA sports carnival is held each January; dates for SAMAGRA are not published.
- **NIT AP:** Vulcanzy fest runs in March (the 2026 edition was 12–14 Mar).
- **SCET:**
  - UTKARSH/HACKSPRINT (IT dept) began 9 Sep 2026.
  - The Design to Build hackathon was held 17–18 Mar 2026; a March 2027 repeat is not announced.
- **SVEC:** its GDG on Campus ran the Hackelerate hackathon in Dec 2025.
- **Other campuses:** RGUKT Nuzvid's Qiskit Fall Fest (5–9 Oct 2026) and VWU's Space Hackathon (19–20 Aug 2026) have both passed.
- No dated Nov 2026–Mar 2027 event was found at the other colleges.
- **Strongest placement contacts:**
  - SRKR (Dean Placements)
  - SCET (Director Placements)
  - DNR (TPO)
  - RCE (Dean Placements, plus a full set of IT-branch HOD lines in contacts_godavari.md)
  - Sasi (Director Placements)

## Other notes
- **WISE (Nallajerla, DB c154):** it was in old West Godavari but now sits in East Godavari district, so it is not in this file. It is active in EAPCET-2026 with 216 convener seats.
- **Pharmacy-only institutions:** pharmacy-only entries in EAPCET-2026 were ignored (for example Nova College of Pharmacy, Vegavaram, and JITS Palakol).
