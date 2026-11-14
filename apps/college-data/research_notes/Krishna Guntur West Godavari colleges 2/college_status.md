# Operating status of doubtful B.Tech colleges: old Krishna, Guntur and West Godavari (as of 7 Nov 2026)

Scope: the 30 `possibly_closed` and 4 `unverified` rows (scope_in=yes) in `master_colleges.csv`, plus c154 WISE. Row-level output is in `status_updates.csv`, which sits next to this file.

**Three official sources were checked this round:**

1. **AP EAPCET-2026 counselling list.** CAP API, 399 institutes, fetched 2026-11-07. [CAP EAPCET](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details)
2. **AP ECET-2026 lateral-entry list.** CAP API, 240 institutes, entry dates 30/06/2026, fetched 2026-11-07. Earlier rounds had not checked this list. [CAP ECET](https://api.cap.apcfss.in/oamreadapi/oam-public/ecet-clg-home-page-details)
3. **JNTUK exam clustering list, dated 09.04.2026.** It covers the II/III/IV B.Tech I & II Sem Regular/Supplementary Examinations of April 2026. It lists every non-autonomous JNTUK college that had B.Tech exam candidates, with a candidate count ("CC COUNT") for each. It is signed by the Controller of Examinations, JNTUK. [JNTUK clustering list PDF (Google Drive, linked from Manabadi)](https://drive.google.com/file/d/1okl0bdDbKKA0VCq9oed1dvpRLHktpUFE/preview) · [Manabadi notice](https://www.manabadi.co.in/Notifications_26/JNTUK-2-3-4-BTech-1st-2nd-Sem-Reg-Supply-Exam-April-2026-Jumbling-Clustering-centers-List--9-4-2026.asp)

**Labels used in this note:**

- **winding_down:** about 40–125 enrolled B.Tech candidates in April 2026, but the college is absent from both the 2026 EAPCET and ECET lists.
- **residual backlog only:** 1–15 candidates in April 2026, which looks like supplementary students only, and no 2026 counselling.
- **no trace:** absent from all three lists.

**Nothing is labelled "closed"**, because no AICTE or JNTUK closure order was located.

## Q1. Are the colleges in the JNTUK / ANU affiliated lists, and do they still have B.Tech students?

### Takeaway
I found no consolidated JNTUK 2025-26 or 2026-27 affiliated-college list online. The JNTUK April-2026 exam clustering list works as a proxy for "B.Tech students still on JNTUK rolls". It shows **17 of the 34 doubtful colleges still had B.Tech exam candidates in April 2026**:

- **7 with real batches (39–123 candidates):** NVRCET, Malineni Perumallu, Mittapalli Women, Narasaraopeta IT, Sai Tirumala NVR, Swarnandhra Institute and VRS & YRN.
- **10 with only 1–15 candidates:** c45, c72, c76, c79, c86, c93, c161, c165, c168 and c169.

The other **17 are on no JNTUK roll**: 16 JNTUK colleges plus Saveetha, which is a university and not JNTUK-affiliated. The c73 row is a duplicate of c72 (same single GDMM entry); it is listed in the CSV for completeness but is not one of the 34.

### Cited Findings
- **The JNTUK affiliated-colleges web page returns 404.** `www.jntuk.edu.in/affiliated-colleges` was fetched on 2026-11-07. The menu entry points to `examinations#affiliated-colleges`, which has no static list. The older `jntuk_uploads/notification/*.pdf` links also return 404. — [JNTUK](https://www.jntuk.edu.in/examinations)
- **Affiliation in 2025-26 is granted college by college.** For example, LBRCE (code 76) received renewal of permanent affiliation for 2025-26 to 2027-28 under Proc. No. JNTUK/D-Affiliation/B2/Perm. Affi./CC:/2026, dated 31.03.2026. No consolidated list was found. — [LBRCE-hosted JNTUK proceedings](https://lbrce.ac.in/college_docs/jntu_affiliations/jntuk_affili_2025-2028.pdf)
- **Candidate counts in the JNTUK April-2026 clustering list (09.04.2026):** — [JNTUK clustering list](https://drive.google.com/file/d/1okl0bdDbKKA0VCq9oed1dvpRLHktpUFE/preview)

  *Guntur*

  | Code | College | DB row | Candidates |
  |---|---|---|---|
  | 7T | Nannapaneni Venkata Rao CoE&T | c21 | 123 |
  | 7W | Malineni Perumallu Educational Society's Group | c20 | 45 |
  | MK | Sri Mittapalli Inst of Tech for Women | c28 | 100 |
  | KH | Narasaraopeta Institute of Technology, Kotappakonda | c37 | 110 |
  | AR | Sai Tirumala NVR Engg College | c41 | 100 |
  | 90 | Sri Chundi Ranganayakulu Engg College | c45 | 1 |

  *Krishna*

  | Code | College | DB row | Candidates |
  |---|---|---|---|
  | KK | Nova CoE&T, Ibrahimpatnam | c76 | 7 |
  | JC | DJR Institute of Engg & Tech, Velpur | c86 | 4 |
  | 7J | Sri Vani Educational Society Group | c79 | 4 |
  | R8 | Sri Sunflower CoE&T, Lankapalli | c93 | 2 |
  | JM | GDMM CoE&T | c72 | 15 |

  *West Godavari*

  | Code | College | DB row | Candidates |
  |---|---|---|---|
  | A0 | Nova CoE&T, Jangareddygudem | c168 | 15 |
  | 9F | Nova Institute of Technology, Eluru | c169 | 1 |
  | JH | GVVR Institute of Technology, Bhimavaram | c161 | 2 |
  | EM | Swarnandhra Inst of Engg & Tech, Narsapur | c167 | 59 |
  | HE | Jogaiah Inst of Tech & Sci | c165 | 1 |
  | PD | West Godavari Instt of Science and Engg, Prakasaraopalem, Nallajerla | c154 | 232 |

  *Prakasam*

  | Code | College | DB row | Candidates |
  |---|---|---|---|
  | L1 | VRS & YRN CoE&T, Chirala | c58 | 39 |
- **Not present in the same list:** c16 Chintalapudi EC, c22 ASN Women's, c34 PNC & Vijai, c55 Tenali EC (old code BN), c57 Vishwa Bharathi, c60 Haji Khasim, c54 Amara (old code AH), c102 Sarojini, c97 MSIT, c99 GIST, c100 Nimra Women's, c101 Nova Women's, c162/c163 Akula Sreeramulu, c164 SVISIT and c166 Gayatri. — [JNTUK clustering list](https://drive.google.com/file/d/1okl0bdDbKKA0VCq9oed1dvpRLHktpUFE/preview)
- **c16 identity:** Chintalapudi Engineering College (CECG, Technocrats Educational Society, est. 2009) and Velaga Nageswara Rao College of Engineering (VNRCE, est. 2008) are separate Ponnur-area colleges. The "NK Velaga Nageswara Rao Coll of Engg, Chintalapudi, Ponnur" entry, with 11 candidates, is **not** c16. — [careers360 VNRCE](https://www.careers360.com/colleges/velaga-nageswara-rao-college-of-engineering-ponnur), [collegedunia CECG](https://s4.collegedunia.com/college/57718-chintalapudi-engineering-college-cecg-guntur)
- **ANU:** none of the doubtful engineering colleges is ANU-affiliated. The only ANU link in this group is A S N Pharmacy College (ASNT), which the EAPCET-2026 list shows as `affiliated_to: ANU`. — [CAP EAPCET](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details)

### Inferences
- **Students admitted in 2022-2024 still sit April-2026 exams.** Exam rolls of 40–125 at colleges absent from 2026 counselling therefore fit a pattern of no new admission plus existing batches running out, as in progressive closure. These colleges will still have final-year (IV-year) students in 2026-27 if they admitted in 2023.
- **Counts of 1–15 almost certainly mean supplementary or backlog candidates only.** Those colleges have effectively stopped B.Tech teaching.
- **c76 Nova CET (KK, 7 candidates) has no real batches**, even though it appears in the 2026 seat matrix.

### Gaps
- No consolidated JNTUK 2025-26 or 2026-27 affiliation list or "no-admission" list was found. Per-college affiliation status therefore rests on proxies.
- The clustering list mixes regular and supplementary candidates, and I could not split them by year.
- No ANU affiliated-college list was fetched. It is not needed, because none of these colleges is ANU-affiliated for engineering.

## Q2. Are they in AICTE approved lists, or in AICTE closure / "progressive closure" lists?

### Takeaway
I could not check this directly. facilities.aicte-india.org timed out or reset the connection from both curl and WebFetch on 2026-11-07, and the press reports on AICTE closures do not name colleges. No named AICTE closure entry was found for any of the 34 colleges.

### Cited Findings
- **The aicte.gov.in home page links to the dashboards** for approved, closedinstitute and closedcourse at `facilities.aicte-india.org/dashboard/pages/angulardashboard.php#!/closedinstitute`. That host was unreachable on 2026-11-07, with no response from curl and ECONNRESET from WebFetch. — [AICTE](https://www.aicte.gov.in/)
- **AICTE reported 58 engineering and technical colleges closed nationally in 2025-26, three of them in Andhra Pradesh.** No names were given. — [Careers360, Jul 2026](https://news.careers360.com/aicte-58-engineering-technical-colleges-closed-academic-year-2025-26-btech-admission)
- **A Lok Sabha reply, reported by Careers360, gives different AP figures:** 1 closure in 2024-25, 7 in 2025-26 and 7 in 2026-27, so 15 over three years and 342 nationally. — [Careers360](https://news.careers360.com/342-aicte-approved-technical-institutions-shut-lok-sabha-reply)
- **What progressive closure means:** the institute cannot admit first-year students in that year, but enrolled students continue to completion. — [Careers360](https://news.careers360.com/aicte-58-engineering-technical-colleges-closed-academic-year-2025-26-btech-admission)
- **WISE (c154):** an aggregator cites the AICTE EoA 2024-25 for WISE, giving AICTE permanent ID 1-6590696 and application number 1-43661798582. — [collegeandfees](https://collegeandfees.com/colleges/west-godavari-institute-of-science-and-engineering-tadepalligudem)

### Inferences
- The 7 + 7 AP closures reported for 2025-26 and 2026-27 could plausibly include some of the "winding_down" or "residual" colleges here. This is not confirmed, so none is labelled closed.

### Gaps
- No AICTE approved, closure or progressive-closure entry was verified for any college. Retry from an Indian network, or ask the AICTE South-Central Regional Office.

## Q3. Do they appear in AP EAPCET 2025/2026 or AP ECET counselling?

### Takeaway
**Only c76 Nova CET (NVAV) of the 34 doubtful colleges is on the EAPCET-2026 seat matrix, and it had zero allotments.** Two colleges appear in ECET-2026:

- **c58 VRS & YRN (CCVY):** lateral entry only, with 0 allotted.
- **c76 Nova CET:** 0 allotted.

**c154 WISE is in both lists, with allotments.**

### Cited Findings
- **c76 Nova CET (EAPCET-2026, code NVAV):** entered 08/09/2026, affiliated to JNTUK. ENG branches AID, CIV, CSE, CSD, EEE, ECE and MEC total 360 convener seats, plus AEC and PHA seats, and 100% are left over. — [CAP EAPCET](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details)
- **c76 Nova CET (ECET-2026, code NVAV):** 12 branch rows with 614 seats, all left over. — [CAP ECET](https://api.cap.apcfss.in/oamreadapi/oam-public/ecet-clg-home-page-details)
- **c58 VRS & YRN (ECET-2026, code CCVY):** entered 30/06/2026. Seven branches (CIV 27, CSE 50, CSD 27, CIC 27, EEE 27, ECE 52, MEC 27) total 237 seats, all left over. It is absent from EAPCET-2026. — [CAP ECET](https://api.cap.apcfss.in/oamreadapi/oam-public/ecet-clg-home-page-details)
- **EAPCET-2026 lists only non-engineering programmes for some related institutions:**
  - pharmacy only: MPES (Malineni Perumallu), ASNT (A S N, Tenali), VBCP (Viswa Bharathi), VANI (Sri Vani School of Pharmacy), JITS (Jogaiah, Palakole), NOVP (Nova College of Pharmacy, Vegavaram) and NCPV (Nova Pharm, Jupudi)
  - B.Tech at the sister colleges, not at the doubtful rows: DJRC (c85, not c86), NMRE (Nimra CoE, c75, not c100) and SWRN (Swarnandhra CET, c155, not c167)

  — [CAP EAPCET](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details)
- **All other doubtful colleges are absent from both the EAPCET-2026 and ECET-2026 lists.** This was checked by name and code search on 2026-11-07. — [CAP EAPCET](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details), [CAP ECET](https://api.cap.apcfss.in/oamreadapi/oam-public/ecet-clg-home-page-details)
- **The APSCHE institution-data pages for codes NVRT, CCVY and WISE return only an empty template.** That page is not usable as evidence either way. — [APSCHE NVRT](https://eapcet-sche.aptonline.in/EAPCETAGR/getInstitutionData?code=NVRT)

### Inferences
- **For EAPCET-2025,** this round relied on the earlier DB claims and did not re-verify them: NVRT and CCVY were in the 2025 list, and NVAV was too. NVRCET and VRS & YRN therefore appear to have dropped out of convener counselling in 2026.

### Gaps
- No official EAPCET-2025 or ECET-2025 college list was re-fetched. The CAP API serves only the current (2026) cycle.

## Q4. Is there news of closure, merger, conversion or court cases, and what is the final status of each college?

### Takeaway
No college-specific news of closure, merger or court action was found. Saveetha Amaravati University has no B.Tech evidence at all. WISE (c154) is clearly active.

### Cited Findings
- **NVRCET (c21):** nannapaneni.org is live (fetched 2026-11-07). It shows college code NVRT, B.Tech branches including AI&ML and DS, M.Tech and polytechnic programmes, and no dated 2025/26 content. No closure news was found. — [nannapaneni.org](https://www.nannapaneni.org/)
- **Saveetha Amaravati (c61):**
  - Wikipedia calls it a state private university (UGC list), established in 2018, that "offers undergraduate studies in health sciences". B.Tech is not mentioned. — [Wikipedia](https://en.wikipedia.org/wiki/Saveetha_Amaravati_University)
  - saveethaamaravati.university did not resolve on 2026-11-07.
  - Aggregators claim 2026-27 admissions are open, but the claims are undated and inconsistent. — [aglasem](https://uni-admission.aglasem.com/andhra-pradesh/sau-vijayawada/)
- **Websites that did not resolve on 2026-11-07:** vycet.org (VRS & YRN), nova.ac.in (Nova) and wiseengineeringcollege.com (WISE). This is not evidence of closure.
- **Older press:** a Hans India article, undated in the results, reported that 6 of 40 Guntur colleges had under 25% admissions and were likely to close. It names no colleges. — [Hans India](https://thehansindia.com/andhra-pradesh/engineering-colleges-with-less-than-25-percent-admissions-in-andhra-to-be-closed-644388)

### Final status per college (detail in status_updates.csv)

| Status | Count | Colleges |
|---|---|---|
| winding_down (enrolled batches in Apr-2026, no 2026-27 B.Tech intake) | 7 | c21 NVRCET (123), c20 Malineni Perumallu (45), c28 Mittapalli Women (100), c37 Narasaraopeta IT (110), c41 Sai Tirumala NVR (100), c167 Swarnandhra Inst (59), c58 VRS & YRN (39, ECET-2026 lateral seats only, 0 allotted) |
| listed but no admissions | 1 | c76 Nova CET (on the 2026 EAPCET/ECET seat matrix, 0 allotted; 7 exam candidates) |
| possibly_closed, residual backlog only (1–15 candidates) | 7 | c45 Chundi (1), c72 GDMM (15), c86 DJR Institute (4), c93 Sunflower (2), c161 GVVR (2), c168 Nova Jangareddygudem (15), c169 Nova IT Eluru (1) |
| no B.Tech intake (institution runs pharmacy only) | 4 | c79 Sri Vani (4 backlog), c165 Jogaiah (1 backlog), c57 Vishwa Bharathi, c22 ASN Women's (the ASN group runs pharmacy only) |
| possibly_closed, no trace | 14 | c16, c34, c55, c60, c102, c97, c99, c100, c101, c54, c162, c163, c164, c166 (c73, status_final=duplicate of c72, is also untraced and is not counted here) |
| still unverified | 1 | c61 Saveetha Amaravati |
| closed (with an order) | 0 | none |

### c154 WISE, Nallajerla (old West Godavari, now East Godavari)

**Status: active.**

- **EAPCET-2026:** code WISE, entered 24/07/2026, affiliated to JNTUK, est. 2008. Convener seats are CSE 144, CSD 24, ECE 24 and MEC 24, so 216 in total, with 134 left over (82 allotted). — [CAP EAPCET](https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details)
- **ECET-2026:** 97 seats, 49 left over. — [CAP ECET](https://api.cap.apcfss.in/oamreadapi/oam-public/ecet-clg-home-page-details)
- **JNTUK April-2026 exams:** 232 candidates (code PD). — [JNTUK clustering list](https://drive.google.com/file/d/1okl0bdDbKKA0VCq9oed1dvpRLHktpUFE/preview)
- **2023-24 intake:** not verified from a primary source.
  - An aggregator citing the AICTE EoA 2024-25 gives 270: CSE 120, AI&DS 60, ECE 60 and ME 30. — [collegeandfees](https://collegeandfees.com/colleges/west-godavari-institute-of-science-and-engineering-tadepalligudem)

### Inferences
- **The 2026 seats are consistent with a sanctioned intake of 270 (180 + 30 + 30 + 30).** This assumes convener seats are 70% of intake plus 10% EWS supernumerary, i.e. 0.8 × intake.
- **Use 270 as the 2023-24 B.Tech intake for WISE, marked estimated.** The 2024-25 EoA (per the aggregator) and the 2026-27 seat matrix both give 270, but no 2023-24 document was seen.
- **The 232 April-2026 candidates across II–IV years suggest actual enrolment well below sanctioned intake,** at roughly 80 or fewer per batch.

### Gaps
- WISE's 2023-24 AICTE EoA and NIRF data were not found. nirfindia.org and the AICTE dashboard were not reachable or not searched.
- No dated news for any individual doubtful college was found. A phone check is still needed for c21 and c58 before any outreach.
