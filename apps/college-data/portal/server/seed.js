// Seed loader (idempotent). Usage:
//   node server/seed.js               load reference data (districts, cities, colleges, branches, exams, settings)
//   node server/seed.js --demo        same, then (re)write clearly flagged is_demo=1 QA data for 6 colleges
//   node server/seed.js --clear-demo  delete all is_demo=1 rows
// Reference seeding NEVER touches people, enrollments, targets, activities, followups, courses or audit_log.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openDb, tx, today, nowIso, slugify, getSettings, deriveBranch, RELEVANT_CATEGORIES, PORTAL_ROOT, normPhone, normEmail } from './db.js';

const SEED_DIR = path.join(PORTAL_ROOT, 'data', 'seed');
const SEED_ACTOR = 'seed';

// ---------------------------------------------------------------------------------------------
// Districts: the 26 fixed ids. HQ coordinates are APPROXIMATE public facts (district headquarters
// town centres, ~0.01 deg), used only as a fallback pin / map focus. Not survey-grade.
// ---------------------------------------------------------------------------------------------
export const DISTRICTS = [
  // id, display name, old (pre-2022) district, HQ lat, HQ lng (approx.)
  ['srikakulam', 'Srikakulam', 'Srikakulam', 18.2969, 83.8973],
  ['vizianagaram', 'Vizianagaram', 'Vizianagaram', 18.1067, 83.3956],
  ['parvathipuram-manyam', 'Parvathipuram Manyam', 'Vizianagaram/Srikakulam', 18.7833, 83.4256],
  ['alluri-sitharama-raju', 'Alluri Sitharama Raju', 'Visakhapatnam/East Godavari', 18.0667, 82.6667], // HQ Paderu
  ['visakhapatnam', 'Visakhapatnam', 'Visakhapatnam', 17.6868, 83.2185],
  ['anakapalli', 'Anakapalli', 'Visakhapatnam', 17.6913, 83.0039],
  ['kakinada', 'Kakinada', 'East Godavari', 16.9891, 82.2475],
  ['east-godavari', 'East Godavari', 'East Godavari', 17.0005, 81.8040], // HQ Rajamahendravaram
  ['konaseema', 'Dr. B.R. Ambedkar Konaseema', 'East Godavari', 16.5787, 82.0061], // HQ Amalapuram
  ['eluru', 'Eluru', 'West Godavari/Krishna', 16.7107, 81.0952],
  ['west-godavari', 'West Godavari', 'West Godavari', 16.5449, 81.5212], // HQ Bhimavaram
  ['ntr', 'NTR', 'Krishna', 16.5062, 80.6480], // HQ Vijayawada
  ['krishna', 'Krishna', 'Krishna', 16.1875, 81.1389], // HQ Machilipatnam
  ['palnadu', 'Palnadu', 'Guntur', 16.2350, 80.0480], // HQ Narasaraopet
  ['guntur', 'Guntur', 'Guntur', 16.3067, 80.4365],
  ['bapatla', 'Bapatla', 'Guntur/Prakasam', 15.9044, 80.4675],
  ['prakasam', 'Prakasam', 'Prakasam', 15.5057, 80.0499], // HQ Ongole
  ['nellore', 'Sri Potti Sriramulu Nellore', 'Nellore', 14.4426, 79.9865],
  ['kurnool', 'Kurnool', 'Kurnool', 15.8281, 78.0373],
  ['nandyal', 'Nandyal', 'Kurnool', 15.4786, 78.4836],
  ['anantapur', 'Anantapur', 'Anantapur', 14.6819, 77.6006],
  ['sri-sathya-sai', 'Sri Sathya Sai', 'Anantapur', 14.1652, 77.8117], // HQ Puttaparthi
  ['kadapa', 'YSR Kadapa', 'Kadapa', 14.4673, 78.8242],
  ['annamayya', 'Annamayya', 'Kadapa/Chittoor', 14.0573, 78.7517], // HQ Rayachoti
  ['tirupati', 'Tirupati', 'Chittoor/Nellore', 13.6288, 79.4192],
  ['chittoor', 'Chittoor', 'Chittoor', 13.2172, 79.1003],
];
const DISTRICT_IDS = new Set(DISTRICTS.map((d) => d[0]));

// Districts created after the 2022 reorganisation that may appear in geo seed files (added only when a
// geo row uses the id). HQ coordinates are APPROXIMATE public facts, as above.
const KNOWN_EXTRA_DISTRICTS = {
  polavaram: ['Polavaram', 'Alluri Sitharama Raju/Eluru', 17.4430, 81.7750], // HQ Rampachodavaram (approx.)
  markapuram: ['Markapuram', 'Prakasam', 15.7350, 79.2700], // HQ Markapur (approx.)
  madanapalle: ['Madanapalle', 'Annamayya', 13.5500, 78.5000], // HQ Madanapalle (approx.)
};

// Master "district" / "old_district" text -> district id
const DISTRICT_ALIASES = {
  'krishna (vijayawada)': 'ntr',
  vijayawada: 'ntr',
  'dr. b.r. ambedkar konaseema': 'konaseema',
  'ysr kadapa': 'kadapa',
  'sri potti sriramulu nellore': 'nellore',
  anantapuramu: 'anantapur',
  rajahmundry: 'east-godavari',
  rajamahendravaram: 'east-godavari',
};

export function districtIdFromText(text) {
  if (!text) return null;
  const t = String(text).replace(/\?/g, '').trim().toLowerCase();
  if (!t) return null;
  if (DISTRICT_ALIASES[t]) return DISTRICT_ALIASES[t];
  const s = slugify(t);
  return DISTRICT_IDS.has(s) ? s : null;
}

