-- Tech Drona outreach portal — SQLite schema (see CONTRACT.md).
-- Idempotent: every statement uses IF NOT EXISTS. Column additions after v1 go in db.js MIGRATIONS.
-- Extra columns beyond the contract (safe for other agents to ignore):
--   districts.updated_at/updated_by, colleges.total_intake/total_intake_source, branches.intake_2023_24,
--   courses.is_demo, targets.is_demo, followups.is_demo/updated_at/updated_by, exams.is_demo.

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT                                   -- JSON
);

CREATE TABLE IF NOT EXISTS districts (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  old_district TEXT,
  hq_lat       REAL,
  hq_lng       REAL,
  targeted     INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT,
  updated_by   TEXT
);

CREATE TABLE IF NOT EXISTS cities (
  id          TEXT PRIMARY KEY,                -- '<district>--<slug>'
  district_id TEXT NOT NULL REFERENCES districts(id),
  name        TEXT NOT NULL,
  lat         REAL,
  lng         REAL
);
CREATE INDEX IF NOT EXISTS ix_cities_district ON cities(district_id);

CREATE TABLE IF NOT EXISTS colleges (
  id               TEXT PRIMARY KEY,           -- 'c<sno>'
  sno              INTEGER UNIQUE,
  name             TEXT NOT NULL,
  short_name       TEXT,
  aliases          TEXT,                       -- JSON array
  district_id      TEXT REFERENCES districts(id),
  city_id          TEXT REFERENCES cities(id),
  address          TEXT,
  lat              REAL,
  lng              REAL,
  geo_precision    TEXT NOT NULL DEFAULT 'pending' CHECK (geo_precision IN ('exact','town','district','pending')),
  geo_source       TEXT,
  website          TEXT,
  phone            TEXT,
  email            TEXT,
  contact_source   TEXT,
  ownership        TEXT,
  autonomous       TEXT,
  affiliation      TEXT,
  naac             TEXT,
  nirf             TEXT,
  tier             TEXT,
  op_status        TEXT NOT NULL DEFAULT 'pending' CHECK (op_status IN ('operational','possibly_closed','closed','pending')),
  op_status_note   TEXT,
  op_status_source TEXT,
  op_2025_26       TEXT CHECK (op_2025_26 IS NULL OR op_2025_26 IN ('yes','no','unknown')),
  op_2026_27       TEXT CHECK (op_2026_27 IS NULL OR op_2026_27 IN ('yes','no','unknown')),
  targeted         INTEGER NOT NULL DEFAULT 0,
  notes            TEXT,
  total_intake        INTEGER,
  total_intake_source TEXT,
  is_demo          INTEGER NOT NULL DEFAULT 0,
  updated_at       TEXT,
  updated_by       TEXT
);
CREATE INDEX IF NOT EXISTS ix_colleges_district ON colleges(district_id);
CREATE INDEX IF NOT EXISTS ix_colleges_city ON colleges(city_id);

CREATE TABLE IF NOT EXISTS branches (
  id                INTEGER PRIMARY KEY,
  college_id        TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  code              TEXT NOT NULL,
  name              TEXT,
  category          TEXT NOT NULL DEFAULT 'other' CHECK (category IN ('it_core','it_allied','circuit','core','other')),
  is_relevant       INTEGER NOT NULL DEFAULT 0,
  intake_per_year   INTEGER,
  intake_basis      TEXT NOT NULL DEFAULT 'pending' CHECK (intake_basis IN ('verified','estimated','pending')),
  intake_source     TEXT,
  intake_year       TEXT,
  intake_2023_24    INTEGER,
  strength_total    INTEGER,
  strength_basis    TEXT NOT NULL DEFAULT 'pending' CHECK (strength_basis IN ('verified','estimated','pending')),
  final_year        INTEGER,
  final_year_basis  TEXT NOT NULL DEFAULT 'pending' CHECK (final_year_basis IN ('verified','estimated','pending')),
  eligible_estimate INTEGER,
  eligible_basis    TEXT NOT NULL DEFAULT 'pending' CHECK (eligible_basis IN ('verified','estimated','pending')),
  notes             TEXT,
  is_demo           INTEGER NOT NULL DEFAULT 0,
  updated_at        TEXT,
  updated_by        TEXT,
  UNIQUE (college_id, code)
);
CREATE INDEX IF NOT EXISTS ix_branches_college ON branches(college_id);

