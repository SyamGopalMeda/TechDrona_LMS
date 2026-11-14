#!/usr/bin/env node
// Tech Drona portal — OPTIONAL offline backup: a read-only JSON snapshot of every GET answer the UI uses.
// The live portal (served by the Tech Drona LMS under /college-portal/) does NOT use it; the frontend has no static fallback. Use it to archive or
// inspect the data of a day without the server (e.g. before a risky change). Output is gitignored and not deployed.
//
//   npm run export:static                       # portal DB -> portal/public/api_static/
//   node export_static_data.js --db <file> --out <dir>
//
// What it does
//   1. Copies the database to a temp file (VACUUM INTO, source opened read-only) — the live DB is never written.
//   2. Answers every GET request the UI makes (every route, college, branch, person, district and town) in-process with the
//      real server code, and writes each answer to <out>/d/<path>/<file>.json, the file name derived from the exact request
//      key (fileForKey below: exact key -> file, no prefix matching).
//      List endpoints (/colleges, /people, /exams, /followups, /contacts, /calls/queue) are exported once, unfiltered; the
//      filter memberships the server computes (call status, progress, team…) are exported alongside, for offline analysis.
//   3. Privacy (public snapshot): team members' phone, email and notes, enrollment student name/contact/notes and the whole
//      audit log are left out. Official college contacts (college phone/email/website, TPO/principal/office contacts) are
//      public institutional data and are kept. A final scan of every file for any team phone/email or student contact
//      removes anything the structural rules missed (and reports it).
//   4. Writes <out>/index.json (key -> file map, export time) and <out>/_version.json {version = content hash, exported_at}.
//   The output folder is cleaned first; files and keys are written in sorted order (deterministic for the same DB + day).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath, pathToFileURL } from 'node:url';


/* ---------------------------------------------------------------- canonical request key and its file name */
/** '/colleges', {districts:'ntr,guntur'} -> '/colleges?districts=guntur%2Cntr' (params sorted, empty dropped, districts sorted) */
export function staticKey(p0, params) {
  const p = String(p0 || '').replace(/^\/?api(?=\/|$)/, '').replace(/^\/+|\/+$/g, '');
  const entries = [];
  const add = (k, v0) => {
    if (v0 === undefined || v0 === null) return;
    let v = String(v0);
    if (v === '') return;
    if (k === 'districts') {
      const parts = [...new Set(v.split(',').map((x) => x.trim()).filter(Boolean))];
      if (!parts.length) return;
      v = parts.some((x) => x.toLowerCase() === 'all') ? 'all' : parts.sort().join(',');
    }
    entries.push([k, v]);
  };
  if (params instanceof URLSearchParams) for (const [k, v] of params) add(k, v);
  else if (params) for (const [k, v] of Object.entries(params)) add(k, v);
  entries.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
  return `/${p}${entries.length ? `?${entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&')}` : ''}`;
}
/** file of a key: '/colleges/c1' -> 'd/colleges/c1.json'; with a query -> 'd/<path>/q_<sha256 of the key>.json' (exact) */
export function fileForKey(key) {
  const i = key.indexOf('?');
  const p = (i < 0 ? key : key.slice(0, i)).replace(/^\//, '');
  const segs = (p || 'root').split('/').map((s) => s.replace(/[^A-Za-z0-9_.-]/g, (c) => `~${c.charCodeAt(0).toString(16)}`));
  return i < 0 ? `d/${segs.join('/')}.json` : `d/${segs.join('/')}/q_${crypto.createHash('sha256').update(key).digest('hex').slice(0, 20)}.json`;
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_OUT_DIR = path.join(HERE, 'public', 'api_static');
export const FORMAT = 'td-static-v1';

const PERSON_PRIVATE = new Set(['phone', 'email', 'notes', 'phone_norm', 'links', 'whatsapp', 'alt_phone']);
const PERSON_KEYS = new Set(['lead', 'owner', 'manager', 'person', 'reports_to_person']);
const ENROLL_PRIVATE = new Set(['student_name', 'student_contact', 'notes']);

/** structural privacy scrub (see header) */
export function scrub(x, parentKey = '') {
  if (Array.isArray(x)) return x.map((v) => scrub(v, parentKey));
  if (!x || typeof x !== 'object') return x;
  const isPerson = 'full_name' in x || PERSON_KEYS.has(parentKey);
  const isEnroll = 'student_name' in x || 'student_contact' in x;
  const out = {};
  for (const [k, v] of Object.entries(x)) {
    if (k === 'audit') { out.audit = []; out.audit_excluded = true; continue; }
    if (isPerson && PERSON_PRIVATE.has(k)) continue;
    if (isEnroll && ENROLL_PRIVATE.has(k)) continue;
    out[k] = scrub(v, k);
  }
  return out;
}

/** official (public institutional) objects: college rows and college contact rows */
const isOfficial = (o) => !!o && !('full_name' in o) && (('sno' in o && 'name' in o) || ('basis' in o && 'college_id' in o && 'role' in o));

/** value scan: removes any private value that is still present; returns the number of removed values */
function leakScan(x, secrets, report, where) {
  if (!secrets.phones.size && !secrets.texts.size) return 0;
  let n = 0;
  const hit = (s) => {
    const digits = s.replace(/\D/g, '');
    if (digits.length >= 10) for (const p of secrets.phones) if (digits.includes(p)) return true;
    const low = s.toLowerCase();
    for (const t of secrets.texts) if (low.includes(t)) return true;
    return false;
  };
  const walk = (o) => {
    if (Array.isArray(o)) { o.forEach(walk); return; }
    if (!o || typeof o !== 'object') return;
    for (const [k, v] of Object.entries(o)) {
      if (typeof v === 'string' && hit(v)) {
        if (isOfficial(o) && ['phone', 'email', 'contact_phone'].includes(k)) { report.push(`kept official ${k} in ${where}`); continue; }
        o[k] = null; n++; report.push(`removed ${k} in ${where}`);
      } else walk(v);
    }
  };
  walk(x);
  return n;
}

function copyDb(src) {
  const dst = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'td-export-')), 'snapshot.db');
  const d = new DatabaseSync(src, { readOnly: true });
  try { d.exec(`VACUUM INTO '${dst.replace(/'/g, "''")}'`); } finally { d.close(); }
  return dst;
}

