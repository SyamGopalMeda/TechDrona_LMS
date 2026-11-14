// Database access: node:sqlite DatabaseSync, idempotent schema + migrations, shared helpers.
import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const PORTAL_ROOT = path.resolve(HERE, '..');
export const DEFAULT_DB_PATH = path.join(PORTAL_ROOT, 'data', 'techdrona.db');

export const DEFAULT_SETTINGS = {
  relevance_factors: { it_core: 1, it_allied: 1, circuit: 0.6, core: 0.15, other: 0.15 },
  min_conversion: 0.05,
  state_target_deadline: '2026-12-31',
  org_name: 'Tech Drona',
  interest_rate: null, // contract lists the key without a default; left null until the team sets it
  // calling: a contact with this many unanswered attempts in a row (no answer / busy / switched off / not reachable,
  // none connected since) is treated as non-working ("unreachable"). See server/calls.js.
  unreachable_after_attempts: 6,
  // Program (district scope + 400 target planner). The user's three target districts are the OLD undivided ones;
  // each maps to present-day district ids. program_target / program_deadline mirror the explicit state target row
  // (targets scope state:ap, all courses) — GET /api/program reads that row first; PATCH /api/program writes both.
  target_district_groups: { Guntur: ['guntur', 'palnadu', 'bapatla'], Krishna: ['krishna', 'ntr'], 'West Godavari': ['west-godavari', 'eluru'] },
  program_target: 400,
  program_deadline: '2026-12-31',
  // v4: pace of programme-period targets is measured from this date (never from when a target row was saved)
  program_start: '2026-11-03',
};

export const RELEVANT_CATEGORIES = new Set(['it_core', 'it_allied', 'circuit']);

// Additive migrations for columns added after the first schema version. Each entry is
// [table, column, column-definition]; applied only if the column is missing.
const COLUMN_MIGRATIONS = [
  // Enrollment funnel (v2). Every enrollment row is ONE student record at exactly one stage. Rows that existed before
  // the funnel were all counted as enrolled, so they become 'confirmed' (the column default) and nothing changes for them.
  ['enrollments', 'stage', "TEXT NOT NULL DEFAULT 'confirmed' CHECK (stage IN ('lead','interested','registered','applied','confirmed','dropped'))"],
  ['enrollments', 'interested_on', 'TEXT'], // first date each stage was reached (lead date = enrolled_on)
  ['enrollments', 'registered_on', 'TEXT'],
  ['enrollments', 'applied_on', 'TEXT'],
  ['enrollments', 'confirmed_on', 'TEXT'],  // NULL on a legacy confirmed row = enrolled_on (queries use COALESCE)
  ['enrollments', 'dropped_on', 'TEXT'],
  ['enrollments', 'student_contact_norm', 'TEXT'], // normalised +91 mobile (or lower-case email) for duplicate checks
  ['enrollments', 'updated_at', 'TEXT'],
  ['enrollments', 'updated_by', 'TEXT'],
  // College participation (calling system): set explicitly by a user (Log call -> "college confirmed participation"
  // or PATCH /api/colleges/:id). Audited like every college edit.
  ['colleges', 'participation_confirmed_on', 'TEXT'],
  ['colleges', 'participation_note', 'TEXT'],
  // v4: per-field verification {field: {source, verified_on, verified_by, note}} and the research importer's stable key
  ['colleges', 'verified_fields', 'TEXT'],
  ['colleges', 'research_id', 'TEXT'],
  // v4: who verified a contact and when (stamped when basis becomes 'verified')
  ['contacts', 'verified_by', 'TEXT'],
  ['contacts', 'verified_on', 'TEXT'],
  // v4: a person's designation (e.g. "3rd-year CSE student") and responsibility (what they own)
  ['people', 'designation', 'TEXT'],
  ['people', 'responsibility', 'TEXT'],
];
// Indexes on migrated columns (created after the columns exist).
const POST_MIGRATION_SQL = `
  CREATE INDEX IF NOT EXISTS ix_enrollments_stage ON enrollments(stage);
  CREATE INDEX IF NOT EXISTS ix_enrollments_contact_norm ON enrollments(student_contact_norm);
  CREATE UNIQUE INDEX IF NOT EXISTS ux_targets_scope_period ON targets(scope_type, scope_id, IFNULL(course_id, 0), period, IFNULL(period_start, ''));
  CREATE INDEX IF NOT EXISTS ix_colleges_research_id ON colleges(research_id);
`;

