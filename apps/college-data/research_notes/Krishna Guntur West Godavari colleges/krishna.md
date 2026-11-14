# Krishna district (plus 2 Polavaram rows): B.Tech college verification

As of 7 Nov 2026. Scope: the 14 DB colleges with `district_id='krishna'`, the 2 with `district_id='polavaram'`, and one missing college that was found. Data files: `krishna_colleges.csv` (17 rows) and `krishna_branches.csv` (88 rows). The portal DB was only read, never changed.

## Headline
- **Active: 13 of the 14 Krishna DB rows plus the new ANR CET.** The 13 include YJR DMS, which is active under a new name. The other three rows:
  - Sunflower CET: possibly closed.
  - Sarojini IT: possibly closed.
  - Sri Viveka IT: merged into Lingayas (it is Lingayas's old EAPCET code, VIVK).
- **Both Polavaram rows are active.**
  - Lenora was in East Godavari district before the districts were split.
  - Dr Paul Raj's was in Khammam district until 2014, then in East Godavari.
  - Neither college was ever in old Krishna, Guntur or West Godavari.
- **One college is missing from the DB:** Akkineni Nageswara Rao College of Engineering & Technology, Gudivada.
  - EAPCET code ANRG; established 2025; 240 seats a year.
  - Its first batch was 49 students in 2025-26, so it has no final-year students until 2028-29.
- **Verified final-year B.Tech batch (students admitted in 2023-24): 4,680 at five colleges.** 2,640 of them are in IT-related branches.

  | College | Final-year batch | Of which IT-related |
  |---|---|---|
  | SRGEC | 1,380 | 900 |
  | SAHE | 1,320 | 600 |
  | PVPSIT | 720 | 420 |
  | Dhanekula | 720 | 420 |
  | Usha Rama | 540 | 300 |

  - For the other active colleges, no 2023-24 intake could be found on an official source. KRUCET's figure of 180 is an estimate.
- **RGUKT IIIT Nuzvid is now in Eluru district.** RGUKT's own tender notice dated Nov 2025 says "RGUKT-Nuzvid campus, Eluru district" (https://rguktn.ac.in/tenders/docs/2025/11/NIQ-20251127-01.pdf). The DB already has it as c96 under eluru, so it was not added here. Sri Sarathi (Nuzvid) and NRI (Agiripalli) are also in Eluru district.

## Corrections the DB needs
1. **SRGEC's 2023-24 intake was 1,380, not 1,500.**
   - Both the AICTE approval letter and the college's Mandatory Disclosure 2026 give 1,380. NIRF 2026 gives 1,500 for 2023-24, but 1,500 only started in 2024-25.
   - The Ambassador blueprint's "SRGEC 1,500 verified" final-year figure should be 1,380.
   - The DB's per-branch figures are 2026-27 EAPCET numbers. They drop the IoT branch, which still had 120 seats in 2025-26.
2. **SAHE and PVPSIT both closed new IT admissions for 2026-27**, approved by AICTE (approval letters on each college's site: SAHE, PVPSIT). The IT batches already admitted continue:
   - SAHE has 180 IT students in the final year.
   - PVPSIT has 120 IT students in the final year.
   - The DB leaves SAHE's IT intake blank and has no IT branch for PVPSIT.
3. **Usha Rama: AI&ML has 60 seats, not 120.**
   - AICTE approval 2025-26: AI&ML 60, CSE 240, total 660.
   - The 2026-27 EAPCET list shows a new CSE (AI) branch and no AI&ML. There is no 2026-27 AICTE approval letter to confirm this.
   - 2023-24 intake was 540 (542 admitted).
4. **Dhanekula:** 2023-24 intake was 720, including IT 120. AICTE approved 840 for 2024-25. The DB has no IT branch.
5. **Branches the DB lists that are not in the 2026 EAPCET counselling list:**
   - Lingayas AI&ML (DB 120)
   - KRUCET AI&ML (DB 60)

   Both appear on the colleges' own websites, but neither has a verified intake.
6. **Website and name corrections:**
   - KRUCET has its own site, krucet.ac.in.
   - PPD's site works only over plain http (http://www.ppdv.info/).
   - YJR DMS: the DB name is still "DMSSVH". The EAPCET code changed from SVHE to YJRC.
   - DPREC: the email in the DB appears only in hidden page code. The email shown on the page is principal@dprec.ac.in.
7. **Change Sri Viveka (c103) from possibly_closed to merged/renamed into Lingayas (c87)**, so it is not counted twice. Sunflower (c93), currently "pending":
   - It had no first-year EAPCET seat allotment in 2025 or 2026. Its last EAPCET cutoff row is from 2024.
   - Its website is stale.
   - No AICTE closure record was found.

## Best outreach targets in Krishna
Ranked by size and how complete the contact details are. All contacts below are official ones taken from the college sites cited in the CSV.

| College | Final year 2023-24 batch (IT-related) | TPO contact | Social media |
|---|---|---|---|
| SRGEC | 1,380 (900) | 9397097070 | Instagram, LinkedIn |
| SAHE | 1,320 (600) | 9440219816 | LinkedIn |
| PVPSIT | 720 (420) | 0866-2581699 ext. 250 | Instagram, LinkedIn, YouTube |
| Dhanekula | 720 (420) | Office 9491017088 | Instagram, YouTube |
| Usha Rama | 540 (300) | 99593 12255 | Instagram, YouTube |

Notes on these five:
- **PVPSIT** has HOD phone numbers on its contact page.
- **Dhanekula** names its TPO (S. Sri Harsha) but publishes no direct number or email for him.
- **PVPSIT event:** Qiskit Fall Fest 2026. The date is not published.
- **SRGEC events:** the PUNARVA '26 waste-to-worth challenge. SRGEC also runs Coding, Drone and Techno clubs.
- **Timing:** SRGEC's IV B.Tech mid exams were rescheduled on 6 Nov 2026.

Mid-size colleges with branch intake known only from the EAPCET counselling list:
- Sri Vasavi IET: 540 seats a year; 1,707 UG students (2024-25, NBA self-assessment report). It has an ISTE chapter of 191 members and an Instagram account.
- VKR VNB AGK: 450 seats a year; TPO Dr N. Dhanunjaya Rao, 9428215555.
- Lingayas: 480 seats a year.
- YJR DMS: 300 seats a year. It ran a Smart India Hackathon internal round on 27 Sep 2026, and has Instagram and LinkedIn accounts.

Very low first-year fill in 2026 counselling: KRUCET, PPD, Lenora and DPREC. The "left_over_seats" field in the official list is close to the full seat count at these four.

## Method and sources
- **Activity:** official AP EAPCET-2026 counselling college list, https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details (re-downloaded 7 Nov 2026), plus each college's own pages.
  - The 2025 allotment check used a third-party list (eduvale), so it is marked as secondary.
- **Verified intake:** AICTE approval letters (EoA) and mandatory disclosures hosted on the college sites, and NIRF PDFs. The exact URL is in each CSV row.
- **"EAPCET-derived" intake:** the convener seats in the 2026 list divided by 0.8. These are marked estimated and medium confidence.
  - KRUCET is a university self-finance college, so its seats are taken as intake plus 10%. Its intake is therefore an estimate.
- **Reused:** contacts and NIRF figures from `research_notes/Path to 400 enrollments 2026/contacts_guntur_krishna.md` and `contacts_godavari.md`.

## Gaps
- **No 2023-24 branch-wise intake was found for:** Lingayas, PPD, YJR DMS, VKR, KRUCET, Lenora, DPREC, and the non-CSE branches of Sri Vasavi.
  - The AICTE dashboard (facilities.aicte-india.org) was unreachable.
  - Sri Vasavi's 2025-26 AICTE approval letter is a scanned image and needs reading by hand.
- **No NIRF figures:** Usha Rama's NIRF links return 404, and NIRF 2026 for Dhanekula is not posted. Six others publish no NIRF data at all: Lingayas, PPD, YJR DMS, KRUCET, VKR and Sri Vasavi.
- **2026-27 AICTE approval not posted** for SRGEC, Usha Rama or Dhanekula. This means it is unconfirmed whether these 2026 branch changes are real:
  - SRGEC dropping IoT
  - Usha Rama replacing AI&ML with CSE (AI)
  - Dhanekula dropping IT
- **Events:** almost no dated fests or hackathons were found for Nov 2026 to Mar 2027. Confirm with each TPO when calling.
- **Not re-checked this pass:** SRGEC's 6,209 and Dhanekula's 2,494 student totals are carried over from earlier notes, because their PDFs timed out.
