// Research import for the target planner: master_colleges_v2.csv + master_branches_v2.csv -> college_plan / college_plan_branches.
//
//   node server/import_research.js [--dry-run] [--csv-dir <dir>] [--db <file>]      (DB_PATH env works too)
//
// Idempotent: a research version's rows are replaced as a whole and an unchanged CSV reports 0 inserts/updates.
// It never changes existing colleges / branches / contacts. The only writes outside the plan tables are for a
// research college that is missing from the DB AND verified active (ANR CET Gudivada, research id 'new-ANRG'):
// that college (+ its branches and its official contacts) is inserted once, audited as actor 'import_research'.
// Values are copied, never invented: a figure without a basis (or with basis 'unavailable') is stored as null/'unavailable'.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openDb, tx, nowIso, writeAudit, slugify, deriveBranch, getSettings, RELEVANT_CATEGORIES, PORTAL_ROOT } from './db.js';
import { normCategory, seedContacts } from './seed.js';

export const RESEARCH_VERSION = 'v2 2026-11-07';
export const SOURCE_REPORT = 'reports/Krishna Guntur West Godavari colleges 2.md';
export const DEFAULT_CSV_DIR = path.resolve(PORTAL_ROOT, '..', 'research_notes', 'Krishna Guntur West Godavari colleges 2');
const ACTOR = 'import_research';
const COLLEGES_CSV = 'master_colleges_v2.csv';
const BRANCHES_CSV = 'master_branches_v2.csv';

/** RFC 4180 CSV: quoted fields may contain commas, quotes ("") and newlines; CRLF or LF; BOM stripped. Returns {header, rows[obj]}. */
export function parseCsv(text) {
  let s = String(text);
  if (s.charCodeAt(0) === 0xfeff) s = s.slice(1);
  const rows = []; let row = []; let f = ''; let q = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (q) {
      if (ch === '"') { if (s[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += ch;
      continue;
    }
    if (ch === '"' && f === '') q = true;
    else if (ch === ',') { row.push(f); f = ''; } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && s[i + 1] === '\n') i++;
      row.push(f); rows.push(row); row = []; f = '';
    } else f += ch;
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row); }
  const header = (rows.shift() || []).map((h) => h.trim());
  const out = rows.filter((r) => r.some((x) => x.trim() !== '')).map((r) => Object.fromEntries(header.map((h, j) => [h, (r[j] ?? '').trim()])));
  return { header, rows: out };
}