/**
 * v4: targets gain target_min / target_max / period / period_start, and uniqueness becomes per period. A pre-v4 table has a
 * table-level UNIQUE(scope_type, scope_id, course_id) that cannot be dropped in place, so the table is rebuilt ONCE inside a
 * transaction: every row is copied unchanged (same id, period 'programme'), the old table is dropped and the copy renamed.
 * Nothing references targets, so no foreign key is affected. Idempotent: a table that already has `period` is left alone.
 */
function migrateTargetsV4(db) {
  const cols = db.prepare('PRAGMA table_info(targets)').all().map((c) => c.name);
  if (cols.includes('period')) return false;
  db.exec('BEGIN IMMEDIATE');
  try {
    db.exec(`CREATE TABLE targets_v4 (
      id INTEGER PRIMARY KEY,
      scope_type TEXT NOT NULL CHECK (scope_type IN ('state','district','city','college','branch','person')),
      scope_id TEXT NOT NULL,
      course_id INTEGER NULL REFERENCES courses(id) ON DELETE CASCADE,
      target INTEGER NOT NULL CHECK (target >= 0),
      target_min INTEGER NULL CHECK (target_min IS NULL OR target_min >= 0),
      target_max INTEGER NULL CHECK (target_max IS NULL OR target_max >= 0),
      period TEXT NOT NULL DEFAULT 'programme' CHECK (period IN ('programme','month','week')),
      period_start TEXT NULL,
      deadline TEXT, notes TEXT, is_demo INTEGER NOT NULL DEFAULT 0, updated_at TEXT, updated_by TEXT)`);
    db.exec(`INSERT INTO targets_v4 (id, scope_type, scope_id, course_id, target, period, deadline, notes, is_demo, updated_at, updated_by)
      SELECT id, scope_type, scope_id, course_id, target, 'programme', deadline, notes, is_demo, updated_at, updated_by FROM targets`);
    const a = db.prepare('SELECT COUNT(*) n FROM targets').get().n; const b = db.prepare('SELECT COUNT(*) n FROM targets_v4').get().n;
    if (a !== b) throw new Error(`targets v4 migration copied ${b} of ${a} rows`);
    db.exec('DROP TABLE targets');
    db.exec('ALTER TABLE targets_v4 RENAME TO targets');
    db.exec('COMMIT');
  } catch (e) { try { db.exec('ROLLBACK'); } catch { /* ignore */ } throw e; }
  return true;
}

/** v4 data migrations (idempotent, cheap): normalise people phones/emails (R6); backfill colleges.research_id from college_plan. */
function migrateDataV4(db) {
  const rows = db.prepare(`SELECT id, phone, email FROM people WHERE (phone IS NOT NULL AND phone NOT GLOB '+91[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')
    OR (email IS NOT NULL AND email <> lower(trim(email)))`).all();
  for (const p of rows) {
    const ph = p.phone == null ? null : (normPhone(p.phone) || p.phone); // unparseable legacy values are kept as typed
    const em = p.email == null ? null : (normEmail(p.email) || p.email);
    if (ph === p.phone && em === p.email) continue;
    db.prepare('UPDATE people SET phone = ?, email = ? WHERE id = ?').run(ph, em, p.id);
    writeAudit(db, 'system', 'update', 'person', p.id, { phone: p.phone, email: p.email }, { phone: ph, email: em });
  }
  db.exec(`UPDATE colleges SET research_id = (SELECT research_id FROM college_plan p WHERE p.college_id = colleges.id ORDER BY imported_at DESC LIMIT 1)
    WHERE research_id IS NULL AND EXISTS (SELECT 1 FROM college_plan p WHERE p.college_id = colleges.id)`);
  migrateCanonicalV41(db);
}

/**
 * v4.1 (SEC-03, SEC-06): one canonical id per scope ("0010" -> "10", " C9 " -> "c9") on follow-ups and targets, so delete guards and
 * rollups see every row; settings rows whose key is an Object.prototype name (junk from before the allow-list) are removed.
 * Idempotent; audited per row; a target that would collide with an existing canonical row is left as it is (reported by integrity()).
 */