const CITY_ALIASES = { rajahmundry: "Rajamahendravaram", palakol: "Palakollu", narsapur: "Narsapuram" };

function cleanPlace(s) {
  if (!s) return null;
  let t = String(s)
    .replace(/\([^)]*\)/g, ' ')
    .replace(/\?/g, ' ')
    .replace(/\bnear\b/gi, ' ')
    .replace(/\b(mdl|mandal|area|rural|urban)\b\.?/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!t || /unknown/i.test(s)) return null;
  return CITY_ALIASES[t.toLowerCase()] || t;
}

/**
 * Parse the master `town` text into {city, districtHint}.
 *  - possibly_closed rows look like "Place[, Mandal] / District" (last "/" segment is the district).
 *  - active rows look like "Village, Mandal mdl" or "A / B" (alternatives) — the hub town is the last
 *    comma segment (mandal/town), first "/" alternative.
 */
export function parseTown(town, hasDistrictField) {
  if (!town) return { city: null, districtHint: null };
  let text = String(town);
  let districtHint = null;
  if (!hasDistrictField && text.includes('/')) {
    const parts = text.split('/').map((p) => p.trim());
    districtHint = parts.pop();
    text = parts.join(' / ');
  }
  if (/unknown/i.test(text)) return { city: null, districtHint };
  const commaParts = text.split(',').map((p) => p.trim()).filter(Boolean);
  let hub = commaParts.length > 1 ? commaParts[commaParts.length - 1] : commaParts[0] || '';
  hub = hub.split('/')[0];
  return { city: cleanPlace(hub), districtHint };
}

function readJson(file) {
  const p = path.join(SEED_DIR, file);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (e) {
    console.warn(`! ${file}: could not parse (${e.message}); skipping`);
    return null;
  }
}

/** Accept an array, {colleges|rows|items|data:[...]}, or an object keyed by sno. */
function asRows(json) {
  if (!json) return [];
  if (Array.isArray(json)) return json;
  for (const k of ['colleges', 'rows', 'items', 'data', 'branches']) if (Array.isArray(json[k])) return json[k];
  return Object.entries(json)
    .filter(([, v]) => v && typeof v === 'object' && !Array.isArray(v))
    .map(([k, v]) => ({ sno: v.sno ?? (Number(k.replace(/^c/, '')) || undefined), ...v }));
}

const pick = (o, ...keys) => {
  for (const k of keys) if (o && o[k] !== undefined && o[k] !== null && o[k] !== '') return o[k];
  return null;
};
const num = (v) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v));
const yesNo = (v) => {
  if (v == null) return null;
  const t = String(v).toLowerCase();
  if (t.startsWith('y') || t === 'true') return 'yes';
  if (t.startsWith('n') || t === 'false') return 'no';
  return 'unknown';
};
const dash = (v) => (v == null || ['—', '-', ''].includes(String(v).trim()) ? null : v);

/** Fields a non-seed user changed on an entity, from audit_log update rows. Read-only use of audit. */
function editedFields(db, entity, id) {
  const fields = new Set();
  const rows = db.prepare("SELECT before, after FROM audit_log WHERE entity = ? AND entity_id = ? AND action IN ('update','create') AND actor <> 'seed'").all(entity, String(id));
  for (const r of rows) {
    let b = {}; let a = {};
    try { b = JSON.parse(r.before || '{}') || {}; a = JSON.parse(r.after || '{}') || {}; } catch { /* ignore */ }
    for (const k of Object.keys(a)) if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) fields.add(k);
  }
  return fields;
}

/** Upsert keeping user-edited fields. Returns 'insert' | 'update' | 'same'. */
function upsertKeepingEdits(db, table, entity, keyCols, row, existing) {
  if (!existing) {
    const cols = Object.keys(row);
    db.prepare(`INSERT INTO ${table} (${cols.join(',')}) VALUES (${cols.map(() => '?').join(',')})`)
      .run(...cols.map((c) => row[c]));
    return 'insert';
  }
  const userEdited = existing.updated_by && existing.updated_by !== SEED_ACTOR;
  let keep = new Set();
  if (userEdited) {
    keep = editedFields(db, entity, existing.id);
    if (keep.size === 0) {
      // edited outside the API (no audit trail): be conservative and keep every non-null value
      for (const [k, v] of Object.entries(existing)) if (v !== null) keep.add(k);
    }
  }
  const sets = [];
  const vals = [];
  for (const [k, v] of Object.entries(row)) {
    if (keyCols.includes(k) || k === 'updated_at' || k === 'updated_by') continue;
    if (keep.has(k)) continue;
    if (JSON.stringify(existing[k] ?? null) !== JSON.stringify(v ?? null)) { sets.push(`${k} = ?`); vals.push(v); }
  }
  if (!sets.length) return 'same';
  sets.push('updated_at = ?'); vals.push(row.updated_at);
  if (!userEdited) { sets.push('updated_by = ?'); vals.push(SEED_ACTOR); }
  const where = keyCols.map((k) => `${k} = ?`).join(' AND ');
  db.prepare(`UPDATE ${table} SET ${sets.join(', ')} WHERE ${where}`).run(...vals, ...keyCols.map((k) => existing[k]));
  return 'update';
}

function normBasis(v, fallback) {
  const t = v == null ? '' : String(v).toLowerCase();
  if (t.startsWith('verif')) return 'verified';
  if (t.startsWith('estim')) return 'estimated';
  if (t.startsWith('pend')) return 'pending';
  return fallback;
}