// ------------------------------------------------------------------------------------------------ value helpers
const blank = (v) => v == null || String(v).trim() === '';
const num = (v) => { if (blank(v)) return null; const t = String(v).replace(/,/g, '').trim(); return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : null; };
/** leading whole number of a cell like "0 (not offered in 2025-26)" */
const leadInt = (v) => { if (blank(v)) return null; const m = /^\s*(\d[\d,]*)/.exec(String(v)); return m ? Number(m[1].replace(/,/g, '')) : null; };
const str = (v) => (blank(v) ? null : String(v).trim());
const firstUrl = (...vals) => { for (const v of vals) { const m = /https?:\/\/[^\s;,)"']+/.exec(String(v || '')); if (m) return m[0]; } return null; };
const isoDate = (v) => (/^\d{4}-\d{2}-\d{2}$/.test(String(v || '').trim()) ? String(v).trim() : null);
export function normBasis(v) {
  const t = String(v || '').trim().toLowerCase();
  if (t.startsWith('verif')) return 'verified';
  if (t.startsWith('estim')) return 'estimated';
  return 'unavailable';
}
/** {value, basis}: a value is kept only with a verified/estimated basis; otherwise null + 'unavailable'. */
function vb(value, basisRaw, extra = {}) {
  const basis = normBasis(basisRaw);
  if (value == null || basis === 'unavailable') return { value: null, basis: 'unavailable', ...extra };
  return { value, basis, ...extra };
}
/** a figure copied from an official document: verified when it has a source URL, else estimated; null -> unavailable */
function sourced(value, source, extra = {}) {
  if (value == null) return { value: null, basis: 'unavailable', ...extra, source: source || null };
  return { value, basis: source ? 'verified' : 'estimated', ...extra, source: source || null };
}
/** basis of a branch's latest-intake figure, from how the research described its year/source */
function intakeLatestBasis(value, yearText, source) {
  if (value == null) return 'unavailable';
  const t = String(yearText || '').toLowerCase();
  if (/estimat|derived|\bdb\b|\/\s*0\.\d|undated/.test(t)) return 'estimated';
  return source ? 'verified' : 'estimated';
}
const splitList = (v) => (blank(v) ? [] : String(v).split(/\s*;\s*/).map((x) => x.trim()).filter(Boolean));

// Research ids that are not 'c<sno>' and how to recognise them in the DB once inserted.
const NEW_COLLEGES = {
  'new-ANRG': {
    short_name: 'ANR CET', aliases: ['ANR CET', 'ANRG', 'ANR College of Engineering & Technology', 'new-ANRG'],
    match: (c) => /akkineni nageswara rao college of engineering/i.test(c.name || '') || /anrcollege\.edu\/cet/i.test(c.website || ''),
    hold_reason: 'No final-year batch until 2028-29 (college opened in 2025-26; first B.Tech batch inducted Aug 2025).',
  },
};
const BRANCH_CODES = [
  [/^computer science and engineering$/i, 'CSE'], [/^artificial intelligence and data science$/i, 'AI-DS'],
  [/^information technology( and engineering)?$/i, 'IT'], [/^electronics and communication engineering$/i, 'ECE'],
  [/^electrical and electronics engineering$/i, 'EEE'], [/^civil engineering$/i, 'CIVIL'], [/^mechanical engineering$/i, 'MECH'],
];
const branchCode = (name) => (BRANCH_CODES.find(([re]) => re.test(name))?.[1]) || slugify(name).toUpperCase().slice(0, 40);

function holdReason(r, F) {
  const o = NEW_COLLEGES[r.college_db_id]?.hold_reason;
  if (o) return o;
  if (r.targeted === 'yes') return null;
  if (r.status_final !== 'active') return str(r.final_decision) || `Status: ${r.status_final}`;
  if (F == null) return 'IT final-year pool unavailable (no usable 2023-24 intake figure), so no estimate was made.';
  if (F === 0) return 'No IT final-year students in the 2023-24 batch (IT final-year pool = 0).';
  return str(r.final_decision);
}

/** Research half of a PlanCollege (live fields — name, district, actual{} — are added by GET /api/plan). */
export function planPayload(r, branchRows) {
  const F = num(r.it_fy_pool_F);
  const inPlan = !['out_of_scope', 'duplicate_merged'].includes(r.status_final) && r.scope_in === 'yes';
  const fySource = firstUrl(r.qa_fy_source_check, r.pool_method_note, r.conflict_resolution, r.total_intake_source_url);
  const tsNote = str(r.T_S_basis);
  const ex41 = isoDate(r.exam_4_1_end); const ex31 = isoDate(r.exam_3_1_end);
  const branches = branchRows.map((b, i) => {
    const latest = leadInt(b.intake_per_year); const src = str(b.intake_source_url);
    const fy = vb(num(b.final_year_intake_2023_24), b.final_year_basis);
    const decision = str(b.final_decision);
    return {
      seq: i + 1, name: b.branch, is_it: /^y/i.test(b.is_it),
      intake_latest: latest, intake_latest_year: str(b.intake_year), intake_latest_basis: intakeLatestBasis(latest, b.intake_year, src),
      intake_2023_24: fy.value, basis: fy.basis, confidence: str(b.confidence), source: src, notes: str(b.notes),
      counted: decision ? decision === 'count' : true, final_decision: decision,
    };
  });
  const payload = {
    research_id: r.college_db_id, research_name: r.college, research_district_id: str(r.new_district_id),
    old_district_group: str(r.old_district_group), research_city: str(r.city), cluster: str(r.cluster),
    status_final: r.status_final, final_decision: str(r.final_decision), status_detail: str(r.status_detail_v2),
    status_evidence: str(r.status_evidence) || str(r.activity_evidence), status_evidence_url: firstUrl(r.status_evidence_url, r.activity_evidence_url),
    duplicate_of: str(r.duplicate_of), in_plan: inPlan,
    targeted: r.targeted === 'yes', hold_reason: holdReason(r, F),
    website: str(r.website), ownership: str(r.ownership), affiliation: str(r.affiliation), autonomous: str(r.autonomous),
    it_branches: splitList(r.it_branches), it_branch_count: num(r.it_branch_count), all_branches: splitList(r.all_branches),
  };
  if (!inPlan) return { payload, branches: [] };
  Object.assign(payload, {
    total_students: sourced(num(r.total_students), firstUrl(r.total_students_source_url), { year: str(r.total_students_year) }),
    total_intake: sourced(num(r.total_intake_per_year), firstUrl(r.total_intake_source_url), { year: str(r.total_intake_year) }),
    fy_pool: vb(num(r.fy_pool_used), r.fy_pool_basis, { source: fySource, definition: str(r.fy_pool_definition) }),
    it_fy: vb(F, r.it_fy_pool_basis, { source: fySource, note: str(r.pool_method_note) }),
    it_3rd: vb(num(r.it_3rd_year_T), tsNote, { note: tsNote }),
    it_2nd: vb(num(r.it_2nd_year_S), tsNote, { note: tsNote }),
    fill_risk_flag: str(r.fill_risk_flag), conflict_resolution: str(r.conflict_resolution),
    strength_confidence: str(r.strength_confidence),
    access_x: num(r.access_x), type: str(r.type), priority_score: num(r.priority_score),
    score_parts: { pool: num(r.score_pool), contact: num(r.score_contact), digital: num(r.score_digital), exam: num(r.score_exam), fill_quality: num(r.score_fill_quality), tier_naac: num(r.score_tier_naac) },
    rank: num(r.rank), p_level: str(r.p_level),
    research_target: { min: num(r.min), avg: num(r.avg), max: num(r.max) },
    buffered_min: num(r.buffered_min), standby: num(r.standby),
    rag_400: str(r.rag_400), mou: { min: num(r.mou_min), avg: num(r.mou_avg), max: num(r.mou_max) },
    ambassadors_research: num(r.ambassadors), college_leads_research: num(r.college_leads), lead_assignment: str(r.lead_assignment),
    lead_offer: str(r.lead_offer), placement_tier: str(r.placement_tier), verify_flag: str(r.verify_flag),
    exam_4_1_end: ex41, exam_4_1_note: ex41 ? null : str(r.exam_4_1_end), exam_4_1_source: str(r.exam_4_1_end_source),
    exam_3_1_end: ex31, exam_3_1_note: ex31 ? null : str(r.exam_3_1_end),
    contact: {
      name: str(r.tpo_or_contact_name), role: str(r.tpo_or_contact_role), phone: str(r.contact_phone), email: str(r.contact_email),
      source: firstUrl(r.contact_source_url), verified: !!firstUrl(r.contact_source_url) && !!(str(r.contact_phone) || str(r.contact_email)),
    },
    social: { instagram: str(r.official_instagram), linkedin: str(r.official_linkedin), facebook_or_youtube: str(r.official_facebook_or_youtube) },
    student_communities: str(r.student_communities), outreach_opportunities: str(r.outreach_opportunities),
    notes: str(r.notes), db_discrepancies: str(r.db_discrepancies), change_note_v2: str(r.change_note_v2),
  });
  return { payload, branches };
}

// ------------------------------------------------------------------------------------------------ new college (verified active, missing from DB)
function findNewCollege(db, rid) {
  // v4 (R12, BE-01): stable keys first, so an admin rename / website change / alias edit never makes the importer insert a duplicate.
  // 1) colleges.research_id (set when the importer inserted it; backfilled by db.js), 2) any college_plan row for this research id.
  const hasCol = db.prepare('PRAGMA table_info(colleges)').all().some((c) => c.name === 'research_id');
  if (hasCol) { const byKey = db.prepare('SELECT id FROM colleges WHERE research_id = ? ORDER BY sno LIMIT 1').get(rid); if (byKey) return byKey.id; }
  const byPlan = db.prepare('SELECT p.college_id FROM college_plan p JOIN colleges c ON c.id = p.college_id WHERE p.research_id = ? ORDER BY p.imported_at DESC LIMIT 1').get(rid);
  if (byPlan) return byPlan.college_id;
  const spec = NEW_COLLEGES[rid]; if (!spec) return null;
  for (const c of db.prepare('SELECT id, name, website, aliases FROM colleges').all()) {
    let al = []; try { al = JSON.parse(c.aliases || '[]') || []; } catch { /* ignore */ }
    if (spec.match(c) || (Array.isArray(al) && al.includes(rid))) return c.id;
  }
  return null;
}
function insertNewCollege(db, r, branchRows, log) {
  const spec = NEW_COLLEGES[r.college_db_id];
  const sno = Number(db.prepare('SELECT COALESCE(MAX(sno), 0) + 1 n FROM colleges').get().n);
  const id = `c${sno}`; const at = nowIso();
  const district = str(r.new_district_id);
  const cityId = `${district}--${slugify(r.city)}`;
  const city = db.prepare('SELECT * FROM cities WHERE id = ? AND district_id = ?').get(cityId, district);
  const evidenceUrl = firstUrl(r.activity_evidence_url);
  const row = {
    id, sno, name: r.college, short_name: spec.short_name, aliases: JSON.stringify(spec.aliases), district_id: district,
    city_id: city ? city.id : null,
    lat: city?.lat ?? null, lng: city?.lng ?? null, geo_precision: city?.lat != null ? 'town' : 'pending',
    geo_source: city?.lat != null ? `Town centre of ${city.name} (cities table); exact campus location pending` : null,
    website: str(r.website), phone: splitList(r.contact_phone)[0] || null, email: str(r.contact_email), contact_source: firstUrl(r.contact_source_url),
    ownership: str(r.ownership), autonomous: str(r.autonomous), affiliation: str(r.affiliation),
    op_status: 'operational', op_status_note: str(r.activity_evidence), op_status_source: evidenceUrl,
    op_2025_26: /^y/i.test(r.admitting_2025_26) ? 'yes' : 'unknown',
    op_2026_27: /2026-27/.test(r.notes + r.activity_evidence) ? 'yes' : 'unknown',
    targeted: 1,
    notes: `Added by the research import (${RESEARCH_VERSION}): missing from the master list, verified active (${str(r.activity_evidence) || 'see research'}). `
      + `${spec.hold_reason} Research notes: ${str(r.notes) || '—'}`,
    total_intake: num(r.total_intake_per_year), total_intake_source: firstUrl(r.total_intake_source_url),
    updated_at: at, updated_by: ACTOR,
  };
  if (db.prepare('PRAGMA table_info(colleges)').all().some((c) => c.name === 'research_id')) row.research_id = r.college_db_id; // v4 stable key
  const cols = Object.keys(row);
  db.prepare(`INSERT INTO colleges (${cols.join(',')}) VALUES (${cols.map(() => '?').join(',')})`).run(...cols.map((c) => row[c]));
  writeAudit(db, ACTOR, 'create', 'college', id, null, db.prepare('SELECT * FROM colleges WHERE id = ?').get(id));
  const factors = getSettings(db).relevance_factors;
  let nb = 0;
  for (const b of branchRows) {
    if (b.final_decision && b.final_decision !== 'count') continue;
    const code = branchCode(b.branch);
    if (db.prepare('SELECT 1 FROM branches WHERE college_id = ? AND code = ?').get(id, code)) continue;
    const category = normCategory(null, code, b.branch);
    const intake = leadInt(b.intake_per_year); const fyBasis = normBasis(b.final_year_basis); const fy = num(b.final_year_intake_2023_24);
    let br = {
      college_id: id, code, name: b.branch, category, is_relevant: RELEVANT_CATEGORIES.has(category) ? 1 : 0,
      intake_per_year: intake, intake_basis: intake == null ? 'pending' : (str(b.intake_source_url) ? 'verified' : 'estimated'),
      intake_source: str(b.intake_source_url), intake_year: str(b.intake_year), intake_2023_24: fyBasis === 'unavailable' ? null : fy,
      strength_total: null, strength_basis: 'pending', final_year: null, final_year_basis: 'pending', eligible_estimate: null, eligible_basis: 'pending',
      notes: `Research import (${RESEARCH_VERSION}): ${str(b.notes) || ''}`.trim(), updated_at: at, updated_by: ACTOR,
    };
    if (fyBasis === 'verified' && fy != null) { br.final_year = fy; br.final_year_basis = 'verified'; }
    br = deriveBranch(br, factors);
    // the college opened in 2025-26: intake x 4 would overstate its strength, so strength stays pending (not estimated)
    br.strength_total = null; br.strength_basis = 'pending';
    const bc = Object.keys(br);
    const res = db.prepare(`INSERT INTO branches (${bc.join(',')}) VALUES (${bc.map(() => '?').join(',')})`).run(...bc.map((c) => br[c]));
    writeAudit(db, ACTOR, 'create', 'branch', Number(res.lastInsertRowid), null, db.prepare('SELECT * FROM branches WHERE id = ?').get(Number(res.lastInsertRowid)));
    nb++;
  }
  log(`  inserted college ${id} ${r.college} (${district}${city ? `, ${city.name}` : ''}) with ${nb} branches`);
  return { id, branches: nb };
}
/** official contacts of a newly inserted college (phones split one per contact by seedContacts; idempotent; own transaction) */
function insertNewCollegeContacts(db, id, r, log) {
  if (!str(r.contact_phone) && !str(r.contact_email)) return 0;
  const res = seedContacts(db, { log: () => {}, rows: [{ college_id: id, role: /principal/i.test(r.tpo_or_contact_role) ? 'principal' : /tpo|placement/i.test(r.tpo_or_contact_role) ? 'tpo' : 'other',
    name: str(r.tpo_or_contact_name), phone: str(r.contact_phone), email: str(r.contact_email), source_url: firstUrl(r.contact_source_url),
    basis: firstUrl(r.contact_source_url) ? 'verified' : 'pending', notes: `Research import (${RESEARCH_VERSION}); role as listed: ${str(r.tpo_or_contact_role) || '—'}` }] });
  log(`  ${id}: ${res.insert || 0} contacts added from the research row`);
  return res.insert || 0;
}

// ------------------------------------------------------------------------------------------------ import
export function readResearch(csvDir = DEFAULT_CSV_DIR) {
  const cf = path.join(csvDir, COLLEGES_CSV); const bf = path.join(csvDir, BRANCHES_CSV);
  for (const f of [cf, bf]) if (!fs.existsSync(f)) throw new Error(`Research file not found: ${f}`);
  return { colleges: parseCsv(fs.readFileSync(cf, 'utf8')), branches: parseCsv(fs.readFileSync(bf, 'utf8')), files: { colleges: cf, branches: bf } };
}

/**
 * Import (or with dryRun, only diff) one research version. Returns stats:
 * {rows, plan:{insert,update,same,delete}, in_plan, excluded, targeted, skipped[], new_colleges[], branches:{rows,counted}, totals}
 */
export function importResearch(db, { csvDir = DEFAULT_CSV_DIR, dryRun = false, log = console.log, version = RESEARCH_VERSION } = {}) {
  const { colleges, branches, files } = readResearch(csvDir);
  const need = ['college_db_id', 'status_final', 'targeted', 'it_fy_pool_F', 'min', 'avg', 'max', 'ambassadors', 'college_leads'];
  const missing = need.filter((h) => !colleges.header.includes(h));
  if (missing.length) throw new Error(`${COLLEGES_CSV} is missing columns: ${missing.join(', ')}`);
  const bByCollege = new Map();
  for (const b of branches.rows) { const a = bByCollege.get(b.college_db_id) || []; a.push(b); bByCollege.set(b.college_db_id, a); }
  const dbIds = new Set(db.prepare('SELECT id FROM colleges').all().map((r) => r.id));
  const stats = { version, rows: colleges.rows.length, plan: { insert: 0, update: 0, same: 0, delete: 0 }, in_plan: 0, excluded: 0, targeted: 0,
    skipped: [], new_colleges: [], branches: { rows: 0, counted: 0 }, totals: { min: 0, avg: 0, max: 0, ambassadors: 0, college_leads: 0 }, dry_run: dryRun };
  const seen = new Set();
  const planned = [];
  for (const r of colleges.rows) {
    const rid = r.college_db_id;
    if (!rid) { stats.skipped.push({ research_id: null, reason: 'row without college_db_id' }); continue; }
    if (seen.has(rid)) { stats.skipped.push({ research_id: rid, reason: 'duplicate row for the same research id' }); continue; }
    seen.add(rid);
    let cid = /^c\d+$/.test(rid) ? rid : findNewCollege(db, rid);
    if (cid && !dbIds.has(cid)) cid = null;
    if (!cid) {
      if (NEW_COLLEGES[rid] && r.status_final === 'active' && r.scope_in === 'yes') { stats.new_colleges.push({ research_id: rid, name: r.college, row: r }); cid = `(new) ${rid}`; } else { stats.skipped.push({ research_id: rid, reason: 'college not in the DB (and not a verified-active new college)' }); continue; }
    }
    const { payload, branches: brs } = planPayload(r, bByCollege.get(rid) || []);
    planned.push({ cid, rid, r, payload, brs });
  }
  for (const p of planned) {
    if (!p.payload.in_plan) { stats.excluded++; continue; }
    stats.in_plan++;
    stats.branches.rows += p.brs.length; stats.branches.counted += p.brs.filter((b) => b.counted).length;
    if (p.payload.targeted) {
      stats.targeted++;
      for (const [k, v] of [['min', p.payload.research_target.min], ['avg', p.payload.research_target.avg], ['max', p.payload.research_target.max], ['ambassadors', p.payload.ambassadors_research], ['college_leads', p.payload.college_leads_research]]) stats.totals[k] += Number(v || 0);
    }
  }
  // diff against what is stored for this version
  const existing = new Map(db.prepare('SELECT * FROM college_plan WHERE research_version = ?').all(version).map((x) => [x.college_id, x]));
  const existingBr = new Map();
  for (const b of db.prepare('SELECT * FROM college_plan_branches WHERE research_version = ? ORDER BY college_id, seq').all(version)) {
    const a = existingBr.get(b.college_id) || []; a.push(b); existingBr.set(b.college_id, a);
  }
  const brKey = (list) => JSON.stringify(list.map((b) => [b.seq, b.name, b.is_it ? 1 : 0, b.intake_latest ?? null, b.intake_latest_year ?? null, b.intake_latest_basis ?? null, b.intake_2023_24 ?? null, b.basis, b.confidence ?? null, b.source ?? null, b.notes ?? null, b.counted ? 1 : 0, b.final_decision ?? null]));
  const keep = new Set();
  for (const p of planned) {
    const ex = existing.get(p.cid);
    keep.add(p.cid);
    if (!ex) { stats.plan.insert++; continue; }
    const same = ex.payload === JSON.stringify(p.payload) && ex.raw === JSON.stringify(p.r) && brKey(existingBr.get(p.cid) || []) === brKey(p.brs);
    if (same) stats.plan.same++; else stats.plan.update++;
  }
  for (const cid of existing.keys()) if (!keep.has(cid)) stats.plan.delete++;

  const s = stats;
  log(`Research ${version}: ${s.rows} college rows in ${path.basename(files.colleges)}, ${branches.rows.length} branch rows in ${path.basename(files.branches)}`);
  log(`  plan rows: ${s.in_plan} in plan (${s.targeted} targeted) + ${s.excluded} excluded (out of scope / duplicate), ${s.skipped.length} skipped`);
  for (const k of s.skipped) log(`  skipped ${k.research_id}: ${k.reason}`);
  for (const n of s.new_colleges) log(`  ${dryRun ? 'would insert' : 'inserting'} missing verified-active college ${n.research_id} (${n.name})`);
  log(`  diff vs stored: ${s.plan.insert} insert, ${s.plan.update} update, ${s.plan.same} unchanged, ${s.plan.delete} delete`);
  log(`  branches: ${s.branches.rows} rows (${s.branches.counted} counted)`);
  log(`  targeted research totals: min ${s.totals.min} / avg ${s.totals.avg} / max ${s.totals.max}, ambassadors ${s.totals.ambassadors}, college leads ${s.totals.college_leads}`);
  if (dryRun) { log('  dry run: nothing written'); return stats; }
  if (s.plan.insert === 0 && s.plan.update === 0 && s.plan.delete === 0 && !s.new_colleges.length) { log('  up to date: nothing written'); return stats; }

  tx(db, () => {
    for (const n of s.new_colleges) {
      const made = insertNewCollege(db, n.row, bByCollege.get(n.research_id) || [], log);
      for (const p of planned) if (p.cid === `(new) ${n.research_id}`) p.cid = made.id;
      n.college_id = made.id;
    }
    const at = nowIso();
    db.prepare('DELETE FROM college_plan_branches WHERE research_version = ?').run(version);
    db.prepare('DELETE FROM college_plan WHERE research_version = ?').run(version);
    const insP = db.prepare(`INSERT INTO college_plan (college_id, research_version, research_id, in_plan, status_final, targeted, hold_reason, priority_score, rank, p_level,
      target_min, target_avg, target_max, ambassadors, college_leads, payload, raw, source_file, imported_at, imported_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
    const insB = db.prepare(`INSERT INTO college_plan_branches (college_id, research_version, seq, name, is_it, intake_latest, intake_latest_year, intake_latest_basis,
      intake_2023_24, basis, confidence, source, notes, counted, final_decision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
    for (const p of planned) {
      const y = p.payload;
      insP.run(p.cid, version, p.rid, y.in_plan ? 1 : 0, y.status_final, y.targeted ? 1 : 0, y.hold_reason, y.priority_score ?? null, y.rank ?? null, y.p_level ?? null,
        y.research_target?.min ?? null, y.research_target?.avg ?? null, y.research_target?.max ?? null, y.ambassadors_research ?? null, y.college_leads_research ?? null,
        JSON.stringify(y), JSON.stringify(p.r), COLLEGES_CSV, at, ACTOR);
      for (const b of p.brs) insB.run(p.cid, version, b.seq, b.name, b.is_it ? 1 : 0, b.intake_latest, b.intake_latest_year, b.intake_latest_basis, b.intake_2023_24, b.basis, b.confidence, b.source, b.notes, b.counted ? 1 : 0, b.final_decision);
    }
    writeAudit(db, ACTOR, s.plan.insert && !existing.size ? 'create' : 'update', 'college_plan', version, existing.size ? { rows: existing.size } : null,
      { rows: planned.length, in_plan: s.in_plan, targeted: s.targeted, totals: s.totals, insert: s.plan.insert, update: s.plan.update, delete: s.plan.delete });
  });
  for (const n of s.new_colleges) { n.contacts = insertNewCollegeContacts(db, n.college_id, n.row, log); delete n.row; }
  log(`  written: ${planned.length} college_plan rows, ${s.branches.rows} college_plan_branches rows`);
  return stats;
}

// ------------------------------------------------------------------------------------------------ CLI
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const args = process.argv.slice(2);
  const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
  if (args.includes('--help') || args.includes('-h')) {
    console.log('Usage: node server/import_research.js [--dry-run] [--csv-dir <dir>] [--db <file>]');
    process.exit(0);
  }
  try {
    const db = openDb(opt('--db') || process.env.DB_PATH || undefined);
    importResearch(db, { csvDir: opt('--csv-dir') || DEFAULT_CSV_DIR, dryRun: args.includes('--dry-run') });
    db.close();
  } catch (e) {
    console.error(`Import failed: ${e.message}`);
    process.exit(1);
  }
}