CREATE TABLE IF NOT EXISTS courses (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL,
  price_inr INTEGER,
  active    INTEGER NOT NULL DEFAULT 1,
  notes     TEXT,
  is_demo   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS people (
  id         INTEGER PRIMARY KEY,
  college_id TEXT REFERENCES colleges(id),
  role       TEXT NOT NULL CHECK (role IN ('college_lead','ambassador_lead','ambassador')),
  full_name  TEXT NOT NULL,
  phone      TEXT,
  email      TEXT,
  reports_to INTEGER NULL REFERENCES people(id) ON DELETE SET NULL,
  status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','onboarding','inactive')),
  joined_on  TEXT,
  notes      TEXT,
  designation    TEXT,                       -- v4 (added by db.js migration on older DBs)
  responsibility TEXT,                       -- v4
  is_demo    INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  updated_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_people_college ON people(college_id);
CREATE INDEX IF NOT EXISTS ix_people_reports_to ON people(reports_to);

CREATE TABLE IF NOT EXISTS person_branches (
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
  PRIMARY KEY (person_id, branch_id)
);
CREATE INDEX IF NOT EXISTS ix_person_branches_branch ON person_branches(branch_id);

CREATE TABLE IF NOT EXISTS targets (
  id           INTEGER PRIMARY KEY,
  scope_type   TEXT NOT NULL CHECK (scope_type IN ('state','district','city','college','branch','person')),
  scope_id     TEXT NOT NULL,
  course_id    INTEGER NULL REFERENCES courses(id) ON DELETE CASCADE,  -- NULL = all courses
  target       INTEGER NOT NULL CHECK (target >= 0),
  target_min   INTEGER NULL CHECK (target_min IS NULL OR target_min >= 0),   -- v4: optional minimum (<= target)
  target_max   INTEGER NULL CHECK (target_max IS NULL OR target_max >= 0),   -- v4: optional stretch (>= target)
  period       TEXT NOT NULL DEFAULT 'programme' CHECK (period IN ('programme','month','week')), -- v4
  period_start TEXT NULL,                                               -- v4: 'YYYY-MM-01' (month) | Monday (week) | NULL (programme)
  deadline     TEXT,
  notes        TEXT,
  is_demo      INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT,
  updated_by   TEXT
);
-- One target per (scope, course, period): unique index ux_targets_scope_period is created in db.js after the v4 migration
-- (SQLite treats NULLs as distinct in UNIQUE, so it uses IFNULL expressions). Pre-v4 databases are rebuilt once by db.js.

CREATE TABLE IF NOT EXISTS enrollments (
  id              INTEGER PRIMARY KEY,
  college_id      TEXT NOT NULL REFERENCES colleges(id),
  branch_id       INTEGER NULL REFERENCES branches(id) ON DELETE SET NULL,
  course_id       INTEGER NULL REFERENCES courses(id) ON DELETE SET NULL,
  person_id       INTEGER NULL REFERENCES people(id) ON DELETE SET NULL,
  student_name    TEXT NULL,
  student_contact TEXT NULL,
  enrolled_on     TEXT NOT NULL,
  amount_inr      INTEGER NULL,
  notes           TEXT,
  is_demo         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT,
  created_by      TEXT
);
CREATE INDEX IF NOT EXISTS ix_enrollments_college ON enrollments(college_id);
CREATE INDEX IF NOT EXISTS ix_enrollments_branch ON enrollments(branch_id);
CREATE INDEX IF NOT EXISTS ix_enrollments_person ON enrollments(person_id);
CREATE INDEX IF NOT EXISTS ix_enrollments_date ON enrollments(enrolled_on);

CREATE TABLE IF NOT EXISTS activities (
  id               INTEGER PRIMARY KEY,
  college_id       TEXT NOT NULL REFERENCES colleges(id),
  branch_id        INTEGER NULL REFERENCES branches(id) ON DELETE SET NULL,
  person_id        INTEGER NULL REFERENCES people(id) ON DELETE SET NULL,
  on_date          TEXT NOT NULL,
  type             TEXT NOT NULL CHECK (type IN ('visit','call','session','whatsapp','followup','other')),
  students_reached INTEGER NOT NULL DEFAULT 0 CHECK (students_reached >= 0),
  notes            TEXT,
  is_demo          INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT,
  created_by       TEXT
);
CREATE INDEX IF NOT EXISTS ix_activities_college ON activities(college_id);
CREATE INDEX IF NOT EXISTS ix_activities_branch ON activities(branch_id);
CREATE INDEX IF NOT EXISTS ix_activities_person ON activities(person_id);
CREATE INDEX IF NOT EXISTS ix_activities_date ON activities(on_date);

CREATE TABLE IF NOT EXISTS followups (
  id              INTEGER PRIMARY KEY,
  scope_type      TEXT NOT NULL CHECK (scope_type IN ('college','branch','person')),
  scope_id        TEXT NOT NULL,
  owner_person_id INTEGER NULL REFERENCES people(id) ON DELETE SET NULL,
  owner_name      TEXT,
  due_date        TEXT,
  status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done')),
  issue           TEXT CHECK (issue IS NULL OR issue IN ('ambassador_gap','low_outreach','low_conversion','unrealistic_target','exams','data','other')),
  title           TEXT NOT NULL,
  notes           TEXT,
  last_contact    TEXT,
  is_demo         INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT,
  created_by      TEXT,
  done_at         TEXT,
  updated_at      TEXT,
  updated_by      TEXT
);
CREATE INDEX IF NOT EXISTS ix_followups_scope ON followups(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS ix_followups_status_due ON followups(status, due_date);

CREATE TABLE IF NOT EXISTS exams (
  id           INTEGER PRIMARY KEY,
  college_id   TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  semester     TEXT NOT NULL CHECK (semester IN ('3-1','4-1')),
  exam_body    TEXT,
  status       TEXT,
  endsem_start TEXT,
  endsem_end   TEXT,
  mid_window   TEXT,
  lab_window   TEXT,
  evidence     TEXT,
  confidence   TEXT,
  source_url   TEXT,
  notice_date  TEXT,
  verified_on  TEXT,
  notes        TEXT,
  is_demo      INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT,
  updated_by   TEXT
);
CREATE INDEX IF NOT EXISTS ix_exams_college ON exams(college_id, semester);

CREATE TABLE IF NOT EXISTS audit_log (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL,
  actor     TEXT NOT NULL,
  action    TEXT NOT NULL CHECK (action IN ('create','update','delete')),
  entity    TEXT NOT NULL,
  entity_id TEXT,
  before    TEXT,                               -- JSON
  after     TEXT                                -- JSON
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log(entity, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit_log(at);

-- ---------------------------------------------------------------------------------------------
-- Calling system (v2, additive). See CONTRACT.md "Calling system".
-- ---------------------------------------------------------------------------------------------
-- A phone/email contact at a college (TPO, principal, office...). phone is stored normalised ('+91' + 10 digits);
-- phone/email are unique per college (partial unique indexes below), so the same number is never stored twice.
-- status: untested until a call says otherwise (see server/calls.js statusFromCalls); status_source 'manual' when a user set it.
CREATE TABLE IF NOT EXISTS contacts (
  id            INTEGER PRIMARY KEY,
  college_id    TEXT NOT NULL REFERENCES colleges(id),
  branch_id     INTEGER NULL REFERENCES branches(id) ON DELETE SET NULL,
  name          TEXT,
  role          TEXT NOT NULL DEFAULT 'other' CHECK (role IN ('tpo','principal','hod','office','admissions','dean','other')),
  phone         TEXT,
  email         TEXT,
  source_url    TEXT,
  basis         TEXT NOT NULL DEFAULT 'pending' CHECK (basis IN ('verified','pending')),
  notes         TEXT,
  status        TEXT NOT NULL DEFAULT 'untested' CHECK (status IN ('untested','working','non_working','invalid')),
  status_source TEXT CHECK (status_source IS NULL OR status_source IN ('calls','manual')),
  is_demo       INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT,
  created_by    TEXT,
  updated_at    TEXT,
  updated_by    TEXT,
  CHECK (phone IS NOT NULL OR email IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_contacts_college ON contacts(college_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_phone ON contacts(college_id, phone) WHERE phone IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_email ON contacts(college_id, email) WHERE email IS NOT NULL;

-- One logged call attempt. caller = X-User. next_action_at (a date) creates a follow-up (followup_id).
-- confirms_participation = 1 when this call recorded the college's participation (colleges.participation_confirmed_on).
CREATE TABLE IF NOT EXISTS calls (
  id                     INTEGER PRIMARY KEY,
  contact_id             INTEGER NULL REFERENCES contacts(id) ON DELETE SET NULL,
  college_id             TEXT NOT NULL REFERENCES colleges(id),
  branch_id              INTEGER NULL REFERENCES branches(id) ON DELETE SET NULL,
  called_at              TEXT NOT NULL,
  caller                 TEXT NOT NULL,
  outcome                TEXT NOT NULL CHECK (outcome IN ('connected_interested','connected_callback','connected_not_interested',
                           'connected_info_only','no_answer','busy','switched_off','not_reachable','wrong_number','invalid_number','disconnected')),
  notes                  TEXT,
  next_action_at         TEXT,
  followup_id            INTEGER NULL REFERENCES followups(id) ON DELETE SET NULL,
  confirms_participation INTEGER NOT NULL DEFAULT 0,
  is_demo                INTEGER NOT NULL DEFAULT 0,
  created_at             TEXT,
  created_by             TEXT
);
CREATE INDEX IF NOT EXISTS ix_calls_college ON calls(college_id, called_at);
CREATE INDEX IF NOT EXISTS ix_calls_contact ON calls(contact_id, called_at);
CREATE INDEX IF NOT EXISTS ix_calls_at ON calls(called_at);

-- ---------------------------------------------------------------------------------------------
-- Target planner research (v3, additive). See CONTRACT.md "Target planner".
-- Filled ONLY by `node server/import_research.js` from the research CSVs (master_colleges_v2.csv / master_branches_v2.csv);
-- never edited through the API. One row per college (per research_version); re-importing a version replaces its rows.
-- in_plan = 0 marks rows the research excluded from planning (out_of_scope / duplicate_merged); they keep status_final
-- and duplicate_of so the UI can explain them, but carry no planning numbers.
-- payload = the research half of the /api/plan PlanCollege object (every value carries {value, basis, source}).
-- raw = the untouched CSV row (traceability).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS college_plan (
  college_id       TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  research_version TEXT NOT NULL,
  research_id      TEXT NOT NULL,                -- college_db_id in the CSV ('c36', 'new-ANRG')
  in_plan          INTEGER NOT NULL DEFAULT 1,
  status_final     TEXT,
  targeted         INTEGER NOT NULL DEFAULT 0,   -- research decision (targeted = 'yes'), NOT colleges.targeted
  hold_reason      TEXT,
  priority_score   REAL,
  rank             INTEGER,
  p_level          TEXT,
  target_min       INTEGER,
  target_avg       INTEGER,
  target_max       INTEGER,
  ambassadors      INTEGER,
  college_leads    REAL,                         -- 0.5 = a College Lead shared with another college in the same town
  payload          TEXT NOT NULL,                -- JSON
  raw              TEXT,                         -- JSON
  source_file      TEXT,
  imported_at      TEXT NOT NULL,
  imported_by      TEXT,
  PRIMARY KEY (college_id, research_version)
);
CREATE INDEX IF NOT EXISTS ix_college_plan_version ON college_plan(research_version, targeted);

CREATE TABLE IF NOT EXISTS college_plan_branches (
  id                 INTEGER PRIMARY KEY,
  college_id         TEXT NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  research_version   TEXT NOT NULL,
  seq                INTEGER NOT NULL,           -- row order within the college in the CSV
  name               TEXT NOT NULL,
  is_it              INTEGER NOT NULL DEFAULT 0,
  intake_latest      INTEGER,
  intake_latest_year TEXT,
  intake_latest_basis TEXT CHECK (intake_latest_basis IN ('verified','estimated','unavailable')),
  intake_2023_24     INTEGER,                    -- the final-year (2023 batch) intake
  basis              TEXT NOT NULL DEFAULT 'unavailable' CHECK (basis IN ('verified','estimated','unavailable')),
  confidence         TEXT,
  source             TEXT,
  notes              TEXT,
  counted            INTEGER NOT NULL DEFAULT 1, -- 0 = research excluded the row (duplicate row, integrated M.Tech, college not admitting)
  final_decision     TEXT,
  UNIQUE (college_id, research_version, seq)
);
CREATE INDEX IF NOT EXISTS ix_college_plan_branches_college ON college_plan_branches(college_id, research_version);