export function normCategory(v, code, name) {
  const t = v == null ? '' : String(v).toLowerCase().replace(/[\s-]+/g, '_');
  if (['it_core', 'it_allied', 'circuit', 'core', 'other'].includes(t)) return t;
  // heuristic fallback from code/name when the data agent didn't classify
  const s = `${code || ''} ${name || ''}`.toUpperCase();
  if (/\b(CSE|CS|IT|COMPUTER SCIENCE|INFORMATION TECHNOLOGY)\b/.test(s) && !/\b(AI|ML|DS|DATA|CYBER|IOT|BLOCK)/.test(s)) return 'it_core';
  if (/(AI|ML|DATA SCIENCE|\bDS\b|CYBER|IOT|BLOCKCHAIN|CSM|CSD|CSO|CSC|AIDS|AIML|CSBS|COMPUTER)/.test(s)) return 'it_allied';
  if (/\b(ECE|EEE|EIE|ECM|ELECTRONICS|ELECTRICAL|VLSI)\b/.test(s)) return 'circuit';
  if (/\b(MECH|ME|CIVIL|CE|CHEM|CHE|MINING|AUTO|AERO|AGRI|BIOTECH|PETRO|METALL)/.test(s)) return 'core';
  return 'other';
}

// ---------------------------------------------------------------------------------------------
// Contacts (optional data/seed/contacts.json and/or contacts_*.json, supplied by the research team; never invented here).
// Each row: {college_id ("c94" or S.No 94) | college_sno, role, name, phone, email, source_url, basis, notes, website?, branch_code?};
// other fields (college_name, confidence, ...) are ignored. Rows without a valid phone or email are skipped.
// Idempotent: matched to an existing contact of the same college by normalised phone, then email. Rows edited by
// a user keep the fields that user changed (audit-based, like colleges). Status is never seeded: it comes from calls.
// ---------------------------------------------------------------------------------------------
const CONTACT_ROLE_SET = new Set(['tpo', 'principal', 'hod', 'office', 'admissions', 'dean', 'other']);
/** college_id may be "c94", 94 or "94"; college_sno / sno are accepted too. */
function contactCollegeId(r) {
  const raw = r.college_id ?? r.college_sno ?? r.sno;
  if (raw == null || raw === '') return null;
  const s = String(raw).trim();
  if (/^c\d+$/i.test(s)) return s.toLowerCase();
  if (/^\d+$/.test(s)) return `c${Number(s)}`;
  return s;
}
/** Contact files: data/seed/contacts.json plus any data/seed/contacts_*.json (each an array of rows). */
function contactSeedRows() {
  if (!fs.existsSync(SEED_DIR)) return null;
  const files = fs.readdirSync(SEED_DIR).filter((f) => f === 'contacts.json' || /^contacts_.+\.json$/i.test(f)).sort();
  if (!files.length) return null;
  return files.flatMap((f) => asRows(readJson(f)).map((r) => ({ ...r, _file: f })));
}
export function seedContacts(db, { log = console.log, rows: given } = {}) {
  const stats = { insert: 0, update: 0, same: 0, skipped: 0, duplicate_in_files: 0, websites_filled: 0 };
  const given0 = given || contactSeedRows();
  if (!given0) return { ...stats, file: false };
  // a row listing several numbers ("0866-2469679 / +91 7013293572") becomes one contact per valid number; the email,
  // and the full text as listed, stay on the first
  const rows = given0.flatMap((r) => {
    const parts = r.phone == null ? [] : String(r.phone).split(/[/,;&]|\bor\b|-\s+-/i).map((x) => x.trim()).filter(Boolean);
    const ok = parts.filter((x) => normPhone(x));
    if (ok.length <= 1) return [r];
    return ok.map((x, j) => (j === 0 ? { ...r, phone: x, _listed: r.phone } : { ...r, phone: x, email: null, _listed: r.phone, _extra: true }));
  });
  const at = nowIso();
  tx(db, () => {
    const colleges = new Map(db.prepare('SELECT id, website FROM colleges').all().map((r) => [r.id, r]));
    const byPhone = db.prepare('SELECT * FROM contacts WHERE college_id = ? AND phone = ?');
    const byEmail = db.prepare('SELECT * FROM contacts WHERE college_id = ? AND email = ?');
    const touched = new Set(); // contacts already written in this run: a later row for the same number is a duplicate
    rows.forEach((r, i) => {
      const where = `${r._file || 'contacts'} row ${i + 1}`;
      const cid = contactCollegeId(r);
      const skip = (why) => { stats.skipped++; log(`  ! ${where}: ${why}; skipped`); };
      if (!cid || !colleges.has(cid)) return skip(`unknown college ${cid ?? '(none)'}`);
      const rawPhone = r.phone == null ? '' : String(r.phone).trim();
      const rawEmail = r.email == null ? '' : String(r.email).trim();
      const phone = rawPhone ? normPhone(rawPhone) : null;
      const email = rawEmail ? normEmail(rawEmail.split(/[\s,;/]+/)[0]) : null;
      if (!phone && !email) return skip(rawPhone || rawEmail ? `no valid phone or email ("${rawPhone || rawEmail}")` : 'no phone or email');
      // keep what normalisation dropped (second number, extension, invalid text) in the notes, so nothing is lost
      const extra = [];
      if (r._listed) extra.push(`Phone as listed: ${r._listed}`);
      else if (rawPhone && (!phone || /[/,;]|ext|x\s*\d/i.test(rawPhone))) extra.push(`Phone as listed: ${rawPhone}`);
      if (rawEmail && (!email || /[\s,;/]/.test(rawEmail))) extra.push(`Email as listed: ${rawEmail}`);
      const notes = [r.notes ? String(r.notes).trim() : null, ...extra].filter(Boolean).join(' · ') || null;
      let branchId = null;
      if (r.branch_code) branchId = db.prepare('SELECT id FROM branches WHERE college_id = ? AND upper(code) = upper(?)').get(cid, String(r.branch_code))?.id ?? null;
      const role = CONTACT_ROLE_SET.has(String(r.role || '').toLowerCase()) ? String(r.role).toLowerCase() : 'other';
      const basis = String(r.basis || '').toLowerCase().startsWith('verif') ? 'verified' : 'pending';
      const existing = (phone && byPhone.get(cid, phone)) || (email && byEmail.get(cid, email)) || null;
      if (existing && touched.has(existing.id)) { stats.duplicate_in_files++; log(`  · ${where}: same number/email as an earlier row for ${cid}; kept the first`); return; }
      const row = { college_id: cid, branch_id: branchId, name: dash(r.name) ?? null, role, phone, email, source_url: r.source_url ?? null, basis, notes, updated_at: at, updated_by: SEED_ACTOR };
      let id;
      if (!existing) {
        // a second identity field may already belong to another contact of this college (e.g. shared office email)
        if (phone && email && byEmail.get(cid, email)) row.email = null;
        stats[upsertKeepingEdits(db, 'contacts', 'contact', ['id'], { ...row, created_at: at, created_by: SEED_ACTOR }, null)]++;
        id = Number(db.prepare('SELECT id FROM contacts WHERE college_id = ? AND (phone IS ? AND email IS ?)').get(cid, row.phone, row.email)?.id);
      } else {
        // identity fields are only filled in, never swapped; values the file leaves out are kept
        if (existing.phone || !row.phone) delete row.phone;
        if (existing.email || !row.email || (row.email && byEmail.get(cid, row.email))) delete row.email;
        for (const k of ['name', 'source_url', 'notes']) if (row[k] == null) delete row[k];
        if (row.branch_id == null) delete row.branch_id;
        stats[upsertKeepingEdits(db, 'contacts', 'contact', ['id'], row, { ...existing })]++;
        id = existing.id;
      }
      if (id) touched.add(id);
      // the college website is filled in only when the college has none (never overwritten)
      const site = r.website ? String(r.website).trim() : '';
      const col = colleges.get(cid);
      if (site && /^https?:\/\//i.test(site) && !col.website) {
        db.prepare("UPDATE colleges SET website = ?, updated_at = ?, updated_by = CASE WHEN updated_by IS NULL OR updated_by = 'seed' THEN 'seed' ELSE updated_by END WHERE id = ? AND (website IS NULL OR website = '')").run(site, at, cid);
        col.website = site; stats.websites_filled++;
      }
    });
  });
  return { ...stats, file: true };
}