const mondayOf = (iso) => { const d = new Date(`${iso}T00:00:00Z`); const wd = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - wd); return d.toISOString().slice(0, 10); };
const sha = (s) => crypto.createHash('sha256').update(s).digest('hex');

/**
 * exportStatic({dbPath?, outDir?, log?}) -> {version, files, bytes, leaks, outDir}
 * outDir is removed and recreated.
 */
export async function exportStatic({ dbPath, outDir = DEFAULT_OUT_DIR, log = console.log } = {}) {
  const { openDb, DEFAULT_DB_PATH } = await import(pathToFileURL(path.join(HERE, 'server', 'db.js')).href);
  const { createApp } = await import(pathToFileURL(path.join(HERE, 'server', 'server.js')).href);
  const src = dbPath || process.env.DB_PATH || DEFAULT_DB_PATH;
  if (!fs.existsSync(src)) throw new Error(`Database not found: ${src}`);
  const tmpDb = copyDb(src);
  const db = openDb(tmpDb);
  try {
    const app = createApp({ db });
    const get = (key) => new Promise((resolve, reject) => {
      const req = { method: 'GET', url: `/api${key}`, headers: { host: 'localhost' }, socket: { remoteAddress: '127.0.0.1' }, readableEnded: true, resume() {}, on() {} };
      const res = { statusCode: 0, writeHead(s) { this.statusCode = s; }, setHeader() {}, end(buf) { resolve({ status: this.statusCode, body: buf ? buf.toString('utf8') : '' }); } };
      app.handler(req, res).catch(reject);
    });
    const getJson = async (key) => { const r = await get(key); if (r.status !== 200) throw new Error(`${key} -> HTTP ${r.status} ${r.body.slice(0, 200)}`); return JSON.parse(r.body); };

    // ---------------------------------------------------------------- what exists
    const health = await getJson('/health');
    const meta = await getJson('/meta');
    const program = await getJson('/program');
    const colleges = await getJson('/colleges');
    const people = await getJson('/people');
    const today = health.today;
    const groups = program.target_district_groups || {};
    const defaultIds = program.default_district_ids || program.target_district_ids || [];
    const districts = (meta.districts || []).map((d) => d.id);
    const cities = (meta.cities || []).map((c) => c.id);
    const collegeIds = colleges.map((c) => c.id);
    const periods = ['programme', `month:${today.slice(0, 7)}`, `week:${mondayOf(today)}`];

    const keys = new Set();
    const add = (p, params) => keys.add(staticKey(p, params));
    // global
    for (const p of ['/health', '/meta', '/program', '/colleges', '/people', '/exams', '/followups', '/contacts', '/targets/unreconciled']) add(p);
    add('/targets', { limit: 5000 });
    add('/plan', { districts: 'all' });
    add('/calls/queue', { filter: 'all', sort: 'priority', limit: 1000 });
    // district-scope variants (none = all districts, the default target districts, each target group, each single district)
    const dvs = [undefined, defaultIds.join(','), ...Object.values(groups).map((g) => g.join(',')), ...districts].filter((v, i, a) => a.findIndex((x) => staticKey('/', { districts: x }) === staticKey('/', { districts: v })) === i);
    for (const d of dvs) {
      const D = { districts: d };
      for (const p of ['/summary', '/target-dashboard', '/attention']) add(p, { ...D, scope: 'state' });
      for (const level of ['district', 'city', 'college', 'branch', 'person']) for (const limit of [200, 500]) add('/leaderboard', { ...D, level, scope: 'state', limit });
      add('/timeseries', { ...D, scope: 'state', days: 60 });
      for (const level of ['person', 'college', 'district']) for (const period of periods) add('/performance', { ...D, level, period });
      add('/plan', D);
      add('/quality', D);
    }
    // places
    const placeScopes = [...districts.map((id) => ['district', id, ['city', 'college', 'branch', 'person']]), ...cities.map((id) => ['city', id, ['college', 'branch', 'person']]),
      ...collegeIds.map((id) => ['college', id, ['branch', 'person']])];
    for (const [type, id, levels] of placeScopes) {
      const scope = `${type}:${id}`;
      add('/summary', { scope }); add('/target-dashboard', { scope }); add('/timeseries', { scope, days: 60 });
      if (type !== 'college') add('/attention', { scope });
      for (const level of levels) for (const limit of [200, 500]) add('/leaderboard', { level, scope, limit });
    }
    // colleges, branches
    const branchIds = [];
    for (const id of collegeIds) {
      add(`/colleges/${id}`);
      add('/branches', { college: id }); add('/branches', { college: id, relevant: 1 });
      for (const period of periods) {
        add('/performance', { level: 'college', college_id: id, period });
        add('/performance', { level: 'person', college_id: id, period, include_inactive: 1 });
        for (const d of [undefined, defaultIds.join(',')]) add('/performance', { districts: d, level: 'person', college_id: id, period });
      }
    }
    // people (team members)
    for (const p of people) {
      add(`/people/${p.id}`);
      add('/targets', { scope: `person:${p.id}` });
      add('/summary', { scope: `person:${p.id}` });
    }

    // ---------------------------------------------------------------- answers
    const secrets = { phones: new Set(), texts: new Set() };
    const digits10 = (s) => String(s || '').replace(/\D/g, '').slice(-10);
    for (const r of db.prepare('SELECT phone, email FROM people').all()) {
      if (digits10(r.phone).length === 10) secrets.phones.add(digits10(r.phone));
      if (r.email && r.email.trim().length >= 5) secrets.texts.add(r.email.trim().toLowerCase());
    }
    for (const r of db.prepare('SELECT student_contact FROM enrollments WHERE student_contact IS NOT NULL').all()) {
      const c = String(r.student_contact).trim();
      if (digits10(c).length === 10) secrets.phones.add(digits10(c)); else if (c.length >= 5) secrets.texts.add(c.toLowerCase());
    }

    fs.rmSync(outDir, { recursive: true, force: true });
    fs.mkdirSync(outDir, { recursive: true });
    const files = {};
    const usedFiles = new Set();
    const report = [];
    let leaks = 0; let bytes = 0; let skipped = 0;
    const hash = crypto.createHash('sha256');
    const write = (key, data) => {
      const rel = fileForKey(key);
      if (usedFiles.has(rel)) throw new Error(`file name collision for ${key}`);
      const txt = JSON.stringify(data);
      fs.mkdirSync(path.dirname(path.join(outDir, rel)), { recursive: true });
      fs.writeFileSync(path.join(outDir, rel), txt);
      files[key] = rel; usedFiles.add(rel); bytes += txt.length;
      hash.update(key).update('\0').update(txt).update('\0');
    };
    for (const key of [...keys].sort()) {
      const r = await get(key);
      if (r.status !== 200) { skipped++; report.push(`skipped ${key}: HTTP ${r.status}`); continue; }
      const data = scrub(JSON.parse(r.body));
      leaks += leakScan(data, secrets, report, key);
      write(key, data);
    }

    // ---------------------------------------------------------------- filter memberships for the client-side list filters
    const ids = (rows) => (Array.isArray(rows) ? rows : rows.items || rows.rows || []).map((r) => r.id ?? r.college_id);
    const collegeFilters = {
      op_status: ['operational', 'possibly_closed', 'closed', 'pending'], targeted: ['1', '0'],
      call_status: ['not_called', 'attempted_no_answer', 'follow_up_due', 'contacted', 'interested', 'participation_confirmed', 'enrolled'],
      contact: ['working', 'non_working', 'untested', 'none'], priority: ['high', 'medium', 'low'],
      exam_state: [...new Set(colleges.map((c) => c.exam_state).filter(Boolean))].sort(), amb: ['gap', 'ok'],
      progress: ['no_target', 'partial_target', 'behind', 'on_track'],
      diagnosis: ['ambassador_gap', 'low_outreach', 'low_conversion', 'unrealistic_target', 'behind_pace'],
      team: ['no_lead', 'has_lead', 'no_ambassadors', 'has_team', 'has_unassigned'], verified: ['verified', 'partly', 'unverified'],
    };
    const cf = {};
    for (const [param, values] of Object.entries(collegeFilters)) {
      cf[param] = {};
      for (const v of values) cf[param][v] = ids(await getJson(staticKey('/colleges', { [param]: v })));
    }
    write('#colleges-filters', cf);
    const qf = {};
    for (const f of ['all', 'working', 'high', 'pending', 'invalid', 'interested', 'confirmed']) qf[f] = ids(await getJson(staticKey('/calls/queue', { filter: f, limit: 1000 })));
    write('#queue-filters', qf);

    const version = hash.digest('hex').slice(0, 16);
    const aud = db.prepare('SELECT MAX(id) id, MAX(at) at FROM audit_log').get();
    const exportedAt = new Date().toISOString();
    const index = {
      files,
      format: FORMAT, version, exported_at: exportedAt, data_today: today, db_data_version: `${aud.id ?? 0}@${aud.at ?? ''}`,
      default_districts: [...defaultIds].sort(), periods,
      privacy: 'Team members’ phone, email and notes, enrollment student name/contact/notes and the audit log are not included. Official college contacts are public institutional data and are included.',
    };
    fs.writeFileSync(path.join(outDir, 'index.json'), JSON.stringify(index));
    fs.writeFileSync(path.join(outDir, '_version.json'), JSON.stringify({ version, exported_at: exportedAt, db_data_version: index.db_data_version, data_today: today }));
    log(`Static snapshot ${version}: ${Object.keys(files).length} files, ${(bytes / 1048576).toFixed(1)} MB, ${skipped} skipped, ${leaks} private values removed by the final scan -> ${outDir}`);
    for (const line of report.filter((l) => !l.startsWith('skipped')).slice(0, 20)) log(`  privacy: ${line}`);
    return { version, files: Object.keys(files).length, bytes, leaks, skipped, report, outDir, exported_at: exportedAt };
  } finally {
    try { db.close(); } catch { /* ignore */ }
    fs.rmSync(path.dirname(tmpDb), { recursive: true, force: true });
  }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const arg = (n) => { const i = process.argv.indexOf(n); return i > 0 ? process.argv[i + 1] : undefined; };
  exportStatic({ dbPath: arg('--db'), outDir: arg('--out') ? path.resolve(arg('--out')) : DEFAULT_OUT_DIR })
    .then(() => process.exit(0))
    .catch((e) => { console.error(`Export failed: ${e.stack || e}`); process.exit(1); });
}