function migrateCanonicalV41(db) {
  for (const table of ['followups', 'targets']) {
    const rows = db.prepare(`SELECT id, scope_type, scope_id FROM ${table} WHERE scope_type IN ('person', 'branch', 'college')`).all();
    for (const r of rows) {
      const canon = canonicalScopeId(r.scope_type, r.scope_id);
      if (canon == null || canon === r.scope_id) continue;
      try {
        db.prepare(`UPDATE ${table} SET scope_id = ? WHERE id = ?`).run(canon, r.id);
        writeAudit(db, 'system', 'update', table === 'targets' ? 'target' : 'followup', r.id, { scope_id: r.scope_id }, { scope_id: canon, reason: 'canonical scope id (v4.1)' });
      } catch { /* unique clash with an existing canonical target row: keep both, integrity() reports it */ }
    }
  }
  const junk = Object.getOwnPropertyNames(Object.prototype);
  const del = db.prepare('DELETE FROM settings WHERE key = ?');
  for (const k of junk) if (db.prepare('SELECT 1 FROM settings WHERE key = ?').get(k)) { del.run(k); writeAudit(db, 'system', 'delete', 'setting', k, { key: k }, { reason: 'reserved key (v4.1)' }); }
}
/** v4.1 (SEC-03): canonical scope id for person/branch (digits, no leading zeros) and college ('c' + digits, lower-case); else unchanged/null. */
export function canonicalScopeId(type, id) {
  if (id == null) return null;
  const s = String(id).trim();
  if (type === 'person' || type === 'branch') return /^\d+$/.test(s) ? String(Number(s)) : null;
  if (type === 'college') return /^c\d+$/i.test(s) ? `c${Number(s.slice(1))}` : null;
  if (type === 'district' || type === 'city') return s.toLowerCase();
  return s;
}

export function openDb(dbPath = process.env.DB_PATH || DEFAULT_DB_PATH) {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec('PRAGMA journal_mode = WAL;');
  db.exec('PRAGMA foreign_keys = ON;');
  db.exec('PRAGMA busy_timeout = 5000;');
  migrate(db);
  return safeBinding(db);
}

/** Bind helper: SQLite rejects `undefined`, so every bound parameter goes through this (undefined -> null). */
export const bindValue = (v) => (v === undefined ? null : v);
const bindArgs = (args) => args.map((a) => (a && typeof a === 'object' && !Array.isArray(a) && !(a instanceof Uint8Array)
  ? Object.fromEntries(Object.entries(a).map(([k, v]) => [k, bindValue(v)]))
  : bindValue(a)));

/** Wrap db.prepare so run/get/all/iterate never receive `undefined` (single choke point for all queries). */
function safeBinding(db) {
  const prepare = db.prepare.bind(db);
  db.prepare = (sql) => {
    const st = prepare(sql);
    return {
      run: (...a) => st.run(...bindArgs(a)),
      get: (...a) => st.get(...bindArgs(a)),
      all: (...a) => st.all(...bindArgs(a)),
      iterate: (...a) => st.iterate(...bindArgs(a)),
      statement: st,
    };
  };
  return db;
}