export function seedReference(db, { log = console.log } = {}) {
  const at = nowIso();
  const master = asRows(readJson('master_colleges.json'));
  if (!master.length) throw new Error('data/seed/master_colleges.json missing or empty');
  const geoRows = [...asRows(readJson('geo_a.json')), ...asRows(readJson('geo_b.json'))];
  const geoBySno = new Map();
  for (const g of geoRows) {
    const sno = num(pick(g, 'sno', 'S.No', 's_no'));
    if (sno != null) geoBySno.set(sno, { ...(geoBySno.get(sno) || {}), ...g });
  }
  const branchesJson = readJson('branches.json');
  const branchRows = asRows(branchesJson);
  const exams = asRows(readJson('exams.json'));
  const settings = getSettings(db);
  const factors = settings.relevance_factors;
  const stats = { districts: 0, cities: 0, colleges: { insert: 0, update: 0, same: 0 }, branches: { insert: 0, update: 0, same: 0 }, exams: { insert: 0, update: 0, same: 0 }, geo_rows: geoBySno.size };

  tx(db, () => {
    // --- districts -------------------------------------------------------------------------
    const extraDistricts = new Set();
    for (const g of geoBySno.values()) {
      const d = pick(g, 'district_id');
      if (d && !DISTRICT_IDS.has(d)) extraDistricts.add(String(d));
    }
    const upD = db.prepare(`INSERT INTO districts(id, name, old_district, hq_lat, hq_lng, targeted, updated_at, updated_by)
      VALUES (?,?,?,?,?,0,?,?) ON CONFLICT(id) DO UPDATE SET
        name = CASE WHEN districts.updated_by IS NULL OR districts.updated_by = 'seed' THEN excluded.name ELSE districts.name END,
        old_district = COALESCE(districts.old_district, excluded.old_district),
        hq_lat = COALESCE(districts.hq_lat, excluded.hq_lat),
        hq_lng = COALESCE(districts.hq_lng, excluded.hq_lng)`);
    for (const [id, name, old, lat, lng] of DISTRICTS) { upD.run(id, name, old, lat, lng, at, SEED_ACTOR); stats.districts++; }
    for (const id of extraDistricts) {
      const g = [...geoBySno.values()].find((x) => x.district_id === id);
      const known = KNOWN_EXTRA_DISTRICTS[id] || [];
      const name = pick(g, 'district_name') || known[0] || id.split('-').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ');
      upD.run(id, name, known[1] ?? null, known[2] ?? null, known[3] ?? null, at, SEED_ACTOR);
      DISTRICT_IDS.add(id);
      stats.districts++;
      log(`  + extra district from geo data: ${id}`);
    }
    const hq = new Map(db.prepare('SELECT id, hq_lat, hq_lng FROM districts').all().map((d) => [d.id, d]));

    // --- colleges (+ cities) -----------------------------------------------------------------
    const cityAcc = new Map(); // id -> {district_id, name, lat, lng, pts:[]}
    const existingColleges = new Map(db.prepare('SELECT * FROM colleges').all().map((c) => [c.sno, c]));
    const collegeRows = [];
    for (const m of master) {
      const sno = num(m.sno);
      if (sno == null) continue;
      const g = geoBySno.get(sno) || null;
      const hasDistrict = !!m.district;
      const parsed = parseTown(m.town, hasDistrict);
      let districtId = (g && pick(g, 'district_id')) || districtIdFromText(m.district) || districtIdFromText(parsed.districtHint) || districtIdFromText(m.old_district);
      if (districtId && !DISTRICT_IDS.has(districtId)) districtId = null;
      const cityName = (g && pick(g, 'city', 'city_name', 'town')) || parsed.city;
      let cityId = (g && pick(g, 'city_id')) || null;
      if (!cityId && cityName && districtId) cityId = `${districtId}--${slugify(cityName)}`;
      if (cityId && districtId) {
        const acc = cityAcc.get(cityId) || { id: cityId, district_id: districtId, name: cityName || cityId.split('--')[1], lat: null, lng: null, pts: [] };
        const clat = num(pick(g, 'city_lat')); const clng = num(pick(g, 'city_lng'));
        if (clat != null && clng != null) { acc.lat = clat; acc.lng = clng; }
        cityAcc.set(cityId, acc);
      }
      let lat = num(pick(g, 'lat', 'latitude')); let lng = num(pick(g, 'lng', 'lon', 'longitude'));
      let precision = pick(g, 'geo_precision', 'precision');
      let geoSource = pick(g, 'geo_source', 'source');
      if (!['exact', 'town', 'district', 'pending'].includes(precision)) precision = lat != null && lng != null ? 'town' : 'pending';
      if ((lat == null || lng == null) && districtId && hq.get(districtId)?.hq_lat != null) {
        lat = hq.get(districtId).hq_lat; lng = hq.get(districtId).hq_lng;
        precision = 'district'; geoSource = 'district HQ (approx.) — geo pending';
      }
      if (lat == null || lng == null) { lat = null; lng = null; precision = 'pending'; }
      if (cityId && (precision === 'exact' || precision === 'town')) cityAcc.get(cityId)?.pts.push([lat, lng]);

      let op = pick(g, 'op_status');
      if (!['operational', 'possibly_closed', 'closed', 'pending'].includes(op)) {
        op = m.master_status === 'possibly_closed' ? 'possibly_closed' : m.master_status === 'active' ? 'operational' : 'pending';
      }
      let aliases = pick(g, 'aliases');
      if (aliases != null && !Array.isArray(aliases)) aliases = String(aliases).split(/\s*[;|]\s*/);
      const official = pick(g, 'official_name');
      if (official && official.trim().toLowerCase() !== String(m.name).trim().toLowerCase()) aliases = [...(aliases || []), official];
      const row = {
        id: `c${sno}`, sno,
        name: m.name, // master list is the canonical name; geo may add short_name/aliases
        short_name: pick(g, 'short_name'),
        aliases: aliases == null ? null : JSON.stringify([...new Set(aliases.filter(Boolean))]),
        district_id: districtId, city_id: cityId,
        address: pick(g, 'address') ?? (m.town || null),
        lat, lng, geo_precision: precision, geo_source: geoSource,
        website: pick(g, 'website', 'url'), phone: pick(g, 'phone'), email: pick(g, 'email'),
        contact_source: pick(g, 'contact_source'),
        ownership: dash(m.ownership) ?? pick(g, 'ownership'), autonomous: dash(m.autonomous) ?? pick(g, 'autonomous'),
        affiliation: pick(g, 'affiliation') ?? null,
        naac: dash(m.naac), nirf: dash(m.nirf), tier: dash(m.tier),
        op_status: op,
        op_status_note: pick(g, 'op_status_note') ?? (m.master_status === 'possibly_closed' ? (m.note || 'Listed as possibly closed in master list') : null),
        op_status_source: pick(g, 'op_status_source') ?? (g ? null : 'master list'),
        op_2025_26: yesNo(pick(g, 'op_2025_26')), op_2026_27: yesNo(pick(g, 'op_2026_27')),
        targeted: op === 'operational' ? 1 : 0,
        notes: [m.tier_basis ? `Tier basis: ${m.tier_basis}` : null, m.eapcet_code && dash(m.eapcet_code) ? `EAPCET: ${m.eapcet_code}` : null,
          m.nba && dash(m.nba) ? `NBA: ${m.nba}` : null, m.note && m.master_status !== 'possibly_closed' ? m.note : null,
          m.last_code && dash(m.last_code) ? `Last code: ${m.last_code}` : null, pick(g, 'notes')].filter(Boolean).join(' | ') || null,
        updated_at: at, updated_by: SEED_ACTOR,
      };
      if (row.website == null) delete row.website; // never blank a website the geo files do not supply (contacts files may fill it)
      collegeRows.push(row);
    }

    // cities first (FK), with coordinates from geo city_lat/lng or the mean of town/exact college pins
    const upC = db.prepare(`INSERT INTO cities(id, district_id, name, lat, lng) VALUES (?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET district_id = excluded.district_id, name = excluded.name,
        lat = COALESCE(excluded.lat, cities.lat), lng = COALESCE(excluded.lng, cities.lng)`);
    for (const c of cityAcc.values()) {
      let { lat, lng } = c;
      if ((lat == null || lng == null) && c.pts.length) {
        lat = +(c.pts.reduce((s, p) => s + p[0], 0) / c.pts.length).toFixed(5);
        lng = +(c.pts.reduce((s, p) => s + p[1], 0) / c.pts.length).toFixed(5);
      }
      upC.run(c.id, c.district_id, c.name, lat, lng);
      stats.cities++;
    }

    for (const row of collegeRows) {
      const r = upsertKeepingEdits(db, 'colleges', 'college', ['id'], row, existingColleges.get(row.sno));
      stats.colleges[r]++;
    }

    // prune seed cities that nothing references any more (e.g. after geo data refined a town)
    db.prepare(`DELETE FROM cities WHERE id NOT IN (SELECT city_id FROM colleges WHERE city_id IS NOT NULL)
      AND id NOT IN (SELECT scope_id FROM targets WHERE scope_type = 'city')`).run();

    // district targeted flag: any targeted college, unless a user edited it
    db.prepare(`UPDATE districts SET targeted = CASE WHEN EXISTS (SELECT 1 FROM colleges c WHERE c.district_id = districts.id AND c.targeted = 1) THEN 1 ELSE 0 END
      WHERE updated_by IS NULL OR updated_by = 'seed'`).run();

    // --- branches ------------------------------------------------------------------------------
    const collegeIds = new Set(db.prepare('SELECT id FROM colleges').all().map((r) => r.id));
    const flat = [];
    const listed = new Set(); // colleges branches.json lists, even with an empty branch list
    for (const entry of branchRows) {
      const sno = num(pick(entry, 'sno'));
      const cid = pick(entry, 'college_id') || (sno != null ? `c${sno}` : null);
      if (!cid || !collegeIds.has(cid)) continue;
      if (Array.isArray(entry.branches)) {
        listed.add(cid);
        for (const b of entry.branches) flat.push({ cid, b });
        const ti = num(entry.total_intake);
        if (ti != null) {
          const ex = db.prepare('SELECT * FROM colleges WHERE id = ?').get(cid);
          upsertKeepingEdits(db, 'colleges', 'college', ['id'], { total_intake: ti, total_intake_source: entry.total_intake_source ?? null, updated_at: at }, ex);
        }
      } else if (entry.code || entry.name) {
        flat.push({ cid, b: entry });
      }
    }
    // Branch identity is (college_id, code). Source codes are not always unique (e.g. several "OTHER"
    // programmes in one college): exact duplicates (same code + name) are merged, preferring the entry
    // with a known intake; same code with different names gets a stable suffix from the name.
    const byCollege = new Map();
    for (const f of flat) { const a = byCollege.get(f.cid) || []; a.push(f); byCollege.set(f.cid, a); }
    const unique = [];
    for (const [cid, list] of byCollege) {
      const named = list.map(({ b }) => {
        const name = pick(b, 'name', 'branch_name', 'branch');
        return { b, name, code: String(pick(b, 'code', 'branch_code') || slugify(name).toUpperCase() || '').trim() };
      }).filter((x) => x.code);
      const namesPerCode = new Map();
      for (const x of named) { const s = namesPerCode.get(x.code) || new Set(); s.add(String(x.name || '').toLowerCase()); namesPerCode.set(x.code, s); }
      const merged = new Map();
      for (const x of named) {
        const code = namesPerCode.get(x.code).size > 1 ? `${x.code}-${slugify(x.name).toUpperCase()}`.slice(0, 60) : x.code;
        const prev = merged.get(code);
        if (!prev || (num(pick(prev.b, 'intake_per_year', 'intake')) == null && num(pick(x.b, 'intake_per_year', 'intake')) != null)) merged.set(code, { ...x, code });
      }
      for (const x of merged.values()) unique.push({ cid, b: x.b, name: x.name, code: x.code });
    }
    const seenBranches = new Set();
    const findBranch = db.prepare('SELECT * FROM branches WHERE college_id = ? AND code = ?');
    for (const { cid, b, name, code } of unique) {
      seenBranches.add(`${cid}|${code}`);
      const category = normCategory(pick(b, 'category'), code, name);
      const intake = num(pick(b, 'intake_per_year', 'intake', 'sanctioned_intake'));
      const src = pick(b, 'intake_source', 'source');
      let row = {
        college_id: cid, code, name: name || code, category,
        is_relevant: RELEVANT_CATEGORIES.has(category) ? 1 : 0,
        intake_per_year: intake,
        intake_basis: intake == null ? 'pending' : normBasis(pick(b, 'intake_basis', 'basis'), src ? 'verified' : 'estimated'),
        intake_source: src, intake_year: pick(b, 'intake_year', 'year') == null ? null : String(pick(b, 'intake_year', 'year')),
        intake_2023_24: num(pick(b, 'intake_2023_24')),
        strength_total: null, strength_basis: 'pending', final_year: null, final_year_basis: 'pending',
        eligible_estimate: null, eligible_basis: 'pending',
        notes: pick(b, 'notes', 'note'),
        updated_at: at, updated_by: SEED_ACTOR,
      };
      const existing = findBranch.get(cid, code);
      if (existing && existing.updated_by && existing.updated_by !== SEED_ACTOR) {
        // keep the user's verified figures when re-deriving
        const keep = editedFields(db, 'branch', existing.id);
        for (const k of keep) if (k in row) row[k] = existing[k];
      }
      row = deriveBranch(row, factors);
      stats.branches[upsertKeepingEdits(db, 'branches', 'branch', ['college_id', 'code'], row, existing)]++;
    }
    // Prune seed-created branches that vanished from branches.json for a college it covers, but only
    // when nothing references them (people, enrollments, activities, targets, follow-ups) and no user edited them.
    stats.branches.pruned = 0;
    const covered = new Set([...byCollege.keys(), ...listed]);
    const refd = db.prepare(`SELECT
      EXISTS(SELECT 1 FROM person_branches WHERE branch_id = ?1) OR EXISTS(SELECT 1 FROM enrollments WHERE branch_id = ?1)
      OR EXISTS(SELECT 1 FROM activities WHERE branch_id = ?1)
      OR EXISTS(SELECT 1 FROM targets WHERE scope_type = 'branch' AND scope_id = CAST(?1 AS TEXT))
      OR EXISTS(SELECT 1 FROM followups WHERE scope_type = 'branch' AND scope_id = CAST(?1 AS TEXT)) AS r`);
    for (const br of db.prepare("SELECT id, college_id, code FROM branches WHERE updated_by = 'seed' AND is_demo = 0").all()) {
      if (!covered.has(br.college_id) || seenBranches.has(`${br.college_id}|${br.code}`)) continue;
      if (refd.get(br.id).r) continue;
      db.prepare('DELETE FROM branches WHERE id = ?').run(br.id);
      stats.branches.pruned++;
    }

    // --- exams (by sno + semester) -------------------------------------------------------------
    const findExam = db.prepare('SELECT * FROM exams WHERE college_id = ? AND semester = ? ORDER BY id LIMIT 1');
    for (const e of exams) {
      const sno = num(e.sno);
      const cid = sno != null ? `c${sno}` : e.college_id;
      if (!cid || !collegeIds.has(cid) || !['3-1', '4-1'].includes(e.semester)) continue;
      const row = {
        college_id: cid, semester: e.semester, exam_body: e.exam_body ?? null, status: e.status ?? null,
        endsem_start: e.endsem_start ?? null, endsem_end: e.endsem_end ?? null, mid_window: e.mid_window ?? null,
        lab_window: e.lab_window ?? null, evidence: e.evidence ?? null, confidence: e.confidence ?? null,
        source_url: e.source_url ?? null, notice_date: e.notice_date ?? null, verified_on: e.verified_on ?? null,
        notes: e.notes ?? null, updated_at: at, updated_by: SEED_ACTOR,
      };
      stats.exams[upsertKeepingEdits(db, 'exams', 'exam', ['id'], row, findExam.get(cid, e.semester))]++;
    }
  });
  stats.contacts = seedContacts(db, { log });
  return stats;
}

