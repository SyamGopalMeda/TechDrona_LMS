# Decisions log v2: Krishna / Guntur / West Godavari consolidation update (7 Nov 2026)

Inputs: v1 `master_colleges.csv` / `master_branches.csv` (folder `Krishna Guntur West Godavari colleges`, read only) plus this folder's
`status_updates.csv`, `strength_updates.csv`, `branch_updates.csv`, `contacts_exams_updates.csv` and `student_demand.md`.
Outputs: `master_colleges_v2.csv` (130 rows), `master_branches_v2.csv` (682 rows), `updated_totals.md`, and
`reports/Krishna Guntur West Godavari colleges 2 tracker.xlsx`. The portal DB was only read (exam dates, contacts, tier) and never written.

## 1. Formulas: reused unchanged

The v1 scoring, target, 400-test, MoU and staffing code (`scratchpad/cons/compute.py`) was reused verbatim, except one fix to the contact (access) rule described in section 4. As a check, it was first run on the v1 master
(with the v1 contact rule) and reproduced v1 exactly: 363 / 637 / 1,113; 290 ambassadors; 62 College Leads; 12 District/City Leads; 91 standby; RAG 0 / 30 / 58; P1 24 / P2 36 / P3 21 / Hold 7;
MoU 28,422 / 47,388 / 75,794; 0 per-college mismatches. Unchanged rules:

- V_s = round(k_s × x × (rF·F + 0.5·rT·T + 0.5·rS·S)); V_min floor 2 where F > 0 and x ≥ 0.8; avg ≥ min, max ≥ avg.
- k by type (a 0.8/1/1.2, b 1/1/1, c 0.8/0.9/1, d 0.9/1/1.1); x = 1.0 TPO line, 0.8 office/principal contact, 0.6 none.
- 400 test: GREEN avg ≥ 400; AMBER max + 0.5(F+T+S) ≥ 400 and type a/b; else RED.
- Ambassadors A = max(3, ceil(ceil(1.2 × min)/2.5)); standby ceil(A/4); own College Lead if A ≥ 4, floor colleges paired in town clusters; District/City Leads = ceil(CL/6) per old district.
- Priority score: pool 35, contact 15, digital 15, exam 10, fill/quality 10, tier/NAAC 15; P1 ≥ 65, P2 ≥ 45, else P3; Hold = no 2026 target.
- T = current IT intake × 0.95, S × 0.97 (× 0.6 at fill-risk colleges). Regional median IT share of verified splits = 0.60 (38 colleges, unchanged).

## 2. Status categories (new)

| Category | Meaning | Count |
|---|---|---|
| active | counted; targeted unless Hold | 89 |
| winding_down | enrolled students on JNTUK Apr-2026 rolls (39–123), no 2026 EAPCET/ECET intake. **Not targeted in 2026**: only small final-year cohorts remain | 6 in scope (+ c58, out of scope) |
| listed_no_admissions | on the 2026 seat matrix, 0 allotted, no live batches | 1 |
| possibly_closed | no 2026 counselling; 1–15 backlog candidates or no trace. Never labelled "closed" (no order found) | 21 |
| pharmacy_only | group runs pharmacy only, no B.Tech intake | 4 |
| unverified | no B.Tech evidence either way | 1 |
| duplicate_merged | counted under another row | 5 |
| out_of_scope | not in old Krishna / Guntur / West Godavari | 3 |

- **c58 VRS & YRN → out_of_scope:** it is in old Prakasam (now Bapatla). It is also winding down (ECET-2026 lateral seats only, 0 allotted; 39 exam candidates).
- **c154 WISE → active, in scope:** Nallajerla was in old West Godavari (now East Godavari). EAPCET-2026 (82 allotted of 216), ECET-2026 and 232 exam candidates. Grouped under Old West Godavari, new district "East Godavari".
- c16 is not VNRCE: "Velaga Nageswara Rao CoE, Chintalapudi-Ponnur" (11 exam candidates) is c56, a separate college.

## 3. Strength rule (final-year pool), in order of preference

1. **Verified ACTUAL admitted 2023-24**, where a primary document gives it:
   - VIT-AP c4: 3,492 B.Tech, IT 3,025 (CSE 2,798 + CSBS 227). The 5-yr integrated M.Tech (288 + 284) is excluded and its two branch rows are marked `exclude`.
   - SMCE c27: 393, IT 363. Usha Rama c83: 542, IT 321. MAMW c40: 111 (v1, unchanged).
   - SRGEC c82: 1,318 and CRR c156: 1,039 (totals only). No actual IT split is published, so their IT pools stay the verified sanctioned splits (900 and 600); their targets do not change. SRGEC's 1,318 may include lateral entry.
