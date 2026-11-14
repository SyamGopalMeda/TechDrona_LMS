# Shared output schema (all district researchers)

Write TWO CSV files (UTF-8, header row, quote fields containing commas) plus one notes .md.

## <slug>_colleges.csv — one row per college (every college in your district list, including possibly_closed / pending / closed)
college_db_id,college,new_district,old_district,city,website,ownership,affiliation,autonomous,
op_status_finding (active|possibly_closed|closed|merged_renamed|unverified),
activity_evidence (short text),activity_evidence_url,activity_evidence_date (YYYY-MM or YYYY),
admitting_2025_26 (yes|no|unknown),
all_branches (semicolon list),it_branches (semicolon list),it_branch_count,
total_intake_per_year,total_intake_year,total_intake_source_url,
total_students (UG B.Tech enrolled, all years),total_students_year,total_students_source_url,
final_year_btech (2023 entry batch),final_year_basis (verified|estimated|unavailable),
it_final_year,it_final_year_basis,
strength_confidence (high|medium|low|unavailable),
tpo_or_contact_name,tpo_or_contact_role,contact_phone,contact_email,contact_source_url,
official_instagram,official_linkedin,official_facebook_or_youtube,
student_communities (clubs, IEEE/CSI/ACM/GDG chapters etc., names only),
outreach_opportunities (events, fests, hackathons with dates if known),
db_discrepancies (where your finding differs from the portal DB),notes

## <slug>_branches.csv — one row per college x branch
college_db_id,college,branch,is_it (yes|no),intake_per_year,intake_year,intake_source_url,
final_year_intake_2023_24,final_year_basis (verified|estimated|unavailable),confidence (high|medium|low),notes

## Rules
- Never invent counts, phones, emails or activity status. Unknown => leave blank and mark unavailable.
- "verified" = read on an official/statutory source (AICTE EoA/approval process, NIRF DCS, NAAC SSR/AQAR, university affiliation list, college site). Give the URL.
- Contacts: ONLY institutional/official published contacts (college/TPO/HOD office). Never collect personal data of students.
- IT-related = CSE, IT, CSE(AI&ML), AI&DS, CSE(DS), CSE(Cyber Security), CSE(IoT), CSBS, AI, DS, CS&D etc.