// ---------------------------------------------------------------------------------------------
// Demo data (QA only). Every row is is_demo=1 and names start with "DEMO".
// ---------------------------------------------------------------------------------------------
export function clearDemo(db) {
  return tx(db, () => {
    const n = {};
    db.prepare('DELETE FROM person_branches WHERE person_id IN (SELECT id FROM people WHERE is_demo = 1) OR branch_id IN (SELECT id FROM branches WHERE is_demo = 1)').run();
    n.calls = Number(db.prepare('DELETE FROM calls WHERE is_demo = 1').run().changes);
    n.contacts = Number(db.prepare('DELETE FROM contacts WHERE is_demo = 1 AND id NOT IN (SELECT contact_id FROM calls WHERE contact_id IS NOT NULL)').run().changes);
    for (const t of ['enrollments', 'activities', 'followups', 'targets']) n[t] = Number(db.prepare(`DELETE FROM ${t} WHERE is_demo = 1`).run().changes);
    db.prepare('UPDATE people SET reports_to = NULL WHERE is_demo = 1').run();
    n.people = Number(db.prepare('DELETE FROM people WHERE is_demo = 1').run().changes);
    n.courses = Number(db.prepare('DELETE FROM courses WHERE is_demo = 1').run().changes);
    n.branches = Number(db.prepare('DELETE FROM branches WHERE is_demo = 1').run().changes);
    return n;
  });
}