2. **Else verified 2023-24 sanctioned (EoA first):**
   - NEC c36: 1,500 / IT 960 (EoA, confirmed by NBA CSE(AI) table). NIRF's 960 rejected as formulaic. Flag: **"absent from CAP 2026 – verify"**.
   - VITB c148: 1,140 / IT 780 (EoA 2023-24 beats NIRF 2026's 1,020).
   - VVIT c5: 1,740 (NIRF 2025); IT 1,044 **estimated** (1,740 × 0.60).
3. **Else estimated:**
   - MIET c74 ~110 (UG strength 436 / 4), IT ~40. Nimra c75 ~115 (408 / 4 = 102; 360 × 36% = 130), IT 69 (× 0.60; branch data incomplete).
     These are actual-batch estimates, so the 0.6 fill-risk factor is **not** applied again to F (it would double-count low fill); flags stay.
   - RGUKT c96 ~1,100 (1,000 + 100 EWS per campus, 2021 entry assumed same), IT 660 (× 0.60, no branch split). T = S = 0 (no current branch intake).
   - KITS c12, KHIT c13, KITS Akshar c14, VNRCE c56, PITM c24: CAP-2026 convener seats ÷ 0.8 × 2026 fill (seats filled ÷ convener seats), labelled estimated:

     | College | CAP-derived intake (IT) | 2026 fill | FY pool | IT pool F | v1 F |
     |---|---|---|---|---|---|
     | c12 KITS | 1,380 (1,140) | 1,098/1,104 = 99.5% | 1373 | 1134 | 969 |
     | c13 KHIT | 1,560 (1,260) | 55% (IT 52%) | 864 | 655 | 1,071 |
     | c14 KITS Akshar | 840 (720) | 525/672 = 78% | 656 | 563 | 612 |
     | c56 VNRCE | 450 (240) | 2/360 | 3 | 1 | 204 |
     | c24 PITM | 360 (210) | 73/288 = 25% | 91 | 53 | 230 |

     The fill factor replaces the v1 0.85 growth haircut; no 0.6 is added on top.
   - **c154 WISE:** estimated 2023-24 intake 270 (IT 180: CSE 120 + AI&DS 60, aggregator citing EoA 2024-25), low-fill rule × 0.6 → FY 162, IT 108; T/S 120/122. The ~80 actual per batch implied by 232 exam candidates suggests even this may be high.
4. **Else previous value** (all other colleges). PITW c26 keeps 153 / IT 120 × 0.85, now × 0.6 because of a new fill-risk flag (IT 102 → 61).
5. **SRM AP c3 stays Hold** (no data).

**New fill-risk flags** (same v1 criterion: most CAP-2026 convener seats left over): c56 VNRCE 358/360, c24 PITM 215/288, c26 PITW 118/144, c27 SMCE 646/744.
Effect: −4 priority points each; T and S × 0.6; F × 0.6 only where F is an estimate not already scaled by fill (c26).

## 4. Contacts and exams

- Added from `contacts_exams_updates.csv` (AP EAPCET-2026 CAP list): college landlines for c12, c14, c56, c8; principal-office emails for c12, c14, c26, c56, c8. c48's line and email were re-confirmed (already present).
- **Not added:** admissions-officer mobiles (officer-designated, possibly personal) and c24's `rangarao_vummaneni@yahoo.com` (personal-looking; not in the CSV either). Only addresses containing the "principal" role word were accepted.
- Access factor: c12, c14, c56, c8 x 0.6 → 0.8 (office line). c26 has a verified principal email but no line; it is given 0.8, consistent with v1, where any verified DB contact (including email-only) gave 0.8.
- New role text avoids the words TPO / placement / training so the v1 keyword rule cannot misread it.
- **Access-rule fix (applied in v2 at the coordinator's request):** v1's keyword test also matched negated text, so roles like "Principal (no TPO published)" or "Admissions office (no CDC phone/email published)" scored x = 1.0. v2 drops any parenthetical containing the word "no" before the keyword test, so these score 0.8 (office/principal line), the rule's lower tier. A verified DB TPO contact still gives 1.0. 13 active colleges moved 1.0 → 0.8: c4, c156, c68, c151, c71, c158, c38, c49, c52, c75, c90, c154, new-ANRG. v2 before → after the fix: min/avg/max 386/674/1,178 → 377/655/1,143; ambassadors 302 → 299; standby 95 → 95; College Leads 64 → 64; District/City Leads 12 → 12; RAG 0/31/58 → 0/31/58; P1/P2/P3/Hold 25/35/24/5 → 24/35/25/5. The baseline check still runs the v1 rule (flag LEGACY_ACCESS) so v1's 363/637/1,113 is reproduced exactly.
- Exam end dates (4-1 and 3-1) come from the portal DB `exams` table, overlaid with the update file (c14, c26 27 Nov; c48 11 Dec; KL not published; VFSTR, SRM AP, VIT-AP not found). These dates were already in the DB, so exam points did not change.

## 5. Lead offer and placement tier (student_demand.md)

- (a) universities KL, VFSTR, SRM AP, VIT-AP, Amrita → "Build & ship" GenAI/full-stack capstone or hackathon bootcamp.
- (b) high-rate autonomous (PVPSIT, SAHE/VRSEC, Bapatla EC, LBRCE, Vignan's Lara, NRIIT Agiripalli) and other Tier 1/2 colleges → "Ninja → Digital" placement upgrade.
- mid-rate (SRKR, RVR&JC, VVIT, KITS, SRGEC, Sasi, Sri Vasavi, Swarnandhra) → (b) for the top quartile + entry placement-test module for the unplaced.
- (c) low-rate named colleges (MIC, Dhanekula, NRI Guntur, ALIET) and all other Tier 3 colleges → entry aptitude + coding module.
- (d) women's colleges → (b) if IT pool ≥ 500 (VWU/SVECW, MLWEC), else (c), with women-in-tech framing.
- All colleges: "Switch to IT" module for non-IT branches. `placement_tier` is filled only where student_demand.md gives a rate or segment (23 active colleges); others say "unknown".

## 6. Branch file changes

- VIT-AP: 2023 admitted figures on CSE (2,798, all CSE specialisations), CSBS 227, ECE 373, Mech 94; integrated M.Tech rows set to `exclude`.
- SMCE and Usha Rama: 2023-24 column now holds actual admitted figures (sanctioned in notes). VITB: EoA 2023-24 seats on all 9 rows.
- PITW: intake verified by EoA 2026-27. PITM: 2021-22 EoA figures noted (not 2023-24). NEC CSE(AI): NBA admitted 104 + 12 noted.
- c154 WISE: 5 branch rows added (2023-24 split estimated from aggregator; current seats from CAP 2026).
- Branch `final_decision` re-derived from the new college status: 656 counted rows.

## 7. Per-college changes to targets and staffing

| College | Min/Avg/Max v1 → v2 | Ambassadors | College Lead | Why |
|---|---|---|---|---|
| c4 VIT-AP | 13/28/54 → 18/36/71 | 7 → 9 (+1 standby) |  | IT pool 1,581 (estimated) → 3,025 verified ACTUAL admitted 2023 (Annual Report 2023-24); integrated M.Tech 572 excluded. Access-rule fix: role is 'Admissions office (no CDC phone/email published)', so x 1.0 → 0.8. |
| c5 VVIT University | 0/0/0 (Hold) → 6/13/25 | 0 → 4 (+1 standby) | +1 own lead | 2023-24 sanctioned 1,740 verified (NIRF 2025); IT 1,044 estimated (× 0.60 median share). Leaves Hold; P1, AMBER. |
| c96 RGUKT Nuzvid | 0/0/0 (Hold) → 4/7/13 | 0 → 3 (+1 standby) | +0.5 (shares with c95) | E4 batch ~1,100 estimated (1,000 + 100 EWS seats); IT 660 estimated (× 0.60). Leaves Hold; P2. |
| c95 Sri Sarathi | unchanged | unchanged | 1 → 0.5 | Now pairs with c96 in Nuzvid instead of having its own lead. |
| c12 KITS | 6/10/17 → 9/15/25 | 4 → 5 (+1 standby) |  | Pool = CAP-2026 intake × 99.5% fill (IT 1,134; was × 0.85 = 969). New office line + principal email: x 0.6 → 0.8. P2 → P1. |
| c13 KHIT | 11/19/30 → 8/13/22 | 6 → 4 (−1 standby) |  | Pool = CAP-2026 intake × 2026 fill (IT 52%): IT 655 (was 1,071). |
| c14 KITS Akshar | 4/6/10 → 5/8/13 | 3 → 3 |  | Pool × 78% fill (IT 563, was 612) but new office line + principal email: x 0.6 → 0.8. |
| c27 SMCE | 7/12/20 → 4/7/11 | 4 → 3 | stays own (no town partner) | IT pool 714 (estimated) → 363 verified ACTUAL admitted 2023-24; new CAP-2026 fill-risk flag (13% filled). P1 → P2. |
| c148 VITB | 7/12/20 → 8/13/21 | 4 → 4 |  | AICTE EoA 2023-24: 1,140 / IT 780 verified (was NIRF 1,020, IT 698 estimated). |
| c83 Usha Rama | 3/5/9 → 3/5/10 | 3 → 3 |  | IT pool 300 sanctioned → 321 ACTUAL admitted. |
| c8 ANUCET | 1/2/4 → 2/3/5 | 3 → 3 |  | New office line + principal email: x 0.6 → 0.8 (min floor of 2 now applies). |
| c26 PITW | 1/1/2 → 2/2/2 | 3 → 3 |  | Principal email added (x 0.6 → 0.8, floor applies); new fill-risk flag cuts IT pool 102 → 61. |
| c56 VNRCE | 1/2/3 → 2/2/2 | 3 → 3 |  | Pool × 2026 fill (2 of 360 seats): IT 204 → 1. New office line (x 0.8) so the floor of 2 applies. Phone-check before staffing. |
| c24 PITM | 2/3/5 → 2/2/2 | 3 → 3 |  | Pool × 25% fill: IT 230 → 53; new fill-risk flag. |
| c74 MIET | 2/2/3 → 2/2/2 | 3 → 3 |  | Sanctioned 315 / IT 120 → estimated actual batch ~110 / IT ~40. P2 → P3. |
| c75 Nimra | 2/3/5 → 2/2/2 | 3 → 3 |  | Sanctioned 360 / IT 216 → estimated actual ~115 / IT 69; access-rule fix x 1.0 → 0.8. P2 → P3. |
| c154 WISE | not counted → 2/2/2 | +3 (+1 standby) | +1 own lead | Now active and in scope (old West Godavari). 270 × 0.6 low-fill: IT 108 estimated; principal line only (x 0.8). |
| c82 SRGEC | unchanged | unchanged |  | Final-year total now ACTUAL 1,318; IT pool stays the verified sanctioned split 900, so the target does not move. |
| c156 Sir CRR | 6/10/19 → 4/8/15 | 4 → 3 | 1 → 0.5 (shares with c158) | Final-year total now ACTUAL 1,039 (IT 600 unchanged). Access-rule fix: principal line only, x 1.0 → 0.8. P1 → P2. |
| c158 Eluru CE | 3/6/10 → 2/4/8 | 3 → 3 | 0.5 (now shares with c156) | Access-rule fix: 'Principal (Head of Placements named, no contact)', x 1.0 → 0.8. |
| c159 Helapuri | unchanged 2/2/3 | unchanged | 0.5 → 1 (no partner left in Eluru) | Lead re-pairing after c156 dropped below 4 ambassadors. |
| c68 PSCMR | 4/8/14 → 3/6/11 | 3 → 3 |  | Access-rule fix: principal line only, x 1.0 → 0.8. |
| c151 Bhimavaram Inst. of Engg | 3/5/9 → 3/4/7 | 3 → 3 |  | Access-rule fix: info line only, x 1.0 → 0.8. |
| c71 VGI | 3/5/9 → 2/4/7 | 3 → 3 |  | Access-rule fix: principal line only, x 1.0 → 0.8. |
| c38 AM Reddy | 2/3/6 → 2/3/5 | 3 → 3 | re-paired with c35 | Access-rule fix, x 1.0 → 0.8. P2 → P3. |
| c49 Bapatla Women's | 2/3/6 → 2/3/5 | 3 → 3 |  | Access-rule fix, x 1.0 → 0.8. |
| c52 Chirala EC | 2/3/5 → 2/2/4 | 3 → 3 |  | Access-rule fix, x 1.0 → 0.8. |
| c90 KRUCET | unchanged 2/2/2 | unchanged |  | Access-rule fix, x 1.0 → 0.8 (already at the floor). |
| c36 NEC | unchanged 11/19/30 | unchanged |  | EoA 1,500 / IT 960 confirmed (NBA filing); flagged 'absent from CAP 2026 – verify'. |
