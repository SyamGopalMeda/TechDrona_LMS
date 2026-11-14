# NTR district: B.Tech colleges (verification notes)

Researched on 7 Nov 2026. Scope: all 25 portal DB rows with `district_id = 'ntr'`. In the old map these were in Krishna district. The data files sit next to this note:
- `ntr_colleges.csv`: 25 rows.
- `ntr_branches.csv`: 132 rows, operational colleges only.

Both follow SCHEMA.md. The DB was only read, never written.

## Method and sources
- **Activity:** each college was checked against the official AP EAPCET-2026 counselling list (CAP). Source: https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details, fetched 7 Nov 2026.
  - CAP `total_seats` = convenor seats. `left_over_seats` = convenor seats not allotted.
  - Allotted = total − left over. This is used only as an activity signal, not as an enrolment count.
- **CAP-to-intake rule:** convenor seats ÷ 0.8 = sanctioned intake for non-minority private colleges.
  - This is the rule the DB uses. It was checked against the AICTE EoA for LBRCE, MIC, MVR, PSCMR and VITW, and it holds for all five. (It is not ÷0.7.)
  - Nimra is a minority college and fits ÷0.7.
- **Intake:** AICTE EoA / approval letters were taken from each college's own website, because the AICTE dashboard (facilities.aicte-india.org) did not respond.
  - EoA letters give branch-wise intake.
  - The "previous year" column of an EoA gives the prior year's intake. RKCE's 2023-24 figures were read this way.
- **Students:** total students come from NIRF DCS PDFs on college sites. NIRF reports total UG intake and UG students for all years.
- **Contacts:** contacts were reused from `Path to 400 enrollments 2026/contacts_guntur_krishna.md` (official pages, as seen on 3 Nov 2026) and spot-checked. Only official or institutional contacts are included.
- **`final_year_btech`** = sanctioned 2023-24 intake (the 2023 entry batch), not the number actually admitted. For low-demand colleges the real batch is much smaller; see the MIET and Nimra NIRF figures.

## Status summary

