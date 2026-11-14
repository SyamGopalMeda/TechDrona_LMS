# Tech Drona – B.Tech college outreach (Andhra Pradesh, 2026)

College data, research and the **Tech Drona Outreach Portal** for managing colleges, College Leads, Campus Ambassadors, targets and enrollments. Main goal: **400 paid enrollments by 31 Dec 2026**, focused on the old Guntur, Krishna and West Godavari districts.

## Contents

| Path | What it contains |
|---|---|
| `portal/` | The outreach portal (Node 24, zero dependencies, SQLite). See `portal/README.md` and the API/data contract in `portal/CONTRACT.md`. |
| `BTech Colleges 2026 Guntur Vijayawada Godavari.xlsx` | Workbook: active B.Tech colleges (128) + possibly-closed (42), ownership, NAAC, NIRF, autonomous status, Tier 1/2/3, placements 2024–2026 |
| `BTech colleges NAAC tiers Excel.md` | College list by region, ownership, NAAC/NIRF, and how tiers were assigned |
| `BTech colleges placements 2024 to 2026.md` | Placement statistics by year, with sources and caveats |
| `BTech exam status 3-1 4-1 Nov 2026.md` / `.csv` | 3-1 and 4-1 semester exam status per college, Nov 2026 |
| `reports/Krishna Guntur West Godavari colleges 2.md` | Main research report: 89 active colleges, verified vs estimated IT strength, priority list, College Lead & ambassador plan, min/avg/max targets, 400-per-college feasibility, marketing strategy |
| `reports/Krishna Guntur West Godavari colleges 2 tracker.xlsx` | Tracking workbook (colleges, branches, priority & targets, team, leads, payments, dashboard). Open and save once in Excel so formulas calculate. |
| `reports/Ambassador blueprint for 400 enrollments.md`, `reports/Path to 400 enrollments 2026.md` | Earlier company-wide plans (69-college blueprint; calling and exam-window strategy) |
| `research_notes/…` | Source notes, per-district CSVs and decision logs behind each report. `Krishna Guntur West Godavari colleges 2/master_colleges_v2.csv` feeds the portal's target planner. |

## Run the portal

```bash
cd portal
npm run seed                          # builds data/techdrona.db from data/seed/*.json (colleges, branches, contacts, exams)
node server/import_research.js        # loads the research plan (targets, IT strength, provenance) from research_notes
npm start                             # http://localhost:4173
npm run selftest                      # automated tests (runs on a temporary copy of the database)
```

The database (`portal/data/*.db`) is local and not committed. Optional: set `PORTAL_PASSCODE` (and `PORTAL_VIEWER_PASSCODE` for read-only users) to require sign-in; set `HOST` only if the portal must be reachable from other machines (a passcode is then required).

## Data principles

Compiled Nov 2026 from AP EAPCET 2025/2026 lists, AICTE approvals, JNTUK/UGC lists, NIRF 2025/2026 data, college websites and aggregators. Every figure is marked **verified** (official source linked), **estimated** (method stated) or **unavailable** — nothing is invented. Tiers are our own classification, not official. Conversion rates and productivity numbers in the plans are assumptions until real results are recorded. Verify on eapcet-sche.aptonline.in, naac.gov.in and nirfindia.org before relying on any figure.