export function migrate(db) {
  const sql = fs.readFileSync(path.join(HERE, 'schema.sql'), 'utf8');
  db.exec(sql);
  for (const [table, col, def] of COLUMN_MIGRATIONS) {
    const cols = db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name);
    if (!cols.includes(col)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${col} ${def}`);
  }
  migrateTargetsV4(db);
  db.exec(POST_MIGRATION_SQL);
  migrateDataV4(db);
  const ins = db.prepare('INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)');
  // program_target / program_deadline start from the explicit state target row when one exists (single source of truth)
  const st = db.prepare("SELECT target, deadline FROM targets WHERE scope_type = 'state' AND course_id IS NULL AND period = 'programme' ORDER BY id LIMIT 1").get();
  const defaults = { ...DEFAULT_SETTINGS };
  if (st) { defaults.program_target = Number(st.target); if (st.deadline) defaults.program_deadline = st.deadline; }
  for (const [k, v] of Object.entries(defaults)) ins.run(k, JSON.stringify(v));
}

export function tx(db, fn) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const r = fn();
    db.exec('COMMIT');
    return r;
  } catch (e) {
    try { db.exec('ROLLBACK'); } catch { /* already rolled back */ }
    throw e;
  }
}

/** Today's date as YYYY-MM-DD in India (Asia/Kolkata, whatever the host's zone), overridable with env TODAY for testing. */
const IST_DATE = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' });
export function today() {
  if (process.env.TODAY && /^\d{4}-\d{2}-\d{2}$/.test(process.env.TODAY)) return process.env.TODAY;
  return IST_DATE.format(new Date());
}

export function nowIso() {
  if (process.env.TODAY && /^\d{4}-\d{2}-\d{2}$/.test(process.env.TODAY)) {
    return `${process.env.TODAY}T${new Date().toISOString().slice(11)}`;
  }
  return new Date().toISOString();
}

export function slugify(s) {
  return String(s || '')
    .normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function getSettings(db) {
  const out = { ...DEFAULT_SETTINGS };
  for (const r of db.prepare('SELECT key, value FROM settings').all()) {
    if (r.key in Object.prototype) continue; // v4.1 (SEC-06): never let a stored key shadow an object method

    try { out[r.key] = JSON.parse(r.value); } catch { out[r.key] = r.value; }
  }
  out.relevance_factors = { ...DEFAULT_SETTINGS.relevance_factors, ...(out.relevance_factors || {}) };
  return out;
}

export function writeAudit(db, actor, action, entity, entityId, before, after) {
  db.prepare('INSERT INTO audit_log(at, actor, action, entity, entity_id, before, after) VALUES (?,?,?,?,?,?,?)')
    .run(nowIso(), actor, action, entity, entityId == null ? null : String(entityId),
      before == null ? null : JSON.stringify(before), after == null ? null : JSON.stringify(after));
}

/**
 * Derive branch estimates. Fields whose basis is 'verified' are kept as-is; everything else is
 * recomputed from intake: strength = intake*4, final_year = intake_2023_24 ?? intake,
 * eligible = final_year * relevance_factors[category]. Unknown intake -> null / 'pending'.
 */
export function deriveBranch(b, factors) {
  const out = { ...b };
  const intake = b.intake_per_year == null ? null : Number(b.intake_per_year);
  if (out.strength_basis !== 'verified') {
    out.strength_total = intake == null ? null : intake * 4;
    out.strength_basis = intake == null ? 'pending' : 'estimated';
  }
  if (out.final_year_basis !== 'verified') {
    const fy = b.intake_2023_24 != null ? Number(b.intake_2023_24) : intake;
    out.final_year = fy;
    out.final_year_basis = fy == null ? 'pending' : 'estimated';
  }
  if (out.eligible_basis !== 'verified') {
    const f = factors[out.category] ?? factors.other ?? 0.15;
    out.eligible_estimate = out.final_year == null ? null : Math.round(out.final_year * f);
    out.eligible_basis = out.final_year == null ? 'pending' : 'estimated';
  }
  return out;
}

/**
 * Indian phone number -> '+91' + 10 digits, or null when it is not a valid Indian number.
 * Accepts mobiles (98765 43210, +91-98765-43210, 0 98765 43210) and landlines with STD code (0863-2344700 -> +918632344700).
 * Anything after an extension marker (ext, x) or a second number (",", ";", "/") is ignored.
 */
export function normPhone(v) {
  if (v == null) return null;
  let s = String(v).split(/\b(?:ext|extn)\b|\bx\s*\d|[,;/]/i)[0];
  s = s.replace(/[^\d+]/g, '');
  let d = s.replace(/\+/g, '');
  if (s.startsWith('+') && !d.startsWith('91')) return null; // foreign number
  if (d.startsWith('0091')) d = d.slice(4);
  if (d.length === 13 && d.startsWith('910')) d = d.slice(3); // '+91 0866 2469665'
  if (d.length === 12 && d.startsWith('91')) d = d.slice(2);
  else if (d.length === 11 && d.startsWith('0')) d = d.slice(1);
  if (!/^[1-9]\d{9}$/.test(d)) return null;
  return `+91${d}`;
}
export const isMobile = (norm) => /^\+91[6-9]\d{9}$/.test(norm || '');
export function normEmail(v) {
  if (v == null) return null;
  const s = String(v).trim().toLowerCase();
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s) ? s : null;
}
