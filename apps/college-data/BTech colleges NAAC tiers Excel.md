# Sorting 128 delta B.Tech colleges into tiers

The four old districts of Guntur, Krishna (Vijayawada), East Godavari and West Godavari have **128 B.Tech institutions that appear active for 2026-27**, plus **42 that look closed or inactive**. Of the 128, **8 are Tier 1, 32 are Tier 2 and 88 are Tier 3** under the rule set out below; the tiers are our classification, not an official one. By ownership the region has **1 national institute (NIT Andhra Pradesh), 9 government state-university colleges or campuses, 4 deemed universities, 7 state private universities, 66 UGC-autonomous private colleges and 41 non-autonomous affiliated private colleges**. Tier 1 is concentrated in the Amaravati–Guntur belt: KL (NIRF 2025 Engineering rank 35), Vignan (80), SRM AP, VIT-AP, Amrita Amaravati and ANU College of Engineering, plus JNTUK UCE Kakinada and NIT AP. Tier 2 is mostly autonomous colleges with a reported NAAC A or better, the five converted universities (VVIT, Aditya, Godavari Global, Vishnu Women's, Siddhartha Academy) and PVPSIT, the only affiliated college holding a NIRF 2025 Engineering band (201-300). The biggest correction to earlier lists is **autonomy**: the UGC list dated 28.02.2026 names many more autonomous colleges than JNTUK directories show, including KITS Akshar (ex-Guntur EC), RV Institute of Technology (ex-Chebrolu EC), St. Ann's Chirala, DNR, Sasi, Ramachandra and Sir C R Reddy ([UGC 2026](https://www.ugc.gov.in/pdfnews/8688705_List-of-Autonomous-Colleges.pdf)). Treat the NAAC column with care: **only about a dozen grades come from official or college documents; the rest are aggregator-reported**, and NIRF 2026 had not been published as of 2 Nov 2026 ([Careers360](https://engineering.careers360.com/articles/nirf-ranking-for-engineering-colleges)).

A machine-readable master file with all 170 rows (128 active, 42 possibly closed) and the full column set is saved alongside this report as `reports/btech_colleges_master.csv`. Row numbers (S.No) in every table below match that file.

## One explicit rule decides every tier

The tier is assigned from three signals in order: national status, NIRF 2025, then NAAC grade combined with UGC autonomy. Each row carries a short "Tier basis" phrase saying which signal placed it.

| Tier | Rule (applied in this order) |
|---|---|
| **Tier 1** | Institute of National Importance (NIT AP); or NIRF 2025 Engineering rank ≤150 or NIRF University rank ≤100 (KL, Vignan deemed, JNTUK UCE Kakinada via JNTUK's Engineering 101-150 band, ANU College of Engineering via ANU's University rank 84); or a major national private university with multi-state standing (SRM AP, VIT-AP, Amrita Amaravati). |
| **Tier 2** | NIRF 2025 Engineering 151-300 or University 101-200; or NAAC A++/A+ (current or recently reported, including aggregator reports); or UGC-autonomous with a reported NAAC A; or a state private university converted from a strong college (VVIT, Aditya, Godavari Global, Vishnu Women's) or Siddhartha Academy. |
| **Tier 3** | Every other active institution, including autonomous colleges with no NAAC grade found, colleges with only B/B++ grades, and colleges where an A grade conflicts with a lower one from another source. |
| **Inactive?** | Possibly closed or inactive institutions get no tier. |

Three judgement calls follow from the rule and are applied consistently. First, a university's NIRF band passes to a constituent college only when that college is the parent's main engineering campus, so UCE Kakinada and ANU College of Engineering inherit, while JNTUK UCE Narasaraopet, the JNTUK School of Food Technology and the two ANGRAU colleges at Bapatla do not. Second, where an A-or-better grade and a lower grade come from sources of similar weight with no dates (Srinivasa IET, Sir C R Reddy), the row stays Tier 3 and is flagged "borderline Tier 2"; where the lower grade is an older, expired first cycle (Bapatla EC, SRGEC), the newer higher report counts. Third, **SRM AP and VIT-AP are Tier 1 by the national-university clause alone**: neither appears in any NIRF 2025 Engineering or University band, and neither has an AP-specific NAAC grade on record ([NIRF 2025 Engineering](https://www.nirfindia.org/Rankings/2025/EngineeringRanking.html); [Careers360 Q&A](https://www.careers360.com/question-give-me-vit-ap-nirf-ranking-document-and-naac-grade-document-proof)).

Ownership uses exactly six categories. "Autonomous" means UGC autonomous-college status, so universities, deemed universities and national institutes show "No" (they are degree-awarding bodies, not autonomous colleges). Autonomy comes from the UGC lists of 27.08.2024 ([UGC 2024](https://www.ugc.gov.in/pdfnews/0062368_Latest-832-Auto-Colleges.pdf)) and 28.02.2026 ([UGC 2026](https://www.ugc.gov.in/pdfnews/8688705_List-of-Autonomous-Colleges.pdf)), and these override the earlier JNTUK-directory labels.

## 66 of 128 active colleges are now UGC autonomous

Autonomy has spread far faster than accreditation data can be confirmed. Every region has more autonomous than non-autonomous private colleges, and in Krishna 22 of 32 private colleges are autonomous. Of the 66 autonomous colleges, 39 remain Tier 3 because no NAAC grade could be found or the reported grade is below A.

**Active institutions by region and ownership category**

| Region (old district) | Govt – National | Govt – State univ/constituent | Deemed (pvt) | State pvt univ | Pvt autonomous | Pvt affiliated | Active total | Possibly closed |
|---|---|---|---|---|---|---|---|---|
| Guntur | 0 | 4 | 3 | 4 | 23 | 19 | **53** | 8 |
| Krishna (Vijayawada) | 0 | 2 | 1 | 0 | 22 | 10 | **35** | 7 |
| East Godavari | 0 | 3 | 0 | 2 | 11 | 9 | **25** | 17 |
| West Godavari | 1 | 0 | 0 | 1 | 10 | 3 | **15** | 10 |
| **All four regions** | **1** | **9** | **4** | **7** | **66** | **41** | **128** | **42** |

**Active institutions by region and tier**

| Region (old district) | Tier 1 | Tier 2 | Tier 3 | Active total |
|---|---|---|---|---|
| Guntur | 6 | 14 | 33 | 53 |
| Krishna (Vijayawada) | 0 | 4 | 31 | 35 |
| East Godavari | 1 | 5 | 19 | 25 |
| West Godavari | 1 | 9 | 5 | 15 |
| **All four regions** | **8** | **32** | **88** | **128** |

Guntur holds 6 of the 8 Tier 1 institutions because the Amaravati capital belt attracted the deemed and national private universities. West Godavari is the opposite profile: few institutions, but 9 of its 15 reach Tier 2 because its Bhimavaram and Tadepalligudem colleges have documented NAAC grades. Krishna's 31 Tier 3 rows are mostly autonomous colleges whose NAAC grade simply could not be found, which makes Krishna the region most likely to gain Tier 2 rows once grades are checked on the NAAC portal.

## Old Guntur: six Tier 1 universities and 14 strong colleges

Old Guntur covers present Guntur, Palnadu and Bapatla districts, including the two Chirala colleges that counselling files under old Prakasam. **KL is NIRF 2025 Engineering 35 (University 26, Overall 46) and Vignan's deemed university is Engineering 80 (University 70)**; these are the only old-Guntur institutions in any NIRF 2025 Engineering list ([NIRF 2025 Engineering](https://www.nirfindia.org/Rankings/2025/EngineeringRanking.html); [NIRF 2025 University](https://www.nirfindia.org/Rankings/2025/UniversityRanking.html)). Acharya Nagarjuna University is University rank 84, which lifts its engineering college into Tier 1. Vignan's NAAC A+ (CGPA 3.49) ran from 26 Oct 2021 to **25 Oct 2026 and has just expired**, with a third cycle pending ([Vignan](https://vignan.ac.in/newvignan/naac.php)); KL's A++ (3.57) dates from about 2018 ([HigherEducationPlus](https://highereducationplus.com/naac-a-accreditation-conferred-to-kl-university/)). Amrita's A++ is university-wide and covers the Amaravati campus ([Amrita](https://www.amrita.edu/accreditation/national-assessment-and-accreditation-council/)).

Two corrections from the new notes change rows. **RV Institute of Technology is the renamed Chebrolu Engineering College and KITS Akshar Institute of Technology is the renamed Guntur Engineering College**, so they appear once each as active colleges rather than as "possibly closed" duplicates ([StartupGrants India](https://www.startupgrantsindia.com/providers/chebrolu-engineering-college); [Collegedunia](https://collegedunia.com/college/13646-guntur-engineering-college-gec-guntur)). **St. Ann's College of Engineering & Technology, Chirala is active and autonomous** (UGC 2026 list). The 2026 UGC list also adds KITS Akshar, Priyadarshini ITM, Priyadarshini ITS, Vignan's Nirula, A.M. Reddy Memorial, Eswar, Newton's Institute of Engineering and Chirala EC to the autonomous column; none of these was autonomous in the 2024 list. The older first-cycle NAAC records from NAAC's Sept 2019 list (KHIT A 3.20, KKR&KSR A 3.02, Bapatla EC B 2.70) have passed their five-year validity, while aggregators now report A or A+ for most of the strong private colleges without dates ([NAAC 2019 list via Scribd](https://www.scribd.com/document/433790073/Institutions-accredited-by-NAAC-whose-accreditation-period-is-valid-as-on-September-2019-xls); [Collegedunia Guntur](https://collegedunia.com/btech/guntur-colleges)).

| S.No | College (town) | New district | Ownership | Auto. | NAAC (grade; CGPA; validity; source) | NBA | NIRF 2025 | EAPCET code | Tier | Tier basis |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **KL University (Koneru Lakshmaiah Education Foundation)** (Vaddeswaram, Tadepalli mdl) | Guntur | Deemed (pvt) | No | A++; 3.57; c.2018; current cycle not found (Aggregator) | — | Engg 35; Univ 26; Overall 46 | Not in EAPCET | Tier 1 | NIRF Engg 35 |
| 2 | **Vignan's Foundation for Science, Technology & Research (deemed)** (Vadlamudi, Chebrolu mdl) | Guntur | Deemed (pvt) | No | A+; 3.49; 2nd cycle 26-10-2021 to 25-10-2026 (just expired; 3rd cycle pending) (College site) | — | Engg 80; Univ 70; Overall 101-150 | Not in EAPCET | Tier 1 | NIRF Engg 80 |
| 3 | **SRM University AP** (Neerukonda, Mangalagiri mdl) | Guntur | State pvt univ | No | — | — | Not in 2025 Engg/Univ lists | EAPCET convener quota (1,450 seats 2026) | Tier 1 | Major national private university (multi-state) |
| 4 | **VIT-AP University** (Inavolu, Thullur mdl) | Guntur | State pvt univ | No | — | — | Not in 2025 Engg/Univ lists | EAPCET convener quota (1,814 seats 2026) | Tier 1 | Major national private university (multi-state) |
| 5 | **VVIT University (Vasireddy Venkatadri International Technological University), formerly VVIT** (Namburu, Pedakakani mdl) | Guntur | State pvt univ | No | A (as college); 3.09; Mar 2016 (college); later cycle not found (Aggregator) | — | Not in 2025 Engg top 300 | EAPCET convener quota (2,240 seats 2026); code not verified | Tier 2 | State pvt university converted from strong college |
| 6 | **Amrita Vishwa Vidyapeetham, Amaravati campus** (Kuragallu, Mangalagiri mdl) | Guntur | Deemed (pvt) | No | A++ (university-wide) (College site) | — | Not listed separately | Not in EAPCET | Tier 1 | Major national private university (multi-state) |
| 7 | **Chalapathi University** (Guntur (Lam area?)) | Guntur | State pvt univ | No | — | — | — | — | Tier 3 | New private university; no NAAC/NIRF |
| 8 | **ANU College of Engineering & Technology (Acharya Nagarjuna University)** (Nagarjuna Nagar) | Guntur | Govt – State univ/constituent | No | A+ (parent ANU); 3.46 (parent); Conflicts with ANU A 3.08 (Dec 2016) (Aggregator) | — | Not in Engg list; parent ANU Univ 84, Overall 101-150 | — | Tier 1 | Parent ANU NIRF Univ 84 |
| 9 | **RVR & JC College of Engineering** (Chowdavaram) | Guntur | Pvt autonomous | Yes | A+; Undated (one listing says A++) (Aggregator) | — | Not in 2025 Engg top 300 | RVRJ (cited; not verified) | Tier 2 | NAAC A+ (reported) + autonomous |
| 10 | **Chalapathi Institute of Engineering & Technology (CIET)** (Lam) | Guntur | Pvt autonomous | Yes | A (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | Autonomous + NAAC A (reported) |
| 11 | **Chalapathi Institute of Technology** (Mothadaka, Tadikonda mdl) | Guntur | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 12 | **KKR & KSR Institute of Technology & Sciences** (Vinjanampadu, Vatticherukuru mdl) | Guntur | Pvt autonomous | Yes | A; 3.02; 1st cycle (NAAC list valid Sept 2019; likely expired) (Official) | Reported (aggregator) | Not in 2025 Engg top 300 | — | Tier 2 | Autonomous + NAAC A |
| 13 | **Kallam Haranadhareddy Institute of Technology (KHIT)** (Chowdavaram) | Guntur | Pvt autonomous | Yes | A; 3.20; 1st cycle (NAAC list valid Sept 2019; likely expired) (Official) | — | Not in 2025 Engg top 300 | KHIT (2025) | Tier 2 | Autonomous + NAAC A |
| 14 | **KITS Akshar Institute of Technology (formerly Guntur Engineering College)** (Yanamadala, Prathipadu mdl) | Guntur | Pvt autonomous | Yes | A (Aggregator) | — | Not in 2025 Engg top 300 | GECG (undated, old name) | Tier 2 | Autonomous + NAAC A (reported) |
| 15 | **RV Institute of Technology (formerly Chebrolu Engineering College)** (Chebrolu) | Guntur | Pvt autonomous | Yes | A (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | Autonomous + NAAC A (reported) |
| 16 | **Chintalapudi Engineering College** (Chintalapudi (Ponnur side)) | Guntur? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 17 | **GVR&S College of Engineering & Technology** (Guntur) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 18 | **Hindu College of Engineering & Technology** (Amaravati Road, Guntur) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 19 | **Malineni Lakshmaiah Women's Engineering College** (Pulladigunta, Vatticherukuru mdl) | Guntur | Pvt autonomous | Yes | A+ (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | NAAC A+ (reported) + autonomous |
| 20 | **Malineni Perumallu Educational Society's Group of Institutions** (Pulladigunta) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 21 | **NVR College of Engineering & Technology** (Tenali) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 22 | **ASN Women's Engineering College** (Tenali) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 23 | **NRI Institute of Technology, Guntur** (Visadala, Medikonduru mdl) | Guntur | Pvt autonomous | Yes | A+ (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | NAAC A+ (reported) + autonomous |
| 24 | **Priyadarshini Institute of Technology & Management** (Kornepadu, Vatticherukuru mdl) | Guntur | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 25 | **Priyadarshini Institute of Technology & Science** (Duggirala / Chintalapudi, Tenali) | Guntur? | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 26 | **Priyadarshini Institute of Technology & Science for Women** (Chintalapudi, Tenali) | Guntur? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 27 | **Sri Mittapalli College of Engineering** (Tummalapalem) | Guntur | Pvt autonomous | Yes | A+ (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | NAAC A+ (reported) + autonomous |
| 28 | **Sri Mittapalli Institute of Technology for Women** (Chintalapudi) | Guntur? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 29 | **St. Mary's Group of Institutions Guntur (for Women)** (Chebrolu) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | SMGG (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 30 | **St. Mary's Women's Engineering College** (Budampadu) | Guntur | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 31 | **Universal College of Engineering & Technology** (Dokiparru, Medikonduru mdl) | Guntur | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 32 | **Vignan's Lara Institute of Technology & Science** (Vadlamudi, Chebrolu mdl) | Guntur | Pvt autonomous | Yes | A+ (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | NAAC A+ (reported) + autonomous |
| 33 | **Vignan's Nirula Institute of Technology & Science for Women** (Palakaluru) | Guntur | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 34 | **PNC & Vijai Institute of Engineering & Technology** (Pirangipuram) | Guntur? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 35 | **JNTUK University College of Engineering Narasaraopet** (Narasaraopet) | Palnadu | Govt – State univ/constituent | No | — | — | Parent JNTUK Engg 101-150 (not inherited) | JNTN (2025) | Tier 3 | Satellite constituent college; parent rank not inherited |
| 36 | **Narasaraopeta Engineering College (NEC)** (Yellamanda, Narasaraopet) | Palnadu | Pvt autonomous | Yes | A+ / A (conflicting) (College site) | — | Not in 2025 Engg top 300 | NSPE (2025) | Tier 2 | NAAC A+ (self-reported) + autonomous |
| 37 | **Narasaraopeta Institute of Technology** (Yellamanda) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 38 | **A.M. Reddy Memorial College of Engineering & Technology** (Petlurivaripalem, Narasaraopet) | Palnadu | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 39 | **Eswar College of Engineering** (Kesanupalli, Narasaraopet) | Palnadu | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 40 | **Krishnaveni Engineering College for Women** (Narasaraopet) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 41 | **Sai Tirumala NVR Engineering College** (Narasaraopet) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 42 | **Tirumala Engineering College** (Jonnalagadda, Narasaraopet) | Palnadu | Pvt autonomous | Yes | A+ (Aggregator) | — | Not in 2025 Engg top 300 | — | Tier 2 | NAAC A+ (reported) + autonomous |
| 43 | **Loyola Institute of Technology & Management (LITAM)** (Dhulipalla, Sattenapalli) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 44 | **Varaprasad Reddy Institute of Technology (formerly Nalanda IET)** (Sattenapalli) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 45 | **Sri Chundi Ranganayakulu Engineering College** (Ganapavaram, Chilakaluripet) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 46 | **Newton's Institute of Engineering** (Arugurajupally, Macherla) | Palnadu | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |
| 47 | **Newton's Institute of Science & Technology** (Macherla) | Palnadu | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Affiliated; no NAAC/NIRF found |
| 48 | **Bapatla Engineering College** (Bapatla) | Bapatla | Pvt autonomous | Yes | A+ (aggregator) / B (2019 NAAC list); 2.70 (B, 1st cycle); B valid to 02-03-2020; A+ undated (Aggregator) | — | Not in 2025 Engg top 300 | BECB (2025) | Tier 2 | NAAC A+ (reported; conflicts) + autonomous |
| 49 | **Bapatla Women's Engineering College** (Bapatla) | Bapatla | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | BWEC (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 50 | **Dr. NTR College of Agricultural Engineering (ANGRAU)** (Bapatla) | Bapatla | Govt – State univ/constituent | No | — | — | Parent ANGRAU Univ 151-200 (not inherited) | CABP (2025) | Tier 3 | Constituent college; parent rank not inherited |
| 51 | **Dr. NTR College of Food Science & Technology (ANGRAU)** (Bapatla) | Bapatla | Govt – State univ/constituent | No | — | — | Parent ANGRAU Univ 151-200 (not inherited) | CFSB (2025) | Tier 3 | Constituent college; parent rank not inherited |
| 52 | **Chirala Engineering College** (Akkayapalem, Vetapalem (Chirala)) | Bapatla | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | CECC (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 53 | **St. Ann's College of Engineering & Technology** (Chirala) | Bapatla | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | — | Tier 3 | Autonomous; NAAC grade not found |

## Old Krishna: Siddhartha and PVPSIT carry the NIRF bands

Old Krishna splits into NTR district, Krishna district and the Nuzvid–Agiripalli belt now in Eluru district. **Siddhartha Academy of Higher Education (ex-VR Siddhartha) is NIRF 2025 Engineering 151-200** and became a deemed university in 2024; it admits through its own SEEE test ([vrsiddhartha.ac.in](https://www.vrsiddhartha.ac.in/?p=11410); [Wikipedia](https://en.wikipedia.org/wiki/Siddhartha_Academy_of_Higher_Education)). **PVPSIT is Engineering 201-300** and reported NAAC A+ ([Shiksha](https://www.shiksha.com/college/prasad-v-potluri-siddhartha-institute-of-technology-vijayawada-24531/ranking); [Zollege](https://zollege.in/college/173908-prasad-v-potluri-siddhartha-institute-of-technology-pvpsit-vijayawada)). LBRCE (NAAC A 3.20, seven NBA-accredited programmes) was 201-300 in 2024 but is absent in 2025 ([Collegedunia](https://collegedunia.com/college/14074-lakireddy-bali-reddy-college-of-engineering-lbrce-krishna)). Gudlavalleru (SRGEC) shows both a B++ (2.91, valid to 27 Sep 2026) and a newer A+ on the same Careers360 page; the A+ is taken as the likely reaccreditation ([Careers360](https://www.careers360.com/colleges/seshadri-rao-gudlavalleru-engineering-college-gudlavalleru)).

The UGC 2026 list settles the autonomy disputes: **Dhanekula (2023-24 to 2027-28), SRK (2023-24 to 2032-33) and Andhra Loyola (2024-25 to 2033-34) are autonomous**, as are PSCMR, both Vikas institutions, Mandava, Nimra, RK, Sree Vahini, Lingayas, VKR VNB AGK, Sri Vasavi IET and Vijaya Women's ([UGC 2026](https://www.ugc.gov.in/pdfnews/8688705_List-of-Autonomous-Colleges.pdf)). Their NAAC grades were not found, so they sit in Tier 3 despite autonomy. EAPCET codes here are undated aggregator codes ([colleges9](https://www.colleges9.in/Andhra-Pradesh/Krishna/Engineering-Colleges/)).

| S.No | College (town) | New district | Ownership | Auto. | NAAC (grade; CGPA; validity; source) | NBA | NIRF 2025 | EAPCET code | Tier | Tier basis |
|---|---|---|---|---|---|---|---|---|---|---|
| 62 | **Lakireddy Bali Reddy College of Engineering (LBRCE)** (Mylavaram) | NTR | Pvt autonomous | Yes | A; 3.20 (Aggregator) | Yes: 7 B.Tech programmes, Tier-I (aggregator) | Not in 2025 Engg top 300 (201-300 in 2024) | LBCE (undated) | Tier 2 | Autonomous + NAAC A |
| 63 | **DVR & Dr HS MIC College of Technology** (Kanchikacherla) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | MICT (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 64 | **Amrita Sai Institute of Science & Technology** (Paritala, Kanchikacherla mdl) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | ASIP (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 65 | **MVR College of Engineering & Technology** (Paritala) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | MVRS (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 66 | **Andhra Loyola Institute of Engineering & Technology** (Vijayawada) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | ALIT (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 67 | **SRK Institute of Technology** (Enikepadu, Vijayawada Rural) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | SRKI (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 68 | **Potti Sriramulu Chalavadi Mallikharjuna Rao College of Engineering & Technology (PSCMR)** (Kothapeta, Vijayawada) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | PSCV (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 69 | **Vijaya Institute of Technology for Women** (Enikepadu) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | VITW (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 70 | **Vikas College of Engineering & Technology** (Nunna, Vijayawada Rural) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | VCTN (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 71 | **Vikas Group of Institutions** (Nunna (or Vissannapet)) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | VGTN (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 72 | **GDMM College of Engineering & Technology** (Nandigama) | NTR | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | GDMM (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 73 | **Gurindapalli Devananda Mary Memorial College of Engineering & Technology for Women** (Nandigama) | NTR | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | GDNW (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 74 | **Mandava Institute of Engineering & Technology** (Jaggayyapeta) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | MIET (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 75 | **Nimra College of Engineering & Technology** (Jupudi, Ibrahimpatnam) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | NMRV (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 76 | **Nova College of Engineering & Technology** (Jupudi, Ibrahimpatnam) | NTR | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | NVAV (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 77 | **RK College of Engineering** (Kethanakonda, Ibrahimpatnam) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | RKCE (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 78 | **Sree Vahini Institute of Science & Technology** (Nadim, Tiruvuru) | NTR | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | VHNI (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 79 | **Sri Vani School of Engineering** (Chevuturu, G. Konduru) | NTR | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | VANI (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 80 | **Siddhartha Academy of Higher Education (formerly VR Siddhartha Engineering College)** (Kanuru, Penamaluru mdl) | Krishna? | Deemed (pvt) | No | — | — | Engg 151-200 | VRSE (pre-2024) | Tier 2 | NIRF Engg 151-200; Siddhartha Academy |
| 81 | **Prasad V Potluri Siddhartha Institute of Technology (PVPSIT)** (Kanuru) | Krishna? | Pvt autonomous | Yes | A+ (Aggregator) | — | Engg 201-300 | PPSV (undated) | Tier 2 | NIRF Engg 201-300 |
| 82 | **Seshadri Rao Gudlavalleru Engineering College (SRGEC)** (Gudlavalleru) | Krishna | Pvt autonomous | Yes | A+ (reported) / B++ (conflicting); 2.91 (B++ cycle); B++ Sep 2021 to 27-09-2026; A+ undated (Aggregator) | Yes (aggregator) | Not in 2025 Engg top 300 | GDLV (undated) | Tier 2 | NAAC A+ (reported; conflicts) + autonomous |
| 83 | **Usha Rama College of Engineering & Technology** (Telaprolu, Unguturu mdl) | Krishna | Pvt autonomous | Yes | Accredited (grade not found) (Aggregator) | — | Not in 2025 Engg top 300 | URCE (undated) | Tier 3 | Autonomous; NAAC grade unknown |
| 84 | **Dhanekula Institute of Engineering & Technology** (Ganguru, Penamaluru mdl) | Krishna | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | DHAN (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 85 | **Sri Chaitanya DJR College of Engineering & Technology** (Velpur / Gudavalli) | Krishna? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | DJRC (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 86 | **Sri Chaitanya DJR Institute of Engineering & Technology** (Velpur / Gudavalli) | Krishna? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | DJRV (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 87 | **Lingayas Institute of Management & Technology** (Madalavarigudem, Gannavaram mdl) | Krishna | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | LIMT (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 88 | **Paladugu Parvathi Devi College of Engineering & Technology** (Surampalli, Gannavaram mdl) | Krishna | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | PPDV (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 89 | **DMSSVH College of Engineering** (Machilipatnam) | Krishna | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | SVHE (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 90 | **Krishna University College of Engineering & Technology** (Rudravaram, Machilipatnam) | Krishna | Govt – State univ/constituent | No | — | — | Not in 2025 Engg top 300 | KRUESF (2025) | Tier 3 | State univ college; no NAAC/NIRF found |
| 91 | **VKR, VNB & AGK College of Engineering** (Gudivada) | Krishna | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | VVGV (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 92 | **Sri Vasavi Institute of Engineering & Technology** (Nandamuru, Pedana) | Krishna | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | SVET (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 93 | **Sri Sunflower College of Engineering & Technology** (Lankapalli, Challapalli) | Krishna | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | SUNL (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 94 | **NRI Institute of Technology, Agiripalli** (Pothavarappadu, Agiripalli mdl) | Eluru? | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | NRIA (undated) | Tier 3 | Autonomous; NAAC grade not found |
| 95 | **Sri Sarathi Institute of Engineering & Technology** (Nuzvid) | Eluru | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | SIEN (undated) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 96 | **RGUKT IIIT Nuzvid** (Nuzvid) | Eluru | Govt – State univ/constituent | No | — | — | — | Not in EAPCET | Tier 3 | State univ campus; no NAAC/NIRF found |

## Old East Godavari: two A++ universities and a long Tier 3 tail

Old East Godavari spans Kakinada, East Godavari and Konaseema districts, plus Lenora and Dr. Paul Raj's colleges now in Alluri Sitharama Raju district, which are counted here because the region is defined by old district. **JNTUK UCE Kakinada (est. 1946) is Tier 1** through JNTUK's NIRF 2025 Engineering 101-150 band, and is reported NAAC A+ to 2028 ([Careers360](https://www.careers360.com/colleges/jawaharlal-nehru-technological-university-college-of-engineering-kakinada); [NIRF 101-150](https://www.nirfindia.org/Rankings/2025/EngineeringRanking150.html)). **Aditya University (A++, 3.60, valid to 30 Apr 2028) and Godavari Global University (A++, 3.58, third cycle claimed) both sit in NIRF 2025 Engineering 201-300** ([Careers360 Aditya](https://www.careers360.com/university/aditya-university-surampalem); [ggu.edu.in](https://ggu.edu.in/?p=2601); [NIRF 201-300](https://www.nirfindia.org/Rankings/2025/EngineeringRanking300.html)). Pragati's own disclosure shows only a first-cycle A (3.08) that expired in Dec 2021, against an unverified A++ claim for 2023 ([pragati.ac.in](https://pragati.ac.in/wp-content/uploads/2024/04/5.1.14.pdf)). All codes are 2025 allotment codes ([eduvale](https://eduvale.in/ap-eapcet/college-wise-cutoff-allotment/)).

| S.No | College (town) | New district | Ownership | Auto. | NAAC (grade; CGPA; validity; source) | NBA | NIRF 2025 | EAPCET code | Tier | Tier basis |
|---|---|---|---|---|---|---|---|---|---|---|
| 104 | **JNTUK University College of Engineering Kakinada (UCEK)** (Kakinada) | Kakinada | Govt – State univ/constituent | Unclear | A+; 2023, valid till 2028 (Aggregator) | — | JNTUK Engg 101-150 (official; parent) | JNTK, JNTKSF, JNTKSS (2025) | Tier 1 | Parent JNTUK NIRF Engg 101-150 |
| 105 | **School of Food Technology, JNTUK Kakinada** (Kakinada) | Kakinada | Govt – State univ/constituent | No | — | — | Not in 2025 Engg top 300 | JNKFSF (2025) | Tier 3 | Constituent unit; parent rank not inherited |
| 106 | **Aditya University (formerly Aditya Engineering College)** (Surampalem, Gandepalli mdl) | Kakinada | State pvt univ | No | A++; 3.60; 2nd cycle, May 2023 to 30-04-2028 (earned as AEC) (Aggregator) | Reported for AEC programmes (aggregator) | Engg 201-300 (official); Univ 151-200 (aggregator) | ADTPPU (2025); old ADTP | Tier 2 | NIRF Engg 201-300; NAAC A++; converted strong college |
| 107 | **Pragati Engineering College** (Surampalem) | Kakinada | Pvt autonomous | Yes | A (official, expired) / A++ claimed; 3.08 (1st cycle); 11-05-2015 to 31-12-2021; A++ 3.76 (2023) unverified (College site) | Yes (aggregator) | Not in 2025 Engg top 300 | PRAG (2025) | Tier 2 | Autonomous + NAAC A |
| 108 | **Kakinada Institute of Engineering & Technology (KIET)** (Korangi, Tallarevu mdl) | Kakinada | Pvt affiliated | No | B++ (Aggregator) | — | Not in 2025 Engg top 300 | KIET (2025) | Tier 3 | Affiliated; NAAC B++ |
| 109 | **Kakinada Institute of Engineering & Technology-II** (Korangi, Tallarevu mdl) | Kakinada | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | KIEK (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 110 | **Kakinada Institute of Engineering & Technology for Women** (Korangi) | Kakinada | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | KIEW (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 111 | **Kakinada Institute of Technology & Science (KITS), Peddapuram** (Tirupathi village, Peddapuram mdl) | Kakinada | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | KTSP (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 112 | **Ideal Institute of Technology** (Vidyut Nagar, Kakinada) | Kakinada | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | IDEL (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 113 | **Pydah College of Engineering** (Patavala, Tallarevu mdl) | Kakinada | Pvt autonomous | Yes | A (Aggregator) | — | Not in 2025 Engg top 300 | PYDE (2025) | Tier 2 | Autonomous + NAAC A (reported) |
| 114 | **Chaitanya Institute of Science & Technology** (Madhavapatnam, Samalkot) | Kakinada | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | CHKN (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 115 | **Adarsh College of Engineering** (Chebrolu, Gollaprolu mdl) | Kakinada | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | ACEE (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 116 | **Godavari Global University (formerly GIET Rajahmundry)** (Velugubanda, Rajanagaram) | East Godavari | State pvt univ | No | A++; 3.58; 3rd cycle claimed (dates not found); cycle 1 CGPA 3.31 (2018) (College site) | — | Engg 201-300 (official) | GGURPU (2025); old GIER | Tier 2 | NIRF Engg 201-300; NAAC A++; converted strong college |
| 117 | **GIET Engineering College** (Velugubanda, Rajanagaram) | East Godavari | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | GIET (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 118 | **BVC College of Engineering, Palacharla** (Palacharla, Rajanagaram mdl) | East Godavari | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | BVCR (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 119 | **Rajamahendri Institute of Engineering & Technology (RIET)** (Bhoopalapatnam, Rajanagaram mdl) | East Godavari | Pvt autonomous | Yes | B / B++ (conflicting) (Aggregator) | — | Not in 2025 Engg top 300 | RIET (2025) | Tier 3 | Autonomous; NAAC B/B++ |
| 120 | **International School of Technology & Sciences for Women (ISTS)** (Rajanagaram (NH-16), Rajahmundry) | East Godavari | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | ISTS (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 121 | **Adikavi Nannaya University College of Engineering (self-finance)** (Rajamahendravaram) | East Godavari | Govt – State univ/constituent | No | — | — | Not in 2025 Engg top 300 | ANURSF (2025) | Tier 3 | State univ college; no NAAC/NIRF found |
| 122 | **B.V.C. Engineering College (Bonam Venkata Chalamayya), Odalarevu** (Odalarevu, Allavaram mdl) | Konaseema | Pvt autonomous | Yes | A (Aggregator) | Yes (aggregator) | Not in 2025 Engg top 300 | BVCE (2025) | Tier 2 | Autonomous + NAAC A (reported) |
| 123 | **Bonam Venkata Chalamayya Institute of Technology & Science** (Batlapalem, Amalapuram mdl) | Konaseema | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | BVTS (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 124 | **Kakinada Institute of Technology & Sciences, Ramachandrapuram** (Ramachandrapuram) | Konaseema | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | KISR (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 125 | **V.S.M. College of Engineering** (Ramachandrapuram) | Konaseema | Pvt autonomous | Yes | — | — | Not in 2025 Engg top 300 | VSMR (2025) | Tier 3 | Autonomous; NAAC grade not found |
| 126 | **Srinivasa Institute of Engineering & Technology** (Cheyyeru, Katrenikona mdl) | Konaseema | Pvt autonomous | Yes | A / B (conflicting) (Aggregator) | — | Not in 2025 Engg top 300 | SRIN (2025) | Tier 3 | Autonomous; NAAC A vs B unresolved (borderline Tier 2) |
| 127 | **Lenora College of Engineering** (Rampachodavaram) | Alluri Sitharama Raju | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | LENO (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 128 | **Dr. Paul Raj's Engineering College** (Bhadrachalam area (AP side)) | Alluri Sitharama Raju? | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | PREC (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |

## Old West Godavari: the best-documented NAAC grades in the region

Old West Godavari covers present West Godavari and Eluru districts; WISE's UGC address is Nallajerla, which moved to East Godavari district in 2022. **NIT Andhra Pradesh is the only national institute and sits in NIRF 2025 Engineering 201-300**; no Bhimavaram, Eluru or Narsapur college appears in any 2025 band ([NIRF 201-300](https://www.nirfindia.org/Rankings/2025/EngineeringRanking300.html)). The college documents here are unusually good: **SRKR is A+ (3.42) valid to 19 Dec 2027**, **Sri Vasavi is A (3.21) from a Feb 2024 Cycle 2 grade sheet**, and **VITB's 3.51 accreditation expired on 31 Dec 2024** with no renewal found ([SRKR](https://www.srkrec.ac.in/vitals/naac/); [Sri Vasavi](https://www.srivasaviengg.ac.in/uploads/NAAC%20Accreditation%20Status%20(Cycle%202).pdf); [VITB AQAR](https://www.vishnu.edu.in/naac/AQAR2023-24.pdf)). Swarnandhra reports an A in its 2023 cycle and SVECW an A+ ([Swarnandhra](https://www.swarnandhra.ac.in/milestones.php); [SVECW report](https://svecw.edu.in/wp-content/uploads/2025/06/91-Annual-Report-of-SVECW-2024-25.pdf)). **The AP Cabinet approved converting SVECW into Vishnu Women's University on 23 Jul 2026** ([Webnewswire](https://www.webnewswire.com/2026/07/24/ap-cabinet-approves-vishnu-womens-university-as-the-first-private-university-for-women/)). DNR's 2026 faculty adverts claim A++ (3.73), contradicting older B++ listings ([FacultyPlus](https://www.facultyplus.com/?p=272349)). The West Godavari research notes could not reach the UGC list, so autonomy for DNR, BIET, Sasi, Ramachandra, Sir C R Reddy, SVECW and WISE was checked directly against the UGC 28.02.2026 PDF for this report; all seven are listed, and SRKR is listed under Andhra University rather than JNTUK ([UGC 2026](https://www.ugc.gov.in/pdfnews/8688705_List-of-Autonomous-Colleges.pdf)).

| S.No | College (town) | New district | Ownership | Auto. | NAAC (grade; CGPA; validity; source) | NBA | NIRF 2025 | EAPCET code | Tier | Tier basis |
|---|---|---|---|---|---|---|---|---|---|---|
| 146 | **NIT Andhra Pradesh** (Tadepalligudem) | West Godavari | Govt – National | No | — | — | Engg 201-300 (official) | Not in EAPCET | Tier 1 | Institute of National Importance |
| 147 | **S.R.K.R. Engineering College (Sagi Rama Krishnam Raju)** (Chinnamiram, Bhimavaram) | West Godavari | Pvt autonomous | Yes | A+; 3.42; 2nd cycle 20-12-2022 to 19-12-2027 (College site) | — | Not in 2025 Engg top 300 | SRKR (2025) | Tier 2 | NAAC A+ (current, 3.42) |
| 148 | **Vishnu Institute of Technology (VITB)** (Vishnupur, Bhimavaram) | West Godavari | Pvt autonomous | Yes | A+ / A++ (label conflict); 3.51; 1st cycle 01-01-2020 to 31-12-2024 (expired; renewal not found) (College site) | Yes: EEE, ECE, CSE, IT, Mech (from 01-07-2022) | Not in 2025 Engg top 300 | VITB (2025) | Tier 2 | NAAC A+ (3.51, recently expired) + autonomous |
| 149 | **Vishnu Women's University (formerly Shri Vishnu Engineering College for Women)** (Vishnupur, Bhimavaram) | West Godavari | State pvt univ | Unclear | A+; Per college annual report 2024-25 (College site) | Yes: Tier I (college report) | Not in 2025 Engg top 300 | VISW (2025); 2026 code unclear | Tier 2 | State pvt university converted from strong college; NAAC A+ |
| 150 | **DNR College of Engineering & Technology** (Balusumudi, Bhimavaram) | West Godavari | Pvt autonomous | Yes | A++ (2026 college adverts) / B++ (2023-24); 3.73; c.2025-26 (unverified) (College site) | Yes: CSE, ECE, EEE (college advert) | Not in 2025 Engg top 300 | DNRE (2025) | Tier 2 | NAAC A++ (self-reported) + autonomous |
| 151 | **Bhimavaram Institute of Engineering & Technology (BIET)** (Pennada, Palakoderu mdl) | West Godavari | Pvt autonomous | Yes | A (single listing) (Aggregator) | — | Not in 2025 Engg top 300 | BVRM (2025) | Tier 2 | Autonomous + NAAC A (single listing; weak) |
| 152 | **Sasi Institute of Technology & Engineering** (Kadakatla, Tadepalligudem) | West Godavari | Pvt autonomous | Yes | A (Aggregator) | Yes (aggregator) | Not in 2025 Engg top 300 | SASI (2025) | Tier 2 | Autonomous + NAAC A (reported) |
| 153 | **Sri Vasavi Engineering College** (Pedatadepalli, Tadepalligudem) | West Godavari | Pvt autonomous | Yes | A; 3.21; Cycle 2, peer visit Feb 2024 (validity ~2029, not seen) (Official) | Reported (forum answer) | Not in 2025 Engg top 300 | VSVT (2025) | Tier 2 | Autonomous + NAAC A (3.21) |
| 154 | **West Godavari Institute of Science & Engineering (WISE)** (Nallajerla (Tadepalligudem area)) | East Godavari | Pvt autonomous | Yes | B++ (Aggregator) | — | Not in 2025 Engg top 300 | WISE (2025) | Tier 3 | Autonomous; NAAC B++ |
| 155 | **Swarnandhra College of Engineering & Technology** (Seetharampuram, Narsapur) | West Godavari | Pvt autonomous | Yes | A; 2023 cycle (earlier A, 3.32, 2013) (College site) | Yes (aggregator) | Not in 2025 Engg top 300 | SWRN (2025) | Tier 2 | Autonomous + NAAC A (2023) |
| 156 | **Sir C R Reddy College of Engineering** (Vatluru, Eluru) | Eluru | Pvt autonomous | Yes | B / A (conflicting) (Aggregator) | — | Not in 2025 Engg top 300 | CRRE (2025) | Tier 3 | Autonomous; NAAC B vs A unresolved (borderline Tier 2) |
| 157 | **Ramachandra College of Engineering** (Vatluru, Eluru) | Eluru | Pvt autonomous | Yes | A+ (one listing says A) (Aggregator) | Yes (aggregator) | Not in 2025 Engg top 300 | RACE (2025) | Tier 2 | NAAC A+ (reported) + autonomous |
| 158 | **Eluru College of Engineering & Technology** (Duggirala, Pedavegi mdl?) | Eluru | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | ELRU (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 159 | **Helapuri Institute of Technology & Science** (Vegavaram, Denduluru mdl) | Eluru | Pvt affiliated | No | — | — | Not in 2025 Engg top 300 | HITE (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |
| 160 | **International School of Technology & Sciences, off-campus (ISTSOC)** (Jangareddygudem) | Eluru | Pvt affiliated | Unclear | — | — | Not in 2025 Engg top 300 | ISTSOC (2025) | Tier 3 | Affiliated; no NAAC/NIRF found |

## All 128 active institutions, Tier 1 to Tier 3

Sorted by tier, then by region (Guntur, Krishna, East Godavari, West Godavari), then by S.No. "Not in top 300" means the institution was not found in the NIRF 2025 Engineering lists, which run only to rank 300.

| Tier | Region | S.No | College | Ownership | Auto. | NAAC (source) | NIRF 2025 | Tier basis |
|---|---|---|---|---|---|---|---|---|
| Tier 1 | Guntur | 1 | **KL University (Koneru Lakshmaiah Education Foundation)** | Deemed (pvt) | No | A++ 3.57 (Aggregator) | Engg 35; Univ 26; Overall 46 | NIRF Engg 35 |
| Tier 1 | Guntur | 2 | **Vignan's Foundation for Science, Technology & Research (deemed)** | Deemed (pvt) | No | A+ 3.49 (College site) | Engg 80; Univ 70; Overall 101-150 | NIRF Engg 80 |
| Tier 1 | Guntur | 3 | **SRM University AP** | State pvt univ | No | — | Not in 2025 Engg/Univ lists | Major national private university (multi-state) |
| Tier 1 | Guntur | 4 | **VIT-AP University** | State pvt univ | No | — | Not in 2025 Engg/Univ lists | Major national private university (multi-state) |
| Tier 1 | Guntur | 6 | **Amrita Vishwa Vidyapeetham, Amaravati campus** | Deemed (pvt) | No | A++ (university-wide) (College site) | Not listed separately | Major national private university (multi-state) |
| Tier 1 | Guntur | 8 | **ANU College of Engineering & Technology (Acharya Nagarjuna University)** | Govt – State univ/constituent | No | A+ (parent ANU) 3.46 (parent) (Aggregator) | Not in Engg list; parent ANU Univ 84, Overall 101-150 | Parent ANU NIRF Univ 84 |
| Tier 1 | East Godavari | 104 | **JNTUK University College of Engineering Kakinada (UCEK)** | Govt – State univ/constituent | Unclear | A+ (Aggregator) | JNTUK Engg 101-150 (official; parent) | Parent JNTUK NIRF Engg 101-150 |
| Tier 1 | West Godavari | 146 | **NIT Andhra Pradesh** | Govt – National | No | — | Engg 201-300 (official) | Institute of National Importance |
| Tier 2 | Guntur | 5 | **VVIT University (Vasireddy Venkatadri International Technological University), formerly VVIT** | State pvt univ | No | A (as college) 3.09 (Aggregator) | Not in top 300 | State pvt university converted from strong college |
| Tier 2 | Guntur | 9 | **RVR & JC College of Engineering** | Pvt autonomous | Yes | A+ (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 2 | Guntur | 10 | **Chalapathi Institute of Engineering & Technology (CIET)** | Pvt autonomous | Yes | A (Aggregator) | Not in top 300 | Autonomous + NAAC A (reported) |
| Tier 2 | Guntur | 12 | **KKR & KSR Institute of Technology & Sciences** | Pvt autonomous | Yes | A 3.02 (Official) | Not in top 300 | Autonomous + NAAC A |
| Tier 2 | Guntur | 13 | **Kallam Haranadhareddy Institute of Technology (KHIT)** | Pvt autonomous | Yes | A 3.20 (Official) | Not in top 300 | Autonomous + NAAC A |
| Tier 2 | Guntur | 14 | **KITS Akshar Institute of Technology (formerly Guntur Engineering College)** | Pvt autonomous | Yes | A (Aggregator) | Not in top 300 | Autonomous + NAAC A (reported) |
| Tier 2 | Guntur | 15 | **RV Institute of Technology (formerly Chebrolu Engineering College)** | Pvt autonomous | Yes | A (Aggregator) | Not in top 300 | Autonomous + NAAC A (reported) |
| Tier 2 | Guntur | 19 | **Malineni Lakshmaiah Women's Engineering College** | Pvt autonomous | Yes | A+ (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 2 | Guntur | 23 | **NRI Institute of Technology, Guntur** | Pvt autonomous | Yes | A+ (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 2 | Guntur | 27 | **Sri Mittapalli College of Engineering** | Pvt autonomous | Yes | A+ (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 2 | Guntur | 32 | **Vignan's Lara Institute of Technology & Science** | Pvt autonomous | Yes | A+ (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 2 | Guntur | 36 | **Narasaraopeta Engineering College (NEC)** | Pvt autonomous | Yes | A+ / A (conflicting) (College site) | Not in top 300 | NAAC A+ (self-reported) + autonomous |
| Tier 2 | Guntur | 42 | **Tirumala Engineering College** | Pvt autonomous | Yes | A+ (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 2 | Guntur | 48 | **Bapatla Engineering College** | Pvt autonomous | Yes | A+ (aggregator) / B (2019 NAAC list) 2.70 (B, 1st cycle) (Aggregator) | Not in top 300 | NAAC A+ (reported; conflicts) + autonomous |
| Tier 2 | Krishna (Vijayawada) | 62 | **Lakireddy Bali Reddy College of Engineering (LBRCE)** | Pvt autonomous | Yes | A 3.20 (Aggregator) | Not in 2025 Engg top 300 (201-300 in 2024) | Autonomous + NAAC A |
| Tier 2 | Krishna (Vijayawada) | 80 | **Siddhartha Academy of Higher Education (formerly VR Siddhartha Engineering College)** | Deemed (pvt) | No | — | Engg 151-200 | NIRF Engg 151-200; Siddhartha Academy |
| Tier 2 | Krishna (Vijayawada) | 81 | **Prasad V Potluri Siddhartha Institute of Technology (PVPSIT)** | Pvt autonomous | Yes | A+ (Aggregator) | Engg 201-300 | NIRF Engg 201-300 |
| Tier 2 | Krishna (Vijayawada) | 82 | **Seshadri Rao Gudlavalleru Engineering College (SRGEC)** | Pvt autonomous | Yes | A+ (reported) / B++ (conflicting) 2.91 (B++ cycle) (Aggregator) | Not in top 300 | NAAC A+ (reported; conflicts) + autonomous |
| Tier 2 | East Godavari | 106 | **Aditya University (formerly Aditya Engineering College)** | State pvt univ | No | A++ 3.60 (Aggregator) | Engg 201-300 (official); Univ 151-200 (aggregator) | NIRF Engg 201-300; NAAC A++; converted strong college |
| Tier 2 | East Godavari | 107 | **Pragati Engineering College** | Pvt autonomous | Yes | A (official, expired) / A++ claimed 3.08 (1st cycle) (College site) | Not in top 300 | Autonomous + NAAC A |
| Tier 2 | East Godavari | 113 | **Pydah College of Engineering** | Pvt autonomous | Yes | A (Aggregator) | Not in top 300 | Autonomous + NAAC A (reported) |
| Tier 2 | East Godavari | 116 | **Godavari Global University (formerly GIET Rajahmundry)** | State pvt univ | No | A++ 3.58 (College site) | Engg 201-300 (official) | NIRF Engg 201-300; NAAC A++; converted strong college |
| Tier 2 | East Godavari | 122 | **B.V.C. Engineering College (Bonam Venkata Chalamayya), Odalarevu** | Pvt autonomous | Yes | A (Aggregator) | Not in top 300 | Autonomous + NAAC A (reported) |
| Tier 2 | West Godavari | 147 | **S.R.K.R. Engineering College (Sagi Rama Krishnam Raju)** | Pvt autonomous | Yes | A+ 3.42 (College site) | Not in top 300 | NAAC A+ (current, 3.42) |
| Tier 2 | West Godavari | 148 | **Vishnu Institute of Technology (VITB)** | Pvt autonomous | Yes | A+ / A++ (label conflict) 3.51 (College site) | Not in top 300 | NAAC A+ (3.51, recently expired) + autonomous |
| Tier 2 | West Godavari | 149 | **Vishnu Women's University (formerly Shri Vishnu Engineering College for Women)** | State pvt univ | Unclear | A+ (College site) | Not in top 300 | State pvt university converted from strong college; NAAC A+ |
| Tier 2 | West Godavari | 150 | **DNR College of Engineering & Technology** | Pvt autonomous | Yes | A++ (2026 college adverts) / B++ (2023-24) 3.73 (College site) | Not in top 300 | NAAC A++ (self-reported) + autonomous |
| Tier 2 | West Godavari | 151 | **Bhimavaram Institute of Engineering & Technology (BIET)** | Pvt autonomous | Yes | A (single listing) (Aggregator) | Not in top 300 | Autonomous + NAAC A (single listing; weak) |
| Tier 2 | West Godavari | 152 | **Sasi Institute of Technology & Engineering** | Pvt autonomous | Yes | A (Aggregator) | Not in top 300 | Autonomous + NAAC A (reported) |
| Tier 2 | West Godavari | 153 | **Sri Vasavi Engineering College** | Pvt autonomous | Yes | A 3.21 (Official) | Not in top 300 | Autonomous + NAAC A (3.21) |
| Tier 2 | West Godavari | 155 | **Swarnandhra College of Engineering & Technology** | Pvt autonomous | Yes | A (College site) | Not in top 300 | Autonomous + NAAC A (2023) |
| Tier 2 | West Godavari | 157 | **Ramachandra College of Engineering** | Pvt autonomous | Yes | A+ (one listing says A) (Aggregator) | Not in top 300 | NAAC A+ (reported) + autonomous |
| Tier 3 | Guntur | 7 | **Chalapathi University** | State pvt univ | No | — | — | New private university; no NAAC/NIRF |
| Tier 3 | Guntur | 11 | **Chalapathi Institute of Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 16 | **Chintalapudi Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 17 | **GVR&S College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 18 | **Hindu College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 20 | **Malineni Perumallu Educational Society's Group of Institutions** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 21 | **NVR College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 22 | **ASN Women's Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 24 | **Priyadarshini Institute of Technology & Management** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 25 | **Priyadarshini Institute of Technology & Science** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 26 | **Priyadarshini Institute of Technology & Science for Women** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 28 | **Sri Mittapalli Institute of Technology for Women** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 29 | **St. Mary's Group of Institutions Guntur (for Women)** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 30 | **St. Mary's Women's Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 31 | **Universal College of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 33 | **Vignan's Nirula Institute of Technology & Science for Women** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 34 | **PNC & Vijai Institute of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 35 | **JNTUK University College of Engineering Narasaraopet** | Govt – State univ/constituent | No | — | Parent JNTUK Engg 101-150 (not inherited) | Satellite constituent college; parent rank not inherited |
| Tier 3 | Guntur | 37 | **Narasaraopeta Institute of Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 38 | **A.M. Reddy Memorial College of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 39 | **Eswar College of Engineering** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 40 | **Krishnaveni Engineering College for Women** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 41 | **Sai Tirumala NVR Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 43 | **Loyola Institute of Technology & Management (LITAM)** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 44 | **Varaprasad Reddy Institute of Technology (formerly Nalanda IET)** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 45 | **Sri Chundi Ranganayakulu Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 46 | **Newton's Institute of Engineering** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 47 | **Newton's Institute of Science & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 49 | **Bapatla Women's Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Guntur | 50 | **Dr. NTR College of Agricultural Engineering (ANGRAU)** | Govt – State univ/constituent | No | — | Parent ANGRAU Univ 151-200 (not inherited) | Constituent college; parent rank not inherited |
| Tier 3 | Guntur | 51 | **Dr. NTR College of Food Science & Technology (ANGRAU)** | Govt – State univ/constituent | No | — | Parent ANGRAU Univ 151-200 (not inherited) | Constituent college; parent rank not inherited |
| Tier 3 | Guntur | 52 | **Chirala Engineering College** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Guntur | 53 | **St. Ann's College of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 63 | **DVR & Dr HS MIC College of Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 64 | **Amrita Sai Institute of Science & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 65 | **MVR College of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 66 | **Andhra Loyola Institute of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 67 | **SRK Institute of Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 68 | **Potti Sriramulu Chalavadi Mallikharjuna Rao College of Engineering & Technology (PSCMR)** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 69 | **Vijaya Institute of Technology for Women** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 70 | **Vikas College of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 71 | **Vikas Group of Institutions** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 72 | **GDMM College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 73 | **Gurindapalli Devananda Mary Memorial College of Engineering & Technology for Women** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 74 | **Mandava Institute of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 75 | **Nimra College of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 76 | **Nova College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 77 | **RK College of Engineering** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 78 | **Sree Vahini Institute of Science & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 79 | **Sri Vani School of Engineering** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 83 | **Usha Rama College of Engineering & Technology** | Pvt autonomous | Yes | Accredited (grade not found) (Aggregator) | Not in top 300 | Autonomous; NAAC grade unknown |
| Tier 3 | Krishna (Vijayawada) | 84 | **Dhanekula Institute of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 85 | **Sri Chaitanya DJR College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 86 | **Sri Chaitanya DJR Institute of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 87 | **Lingayas Institute of Management & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 88 | **Paladugu Parvathi Devi College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 89 | **DMSSVH College of Engineering** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 90 | **Krishna University College of Engineering & Technology** | Govt – State univ/constituent | No | — | Not in top 300 | State univ college; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 91 | **VKR, VNB & AGK College of Engineering** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 92 | **Sri Vasavi Institute of Engineering & Technology** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 93 | **Sri Sunflower College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 94 | **NRI Institute of Technology, Agiripalli** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | Krishna (Vijayawada) | 95 | **Sri Sarathi Institute of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | Krishna (Vijayawada) | 96 | **RGUKT IIIT Nuzvid** | Govt – State univ/constituent | No | — | — | State univ campus; no NAAC/NIRF found |
| Tier 3 | East Godavari | 105 | **School of Food Technology, JNTUK Kakinada** | Govt – State univ/constituent | No | — | Not in top 300 | Constituent unit; parent rank not inherited |
| Tier 3 | East Godavari | 108 | **Kakinada Institute of Engineering & Technology (KIET)** | Pvt affiliated | No | B++ (Aggregator) | Not in top 300 | Affiliated; NAAC B++ |
| Tier 3 | East Godavari | 109 | **Kakinada Institute of Engineering & Technology-II** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 110 | **Kakinada Institute of Engineering & Technology for Women** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 111 | **Kakinada Institute of Technology & Science (KITS), Peddapuram** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | East Godavari | 112 | **Ideal Institute of Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 114 | **Chaitanya Institute of Science & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 115 | **Adarsh College of Engineering** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 117 | **GIET Engineering College** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | East Godavari | 118 | **BVC College of Engineering, Palacharla** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | East Godavari | 119 | **Rajamahendri Institute of Engineering & Technology (RIET)** | Pvt autonomous | Yes | B / B++ (conflicting) (Aggregator) | Not in top 300 | Autonomous; NAAC B/B++ |
| Tier 3 | East Godavari | 120 | **International School of Technology & Sciences for Women (ISTS)** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | East Godavari | 121 | **Adikavi Nannaya University College of Engineering (self-finance)** | Govt – State univ/constituent | No | — | Not in top 300 | State univ college; no NAAC/NIRF found |
| Tier 3 | East Godavari | 123 | **Bonam Venkata Chalamayya Institute of Technology & Science** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | East Godavari | 124 | **Kakinada Institute of Technology & Sciences, Ramachandrapuram** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 125 | **V.S.M. College of Engineering** | Pvt autonomous | Yes | — | Not in top 300 | Autonomous; NAAC grade not found |
| Tier 3 | East Godavari | 126 | **Srinivasa Institute of Engineering & Technology** | Pvt autonomous | Yes | A / B (conflicting) (Aggregator) | Not in top 300 | Autonomous; NAAC A vs B unresolved (borderline Tier 2) |
| Tier 3 | East Godavari | 127 | **Lenora College of Engineering** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | East Godavari | 128 | **Dr. Paul Raj's Engineering College** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | West Godavari | 154 | **West Godavari Institute of Science & Engineering (WISE)** | Pvt autonomous | Yes | B++ (Aggregator) | Not in top 300 | Autonomous; NAAC B++ |
| Tier 3 | West Godavari | 156 | **Sir C R Reddy College of Engineering** | Pvt autonomous | Yes | B / A (conflicting) (Aggregator) | Not in top 300 | Autonomous; NAAC B vs A unresolved (borderline Tier 2) |
| Tier 3 | West Godavari | 158 | **Eluru College of Engineering & Technology** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | West Godavari | 159 | **Helapuri Institute of Technology & Science** | Pvt affiliated | No | — | Not in top 300 | Affiliated; no NAAC/NIRF found |
| Tier 3 | West Godavari | 160 | **International School of Technology & Sciences, off-campus (ISTSOC)** | Pvt affiliated | Unclear | — | Not in top 300 | Affiliated; no NAAC/NIRF found |

## 42 institutions look closed or inactive

These appear on older JNTUK lists or aggregators but have no 2025 allotment code, no current JNTUK directory record, or both ([JNTUFastUpdates 2019-20](https://www.jntufastupdates.com/jntuk-affiliated-colleges-list-with-codes/); [colleges9](https://www.colleges9.in/Andhra-Pradesh/East-Godavari/Engineering-Colleges/); [Careers360 WG](https://engineering.careers360.com/colleges/list-of-engineering-colleges-in-west-godavari)). Two deserve a second look: **Aditya College of Engineering & Technology (ACET) and Aditya College of Engineering (ACES) are still on the UGC 28.02.2026 autonomous list**, so they exist as legal entities even though they had no 2025 EAPCET code; they may now admit under Aditya University. Saveetha Amaravati University stays here because no B.Tech offering was confirmed. The earlier "possibly closed" rows for RV Institute of Technology and KITS Akshar are removed because they are the renamed Chebrolu EC and Guntur EC, now listed as active.

| S.No | Region | College | Town / new district | Last known code | Note |
|---|---|---|---|---|---|
| 54 | Guntur | Amara Institute of Engineering & Technology | Satuluru / Palnadu | — | JNTUK code AH (2019-20); missing from current directory |
| 55 | Guntur | Tenali Engineering College | Anumarlapudi / Guntur? | — | JNTUK code BN (2019-20) |
| 56 | Guntur | Velaga Nageswara Rao College of Engineering | Ponnur / Guntur | — | JNTUK code NK (2019-20) |
| 57 | Guntur | Vishwa Bharathi College of Technology & Management | Guntur / Guntur? | — | May not offer B.Tech |
| 58 | Guntur | VRS & YRN College of Engineering & Technology | Chirala / Bapatla | — | JNTUK code L1 (2019-20); no 2025 counselling trace |
| 59 | Guntur | MAM Women's Engineering College | Narasaraopet / Palnadu | — | Aggregator only |
| 60 | Guntur | Haji Mohammad Khasim Saheb & Mohammad Galab Saheb College of Engineering | Guntur area / ? | — | Aggregator only |
| 61 | Guntur | Saveetha Amaravati University | Amaravati / Guntur | — | B.Tech offering unconfirmed |
| 97 | Krishna (Vijayawada) | Montessori Siva Sivani Institute of Science & Technology | Gurrajupalem, Mylavaram / NTR | MSIT (undated) | — |
| 98 | Krishna (Vijayawada) | Prasad Institute of Technology & Sciences | Jaggayyapeta / NTR | PITS (undated) | — |
| 99 | Krishna (Vijayawada) | Gandhiji Institute of Science & Technology | near Jaggayyapeta / NTR | GIST (undated) | — |
| 100 | Krishna (Vijayawada) | Nimra Women's College of Engineering | Jupudi, Ibrahimpatnam / NTR | NMRW (undated) | Women's wing; not on UGC list |
| 101 | Krishna (Vijayawada) | Nova College of Engineering & Technology for Women | Jupudi, Ibrahimpatnam / NTR | NOVW (undated) | Women's wing |
| 102 | Krishna (Vijayawada) | Sarojini Institute of Technology | Telaprolu / Krishna | SITT (undated) | — |
| 103 | Krishna (Vijayawada) | Sri Viveka Institute of Technology | Madalavarigudem / Krishna | VIVK (undated) | — |
| 129 | East Godavari | Aditya College of Engineering & Technology (ACET) | Surampalem / Gandepalli / Kakinada | ACET (old) | Still on UGC 28.02.2026 autonomous list (to 2032-33); may admit under Aditya University |
| 130 | East Godavari | Aditya College of Engineering (ACES) | Surampalem / Kakinada | ACES (old) | Still on UGC 28.02.2026 autonomous list |
| 131 | East Godavari | Sri Aditya Engineering College | Surampalem / Kakinada | SACS (old) | Possibly folded into Aditya University |
| 132 | East Godavari | Sri Sai Aditya Institute of Science & Technology | Surampalem / Kakinada | SISS (old) | Possibly folded into Aditya University |
| 133 | East Godavari | ASR College of Engineering & Technology | Turangi, Kakinada Rural / Kakinada | ASRK (old) | — |
| 134 | East Godavari | Badari Institute of Technology for Women | Kakinada / Kakinada | BITW (old) | — |
| 135 | East Godavari | V.S. Lakshmi Engineering College for Women | Kakinada / Kakinada | VSLW (old) | In Careers360 2026 'expected' list |
| 136 | East Godavari | Sri Prakash College of Engineering | Tuni / Kakinada | SPCT (old) | — |
| 137 | East Godavari | Benaiah Institute of Technology & Sciences | Rajahmundry / East Godavari | BENA (old) | In Careers360 2026 'expected' list |
| 138 | East Godavari | Chaitanya Institute of Engineering & Technology | Rajanagaram / East Godavari | CETR (old) | — |
| 139 | East Godavari | Krishna's Pragati Institute of Technology | Rajahmundry / East Godavari | KPIT (old) | — |
| 140 | East Godavari | Rajahmundry Engineering College | Rajahmundry / East Godavari | RECR (old) | — |
| 141 | East Godavari | Sri Prakash College of Technology | Rajahmundry / East Godavari | SPCR (old) | — |
| 142 | East Godavari | Sri Sai Madhavi Institute of Science & Technology | Rajanagaram / East Godavari | SSMR (old) | — |
| 143 | East Godavari | Amalapuram Institute of Management Sciences & College of Engineering | Mummidivaram / Konaseema | AIME (old) | — |
| 144 | East Godavari | Konaseema Institute of Medical Sciences & College of Engineering | Amalapuram / Konaseema | KIMS (old) | — |
| 145 | East Godavari | Prasiddha College of Engineering & Technology | Amalapuram / Konaseema | PCET (old) | — |
| 161 | West Godavari | GVVR Institute of Technology | Bhimavaram / West Godavari | — | In 2026 expected list only |
| 162 | West Godavari | Akula Sreeramulu College of Engineering | Tanuku / West Godavari | — | — |
| 163 | West Godavari | Akula Sree Ramulu Institute of Engineering & Technology | Tadepalligudem / Tanuku / West Godavari | — | — |
| 164 | West Godavari | Sri Venkateswara Institute of Science & IT (SVISIT) | Tadepalligudem / West Godavari | — | — |
| 165 | West Godavari | Jogaiah Institute of Technology & Sciences | Palakol / West Godavari | — | May be a polytechnic/architecture college |
| 166 | West Godavari | Gayatri Institute of Engineering & Technology | West Godavari (place unknown) / ? | — | — |
| 167 | West Godavari | Swarnandhra Institute of Engineering & Technology | Narsapur / West Godavari | — | Likely duplicate of / merged into SWRN |
| 168 | West Godavari | NOVA College of Engineering & Technology, Jangareddygudem | Jangareddygudem / Eluru | — | Last cut-off data 2022 |
| 169 | West Godavari | Nova Institute of Technology | Eluru / Eluru | — | — |
| 170 | West Godavari | AKRG College of Engineering & Technology | Nallajerla / East Godavari | — | Nallajerla moved to East Godavari district in 2022 |

## What the tiers cannot tell you yet

**NAAC grades are the weakest column.** The NAAC portal could not be queried, so only a handful of grades come from official or college documents (Vignan, SRKR, Sri Vasavi, VITB, Swarnandhra, SVECW, Pragati, GGU, DNR, and the 2019 NAAC list entries for KHIT, KKR&KSR and Bapatla EC); every other grade is aggregator-reported, usually without CGPA or validity dates. Aggregator pages also carry rotating "NAAC A++" advertising banners, which can leak into scraped grades. NAAC is moving to binary accreditation with maturity levels, so outcomes from 2026 onward may read "Accredited" with no letter grade, which will break any tier rule that depends on letters ([Edifyedu](https://edifyedu.in/blog/naac-accreditation-explained-grades-india-2026)). Because UGC normally requires a valid NAAC or NBA rating to grant autonomy, **many Tier 3 autonomous colleges probably hold an A grade that this research could not confirm**; they are the likeliest Tier 2 upgrades.

**NIRF 2026 has not been released.** The official 2026 URLs returned 404 on 2 Nov 2026, so every rank here is NIRF 2025 ([Careers360](https://engineering.careers360.com/articles/nirf-ranking-for-engineering-colleges)). Old Guntur and West Godavari rows were checked against the official 2025 band pages; Krishna and East Godavari bands partly rest on aggregators, although the official 101-300 pages name only SAHE/VRSEC, PVPSIT, JNTUK, Aditya and GIET (GGU) from those regions.

**NBA is mostly blank.** nbaind.org was not checked; NBA entries come from college documents (VITB, SVECW, DNR) or aggregators.

**Codes and the active list are mostly 2025 evidence.** The official 2026 MPC college list could not be opened, so East and West Godavari codes are 2025 allotment codes, Krishna codes are undated aggregator codes, and old Guntur rests largely on an undated JNTUK directory. For scale, the official 2026 final phase had 241 participating institutions statewide ([Deccan Chronicle](https://www.deccanchronicle.com/amp/southern-states/andhra-pradesh/final-ap-eapcet-phase-fills-3141-fresh-seats-1989068)). Private-university convener seat counts are from the 2026 seat matrix ([Careers360](https://engineering.careers360.com/articles/how-many-seats-are-in-ap-eamcet-2026-check-college-wise-btech-seat-matrix)). Admission routes for deemed and national private universities (KLEEE, V-SAT, SRMJEEE, VITEEE, AEEE) are the commonly known ones and were not confirmed on 2026 admission pages. Validity periods for some UGC 2026 entries on pages 9–11 could not be extracted reliably because of the PDF layout, so this report uses list membership, not those dates, for colleges that the regional notes did not already cover. New-district placements are mapped from town and mandal; a "?" marks uncertain ones.

## Conclusion

The real dividing line in this region is no longer autonomy, which half the colleges now hold, but documented accreditation. Ranking power is concentrated in roughly 40 institutions, and the converted universities (VVIT, Aditya, Godavari Global, Siddhartha, Vishnu Women's, and now Chalapathi) are absorbing the strongest colleges out of the affiliated system. The tier boundary between 2 and 3 is the least stable part of this classification: one afternoon on the NAAC portal checking the 39 autonomous Tier 3 colleges would likely move several up, and NIRF 2026 could shift the Tier 1/2 line for Vignan, ANU and the 201-300 group. Anyone using the CSV for admissions advice should filter on "NAAC source confidence" and treat Aggregator rows as provisional until verified.