| Status | Colleges |
|---|---|
| active (15) | LBRCE, MIC, Amrita Sai, MVR, ALIET, SRKIT, PSCMR, VITW, Vikas CET, VGI, MIET, Nimra CET, RKCE, SVIST, DJRCET |
| unverified (1) | Nova CET (c76). It appears in CAP 2026 only from 08/09/2026, with 504 convenor seats and **0 allotted**. In 2025 it was listed only for BiPC Agricultural Engg. It has no working website. |
| merged_renamed (1) | c98 PITS. This is the **same institution as c74 MIET**: AICTE approved the name change on 05-09-2011 ([letter](https://mandava.ac.in/wp-content/uploads/2026/04/Name-Change-Approval-by-AICTE-From-Prasad-Institute-to-Mandava-Institute.jpg.jpeg)). |
| possibly_closed (8) | c72 GDMM, c73 GDMM Women, c79 Sri Vani (engineering), c86 DJRIET, c97 MSIT, c99 GIST, c100 Nimra Women's, c101 Nova Women's. None is in CAP 2026. APSCHE's institution-data page returns nothing for their codes (GDMM, GDNW, DJRV, MSIT, GIST, NMRW, NOVW). The code VANI now belongs to Sri Vani School of **Pharmacy** (B.Pharm only). |

**Allotted in CAP 2026** (convenor seats allotted / total convenor seats):

| Group | Colleges |
|---|---|
| Nearly full | LBRCE 1099/1104, MIC 854/864, SRKIT 690/720, PSCMR 593/624, ALIET 522/528 |
| Half-filled | Vikas CET 472/840, MVR 419/912, Amrita Sai 356/792, RKCE 228/600, SVIST 194/408, VGI 184/552, VITW 137/432 |
| Very weak | MIET 77/252, Nimra 28/84, DJRCET 1/288, Nova 0/504 |

**Missing-college check:** every NTR-area college in CAP 2026 is already in the DB. CAP 2026 tags them all as district "KRISHNA"; the NTR ones were picked out by place name. No functioning B.Tech college in NTR district is missing, so no extra rows were added.
- Vijayawada-area colleges that are **Krishna district** (Penamaluru and Gannavaram mandals) and already in the DB under `krishna`:
  - SAHE/VRSEC and PVPSIT (Kanuru)
  - Dhanekula (Ganguru)
  - Lingayas (Madalavarigudem)
  - PPD (Surampalli)
- NRIIT is in Eluru district.
- KBN College does not appear in CAP 2026 as an engineering college.
- **Caveat:** the JNTUK affiliation list and AICTE approved-institute list could not be queried. The AICTE portal did not respond, and the shared web-search budget ran out mid-task. So this check rests on the CAP and APSCHE lists.

## Largest IT-heavy targets
"IT final year" = sanctioned 2023-24 intake in IT-related branches.

| College | Intake | IT final year | UG students (NIRF) | Contact |
|---|---|---|---|---|
| LBRCE (c62) | 1380 (2026-27) | 600 | 4416 | Dr. Sujit Rath, Head T&P, 8919482365, headplacements@lbrce.ac.in |
| MIC (c63) | 1080 | 540 | 3495 | no TPO published; office 08678-273535 |
| PSCMR (c68) | 780 | 480 | 2575 | CSE HOD hodcse@pscmr.ac.in |
| Amrita Sai (c64) | 1050 | 390 | 2970 | TPO Dr. P. Chiranjeevi, 9490794017 |
| SRKIT (c67) | 900 | 360 | 2831 | TPO A. Siva Nageswara Rao, 7674098333 |

- **LBRCE:** has IEEE, ACM, CSI and IETE chapters. Its LAKSHYA fest runs in Dec–Jan.
- **PSCMR:** the CSE department runs an internal Smart India Hackathon (SIH) in September. It also has 7 clubs.
- **SRKIT:** its TPO is shared with VITW (both under SRK Foundation).
- **Next tier:**
  - Vikas CET: 1110 intake in 2025-26
  - MVR: 1140
  - RKCE: 750, IT final year 300
  - VGI: 750
  - VITW: 540, IT final year 300. It runs the SAVISHKAR fest (5–7 Mar 2026) and the Binary Brains hackathon (Feb 2026).
  - SVIST: 540. It runs the SVISTA fest (12–13 Mar 2026).

## Key DB discrepancies (details in the CSV `db_discrepancies` column)

**1. Rows where the DB is right and can be upgraded.** The DB marks these branch intakes "estimated", but they match the official AICTE letters exactly:

| College | Matching letter |
|---|---|
| LBRCE | EoA 2026-27 |
| PSCMR | approval 2026-27 |
| VITW | EoA 2026-27 |

**2. Totals that differ from the AICTE letters:**
- Amrita Sai: EoA 2026-27 = 1050; DB has 990.
- Vikas CET: EoA 2025-26 = 1110; DB is null.
- VGI: 750; DB is null.
- SVIST: 540; DB has 510. Civil is missing from CAP 2026.
- Nimra: NIRF gives 240; the DB's CAP-derived figure is 120.

**3. Branch splits that differ** (the totals agree, but CAP 2026 differs from the latest EoA, so the split probably changed for 2026-27):
- MIC: IT and AI&ML
- MVR: CSE, AI&DS and AI&ML
- RKCE: CSE vs CSE(AI&DS)
- MIET: CSE 90 and no EEE, vs CSE 60 and EEE 30
- Vikas CET: CSE(IoT) not in CAP
- VGI: CSE(DS) not in CAP

**4. 2023-24 intake is blank in the DB for every college.** Verified final-year totals were found for 12 colleges:
- LBRCE 1080, MIC 900, Amrita Sai 780, SRKIT 660, PSCMR 660
- VITW 420 (NIRF says 480, which conflicts), Vikas CET 480, VGI 480, RKCE 480, SVIST 480
- MIET 315, Nimra 360

**5. Duplicates and status:**
- c98 duplicates c74.
- c73 is a probable duplicate of c72.
- c76 Nova "operational" is not supported by the evidence.

**6. Contacts:** several emails from the CAP data do not appear on the official sites. These are Amrita Sai, PSCMR and SRKIT, plus the LBRCE CAP typo (ibreemym@yahoo.com).

## Upcoming timing
- **Exams:** JNTUK-pattern 4-1 end-semester exams run about 16–28 Nov 2026.
  - VGI's homepage gives 4-1 from 16-11-26 and 3-1 from 19-11-26.
  - Vikas CET's 3-1 runs 30 Nov–9 Dec.
- **Fests:** these mostly happen in Feb–Mar (SAVISHKAR, SVISTA, MICFEST, VIKALPA) or Dec–Jan (LAKSHYA). No 2027 dates have been announced yet.

## Limitations
- The WebSearch budget for the run was used up partway through. Social handles, clubs and events come only from the colleges' own sites.
- Instagram and LinkedIn are blank where the site doesn't link them (PSCMR, RKCE, VITW, SRKIT Instagram).
- No NIRF or EoA was found for ALIET, MVR (2023-24), DJRCET or Nova. Their 2023-24 figures are "unavailable".