function addDays(iso, d) {
  const t = new Date(`${iso}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + d);
  return t.toISOString().slice(0, 10);
}

export function seedDemo(db) {
  clearDemo(db);
  const T = today();
  const startAt = `${addDays(T, -30)}T09:00:00.000Z`;
  const factors = getSettings(db).relevance_factors;
  return tx(db, () => {
    const course = db.prepare("INSERT INTO courses(name, price_inr, active, notes, is_demo) VALUES ('DEMO Full-Stack Bootcamp', 15000, 1, 'DEMO DATA — QA only', 1)").run();
    const courseId = Number(course.lastInsertRowid);
    const picks = db.prepare("SELECT id FROM colleges WHERE id = 'c6' UNION ALL SELECT id FROM (SELECT id FROM colleges WHERE targeted = 1 AND id <> 'c6' ORDER BY sno LIMIT 5)").all().map((r) => r.id);
    const insP = db.prepare("INSERT INTO people(college_id, role, full_name, phone, email, reports_to, status, joined_on, notes, is_demo, updated_at, updated_by) VALUES (?,?,?,?,?,?,?,?, 'DEMO DATA', 1, ?, 'demo')");
    const insPB = db.prepare('INSERT OR IGNORE INTO person_branches(person_id, branch_id) VALUES (?,?)');
    const insT = db.prepare("INSERT INTO targets(scope_type, scope_id, course_id, target, deadline, notes, is_demo, updated_at, updated_by) VALUES (?,?,?,?,?, 'DEMO DATA', 1, ?, 'demo')");
    const insE = db.prepare("INSERT INTO enrollments(college_id, branch_id, course_id, person_id, student_name, enrolled_on, amount_inr, notes, is_demo, created_at, created_by) VALUES (?,?,?,?,?,?,?, 'DEMO DATA', 1, ?, 'demo')");
    const insA = db.prepare("INSERT INTO activities(college_id, branch_id, person_id, on_date, type, students_reached, notes, is_demo, created_at, created_by) VALUES (?,?,?,?,?,?, 'DEMO DATA', 1, ?, 'demo')");
    const insF = db.prepare("INSERT INTO followups(scope_type, scope_id, owner_person_id, owner_name, due_date, status, issue, title, notes, is_demo, created_at, created_by) VALUES (?,?,?,?,?,'open',?,?, 'DEMO DATA', 1, ?, 'demo')");
    const insB = db.prepare("INSERT INTO branches(college_id, code, name, category, is_relevant, intake_per_year, intake_basis, intake_source, strength_total, strength_basis, final_year, final_year_basis, eligible_estimate, eligible_basis, notes, is_demo, updated_at, updated_by) VALUES (?,?,?,?,1,?,'estimated','DEMO DATA',?,?,?,?,?,?,'DEMO DATA',1,?,'demo')");
    let k = 0;
    for (const cid of picks) {
      k++;
      let branches = db.prepare('SELECT * FROM branches WHERE college_id = ? AND is_relevant = 1 ORDER BY id LIMIT 2').all(cid);
      if (branches.length < 2) {
        for (const [code, name, cat, intake] of [['DEMO-CSE', 'DEMO Computer Science & Engg', 'it_core', 120], ['DEMO-ECE', 'DEMO Electronics & Comm. Engg', 'circuit', 60]]) {
          if (branches.some((b) => b.code === code)) continue;
          const d = deriveBranch({ category: cat, intake_per_year: intake }, factors);
          insB.run(cid, code, name, cat, intake, d.strength_total, d.strength_basis, d.final_year, d.final_year_basis, d.eligible_estimate, d.eligible_basis, startAt);
        }
        branches = db.prepare('SELECT * FROM branches WHERE college_id = ? AND is_relevant = 1 ORDER BY id LIMIT 2').all(cid);
      }
      const lead = Number(insP.run(cid, 'college_lead', `DEMO Lead ${cid}`, '+910000000000', null, null, 'active', addDays(T, -40), startAt).lastInsertRowid);
      const al = Number(insP.run(cid, 'ambassador_lead', `DEMO Amb Lead ${cid}`, null, null, lead, 'active', addDays(T, -35), startAt).lastInsertRowid);
      // Ambassadors only on the first relevant branch for odd-numbered picks -> ambassador gaps elsewhere
      const ambBranches = k % 2 ? [branches[0]] : branches;
      const ambs = [];
      for (const b of ambBranches) {
        for (let i = 1; i <= 2; i++) {
          const p = Number(insP.run(cid, 'ambassador', `DEMO Ambassador ${cid}-${b.code}-${i}`, null, null, al, i === 2 && k === 3 ? 'onboarding' : 'active', addDays(T, -30), startAt).lastInsertRowid);
          insPB.run(p, b.id);
          ambs.push({ id: p, branch: b });
          insT.run('person', String(p), null, 8, null, startAt);
        }
      }
      insPB.run(al, branches[0].id);
      // college target; branch target for first branch on even picks (so college stays "explicit")
      insT.run('college', cid, null, 20 + k * 5, null, startAt);
      insT.run('college', cid, courseId, 10 + k, null, startAt);
      if (k % 2 === 0) insT.run('branch', String(branches[0].id), null, 12, null, startAt);
      // enrollments: variable pace (k=1 strong, k=6 weak)
      const nEnroll = Math.max(0, 14 - k * 2);
      for (let i = 0; i < nEnroll; i++) {
        const a = ambs[i % ambs.length];
        insE.run(cid, a.branch.id, i % 2 ? courseId : null, a.id, `DEMO Student ${cid}-${i + 1}`, addDays(T, -((i * 3) % 28) - 1), i % 2 ? 15000 : null, startAt);
      }
      // activities
      for (let i = 0; i < 4; i++) {
        const a = ambs[i % ambs.length];
        insA.run(cid, a.branch.id, a.id, addDays(T, -(i * 6) - 2), ['visit', 'session', 'call', 'whatsapp'][i], k === 5 ? 3 : 40 + i * 10, startAt);
      }
      // follow-ups: one overdue, one upcoming
      insF.run('college', cid, lead, `DEMO Lead ${cid}`, addDays(T, -3), k % 2 ? 'ambassador_gap' : 'low_outreach', `DEMO follow-up (overdue) ${cid}`, startAt);
      insF.run('branch', String(branches[0].id), al, `DEMO Amb Lead ${cid}`, addDays(T, 4), 'other', `DEMO follow-up ${cid}`, startAt);
    }
    return { colleges: picks, course_id: courseId };
  });
}

// ---------------------------------------------------------------------------------------------
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const args = new Set(process.argv.slice(2));
  const db = openDb();
  if (args.has('--clear-demo')) {
    console.log('Cleared demo rows:', clearDemo(db));
  } else {
    const s = seedReference(db);
    console.log(`Seeded: ${s.districts} districts, ${s.cities} cities, colleges ${JSON.stringify(s.colleges)}, branches ${JSON.stringify(s.branches)}, exams ${JSON.stringify(s.exams)} (geo rows: ${s.geo_rows})`);
    console.log(s.contacts.file ? `Contacts from data/seed/contacts*.json: ${JSON.stringify(s.contacts)}` : 'No data/seed/contacts.json / contacts_*.json yet (contacts are added in the app or supplied by the research team).');
    if (args.has('--demo')) {
      const d = seedDemo(db);
      console.log(`DEMO data written (is_demo=1) for ${d.colleges.join(', ')}. Remove with: node server/seed.js --clear-demo`);
    }
  }
  db.close();
}
