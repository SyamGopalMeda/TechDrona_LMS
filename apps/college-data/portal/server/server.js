// Tech Drona portal HTTP server: static files from public/ + JSON REST API (see CONTRACT.md).
// Zero dependencies: node:http + node:sqlite.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createLive, SOURCES as LIVE_SOURCES } from './live.js';
import { openDb, tx, today, nowIso, slugify, getSettings, writeAudit, deriveBranch, RELEVANT_CATEGORIES, PORTAL_ROOT, normPhone, normEmail, isMobile, canonicalScopeId } from './db.js';
import {
  buildContext, parseScope, scopeExists, scopeLabel, hrefFor, scopeColleges, scopeBranches, scopePeople,
  summary, personRollup, collegeRow, progressBucket, addDays, daysBetween, activeAmbassadorCount, isoIn, effectiveTarget, parseIsoDate, STAGES,
  withDistricts, assignmentOf, managerIssue, subtreeOf, performance, targetPeriodFields, judge, programStart, MANAGER_ROLES,
  stateRowApplies, programmeTargetReason, programmeDistricts,
} from './rollup.js';
import {
  CONTACT_ROLES, CONTACT_STATUSES, CALL_OUTCOMES, CONNECTED, CALL_STATUSES, PRIORITY_TIERS, CONTACT_FILTERS, QUEUE_FILTERS,
  statusFromCalls, callsCtx, collegeCallInfo, queueRow, matchesQueueFilter, contactFilter, funnelOut, targetDashboard, contactLite,
} from './calls.js';

const PUBLIC_DIR = path.join(PORTAL_ROOT, 'public');
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.geojson': 'application/geo+json; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8', '.map': 'application/json; charset=utf-8', '.webmanifest': 'application/manifest+json',
};

class HttpError extends Error {
  constructor(status, message, fields, extra) { super(message); this.status = status; this.fields = fields; this.extra = extra; }
}
/** Human label for a field name in messages: "college_id" -> "College", "full_name" -> "Full name". */
const fieldLabel = (k) => { const s = String(k).replace(/^_body$/, 'request').replace(/_ids?$/, '').replace(/_/g, ' ').trim(); return s.charAt(0).toUpperCase() + s.slice(1); };
/** v4.1 (D3): lower-case the first word of a field message only when it is one of our own message words ("Required" -> "required"),
 *  never a proper name ("QA Amb Sita belongs to …" stays as typed). */
const MSG_WORDS = new Set(['required', 'must', 'unknown', 'not', 'use', 'enter', 'at', 'date', 'only', 'already', 'same', 'this', 'that', 'the', 'a', 'an',
  'cannot', 'choose', 'give', 'add', 'expected', 'invalid', 'nothing', 'possible', 'end', 'next', 'branch', 'person', 'contact', 'source', 'make', 'remove', 'reactivate', 'refused']);
const lowerLabel = (v) => { const w = /^([A-Z][a-z]*)\b/.exec(v)?.[1]; return w && MSG_WORDS.has(w.toLowerCase()) ? v.charAt(0).toLowerCase() + v.slice(1) : v; };
/** v4.1 (SEC-10/11): invisible format characters (zero-width space/joiner, BOM, bidi marks …). */
const INVISIBLE = /[\p{Cf}\u180e]/gu;
/** 400 with per-field messages. The top-level message also names the fields, so a toast-only UI is still helpful. */
const bad = (fields, msg) => {
  if (!msg) {
    const parts = Object.entries(fields || {}).map(([k, v]) => `${fieldLabel(k)}: ${lowerLabel(String(v))}`);
    msg = parts.length ? `Please fix ${parts.length === 1 ? 'this field' : `${parts.length} fields`} — ${parts.join('; ')}` : 'Please fix the highlighted fields';
  }
  return new HttpError(400, msg, fields);
};
const notFound = (what = 'Not found') => new HttpError(404, what);
const ENTITY_LABEL = { college: 'College', branch: 'Branch', person: 'Person', course: 'Course', target: 'Target', enrollment: 'Enrollment', activity: 'Activity', followup: 'Follow-up', exam: 'Exam row', contact: 'Contact', call: 'Call' };

// ---------------------------------------------------------------------------------------------
// Search matching: case-, accent- and punctuation-insensitive ("K.L." = "kl", "Vignans" = "Vignan's",
// "AI&DS" = "AI-DS" = "aids"); multi-word queries match when every word starts a word somewhere in the record.
// ---------------------------------------------------------------------------------------------
const normCache = new Map(); // record texts repeat on every query; memoise their normal form
export const normText = (s) => { if (s == null || s === '') return ''; let v = normCache.get(s); if (v === undefined) { if (normCache.size > 50000) normCache.clear(); v = normRaw(s); normCache.set(s, v); } return v; };
const normRaw = (s) => String(s ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/['‘’`.]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
export function makeMatcher(raw) {
  const q = normText(raw);
  if (!q) return null;
  const tokens = q.split(' ');
  const compact = q.replace(/ /g, '');
  const score = (text) => {
    const t = normText(text);
    if (!t) return 0;
    if (t === q) return 100;
    const tc = t.replace(/ /g, '');
    if (tc === compact) return 90;
    if (t.startsWith(q)) return 80;
    if (` ${t}`.includes(` ${q}`)) return 60;
    if (t.includes(q)) return 40;
    if (compact.length >= 3 && tc.includes(compact)) return 35;
    return 0;
  };
  /** every query word is the start of some word in the given texts (word order free) */
  const allWords = (texts) => {
    const words = texts.map(normText).join(' ').split(' ');
    return tokens.every((tk) => words.some((w) => w.startsWith(tk)));
  };
  /** best score over texts, or 30 for a multi-word match spread over several fields */
  const best = (texts) => { const s = Math.max(0, ...texts.map(score)); return s || (tokens.length > 1 && allWords(texts) ? 30 : 0); };
  return { q, tokens, score, allWords, best };
}
/** v4 (R7): true when a link/source text starts with a URL scheme other than http(s) — "javascript:", "data:", "vbscript:", "file:" … */
/*    Plain notes such as "Note: confirmed by phone" stay allowed; any "<scheme>://" other than http(s) and the script-capable schemes are refused. */
const DANGEROUS_SCHEMES = /^(javascript|data|vbscript|file|blob|about|jar|livescript|mocha|filesystem):/;
// eslint-disable-next-line no-control-regex
const badScheme = (s) => { const t = String(s).replace(/[\u0000- \u007f-\u009f]+/g, '').toLowerCase(); const raw = String(s).trim().toLowerCase(); return DANGEROUS_SCHEMES.test(t) || (/^[a-z][a-z0-9+.-]*:\/\//.test(raw) && !/^https?:\/\//.test(raw)); };
const aliasList = (a) => { if (!a) return []; try { const v = JSON.parse(a); return Array.isArray(v) ? v.map(String) : [String(v)]; } catch { return [String(a)]; } };

// ---------------------------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------------------------
export function createApp({ db = openDb(), liveFetch } = {}) {
  // official-source data (server/live.js): fetched in the background when users open the site, cached in SQLite
  const live = createLive(db, liveFetch ? { fetchImpl: liveFetch } : {});
  // Rollup context cache. Invalidated by:
  //  - `version`: bumped by every API write on this connection (PRAGMA data_version does not change for
  //    a connection's own commits);
  //  - `PRAGMA data_version`: changes whenever ANOTHER connection commits (seed.js, sqlite3 CLI, a second server);
  //  - the date (pace and exam state depend on today).
  let version = 0;
  let cache = null;
  const dataVersion = db.prepare('PRAGMA data_version');
  const getCtx = () => {
    const key = `${version}|${dataVersion.get().data_version}|${today()}`;
    if (!cache || cache.key !== key) cache = { key, ctx: buildContext(db) };
    return cache.ctx;
  };
  // While `batching` (bulk writes such as allocate), invalidation is deferred to the end of the batch so the
  // context is not rebuilt (~25 ms) once per written row.
  let batching = false; let pending = false;
  const changed = () => { if (batching) { pending = true; return; } version++; cache = null; };
  const batch = (fn) => { batching = true; try { return fn(); } finally { batching = false; if (pending) { pending = false; changed(); } } };

  // ------------------------------------------------------------------ validation
  // v4 (R7): a strict calendar date ('2026-02-31' is refused; Date.parse would accept it)
  /** v4 (R7, BE-15): a limit/page param as a whole number in 1..max (missing, 0, negative or junk -> the default). */
  const lim = (v, d, max) => { const n = Math.trunc(Number(v)); return Math.min(Number.isFinite(n) && n >= 1 ? n : d, max); };
  const isDate = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && parseIsoDate(v) === v;
  function coerce(spec, v, name, fields) {
    if (v === undefined) return undefined;
    // v4 (R7): text that is only whitespace counts as blank
    // v4.1 (SEC-11): text made only of invisible characters (zero-width space …) is blank. Visible text keeps them (ZWJ/ZWNJ matter in Telugu).
    if (typeof v === 'string' && (spec.type === 'text' || spec.type === 'url') && v.replace(INVISIBLE, '').trim() === '') v = '';
    if (typeof v === 'string' && v.trim() === '' && (spec.type === 'text' || spec.type === 'url' || spec.type === 'date' || spec.type === 'enum')) v = '';
    if (v === null || v === '') {
      if (spec.required) { fields[name] = 'Required'; return undefined; }
      return spec.type === 'bool' ? 0 : null;
    }
    switch (spec.type) {
      case 'text': case 'url': {
        if (typeof v === 'object' || typeof v === 'boolean') { fields[name] = 'Must be text'; return undefined; } // v4.1 (BE-18): true is not "true"
        const s = String(v).trim();
        if (spec.max && s.length > spec.max) { fields[name] = `At most ${spec.max} characters`; return undefined; }
        if (spec.pattern && !spec.pattern.test(s)) { fields[name] = spec.patternMsg || 'Invalid format'; return undefined; }
        // v4 (R7, BE-12): links and sources may be an http(s) URL or plain text, never another scheme (javascript:, data:, …)
        if (spec.type === 'url' && badScheme(s)) { fields[name] = 'Only http:// or https:// links are allowed'; return undefined; }
        return s;
      }
      case 'int': case 'num': {
        const n = Number(v);
        if (!Number.isFinite(n) || (spec.type === 'int' && !Number.isInteger(n))) { fields[name] = spec.type === 'int' ? 'Must be a whole number' : 'Must be a number'; return undefined; }
        if (spec.min != null && n < spec.min) { fields[name] = `Must be at least ${spec.min}`; return undefined; }
        if (spec.max != null && n > spec.max) { fields[name] = `Must be at most ${spec.max}`; return undefined; }
        return n;
      }
      case 'bool': {
        // v4 (R7): strict booleans ("maybe" is an error, not a silent 0)
        if ([true, 1, '1', 'true', 'yes'].includes(v)) return 1;
        if ([false, 0, '0', 'false', 'no'].includes(v)) return 0;
        fields[name] = 'Must be true or false'; return undefined;
      }
      case 'date': if (!isDate(String(v))) { fields[name] = 'Use a date like 2026-11-30'; return undefined; } return String(v);
      case 'enum': if (!spec.values.includes(v)) { fields[name] = `Must be one of: ${spec.values.join(', ')}`; return undefined; } return v;
      case 'json': {
        if (spec.array && !Array.isArray(v)) { fields[name] = 'Must be a list'; return undefined; }
        return JSON.stringify(v);
      }
      default: return v;
    }
  }
  // NOT NULL columns per table (name -> has a DB default), so an explicit null/"" gets a field error, not a 500.
  const notNullCache = new Map();
  const notNullCols = (table) => {
    if (!notNullCache.has(table)) notNullCache.set(table, new Map(db.prepare(`PRAGMA table_info(${table})`).all().filter((c) => c.notnull && !c.pk).map((c) => [c.name, c.dflt_value != null])));
    return notNullCache.get(table);
  };
  function validate(specs, body, { create, table }) {
    const fields = {}; const out = {};
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw bad({ _body: 'Expected a JSON object' }, 'Expected a JSON object');
    for (const [name, spec] of Object.entries(specs)) {
      if (spec.readonly) continue;
      const v = coerce(spec, body[name], name, fields);
      if (v !== undefined) out[name] = v;
      else if (create && spec.required && !(name in fields) && spec.default === undefined) fields[name] = 'Required';
      else if (create && v === undefined && spec.default !== undefined && !(name in fields)) out[name] = typeof spec.default === 'function' ? spec.default() : spec.default;
    }
    if (table) {
      for (const [col, hasDefault] of notNullCols(table)) {
        if (out[col] !== null) continue;
        const sd = specs[col]?.default;
        if (create && sd !== undefined) out[col] = typeof sd === 'function' ? sd() : sd; // e.g. on_date -> today
        else if (create && hasDefault) delete out[col]; // blank on create -> the column default (e.g. category 'other')
        else fields[col] = 'Required';
      }
    }
    if (Object.keys(fields).length) throw bad(fields);
    return out;
  }
  const exists = (table, id) => id == null || !!db.prepare(`SELECT 1 FROM ${table} WHERE id = ?`).get(id);
  function checkRefs(row, refs) {
    const fields = {};
    for (const [col, table] of Object.entries(refs)) if (row[col] != null && !exists(table, row[col])) fields[col] = `Unknown ${col.replace(/_id$/, '')}`;
    if (Object.keys(fields).length) throw bad(fields);
  }

  const BASIS = { type: 'enum', values: ['verified', 'estimated', 'pending'] };
  const YNU = { type: 'enum', values: ['yes', 'no', 'unknown'] };
  const T = (max = 500) => ({ type: 'text', max });
  const U = (max = 500) => ({ type: 'url', max }); // v4: link/source text (http(s) or plain text, never another scheme)

  // ------------------------------------------------------------------ entity definitions
  const ENT = {
    colleges: {
      table: 'colleges', entity: 'college', textId: true, stamp: 'updated',
      fields: {
        // v4: sno is optional on create (next free number) and read-only afterwards (R12, BE-07)
        sno: { type: 'int', min: 1 }, name: { ...T(300), required: true }, short_name: T(80),
        aliases: { type: 'json', array: true }, district_id: T(80), city_id: T(160), address: T(500),
        lat: { type: 'num', min: -90, max: 90 }, lng: { type: 'num', min: -180, max: 180 },
        geo_precision: { type: 'enum', values: ['exact', 'town', 'district', 'pending'] }, geo_source: U(),
        website: U(), phone: T(100), email: T(200), contact_source: U(),
        ownership: T(), autonomous: T(), affiliation: T(), naac: T(), nirf: T(), tier: T(),
        op_status: { type: 'enum', values: ['operational', 'possibly_closed', 'closed', 'pending'] }, op_status_note: T(2000), op_status_source: U(),
        op_2025_26: YNU, op_2026_27: YNU, targeted: { type: 'bool' }, notes: T(5000),
        total_intake: { type: 'int', min: 0 }, total_intake_source: U(),
        participation_confirmed_on: { type: 'date' }, participation_note: T(2000),
      },
      refs: { district_id: 'districts', city_id: 'cities' },
      prepare(row, body, before) {
        if (before && row.sno !== undefined && row.sno !== before.sno) throw bad({ sno: 'The S.No of a college cannot be changed (it is its permanent id)' });
        if (before) delete row.sno;
        const did0 = row.district_id ?? before?.district_id;
        if (did0 && !exists('districts', did0)) throw bad({ district_id: 'Unknown district' });
        if (body.city_name !== undefined && body.city_name !== null && String(body.city_name).trim() && did0) {
          const cname = String(body.city_name).trim().slice(0, 160);
          const cid = `${did0}--${slugify(cname)}`;
          db.prepare('INSERT OR IGNORE INTO cities(id, district_id, name) VALUES (?,?,?)').run(cid, did0, cname);
          row.city_id = cid;
        }
        if (!before) {
          const f = {};
          if (!row.district_id) f.district_id = 'Required';
          if (!row.city_id) f.city_id = 'Required (choose a town or type its name in city_name)';
          if (Object.keys(f).length) throw bad(f);
          if (row.sno == null) row.sno = Number(db.prepare('SELECT COALESCE(MAX(sno), 0) + 1 n FROM colleges').get().n);
          row.id = `c${row.sno}`;
          if (row.targeted === undefined) row.targeted = (row.op_status || 'pending') === 'operational' ? 1 : 0;
        }
        const did = row.district_id ?? before?.district_id; const cid = row.city_id ?? before?.city_id;
        if (cid && did) { const city = db.prepare('SELECT district_id FROM cities WHERE id = ?').get(cid); if (city && city.district_id !== did) throw bad({ city_id: 'This town is not in the selected district' }); }
        // R7: college phone may hold several numbers ("0863-2344700 / 98765 43210"); each must be a valid Indian number
        if (row.phone != null && row.phone !== before?.phone) {
          const parts = String(row.phone).split(/[/,;]|\bor\b/i).map((x) => x.trim()).filter(Boolean);
          if (!parts.length || parts.some((x) => !normPhone(x))) throw bad({ phone: 'Enter valid Indian numbers, e.g. 0863 2344700 / 98765 43210' });
        }
        if (row.email != null && row.email !== before?.email) { const e = normEmail(row.email); if (!e) throw bad({ email: 'Not a valid email' }); row.email = e; }
        // R6-style duplicate check: the same college name (ignoring case/punctuation) in the same district
        const name = row.name ?? before?.name;
        if (!before || row.name !== undefined || row.district_id !== undefined) {
          const key = normText(name);
          const dup = (db.prepare('SELECT id, name FROM colleges WHERE district_id IS ? AND id IS NOT ?').all(did ?? null, before?.id ?? row.id ?? null)).find((c) => normText(c.name) === key);
          if (dup) throw new HttpError(409, `${dup.name} (${dup.id}) is already in this district. Open that college instead of adding it again.`, { name: `Already listed as ${dup.id}` }, { code: 'duplicate_college', existing_id: dup.id });
        }
        if (!before && db.prepare('SELECT 1 FROM colleges WHERE id = ? OR sno = ?').get(row.id, row.sno)) throw new HttpError(409, `S.No ${row.sno} is already used`, { sno: 'Already used by another college' }, { code: 'duplicate_sno' });
        // R13: a field changed without a source becomes unverified; with sources.{field} it is stamped verified
        applyVerification(row, body, before);
      },
    },
    branches: {
      table: 'branches', entity: 'branch', stamp: 'updated',
      fields: {
        college_id: { ...T(40), required: true }, code: { ...T(40), required: true }, name: T(200),
        category: { type: 'enum', values: ['it_core', 'it_allied', 'circuit', 'core', 'other'], default: 'other' },
        is_relevant: { type: 'bool' }, intake_per_year: { type: 'int', min: 0, max: 5000 }, intake_basis: BASIS, intake_source: U(), intake_year: T(20),
        intake_2023_24: { type: 'int', min: 0, max: 5000 },
        strength_total: { type: 'int', min: 0 }, strength_basis: BASIS, final_year: { type: 'int', min: 0 }, final_year_basis: BASIS,
        eligible_estimate: { type: 'int', min: 0 }, eligible_basis: BASIS, notes: T(5000),
      },
      refs: { college_id: 'colleges' },
      prepare(row, body, before) {
        if (before && row.college_id && row.college_id !== before.college_id) throw bad({ college_id: 'A branch cannot move to another college' });
        const merged = { ...(before || {}), ...row };
        if (row.code !== undefined && (!before || row.code !== before.code)) {
          const dup = db.prepare('SELECT id FROM branches WHERE college_id = ? AND code = ? AND id IS NOT ?').get(merged.college_id, row.code, before?.id ?? null);
          if (dup) throw new HttpError(409, `This college already has a branch with code ${row.code}`, { code: 'Already used in this college' }, { existing_id: dup.id });
        }
        if (row.category && body.is_relevant === undefined) row.is_relevant = RELEVANT_CATEGORIES.has(merged.category) ? 1 : 0;
        if (!before && row.is_relevant === undefined) row.is_relevant = RELEVANT_CATEGORIES.has(merged.category) ? 1 : 0;
        // v4 (R13, BE-19): an intake typed without a basis is 'estimated' (verified only with an http(s) source in the same request).
        // Typed overrides of the DERIVED numbers (strength / final year / eligible) stay 'verified' so the derivation never overwrites them.
        for (const [v, b] of [['intake_per_year', 'intake_basis'], ['strength_total', 'strength_basis'], ['final_year', 'final_year_basis'], ['eligible_estimate', 'eligible_basis']]) {
          if (body[v] !== undefined && body[b] === undefined) {
            if (row[v] == null) row[b] = 'pending';
            else if (v === 'intake_per_year') row[b] = /^https?:\/\//i.test(String(row.intake_source ?? before?.intake_source ?? '')) ? 'verified' : 'estimated';
            else row[b] = 'verified';
          }
        }
        const d = deriveBranch({ ...merged, ...row }, getSettings(db).relevance_factors);
        for (const k of ['intake_basis', 'strength_total', 'strength_basis', 'final_year', 'final_year_basis', 'eligible_estimate', 'eligible_basis']) {
          if (k === 'intake_basis') { if (d.intake_per_year == null) row.intake_basis = 'pending'; continue; }
          if (!before || d[k] !== before[k]) row[k] = d[k];
        }
      },
    },
    people: {
      table: 'people', entity: 'person', stamp: 'updated',
      fields: {
        college_id: { ...T(40), required: true }, role: { type: 'enum', values: ['college_lead', 'ambassador_lead', 'ambassador'], required: true },
        full_name: { ...T(200), required: true }, phone: T(40), email: { ...T(200), pattern: /^[^@\s]+@[^@\s]+\.[^@\s]+$/, patternMsg: 'Not a valid email' },
        reports_to: { type: 'int', min: 1 }, status: { type: 'enum', values: ['active', 'onboarding', 'inactive'], default: 'active' },
        joined_on: { type: 'date' }, notes: T(5000),
        designation: T(120), responsibility: T(500), // v4: free text, trimmed
      },
      refs: { college_id: 'colleges', reports_to: 'people' },
      prepare(row, body, before) { preparePerson(row, body, before); },
      after(id, body, before) { afterPerson(id, body, before); },
      snapshot(row) { return row && { ...row, branch_ids: db.prepare('SELECT branch_id FROM person_branches WHERE person_id = ? ORDER BY branch_id').all(row.id).map((r) => r.branch_id) }; },
    },
    courses: {
      table: 'courses', entity: 'course', stamp: null,
      fields: { name: { ...T(200), required: true }, price_inr: { type: 'int', min: 0, max: 10000000 }, active: { type: 'bool', default: 1 }, notes: T(2000) },
      refs: {},
    },
    targets: {
      table: 'targets', entity: 'target', stamp: 'updated',
      fields: {
        scope_type: { type: 'enum', values: ['state', 'district', 'city', 'college', 'branch', 'person'], required: true },
        scope_id: T(160) /* required except for state, whose id is always 'ap' */, course_id: { type: 'int', min: 1 }, target: { type: 'int', min: 0, max: 10000000, required: true },
        target_min: { type: 'int', min: 0, max: 10000000 }, target_max: { type: 'int', min: 0, max: 10000000 },
        period: T(30), period_start: { type: 'date' },
        deadline: { type: 'date' }, notes: T(2000),
      },
      refs: { course_id: 'courses' },
      prepare(row, body, before) { prepareTarget(row, body, before); },
    },
    enrollments: {
      table: 'enrollments', entity: 'enrollment', stamp: 'both',
      fields: {
        college_id: T(40), branch_id: { type: 'int', min: 1 }, course_id: { type: 'int', min: 1 }, person_id: { type: 'int', min: 1 },
        student_name: T(200), student_contact: T(200), enrolled_on: { type: 'date', default: () => today() },
        amount_inr: { type: 'int', min: 0, max: 10000000 }, notes: T(2000), // v4.1 (SEC-08): 0..1 crore
        // funnel stage; omitted on create = 'confirmed' (what every enrollment meant before the funnel existed)
        stage: { type: 'enum', values: STAGES, default: 'confirmed' },
        interested_on: { type: 'date' }, registered_on: { type: 'date' }, applied_on: { type: 'date' }, confirmed_on: { type: 'date' }, dropped_on: { type: 'date' },
      },
      refs: { college_id: 'colleges', branch_id: 'branches', course_id: 'courses', person_id: 'people' },
      prepare(row, body, before) { prepareEnrollment(row, body, before); },
    },
    contacts: {
      table: 'contacts', entity: 'contact', stamp: 'both',
      fields: {
        college_id: { ...T(40), required: true }, branch_id: { type: 'int', min: 1 }, name: T(200),
        role: { type: 'enum', values: CONTACT_ROLES, default: 'other' }, phone: T(60), email: T(200), source_url: U(1000),
        basis: { type: 'enum', values: ['verified', 'pending'], default: 'pending' }, notes: T(5000),
        status: { type: 'enum', values: CONTACT_STATUSES },
        verified_on: { type: 'date' }, // v4: optional with basis 'verified' (defaults to today; never in the future)
      },
      refs: { college_id: 'colleges', branch_id: 'branches' },
      prepare(row, body, before) { prepareContact(row, before); },
    },
    calls: {
      table: 'calls', entity: 'call', stamp: 'created',
      fields: {
        contact_id: { type: 'int', min: 1 }, college_id: T(40), branch_id: { type: 'int', min: 1 }, called_at: T(40),
        outcome: { type: 'enum', values: CALL_OUTCOMES, required: true }, notes: T(5000), next_action_at: { type: 'date' },
        confirms_participation: { type: 'bool' },
      },
      refs: { contact_id: 'contacts', college_id: 'colleges', branch_id: 'branches' },
    },
    activities: {
      table: 'activities', entity: 'activity', stamp: 'created',
      fields: {
        college_id: T(40), branch_id: { type: 'int', min: 1 }, person_id: { type: 'int', min: 1 },
        on_date: { type: 'date', default: () => today() },
        type: { type: 'enum', values: ['visit', 'call', 'session', 'whatsapp', 'followup', 'other'], required: true },
        students_reached: { type: 'int', min: 0, max: 100000, default: 0 }, notes: T(5000),
      },
      refs: { college_id: 'colleges', branch_id: 'branches', person_id: 'people' },
      prepare(row, body, before) { inferCollege(row, before); },
    },
    followups: {
      table: 'followups', entity: 'followup', stamp: 'both',
      fields: {
        scope_type: { type: 'enum', values: ['college', 'branch', 'person'], required: true }, scope_id: { ...T(160), required: true },
        owner_person_id: { type: 'int', min: 1 }, owner_name: T(200), due_date: { type: 'date' },
        status: { type: 'enum', values: ['open', 'done'], default: 'open' },
        issue: { type: 'enum', values: ['ambassador_gap', 'low_outreach', 'low_conversion', 'unrealistic_target', 'exams', 'data', 'other'] },
        title: { ...T(300), required: true }, notes: T(5000), last_contact: { type: 'date' },
      },
      refs: { owner_person_id: 'people' },
      prepare(row, body, before) {
        const st = row.scope_type ?? before?.scope_type; let sid = row.scope_id ?? before?.scope_id;
        // v4.1 (SEC-03): one canonical id per scope ("0010" -> "10", "C9" -> "c9"), so delete guards and rollups find the row
        if (row.scope_id !== undefined || row.scope_type !== undefined) { const c = canonicalScopeId(st, sid); if (c == null) throw bad({ scope_id: `Unknown ${st}` }); sid = c; row.scope_id = c; }
        if (!scopeExists(getCtx(), { type: st, id: sid })) throw bad({ scope_id: `Unknown ${st}` });
        if (row.status === 'done' && before?.status !== 'done') row.done_at = nowIso();
        if (row.status === 'open' && before?.status === 'done') row.done_at = null;
        if (!before && row.status === 'done') row.done_at = nowIso();
        if (row.owner_person_id && !row.owner_name && !before?.owner_name) row.owner_name = db.prepare('SELECT full_name FROM people WHERE id = ?').get(row.owner_person_id)?.full_name ?? null;
      },
    },
    exams: {
      table: 'exams', entity: 'exam', stamp: 'updated',
      fields: {
        college_id: { ...T(40), required: true }, semester: { type: 'enum', values: ['3-1', '4-1'], required: true },
        exam_body: T(), status: T(100), endsem_start: T(200), endsem_end: T(200), // free text allowed (seed has "Nov 2026 (no dates)"); the first ISO date inside is used
        mid_window: T(1000), lab_window: T(1000),
        evidence: T(), confidence: T(50), source_url: U(1000), notice_date: T(200), verified_on: T(200), notes: T(5000),
      },
      refs: { college_id: 'colleges' },
      prepare(row, body, before) {
        const s = isoIn(row.endsem_start ?? before?.endsem_start); const e = isoIn(row.endsem_end ?? before?.endsem_end);
        if (s && e && e < s) throw bad({ endsem_end: 'End date is before start date' });
      },
    },
  };
  const STAGE_DATE = { interested: 'interested_on', registered: 'registered_on', applied: 'applied_on', confirmed: 'confirmed_on', dropped: 'dropped_on' };
  function prepareContact(row, before) {
    if (before && row.college_id && row.college_id !== before.college_id) throw bad({ college_id: 'A contact cannot move to another college. Add it to the other college instead.' });
    const cid = row.college_id ?? before?.college_id;
    const bid = row.branch_id !== undefined ? row.branch_id : before?.branch_id;
    if (bid != null) { const b = db.prepare('SELECT college_id FROM branches WHERE id = ?').get(bid); if (!b) throw bad({ branch_id: 'Unknown branch' }); if (b.college_id !== cid) throw bad({ branch_id: 'Branch belongs to another college' }); }
    const fields = {};
    if (row.phone != null) { const n = normPhone(row.phone); if (!n) fields.phone = 'Enter a 10-digit Indian number, e.g. 98765 43210 or 0863 2344700'; else row.phone = n; }
    if (row.email != null) { const n = normEmail(row.email); if (!n) fields.email = 'Not a valid email'; else row.email = n; }
    if (Object.keys(fields).length) throw bad(fields);
    const phone = row.phone !== undefined ? row.phone : before?.phone; const email = row.email !== undefined ? row.email : before?.email;
    if (!phone && !email) throw bad({ phone: 'Add a phone number or an email', email: 'Add a phone number or an email' });
    for (const [k, v] of [['phone', phone], ['email', email]]) {
      if (!v || (row[k] === undefined && before)) continue;
      const dup = db.prepare('SELECT id, name, role FROM contacts WHERE college_id = ? AND ' + k + ' = ? AND id IS NOT ?').get(cid, v, before?.id ?? null);
      if (dup) throw new HttpError(409, 'This ' + (k === 'phone' ? 'number' : 'email') + ' is already recorded for this college (contact ' + dup.id + (dup.name ? ', ' + dup.name : '') + '). Edit that contact instead.', { [k]: 'Already recorded (contact ' + dup.id + ')' }, { existing_id: dup.id });
    }
    if (row.status !== undefined && row.status !== before?.status) row.status_source = row.status == null ? null : 'manual';
    if (row.status === null) row.status = 'untested';
    // v4 (R13): who verified the contact and when
    const basis = row.basis ?? before?.basis;
    if (row.basis !== undefined && row.basis !== before?.basis) {
      if (basis === 'verified') { row.verified_by = cur.actor; row.verified_on = row.verified_on || today(); } else { row.verified_by = null; row.verified_on = null; }
    } else if (row.verified_on !== undefined && basis !== 'verified') delete row.verified_on; // a date only makes sense on a verified contact
    if (row.verified_on && row.verified_on > today()) throw bad({ verified_on: 'Date is in the future' });
  }
  function inferCollege(row, before) {
    if (row.branch_id != null) {
      const b = db.prepare('SELECT college_id FROM branches WHERE id = ?').get(row.branch_id);
      if (!b) throw bad({ branch_id: 'Unknown branch' });
      const cid = row.college_id ?? before?.college_id;
      if (cid && cid !== b.college_id) throw bad({ branch_id: 'Branch belongs to another college' });
      row.college_id = b.college_id;
    }
    if (row.person_id != null && !row.college_id && !before?.college_id) {
      const p = db.prepare('SELECT college_id FROM people WHERE id = ?').get(row.person_id);
      if (p) row.college_id = p.college_id;
    }
    if (!before && !row.college_id) throw bad({ college_id: 'Required' });
  }

  // ------------------------------------------------------------------ v4 write rules (R1–R8, R10, R11, R13)
  // State of the write in progress. node:sqlite is synchronous and every write runs inside one tx(), so writes never interleave.
  const cur = { actor: null, side: null, moved: false, internalTarget: false };
  const newSide = () => ({ unassigned: [], removed_branches: [], reassigned: [], cleared_reports_to: false });
  const ISSUE_MSG = {
    lead_missing: 'Unknown person',
    lead_inactive: 'That lead is inactive. Choose an active lead of this college',
    lead_other_college: 'That lead belongs to another college. Choose a lead of the same college',
    lead_wrong_role: { ambassador: 'An ambassador reports to the College Lead or an Ambassador Lead of the same college', ambassador_lead: 'An Ambassador Lead reports to the College Lead of the same college' },
  };
  const issueText = (issue, role) => (typeof ISSUE_MSG[issue] === 'object' ? ISSUE_MSG[issue][role] : ISSUE_MSG[issue]) || 'Not a valid lead for this person';
  const nameKey = (s) => normText(s);
  const collegeLabel = (id) => { const c = db.prepare('SELECT name, short_name FROM colleges WHERE id = ?').get(id); return c ? (c.short_name || c.name) : id; };
  const parseObj = (s) => { if (!s) return {}; try { const v = JSON.parse(s); return v && typeof v === 'object' && !Array.isArray(v) ? v : {}; } catch { return {}; } };

  /** R13: college fields that carry a verified/unverified state. */
  const VERIFIABLE = ['name', 'short_name', 'district_id', 'city_id', 'address', 'phone', 'email', 'website', 'ownership', 'affiliation', 'autonomous', 'naac', 'op_status'];
  function checkSource(k, v) {
    const s = String(v).trim();
    if (s.length > 500) throw bad({ sources: `${k}: at most 500 characters` });
    if (badScheme(s)) throw bad({ sources: `${k}: only http:// or https:// links are allowed` });
    return s;
  }
  /** Changed field + sources.{field} -> verified stamp; changed field without a source -> unverified (entry removed). */
  function applyVerification(row, body, before) {
    const srcs = body.sources;
    if (srcs !== undefined && srcs !== null && (typeof srcs !== 'object' || Array.isArray(srcs))) throw bad({ sources: 'Must be an object of field: source' });
    const vf = parseObj(before?.verified_fields);
    let changed = false;
    for (const k of VERIFIABLE) {
      if (row[k] === undefined) continue;
      const same = !!before && JSON.stringify(row[k] ?? null) === JSON.stringify(before[k] ?? null);
      const src = srcs?.[k];
      if (src != null && String(src).trim() && row[k] != null) {
        const s = checkSource(k, src);
        if (!same || !vf[k] || vf[k].source !== s) { vf[k] = { source: s, verified_on: today(), verified_by: cur.actor }; changed = true; }
      } else if (!same && vf[k]) { delete vf[k]; changed = true; }
    }
    if (changed || (!before && Object.keys(vf).length)) row.verified_fields = JSON.stringify(vf);
  }

  /** R1–R7 for people (create and update; `before` = the current row or null). */
  function preparePerson(row, body, before) {
    cur.side = newSide(); cur.moved = false;
    const fields = {};
    // v4.1 (F6): people need an Indian MOBILE number (+91 then 6-9 and 9 more digits); contacts may also be STD landlines
    if (row.phone != null) { const n = normPhone(row.phone); if (!n || !isMobile(n)) fields.phone = 'Enter a 10-digit Indian mobile number, e.g. 98765 43210'; else row.phone = n; }
    if (row.email != null) { const n = normEmail(row.email); if (!n) fields.email = 'Not a valid email'; else row.email = n; }
    if (row.full_name != null && !/\p{L}/u.test(row.full_name)) fields.full_name = 'Enter a name with letters'; // v4.1 (SEC-11)
    if (row.joined_on && row.joined_on > today()) fields.joined_on = 'Date is in the future';
    if (body.branch_ids !== undefined && !Array.isArray(body.branch_ids)) fields.branch_ids = 'Must be a list';
    if (Object.keys(fields).length) throw bad(fields);
    const m = { ...(before || {}), ...row };
    if (m.college_id && !exists('colleges', m.college_id)) throw bad({ college_id: 'Unknown college' });
    cur.moved = !!before && row.college_id !== undefined && row.college_id !== before.college_id;
    // R2: a College Lead reports to nobody; a move clears the old college's lead unless a new one is sent
    if (m.role === 'college_lead') {
      if (row.reports_to != null) throw bad({ reports_to: 'A College Lead does not report to anyone' });
      if (m.reports_to != null) { row.reports_to = null; m.reports_to = null; if (before?.reports_to != null) cur.side.cleared_reports_to = true; }
    }
    if (cur.moved && row.reports_to === undefined && m.reports_to != null) { row.reports_to = null; m.reports_to = null; cur.side.cleared_reports_to = true; }
    if (m.reports_to != null) {
      if (before && Number(m.reports_to) === before.id) throw bad({ reports_to: 'A person cannot report to themselves' });
      const mgr = db.prepare('SELECT * FROM people WHERE id = ?').get(Number(m.reports_to));
      const issue = managerIssue(m, mgr);
      if (issue) {
        if (row.reports_to !== undefined) throw bad({ reports_to: issueText(issue, m.role) });
        row.reports_to = null; m.reports_to = null; cur.side.cleared_reports_to = true; // an inherited link that the change made invalid
      } else if (before) {
        // no cycles: walk up from the new manager (roles already prevent them; this guards legacy data)
        let up = mgr; let guard = 0;
        while (up && up.reports_to != null && guard++ < 100) {
          if (Number(up.reports_to) === before.id) throw bad({ reports_to: 'This would create a reporting loop' });
          up = db.prepare('SELECT id, reports_to FROM people WHERE id = ?').get(up.reports_to);
        }
      }
    }
    const active = m.status !== 'inactive';
    const reactivated = !!before && before.status === 'inactive' && active;
    // R1: one not-inactive College Lead per college
    if (m.role === 'college_lead' && active && (!before || row.role !== undefined || row.status !== undefined || row.college_id !== undefined)) {
      const other = db.prepare("SELECT id, full_name FROM people WHERE college_id = ? AND role = 'college_lead' AND status <> 'inactive' AND id IS NOT ?").get(m.college_id, before?.id ?? null);
      if (other) throw new HttpError(409, `${collegeLabel(m.college_id)} already has a College Lead (${other.full_name}). Use "Replace lead", or make this person an Ambassador Lead.`, { role: `Already has a College Lead: ${other.full_name}` }, { code: 'lead_exists', existing_id: other.id, existing_name: other.full_name });
    }
    // R6: the same phone or email on another active person, anywhere
    if (active) {
      for (const k of ['phone', 'email']) {
        if (m[k] == null || (before && row[k] === undefined && !reactivated)) continue;
        const dup = db.prepare(`SELECT id, full_name, college_id FROM people WHERE ${k} = ? AND status <> 'inactive' AND id IS NOT ?`).get(m[k], before?.id ?? null);
        if (dup) throw new HttpError(409, `${k === 'phone' ? 'This number' : 'This email'} already belongs to ${dup.full_name} (${collegeLabel(dup.college_id)}). Open that person instead of adding them again.`, { [k]: `Already used by ${dup.full_name}` }, { code: 'duplicate_person', existing_id: dup.id, existing_name: dup.full_name, existing_college_id: dup.college_id, college: collegeLabel(dup.college_id) });
      }
      if (!body.allow_same_name && (!before || row.full_name !== undefined || row.college_id !== undefined || reactivated)) {
        const key = nameKey(m.full_name);
        const same = db.prepare("SELECT id, full_name FROM people WHERE college_id = ? AND status <> 'inactive' AND id IS NOT ?").all(m.college_id, before?.id ?? null).find((p) => nameKey(p.full_name) === key);
        if (same && (!before || nameKey(before.full_name) !== key || row.college_id !== undefined || reactivated)) {
          throw new HttpError(409, `${same.full_name} is already on this college's team. If this is a different person with the same name, save again with "allow_same_name".`, { full_name: `Same name as person ${same.id}` }, { code: 'possible_duplicate_name', existing_id: same.id, existing_name: same.full_name });
        }
      }
    }
    if (Array.isArray(body.branch_ids)) {
      for (const b of body.branch_ids) {
        const br = db.prepare('SELECT college_id FROM branches WHERE id = ?').get(Number(b));
        if (!br) throw bad({ branch_ids: `Unknown branch ${b}` });
        if (br.college_id !== m.college_id) throw bad({ branch_ids: `Branch ${b} belongs to another college` });
      }
    }
  }
  /** After a person write: branch links (R4) and reports whose link became invalid (R5). Records side effects in cur.side. */
  function afterPerson(id, body, before) {
    const side = cur.side || (cur.side = newSide());
    if (Array.isArray(body.branch_ids)) {
      db.prepare('DELETE FROM person_branches WHERE person_id = ?').run(id);
      const ins = db.prepare('INSERT OR IGNORE INTO person_branches(person_id, branch_id) VALUES (?,?)');
      for (const b of body.branch_ids) ins.run(id, Number(b));
    } else if (cur.moved) {
      const me0 = db.prepare('SELECT college_id FROM people WHERE id = ?').get(id);
      const rm = db.prepare('SELECT pb.branch_id FROM person_branches pb JOIN branches b ON b.id = pb.branch_id WHERE pb.person_id = ? AND b.college_id <> ?').all(id, me0.college_id).map((r) => r.branch_id);
      for (const b of rm) db.prepare('DELETE FROM person_branches WHERE person_id = ? AND branch_id = ?').run(id, b);
      side.removed_branches.push(...rm);
    }
    if (!before) return;
    const me = db.prepare('SELECT * FROM people WHERE id = ?').get(id);
    for (const r of db.prepare('SELECT * FROM people WHERE reports_to = ?').all(id)) {
      if (!managerIssue(r, me)) continue;
      db.prepare('UPDATE people SET reports_to = NULL, updated_at = ?, updated_by = ? WHERE id = ?').run(nowIso(), cur.actor, r.id);
      writeAudit(db, cur.actor, 'update', 'person', r.id, { reports_to: r.reports_to }, { reports_to: null, reason: `lead ${id} changed (${me.status === 'inactive' ? 'deactivated' : 'moved or role changed'})` });
      side.unassigned.push(r.id);
    }
  }

  /** R10/R11 for target rows (create/upsert and PATCH). */
  function prepareTarget(row, body, before) {
    const st = row.scope_type ?? before?.scope_type; let sid = row.scope_id ?? before?.scope_id;
    if (st === 'state') { sid = 'ap'; if (row.scope_id !== undefined || !before) row.scope_id = 'ap'; }
    if (sid == null || sid === '') throw bad({ scope_id: 'Required' });
    if ((st === 'person' || st === 'branch') && (row.scope_id !== undefined || !before)) {
      // BE-09: one canonical id per person/branch ("04" -> "4"), so no hidden duplicate rows
      if (!/^\s*\d+\s*$/.test(String(sid))) throw bad({ scope_id: `Unknown ${st}` });
      sid = String(Number(sid)); row.scope_id = sid;
    } else if (st !== 'state' && (row.scope_id !== undefined || !before)) {
      const c = canonicalScopeId(st, sid); if (c == null) throw bad({ scope_id: `Unknown ${st}` }); sid = c; row.scope_id = c; // v4.1 (SEC-03)
    }
    if (!scopeExists(getCtx(), { type: st, id: sid })) throw bad({ scope_id: `Unknown ${st}` });
    if (row.period !== undefined || row.period_start !== undefined || !before) {
      const per = row.period !== undefined && row.period !== null ? row.period : (before?.period ?? 'programme');
      const ps = row.period_start !== undefined ? row.period_start : (row.period === undefined ? before?.period_start : undefined);
      const pf = targetPeriodFields(getCtx(), per, ps);
      if (pf.error) throw bad({ period: pf.error });
      row.period = pf.period; row.period_start = pf.period_start;
    }
    const m = { ...(before || {}), ...row };
    const f = {};
    if (m.target_min != null && m.target != null && m.target_min > m.target) f.min = 'The minimum cannot be above the target';
    if (m.target_max != null && m.target != null && m.target_max < m.target) f.max = 'The maximum cannot be below the target';
    if (st === 'person') {
      if (row.course_id != null) f.course_id = 'Person targets are for all courses (leave the course empty)';
      if (!before && db.prepare('SELECT status FROM people WHERE id = ?').get(Number(sid))?.status === 'inactive') f.scope_id = 'This person is inactive. Reactivate them before giving them a target';
    }
    if (Object.keys(f).length) throw bad(f);
    if (st === 'state' && m.period === 'programme' && m.course_id == null && !cur.internalTarget && body?.confirm_programme !== true) {
      throw new HttpError(409, 'The programme target is protected. Change it in Settings (programme target), or send confirm_programme: true.', { target: 'Protected programme target' }, { code: 'programme_target_protected' });
    }
  }

  /** R7/R8 for enrollments. */
  function prepareEnrollment(row, body, before) {
    inferCollege(row, before);
    const m = { ...(before || {}), ...row };
    const T0 = today();
    const fields = {};
    if ((row.enrolled_on !== undefined || !before) && m.enrolled_on > T0) fields.enrolled_on = 'Date is in the future';
    for (const k of ['interested_on', 'registered_on', 'applied_on', 'confirmed_on', 'dropped_on']) {
      if (!row[k]) continue;
      if (row[k] > T0) fields[k] = 'Date is in the future';
      else if (m.enrolled_on && row[k] < m.enrolled_on) fields[k] = 'Cannot be before the first (lead) date';
    }
    // R8: credit only someone of the enrollment's own college
    if (m.person_id != null && (row.person_id !== undefined || row.college_id !== undefined || !before)) {
      const p = db.prepare('SELECT full_name, college_id FROM people WHERE id = ?').get(Number(m.person_id));
      if (p && p.college_id !== m.college_id) fields.person_id = `${p.full_name} belongs to another college (${collegeLabel(p.college_id)}). Credit someone from this college.`;
    }
    if (Object.keys(fields).length) throw bad(fields);
    // entering a stage stamps its date once (first time reached); the lead date is enrolled_on
    const stage = row.stage ?? before?.stage ?? 'confirmed';
    if (row.stage !== undefined && row.stage !== before?.stage) {
      const col = STAGE_DATE[stage];
      if (col && row[col] === undefined && !before?.[col]) row[col] = before ? T0 : (row.enrolled_on ?? T0);
    }
    // R7 (TG-18): the contact must be a real mobile number or an email; one student record per contact and course
    if (row.student_contact !== undefined) {
      if (row.student_contact == null) row.student_contact_norm = null;
      else {
        const raw = String(row.student_contact);
        let norm = null;
        if (raw.includes('@')) norm = normEmail(raw);
        else if (!/[a-z]/i.test(raw)) { const ph = normPhone(raw); norm = isMobile(ph) ? ph : null; }
        if (!norm) throw bad({ student_contact: 'Enter a 10-digit mobile number or an email' });
        row.student_contact_norm = norm;
      }
    }
    const norm = row.student_contact_norm !== undefined ? row.student_contact_norm : before?.student_contact_norm;
    const course = row.course_id !== undefined ? row.course_id : before?.course_id;
    if (norm && (row.student_contact !== undefined || row.course_id !== undefined)) {
      const dup = db.prepare('SELECT id, stage FROM enrollments WHERE student_contact_norm = ? AND IFNULL(course_id, 0) = IFNULL(?, 0) AND id IS NOT ?').get(norm, course ?? null, before?.id ?? null);
      if (dup) throw new HttpError(409, 'This student is already recorded (enrollment ' + dup.id + ', stage ' + dup.stage + "). Update that record's stage instead of adding a new one.", { student_contact: 'Already recorded as enrollment ' + dup.id }, { code: 'duplicate_enrollment', existing_id: dup.id });
    }
    // TG-10: a record without any contact is checked by name + college + date (overridable with force:true)
    if (!norm && m.student_name && body.force !== true && (!before || row.student_name !== undefined || row.enrolled_on !== undefined || row.college_id !== undefined || row.student_contact !== undefined)) {
      const dup = db.prepare('SELECT id FROM enrollments WHERE college_id = ? AND enrolled_on = ? AND lower(trim(student_name)) = lower(trim(?)) AND student_contact_norm IS NULL AND id IS NOT ?').get(m.college_id, m.enrolled_on, m.student_name, before?.id ?? null);
      if (dup) throw new HttpError(409, `A record for ${m.student_name} on ${m.enrolled_on} at this college already exists (enrollment ${dup.id}). Open it, or save again with "force" if this is a different student.`, { student_name: `Possible duplicate of enrollment ${dup.id}` }, { code: 'possible_duplicate', existing_id: dup.id });
    }
  }

  const getRow = (def, id) => {
    const r = db.prepare(`SELECT * FROM ${def.table} WHERE id = ?`).get(def.textId ? String(id) : Number(id));
    return r ? { ...r } : null;
  };
  const snap = (def, r) => (def.snapshot ? def.snapshot(r) : r);
  function stampRow(def, row, actor, create) {
    const at = nowIso();
    if (def.stamp === 'updated' || def.stamp === 'both') { row.updated_at = at; row.updated_by = actor; }
    if ((def.stamp === 'created' || def.stamp === 'both') && create) { row.created_at = at; row.created_by = actor; }
  }
  function insertRow(table, row) {
    const cols = Object.keys(row);
    return db.prepare(`INSERT INTO ${table} (${cols.join(',')}) VALUES (${cols.map(() => '?').join(',')})`).run(...cols.map((c) => row[c]));
  }
  function updateRow(table, id, row) {
    const cols = Object.keys(row);
    if (!cols.length) return;
    db.prepare(`UPDATE ${table} SET ${cols.map((c) => `${c} = ?`).join(', ')} WHERE id = ?`).run(...cols.map((c) => row[c]), id);
  }

  /** v4: target bodies accept min / max as aliases of target_min / target_max. */
  const targetBody = (body) => {
    if (!body || typeof body !== 'object' || Array.isArray(body)) return body;
    const b = { ...body };
    if ('min' in b && !('target_min' in b)) b.target_min = b.min;
    if ('max' in b && !('target_max' in b)) b.target_max = b.max;
    return b;
  };
  function createEntity(name, body, actor) {
    const def = ENT[name];
    if (name === 'targets') return upsertTarget(body, actor);
    const row = validate(def.fields, body, { create: true, table: def.table });
    return tx(db, () => {
      cur.actor = actor;
      def.prepare?.(row, body, null);
      checkRefs(row, def.refs);
      if (name === 'colleges' && getRow(def, row.id)) throw new HttpError(409, `College ${row.id} already exists`, { sno: 'Already used' }, { code: 'duplicate_sno' });
      stampRow(def, row, actor, true);
      const r = insertRow(def.table, row);
      const id = def.textId ? row.id : Number(r.lastInsertRowid);
      def.after?.(id, body, null);
      const after = snap(def, getRow(def, id));
      writeAudit(db, actor, 'create', def.entity, id, null, after);
      changed();
      return after;
    });
  }
  function updateEntity(name, id, body, actor) {
    const def = ENT[name];
    if (name === 'targets') body = targetBody(body);
    return tx(db, () => {
      cur.actor = actor;
      const before = snap(def, getRow(def, id));
      if (!before) throw notFound(`${ENTITY_LABEL[def.entity] || def.entity} ${id} not found`);
      const row = validate(def.fields, body, { create: false, table: def.table });
      def.prepare?.(row, body, before);
      checkRefs(row, def.refs);
      for (const k of Object.keys(row)) if (JSON.stringify(row[k]) === JSON.stringify(before[k])) delete row[k];
      if (!Object.keys(row).length && body.branch_ids === undefined) return before;
      stampRow(def, row, actor, false);
      updateRow(def.table, before.id, row);
      def.after?.(before.id, body, before);
      const after = snap(def, getRow(def, before.id));
      writeAudit(db, actor, 'update', def.entity, before.id, before, after);
      if (name === 'targets') syncProgramFromStateTarget(after, actor);
      changed();
      return after;
    });
  }
  const DELETE_GUARDS = {
    courses: [['SELECT COUNT(*) n FROM enrollments WHERE course_id = ?', 'enrollment'], ['SELECT COUNT(*) n FROM targets WHERE course_id = ?', 'course target']],
    branches: [['SELECT COUNT(*) n FROM enrollments WHERE branch_id = ?', 'enrollment'], ['SELECT COUNT(*) n FROM activities WHERE branch_id = ?', 'activity'],
      ["SELECT COUNT(*) n FROM followups WHERE scope_type = 'branch' AND scope_id = CAST(CAST(? AS INTEGER) AS TEXT)", 'follow-up']],
    people: [['SELECT COUNT(*) n FROM enrollments WHERE person_id = ?', 'credited enrollment'], ['SELECT COUNT(*) n FROM activities WHERE person_id = ?', 'logged activity'],
      ["SELECT COUNT(*) n FROM followups WHERE scope_type = 'person' AND scope_id = CAST(CAST(? AS INTEGER) AS TEXT)", 'follow-up']],
    contacts: [['SELECT COUNT(*) n FROM calls WHERE contact_id = ?', 'logged call']],
    colleges: [['SELECT COUNT(*) n FROM branches WHERE college_id = ?', 'branch'], ['SELECT COUNT(*) n FROM people WHERE college_id = ?', 'person'],
      ['SELECT COUNT(*) n FROM enrollments WHERE college_id = ?', 'enrollment'], ['SELECT COUNT(*) n FROM activities WHERE college_id = ?', 'activity'],
      ['SELECT COUNT(*) n FROM exams WHERE college_id = ?', 'exam row'], ['SELECT COUNT(*) n FROM contacts WHERE college_id = ?', 'contact'],
      ['SELECT COUNT(*) n FROM calls WHERE college_id = ?', 'logged call'],
      // v4 (R15, BE-11): follow-ups and research plan rows would be orphaned / silently cascaded
      ["SELECT COUNT(*) n FROM followups WHERE scope_type = 'college' AND scope_id = ?", 'follow-up'],
      ['SELECT COUNT(*) n FROM college_plan WHERE college_id = ?', 'research plan row']],
  };
  const DELETE_HINT = {
    courses: 'Mark the course inactive instead, so past enrollments keep their course and revenue.',
    branches: 'Those records would lose their branch. Edit or remove them first.',
    people: 'Set their status to inactive instead, so their credited work stays on record.',
    colleges: 'Set its status to closed or untarget it instead.',
    contacts: 'Mark it non-working or invalid instead, so the call history stays.',
  };
  const plural = (n, what) => `${n} ${n === 1 ? what : what === 'person' ? 'people' : what.replace(/y$/, 'ie').replace(/(ch|s)$/, '$1e') + 's'}`;
  function deleteEntity(name, id, actor, q = null) {
    const def = ENT[name];
    return tx(db, () => {
      cur.actor = actor;
      const before = snap(def, getRow(def, id));
      if (!before) throw notFound(`${ENTITY_LABEL[def.entity] || def.entity} ${id} not found`);
      if (name === 'targets' && before.scope_type === 'state' && (before.period || 'programme') === 'programme' && before.course_id == null && q?.get('confirm_programme') !== '1') {
        throw new HttpError(409, 'The programme target is protected. Change it in Settings instead of deleting it (or add ?confirm_programme=1).', null, { code: 'programme_target_protected' });
      }
      if (name === 'branches' || name === 'colleges' || name === 'people') {
        const st = { branches: 'branch', colleges: 'college', people: 'person' }[name];
        const n = db.prepare('SELECT COUNT(*) n FROM targets WHERE scope_type = ? AND scope_id = ?').get(st, String(before.id)).n;
        if (n) throw new HttpError(409, `Remove the ${n} target(s) set on this ${def.entity} first`, null, { code: 'has_targets' });
      }
      // Refuse deletes that would silently cascade to, or blank out, other records without an audit trail.
      const linked = DELETE_GUARDS[name]?.map(([sql, what]) => [Number(db.prepare(sql).get(before.id).n), what]).filter(([n]) => n > 0) || [];
      if (linked.length) {
        throw new HttpError(409, `This ${ENTITY_LABEL[def.entity]?.toLowerCase() || def.entity} is linked to ${linked.map(([n, w]) => plural(n, w)).join(', ')}. ${DELETE_HINT[name]}`, null, { code: 'linked_records', linked: Object.fromEntries(linked.map(([n, w]) => [w, n])) });
      }
      const side = newSide();
      if (name === 'people') {
        for (const r of db.prepare('SELECT * FROM people WHERE reports_to = ?').all(before.id)) {
          db.prepare('UPDATE people SET reports_to = NULL, updated_at = ?, updated_by = ? WHERE id = ?').run(nowIso(), actor, r.id);
          writeAudit(db, actor, 'update', 'person', r.id, { reports_to: r.reports_to }, { reports_to: null, reason: `lead ${before.id} deleted` });
          side.unassigned.push(r.id);
        }
      }
      db.prepare(`DELETE FROM ${def.table} WHERE id = ?`).run(before.id);
      writeAudit(db, actor, 'delete', def.entity, before.id, before, null);
      changed();
      return { ok: true, deleted: before, ...(name === 'people' ? { side_effects: side } : {}) };
    });
  }

  // targets: POST/PUT upserts on (scope_type, scope_id, course_id, period, period_start)
  function upsertTarget(body, actor) {
    const def = ENT.targets;
    const b = targetBody(body);
    const row = validate(def.fields, b, { create: true, table: def.table });
    return tx(db, () => { cur.actor = actor; return decorateTarget(upsertTargetRow(row, actor, b)); });
  }
  /** v4: target rows carry min / max / period_key aliases for the UI. */
  function decorateTarget(t) {
    if (!t || typeof t !== 'object') return t;
    const period = t.period || 'programme';
    return { ...t, min: t.target_min ?? null, max: t.target_max ?? null, period, period_key: period === 'programme' ? 'programme' : `${period}:${period === 'month' ? String(t.period_start).slice(0, 7) : t.period_start}` };
  }
  function upsertTargetRow(row, actor, body = row, { internal = false } = {}) {
    const def = ENT.targets;
    cur.internalTarget = internal;
    try { def.prepare(row, body, null); } finally { cur.internalTarget = false; }
    checkRefs(row, def.refs);
    const course = row.course_id ?? null;
    const existing = db.prepare("SELECT * FROM targets WHERE scope_type = ? AND scope_id = ? AND IFNULL(course_id, 0) = IFNULL(?, 0) AND period = ? AND IFNULL(period_start, '') = IFNULL(?, '')")
      .get(row.scope_type, row.scope_id, course, row.period || 'programme', row.period_start ?? null);
    stampRow(def, row, actor, true);
    if (existing) {
      const upd = { target: row.target, updated_at: row.updated_at, updated_by: row.updated_by };
      for (const k of ['deadline', 'notes', 'target_min', 'target_max']) if (row[k] !== undefined) upd[k] = row[k];
      const m = { ...existing, ...upd };
      if (m.target_min != null && m.target_min > m.target) throw bad({ min: 'The minimum cannot be above the target' });
      if (m.target_max != null && m.target_max < m.target) throw bad({ max: 'The maximum cannot be below the target' });
      // re-saving the same values is a no-op: no audit entry, updated_at kept
      if (['target', 'deadline', 'notes', 'target_min', 'target_max'].every((k) => upd[k] === undefined || upd[k] === existing[k])) return { ...existing };
      updateRow('targets', existing.id, upd);
      const after = getRow(def, existing.id);
      writeAudit(db, actor, 'update', 'target', existing.id, existing, after);
      syncProgramFromStateTarget(after, actor);
      changed();
      return after;
    }
    const r = insertRow('targets', { ...row, course_id: course });
    const after = getRow(def, Number(r.lastInsertRowid));
    writeAudit(db, actor, 'create', 'target', after.id, null, after);
    syncProgramFromStateTarget(after, actor);
    changed();
    return after;
  }
  // settings
  const SETTING_SPECS = {
    relevance_factors: (v) => {
      if (!v || typeof v !== 'object' || Array.isArray(v)) return 'Must be an object of category: factor';
      for (const [k, f] of Object.entries(v)) {
        if (!['it_core', 'it_allied', 'circuit', 'core', 'other'].includes(k)) return `Unknown category ${k}`;
        if (typeof f !== 'number' || f < 0 || f > 1) return `Factor for ${k} must be between 0 and 1`;
      }
      return null;
    },
    min_conversion: (v) => (typeof v === 'number' && v >= 0 && v <= 1 ? null : 'Must be a number between 0 and 1'),
    interest_rate: (v) => (v === null || (typeof v === 'number' && v >= 0 && v <= 1) ? null : 'Must be a number between 0 and 1, or empty'),
    state_target_deadline: (v) => (typeof v === 'string' && isDate(v) ? null : 'Use a date like 2026-12-31'),
    org_name: (v) => (typeof v === 'string' && v.trim() && v.length <= 100 ? null : 'Required, at most 100 characters'),
    unreachable_after_attempts: (v) => (Number.isInteger(v) && v >= 0 && v <= 50 ? null : 'Must be a whole number from 0 (never) to 50'),
  };
  function saveSettings(obj, actor) {
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) throw bad({ _body: 'Expected an object of settings' });
    const fields = Object.create(null); // v4.1 (SEC-06): a '__proto__' key must land in fields, not change its prototype
    for (const [k, v] of Object.entries(obj)) {
      if (!Object.hasOwn(SETTING_SPECS, k)) { fields[k] = 'Unknown setting'; continue; } // v4.1 (SEC-06): never Object.prototype names
      const err = SETTING_SPECS[k](v); if (err) fields[k] = err;
    }
    if (Object.keys(fields).length) throw bad(fields);
    return tx(db, () => {
      const cur = getSettings(db);
      for (const [k, v0] of Object.entries(obj)) {
        const v = k === 'relevance_factors' ? { ...cur.relevance_factors, ...v0 } : v0;
        if (JSON.stringify(cur[k]) === JSON.stringify(v)) continue;
        db.prepare('INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(k, JSON.stringify(v));
        writeAudit(db, actor, 'update', 'setting', k, { [k]: cur[k] }, { [k]: v });
        if (k === 'relevance_factors') rederiveBranches(v);
      }
      changed();
      return getSettings(db);
    });
  }
  function rederiveBranches(factors) {
    const upd = db.prepare('UPDATE branches SET eligible_estimate = ?, eligible_basis = ? WHERE id = ?');
    for (const b of db.prepare("SELECT * FROM branches WHERE eligible_basis <> 'verified'").all()) {
      const d = deriveBranch(b, factors);
      if (d.eligible_estimate !== b.eligible_estimate) upd.run(d.eligible_estimate, d.eligible_basis, b.id);
    }
  }

  // ------------------------------------------------------------------ allocate
  function largestRemainder(total, weights) {
    const sum = weights.reduce((s, w) => s + w, 0);
    if (!weights.length) return [];
    const quotas = weights.map((w) => (sum > 0 ? (total * w) / sum : total / weights.length));
    const base = quotas.map(Math.floor);
    let left = total - base.reduce((s, x) => s + x, 0);
    const order = quotas.map((q, i) => ({ i, frac: q - Math.floor(q), w: weights[i] })).sort((a, b) => b.frac - a.frac || b.w - a.w || a.i - b.i);
    for (let k = 0; left > 0; k = (k + 1) % order.length, left--) base[order[k].i]++;
    return base;
  }
  function allocate(body, actor) {
    const fields = {};
    const ptypes = ['state', 'district', 'city', 'college', 'branch'];
    if (!ptypes.includes(body?.parent_type)) fields.parent_type = `Must be one of: ${ptypes.join(', ')}`;
    const total = Number(body?.total);
    if (!Number.isInteger(total) || total < 0) fields.total = 'Must be a whole number ≥ 0';
    const method = body?.method || 'eligible';
    if (!['eligible', 'strength', 'equal'].includes(method)) fields.method = 'Must be eligible, strength or equal';
    if (body?.deadline != null && body.deadline !== '' && !isDate(body.deadline)) fields.deadline = 'Use a date like 2026-12-31';
    const courseId = body?.course_id == null || body.course_id === '' ? null : Number(body.course_id);
    if (courseId != null && !exists('courses', courseId)) fields.course_id = 'Unknown course';
    if (Object.keys(fields).length) throw bad(fields);
    const ctx = getCtx();
    const sc = { type: body.parent_type, id: body.parent_type === 'state' ? 'ap' : String(body.parent_id ?? '') };
    if (!scopeExists(ctx, sc)) throw bad({ parent_id: `Unknown ${sc.type}` });
    const onlyTargeted = body.only_targeted !== false;
    const dryRun = body.dry_run !== false;

    const relevantOf = (colleges) => colleges.flatMap((c) => ctx.branchesByCollege.get(c.id) || []).filter((b) => b.is_relevant);
    const okCollege = (c) => !onlyTargeted || (c.targeted && c.op_status !== 'closed');
    const basisOf = (branches) => branches.reduce((s, b) => s + Number((method === 'strength' ? b.strength_total : b.eligible_estimate) ?? 0), 0);
    let kids = [];
    if (sc.type === 'state') {
      kids = [...ctx.districts.values()].map((d) => ({ scope_type: 'district', scope_id: d.id, label: d.name, cols: (ctx.collegesByDistrict.get(d.id) || []).filter(okCollege), flag: d.targeted }));
      kids = kids.filter((k) => !onlyTargeted || k.cols.length > 0);
    } else if (sc.type === 'district') {
      kids = (ctx.citiesByDistrict.get(sc.id) || []).map((c) => ({ scope_type: 'city', scope_id: c.id, label: c.name, cols: (ctx.collegesByCity.get(c.id) || []).filter(okCollege) }));
      kids.push(...(ctx.orphansByDistrict.get(sc.id) || []).filter(okCollege).map((c) => ({ scope_type: 'college', scope_id: c.id, label: c.short_name || c.name, cols: [c] })));
      kids = kids.filter((k) => !onlyTargeted || k.cols.length > 0);
    } else if (sc.type === 'city') {
      kids = (ctx.collegesByCity.get(sc.id) || []).filter(okCollege).map((c) => ({ scope_type: 'college', scope_id: c.id, label: c.short_name || c.name, cols: [c] }));
    } else if (sc.type === 'college') {
      kids = (ctx.branchesByCollege.get(sc.id) || []).filter((b) => b.is_relevant).map((b) => ({ scope_type: 'branch', scope_id: String(b.id), label: `${b.code}${b.name ? ` · ${b.name}` : ''}`, branches: [b] }));
    } else if (sc.type === 'branch') {
      kids = (ctx.peopleOfBranch.get(Number(sc.id)) || []).map((id) => ctx.people.get(id))
        .filter((p) => p && p.role === 'ambassador' && p.status !== 'inactive')
        .map((p) => ({ scope_type: 'person', scope_id: String(p.id), label: p.full_name, equalOnly: true }));
    }
    if (!kids.length) throw bad({ parent_id: 'Nothing to allocate to: no eligible children at the next level' }, 'No children to allocate to');
    let methodUsed = method;
    let weights = kids.map((k) => (method === 'equal' || k.equalOnly ? 1 : basisOf(k.branches || relevantOf(k.cols))));
    if (kids[0].equalOnly) methodUsed = 'equal';
    if (methodUsed !== 'equal' && weights.every((w) => w <= 0)) { weights = kids.map(() => 1); methodUsed = 'equal'; }
    const proposed = largestRemainder(total, weights);
    const rows = kids.map((k, i) => ({ scope_type: k.scope_type, scope_id: k.scope_id, label: k.label, basis_value: weights[i], proposed: proposed[i] }));
    const sum = proposed.reduce((s, x) => s + x, 0);
    if (!dryRun) {
      batch(() => tx(db, () => {
        for (const r of rows) upsertTargetRow({ scope_type: r.scope_type, scope_id: r.scope_id, course_id: courseId, target: r.proposed, deadline: body.deadline || undefined, notes: `Allocated from ${sc.type}:${sc.id} by ${methodUsed}` }, actor);
      }));
    }
    return { rows, sum, total, method: methodUsed, dry_run: dryRun, parent_type: sc.type, parent_id: sc.id, course_id: courseId };
  }

  // ------------------------------------------------------------------ calls (custom writes: side effects on contacts/follow-ups/college)
  const OUTCOME_LABEL = {
    connected_interested: 'interested', connected_callback: 'asked for a call-back', connected_not_interested: 'not interested',
    connected_info_only: 'took information', no_answer: 'no answer', busy: 'busy', switched_off: 'switched off', not_reachable: 'not reachable',
    wrong_number: 'wrong number', invalid_number: 'invalid number', disconnected: 'disconnected',
  };
  const ROLE_TEXT = { tpo: 'TPO', principal: 'Principal', hod: 'HOD', office: 'Office', admissions: 'Admissions', dean: 'Dean', other: 'Contact' };
  const DECISIVE = (o) => (CONNECTED.has(o) ? 'working' : o === 'wrong_number' || o === 'invalid_number' ? 'invalid' : o === 'disconnected' ? 'non_working' : null);
  function setContactStatus(contact, status, source, actor) {
    if (contact.status === status && contact.status_source === source) return;
    const upd = { status, status_source: source, updated_at: nowIso(), updated_by: actor };
    updateRow('contacts', contact.id, upd);
    writeAudit(db, actor, 'update', 'contact', contact.id, contact, getRow(ENT.contacts, contact.id));
  }
  /** After a call is logged: a decisive outcome sets the status; N unanswered attempts in a row make it non-working. */
  function applyCallToContact(contactId, outcome, actor) {
    const k = getRow(ENT.contacts, contactId); if (!k) return;
    const d = DECISIVE(outcome);
    if (d) return setContactStatus(k, d, 'calls', actor);
    const calls = db.prepare('SELECT outcome FROM calls WHERE contact_id = ? ORDER BY called_at, id').all(contactId);
    const r = statusFromCalls(calls, getSettings(db).unreachable_after_attempts);
    if (r?.unreachable && k.status !== 'invalid' && k.status !== 'non_working') setContactStatus(k, 'non_working', 'calls', actor);
  }
  /** After a call is deleted: recompute from the remaining calls unless a user set the status by hand. */
  function recomputeContact(contactId, actor) {
    const k = getRow(ENT.contacts, contactId); if (!k || k.status_source === 'manual') return;
    const calls = db.prepare('SELECT outcome FROM calls WHERE contact_id = ? ORDER BY called_at, id').all(contactId);
    const r = statusFromCalls(calls, getSettings(db).unreachable_after_attempts);
    if (r?.status) setContactStatus(k, r.status, 'calls', actor);
    else if (k.status_source === 'calls') setContactStatus(k, 'untested', null, actor);
  }
  const callDetailSql = `SELECT x.*, k.name AS contact_name, k.role AS contact_role, k.phone AS contact_phone, k.status AS contact_status,
      c.short_name AS college_short_name, c.name AS college_name, f.status AS followup_status, f.due_date AS followup_due
    FROM calls x LEFT JOIN contacts k ON k.id = x.contact_id LEFT JOIN colleges c ON c.id = x.college_id LEFT JOIN followups f ON f.id = x.followup_id`;
  function createCall(body, actor) {
    const def = ENT.calls;
    const row = validate(def.fields, body, { create: true, table: 'calls' });
    return tx(db, () => {
      let contact = null;
      if (row.contact_id != null) {
        contact = getRow(ENT.contacts, row.contact_id);
        if (!contact) throw bad({ contact_id: 'Unknown contact' });
        if (row.college_id && row.college_id !== contact.college_id) throw bad({ contact_id: 'Contact belongs to another college' });
        row.college_id = contact.college_id;
        if (row.branch_id == null && contact.branch_id != null) row.branch_id = contact.branch_id;
      }
      if (!row.college_id) throw bad({ college_id: 'Required' });
      checkRefs(row, def.refs);
      if (row.branch_id != null && db.prepare('SELECT college_id FROM branches WHERE id = ?').get(row.branch_id)?.college_id !== row.college_id) throw bad({ branch_id: 'Branch belongs to another college' });
      if (row.called_at == null) row.called_at = nowIso();
      const calledDate = parseIsoDate(row.called_at);
      if (!calledDate) throw bad({ called_at: 'Use a date like 2026-11-03 or a date-time like 2026-11-03T10:30' });
      if (calledDate > addDays(today(), 1)) throw bad({ called_at: 'Date is in the future' });
      if (row.next_action_at && row.next_action_at < calledDate) throw bad({ next_action_at: 'Next action is before the call' });
      if (row.confirms_participation && !CONNECTED.has(row.outcome)) throw bad({ confirms_participation: 'Only a call where you spoke to someone can confirm participation' });
      row.caller = actor;
      stampRow(def, row, actor, true);
      const id = Number(insertRow('calls', row).lastInsertRowid);
      writeAudit(db, actor, 'create', 'call', id, null, getRow(def, id));
      // a new call supersedes earlier open call-backs for the same contact (or the college when no contact)
      const prev = db.prepare(`SELECT f.* FROM calls x JOIN followups f ON f.id = x.followup_id
        WHERE x.id <> ? AND f.status = 'open' AND x.college_id = ? AND IFNULL(x.contact_id, 0) = IFNULL(?, 0)`).all(id, row.college_id, row.contact_id ?? null);
      for (const f of prev) {
        updateRow('followups', f.id, { status: 'done', done_at: nowIso(), updated_at: nowIso(), updated_by: actor });
        writeAudit(db, actor, 'update', 'followup', f.id, f, getRow(ENT.followups, f.id));
      }
      let followup = null;
      if (row.next_action_at) {
        const col = db.prepare('SELECT short_name, name FROM colleges WHERE id = ?').get(row.college_id);
        const who = contact ? (contact.name || ROLE_TEXT[contact.role] || 'contact') : (col.short_name || col.name);
        const fu = { scope_type: 'college', scope_id: row.college_id, owner_name: actor, due_date: row.next_action_at, status: 'open', issue: 'other',
          title: `Call back ${who} (${OUTCOME_LABEL[row.outcome]})`.slice(0, 300), notes: row.notes ?? null, last_contact: calledDate };
        stampRow(ENT.followups, fu, actor, true);
        const fid = Number(insertRow('followups', fu).lastInsertRowid);
        followup = getRow(ENT.followups, fid);
        writeAudit(db, actor, 'create', 'followup', fid, null, followup);
        db.prepare('UPDATE calls SET followup_id = ? WHERE id = ?').run(fid, id);
      }
      if (contact) applyCallToContact(contact.id, row.outcome, actor);
      if (row.confirms_participation) {
        const cb = getRow(ENT.colleges, row.college_id);
        if (!cb.participation_confirmed_on) {
          updateRow('colleges', cb.id, { participation_confirmed_on: calledDate, participation_note: `Confirmed on a call by ${actor}${row.notes ? `: ${row.notes}` : ''}`.slice(0, 2000), updated_at: nowIso(), updated_by: actor });
          writeAudit(db, actor, 'update', 'college', cb.id, cb, getRow(ENT.colleges, cb.id));
        }
      }
      changed();
      return { ...db.prepare(`${callDetailSql} WHERE x.id = ?`).get(id), followup, contact: contact ? getRow(ENT.contacts, contact.id) : null, closed_followups: prev.map((f) => f.id) };
    });
  }
  function patchCall(id, body, actor) {
    if (!body || typeof body !== 'object') throw bad({ _body: 'Expected a JSON object' });
    const extra = Object.keys(body).filter((k) => k !== 'notes');
    if (extra.length) throw bad(Object.fromEntries(extra.map((k) => [k, 'Only notes can be edited on a logged call. Delete the call and log it again to change it.'])));
    return tx(db, () => {
      const before = getRow(ENT.calls, id); if (!before) throw notFound(`Call ${id} not found`);
      const row = validate({ notes: T(5000) }, body, { create: false });
      if ((row.notes ?? null) === before.notes) return before;
      updateRow('calls', before.id, row);
      const after = getRow(ENT.calls, before.id);
      writeAudit(db, actor, 'update', 'call', before.id, before, after);
      changed();
      return after;
    });
  }
  function deleteCall(id, actor) {
    return tx(db, () => {
      const before = getRow(ENT.calls, id); if (!before) throw notFound(`Call ${id} not found`);
      db.prepare('DELETE FROM calls WHERE id = ?').run(before.id);
      writeAudit(db, actor, 'delete', 'call', before.id, before, null);
      if (before.contact_id) recomputeContact(before.contact_id, actor);
      changed();
      return { ok: true, deleted: before };
    });
  }

  // ------------------------------------------------------------------ calling read endpoints
  const oneOf = (q, key, values) => {
    const v = q.get(key); if (v == null || v === '') return null;
    const set = v.split(',').map((x) => x.trim()).filter(Boolean);
    const badV = set.filter((x) => !values.includes(x));
    if (badV.length) throw bad({ [key]: `Must be one or more of: ${values.join(', ')}` });
    return new Set(set);
  };
  function contactRow(ctx, k) {
    const K = callsCtx(ctx);
    const calls = K.callsByContact.get(k.id) || [];
    const last = calls.length ? calls[calls.length - 1] : null;
    const c = ctx.colleges.get(k.college_id);
    const r = statusFromCalls(calls, ctx.settings.unreachable_after_attempts);
    return { ...k, college_label: c?.short_name || c?.name || k.college_id, district_id: c?.district_id ?? null, calls_total: calls.length,
      last_call: last ? { id: last.id, called_at: last.called_at, outcome: last.outcome, caller: last.caller } : null,
      unanswered_streak: r?.streak ?? 0 };
  }
  function listContacts(q) {
    const ctx = getCtx();
    let rows = callsCtx(ctx).contacts;
    const col = q.get('college') || q.get('college_id');
    if (col) rows = rows.filter((k) => k.college_id === col);
    if (q.get('district')) rows = rows.filter((k) => ctx.colleges.get(k.college_id)?.district_id === q.get('district'));
    const ds = districtSet(q); if (ds) rows = rows.filter((k) => ds.has(ctx.colleges.get(k.college_id)?.district_id));
    const st = oneOf(q, 'status', CONTACT_STATUSES); if (st) rows = rows.filter((k) => st.has(k.status));
    const ro = oneOf(q, 'role', CONTACT_ROLES); if (ro) rows = rows.filter((k) => ro.has(k.role));
    const ba = oneOf(q, 'basis', ['verified', 'pending']); if (ba) rows = rows.filter((k) => ba.has(k.basis));
    const m = makeMatcher(q.get('q'));
    if (m) rows = rows.filter((k) => phoneHit(k.phone, q.get('q')) || m.best([k.name, k.email, ctx.colleges.get(k.college_id)?.short_name, ctx.colleges.get(k.college_id)?.name]) > 0);
    return rows.map((k) => contactRow(ctx, k));
  }
  function contactDetail(id) {
    const ctx = getCtx();
    const k = callsCtx(ctx).contactById.get(Number(id));
    if (!k) throw notFound(`Contact ${id} not found`);
    return { contact: contactRow(ctx, k), calls: db.prepare(`${callDetailSql} WHERE x.contact_id = ? ORDER BY x.called_at DESC, x.id DESC`).all(k.id) };
  }
  function listCalls(q) {
    const where = []; const p = [];
    const col = q.get('college') || q.get('college_id');
    if (col) { where.push('x.college_id = ?'); p.push(col); }
    if (q.get('contact')) { where.push('x.contact_id = ?'); p.push(Number(q.get('contact'))); }
    if (q.get('caller')) { where.push('x.caller = ?'); p.push(q.get('caller')); }
    const ds = districtSet(q);
    if (ds) { where.push(`x.college_id IN (SELECT id FROM colleges WHERE district_id IN (${[...ds].map(() => '?').join(',')}))`); p.push(...ds); }
    const oc = oneOf(q, 'outcome', CALL_OUTCOMES); if (oc) { where.push(`x.outcome IN (${[...oc].map(() => '?').join(',')})`); p.push(...oc); }
    if (q.get('from')) { if (!isDate(q.get('from'))) throw bad({ from: 'Use a date like 2026-11-01' }); where.push('x.called_at >= ?'); p.push(q.get('from')); }
    if (q.get('to')) { if (!isDate(q.get('to'))) throw bad({ to: 'Use a date like 2026-11-30' }); where.push('x.called_at < ?'); p.push(addDays(q.get('to'), 1)); }
    const limit = lim(q.get('limit'), 200, 2000);
    return db.prepare(`${callDetailSql} ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY x.called_at DESC, x.id DESC LIMIT ?`).all(...p, limit);
  }
  function callQueue(q) {
    const ctx = getCtx();
    const filter = q.get('filter') || 'all';
    if (!QUEUE_FILTERS.includes(filter)) throw bad({ filter: `Must be one of: ${QUEUE_FILTERS.join(', ')}` });
    const sort = q.get('sort') || 'priority';
    if (!['priority', 'next_action', 'name', 'last_call'].includes(sort)) throw bad({ sort: 'Must be priority, next_action, name or last_call' });
    let cols = [...ctx.colleges.values()];
    // Default queue: operational colleges only (possibly-closed / pending / closed are not worth calling first).
    if (q.get('include_closed') !== '1') cols = cols.filter((c) => c.op_status === 'operational');
    const ds = districtSet(q); if (ds) cols = cols.filter((c) => ds.has(c.district_id));
    if (q.get('district')) cols = cols.filter((c) => c.district_id === q.get('district'));
    if (q.get('city')) cols = cols.filter((c) => c.city_id === q.get('city'));
    if (q.get('targeted') === '1') cols = cols.filter((c) => c.targeted);
    const m = makeMatcher(q.get('q'));
    if (m) cols = cols.filter((c) => m.q === String(c.sno) || m.q === c.id || m.best(collegeTexts(ctx, c)) > 0);
    const all = cols.map((c) => queueRow(ctx, c));
    const counts = Object.fromEntries(QUEUE_FILTERS.map((f) => [f, all.filter((r) => matchesQueueFilter(r, f)).length]));
    let rows = all.filter((r) => matchesQueueFilter(r, filter));
    const cs = oneOf(q, 'call_status', CALL_STATUSES); if (cs) rows = rows.filter((r) => cs.has(r.call_status));
    const cmp = {
      priority: (a, b) => b.priority.score - a.priority.score,
      next_action: (a, b) => (a.next_action?.due_date || '9999').localeCompare(b.next_action?.due_date || '9999') || b.priority.score - a.priority.score,
      name: () => 0,
      last_call: (a, b) => String(b.last_call?.called_at || '').localeCompare(String(a.last_call?.called_at || '')),
    }[sort];
    rows.sort((a, b) => cmp(a, b) || String(a.short_name || a.name).localeCompare(String(b.short_name || b.name)));
    const limit = lim(q.get('limit'), 500, 1000);
    return { filter, sort, total: rows.length, counts, today: ctx.today, districts_filter: ds ? [...ds] : null, rows: rows.slice(0, limit) };
  }

  // ------------------------------------------------------------------ read endpoints
  const branchLite = (b) => ({ id: b.id, code: b.code, name: b.name, category: b.category, is_relevant: b.is_relevant });
  const personLite = (p) => ({ id: p.id, full_name: p.full_name, role: p.role, status: p.status, phone: p.phone, email: p.email });

  function meta() {
    const ctx = getCtx();
    const counts = db.prepare(`SELECT
      (SELECT COUNT(*) FROM colleges) colleges, (SELECT COUNT(*) FROM colleges WHERE targeted = 1) targeted_colleges,
      (SELECT COUNT(*) FROM branches) branches, (SELECT COUNT(*) FROM people) people, (SELECT COUNT(*) FROM enrollments) enrollments,
      (SELECT COUNT(*) FROM activities) activities, (SELECT COUNT(*) FROM followups WHERE status = 'open') followups_open,
      (SELECT COUNT(*) FROM targets) targets, (SELECT COUNT(*) FROM courses) courses, (SELECT COUNT(*) FROM exams) exams,
      (SELECT COUNT(*) FROM enrollments WHERE stage = 'confirmed') enrollments_confirmed, (SELECT COUNT(*) FROM contacts) contacts, (SELECT COUNT(*) FROM calls) calls`).get();
    const demo = !!db.prepare(`SELECT 1 FROM (
      SELECT is_demo FROM people WHERE is_demo = 1 UNION ALL SELECT is_demo FROM enrollments WHERE is_demo = 1 UNION ALL
      SELECT is_demo FROM activities WHERE is_demo = 1 UNION ALL SELECT is_demo FROM followups WHERE is_demo = 1 UNION ALL
      SELECT is_demo FROM targets WHERE is_demo = 1 UNION ALL SELECT is_demo FROM courses WHERE is_demo = 1 UNION ALL
      SELECT is_demo FROM branches WHERE is_demo = 1 UNION ALL SELECT is_demo FROM colleges WHERE is_demo = 1 UNION ALL
      SELECT is_demo FROM contacts WHERE is_demo = 1 UNION ALL SELECT is_demo FROM calls WHERE is_demo = 1) LIMIT 1`).get();
    const colCount = new Map(); for (const c of ctx.colleges.values()) colCount.set(c.city_id, (colCount.get(c.city_id) || 0) + 1);
    return {
      districts: [...ctx.districts.values()].map((d) => ({ ...d, colleges: (ctx.collegesByDistrict.get(d.id) || []).length })),
      cities: [...ctx.cities.values()].map((c) => ({ ...c, colleges: colCount.get(c.id) || 0 })),
      courses: ctx.courses, settings: ctx.settings, counts: Object.fromEntries(Object.entries(counts).map(([k, v]) => [k, Number(v)])),
      demo, today: ctx.today, passcode_required: !!process.env.PORTAL_PASSCODE,
    };
  }

  function scopeFromQuery(q, key = 'scope') {
    const sc = parseScope(q.get(key) || 'state');
    const ctx = getCtx();
    if (!sc || !scopeExists(ctx, sc)) throw bad({ [key]: 'Unknown scope' }, `Unknown scope "${q.get(key)}"`);
    return withDistricts(sc, districtsFromQuery(q).ids);
  }

  /**
   * `districts=` query param: comma-separated district ids, or `all` (= no filter). Absent/blank = no filter.
   * Unknown id -> 400 {fields:{districts}}. Returns {present, all, ids (array | null = no filter)}.
   */
  function districtsFromQuery(q) {
    const raw = q.get('districts');
    if (raw == null || !raw.trim()) return { present: false, all: false, ids: null };
    const parts = [...new Set(raw.split(',').map((x) => x.trim()).filter(Boolean))];
    if (parts.some((x) => x.toLowerCase() === 'all')) return { present: true, all: true, ids: null };
    const ctx = getCtx();
    const unknown = parts.filter((x) => !ctx.districts.has(x));
    if (unknown.length || !parts.length) throw bad({ districts: `Unknown district${unknown.length === 1 ? '' : 's'}: ${unknown.join(', ') || raw}. Use district ids (e.g. guntur,ntr) or all.` });
    return { present: true, all: false, ids: parts };
  }
  /** Set of district ids to keep, or null (no filter). */
  const districtSet = (q) => { const d = districtsFromQuery(q); return d.ids ? new Set(d.ids) : null; };

  /** the texts a college is found by: name, short name, aliases, town, district */
  const collegeTexts = (ctx, c) => [c.name, c.short_name, ...aliasList(c.aliases), ctx.cities.get(c.city_id)?.name, ctx.districts.get(c.district_id)?.name];
  /** phone match only for digit-like queries of 4+ digits (so "c9" or "9" do not match every phone number) */
  const phoneHit = (phone, raw) => { const d = String(raw || '').replace(/\D/g, ''); return !!phone && /^[\d\s+()-]+$/.test(String(raw).trim()) && d.length >= 4 && String(phone).replace(/\D/g, '').includes(d); };

  /** v4 (R13): per-field verification state of a college and an overall data_status. */
  const FIELD_STATUS_KEYS = ['name', 'district_id', 'city_id', 'phone', 'email', 'website', 'ownership', 'affiliation', 'op_status'];
  function verificationOf(c) {
    const vf = parseObj(c.verified_fields);
    const field_status = {};
    for (const k of FIELD_STATUS_KEYS) {
      const v = c[k];
      field_status[k] = v == null || v === '' || (k === 'op_status' && v === 'pending') ? 'missing' : vf[k] ? 'verified' : 'unverified';
    }
    const present = Object.values(field_status).filter((x) => x !== 'missing');
    const ver = present.filter((x) => x === 'verified').length;
    return { verified_fields: vf, field_status, data_status: present.length && ver === present.length ? 'verified' : ver ? 'partly' : 'unverified' };
  }
  const COLLEGE_SORTS = ['sno', 'name', 'district', 'ambassadors', 'unassigned', 'enrolled', 'pct', 'target'];
  function listColleges(q) {
    const ctx = getCtx();
    let rows = [...ctx.colleges.values()];
    const f = (k) => q.get(k);
    const ds = districtSet(q); if (ds) rows = rows.filter((c) => ds.has(c.district_id));
    if (f('district')) rows = rows.filter((c) => c.district_id === f('district'));
    if (f('city')) rows = rows.filter((c) => c.city_id === f('city'));
    const ops = oneOf(q, 'op_status', ['operational', 'possibly_closed', 'closed', 'pending']); if (ops) rows = rows.filter((c) => ops.has(c.op_status)); // v4.1 (BE-15)
    if (f('targeted') !== null && f('targeted') !== '') rows = rows.filter((c) => String(c.targeted) === (['1', 'true', 'yes'].includes(f('targeted')) ? '1' : '0'));
    if (f('branch_code')) { const code = f('branch_code').toUpperCase(); rows = rows.filter((c) => (ctx.branchesByCollege.get(c.id) || []).some((b) => b.code.toUpperCase() === code)); }
    const m = makeMatcher(q.get('q'));
    if (m) rows = rows.filter((c) => m.q === String(c.sno) || m.q === c.id || m.best(collegeTexts(ctx, c)) > 0);
    // calling filters (validated): call_status, contact, priority. Priority is used only to filter, never returned in list rows.
    const cs = oneOf(q, 'call_status', CALL_STATUSES);
    const cf = oneOf(q, 'contact', CONTACT_FILTERS);
    const pr = oneOf(q, 'priority', PRIORITY_TIERS);
    if (cs || cf || pr) rows = rows.filter((c) => { const i = collegeCallInfo(ctx, c); return (!cs || cs.has(i.call_status)) && (!cf || [...cf].some((f) => contactFilter(i, f))) && (!pr || pr.has(i.priority.tier)); });
    let out = rows.map((c) => { const i = collegeCallInfo(ctx, c); return { ...collegeRow(ctx, c), call_status: i.call_status, contact_counts: i.contact_counts }; });
    if (f('exam_state')) { const set = new Set(f('exam_state').split(',')); out = out.filter((r) => set.has(r.exam_state)); }
    if (f('amb') === 'gap') out = out.filter((r) => r.branches_needing_ambassadors > 0);
    if (f('amb') === 'ok') out = out.filter((r) => r.branches_relevant > 0 && r.branches_needing_ambassadors === 0);
    if (f('progress')) out = out.filter((r) => progressBucket(r) === f('progress'));
    if (f('diagnosis')) {
      const DX = ['ambassador_gap', 'low_outreach', 'low_conversion', 'unrealistic_target', 'behind_pace'];
      const set = new Set(f('diagnosis').split(',').map((x) => x.trim()).filter(Boolean));
      const badDx = [...set].filter((x) => !DX.includes(x));
      if (badDx.length) throw bad({ diagnosis: `Must be one or more of: ${DX.join(', ')}` });
      out = out.filter((r) => set.has(r.diagnosis));
    }
    // v4: data_status + team filter (R3) + verified filter, sort, optional paging envelope
    out = out.map((r) => ({ ...r, data_status: verificationOf(ctx.colleges.get(r.id)).data_status }));
    const team = oneOf(q, 'team', ['no_lead', 'has_lead', 'no_ambassadors', 'has_team', 'has_unassigned']);
    if (team) out = out.filter((r) => (team.has('no_lead') && !r.lead) || (team.has('has_lead') && !!r.lead) || (team.has('no_ambassadors') && r.ambassador_count === 0)
      || (team.has('has_team') && !!r.lead && r.ambassador_count > 0) || (team.has('has_unassigned') && r.unassigned_count > 0));
    const ver = oneOf(q, 'verified', ['verified', 'partly', 'unverified']); if (ver) out = out.filter((r) => ver.has(r.data_status));
    const sortRaw = q.get('sort');
    if (sortRaw) {
      const desc = sortRaw.startsWith('-'); const key = sortRaw.replace(/^-/, '');
      if (!COLLEGE_SORTS.includes(key)) throw bad({ sort: `Must be one of: ${COLLEGE_SORTS.join(', ')} (prefix - for descending)` });
      const v = (r) => ({ sno: r.sno, name: r.short_name || r.name, district: ctx.districts.get(r.district_id)?.name || '', ambassadors: r.ambassador_count,
        unassigned: r.unassigned_count, enrolled: r.enrolled, pct: r.pct ?? -1, target: r.target ?? -1 }[key]);
      out.sort((a, b) => { const x = v(a); const y = v(b); const c = typeof x === 'number' ? x - y : String(x).localeCompare(String(y)); return (desc ? -c : c) || a.sno - b.sno; });
    }
    if (q.has('page') || q.has('page_size')) {
      const pageSize = lim(q.get('page_size'), 50, 200); const page = lim(q.get('page'), 1, 100000);
      return { items: out.slice((page - 1) * pageSize, page * pageSize), total: out.length, page, page_size: pageSize };
    }
    return out;
  }

  function collegeDetail(id) {
    const ctx = getCtx();
    const c = ctx.colleges.get(id);
    if (!c) throw notFound(`College ${id} not found`);
    const sc = { type: 'college', id };
    const branches = ctx.branchesByCollege.get(id) || [];
    const people = (ctx.peopleByCollege.get(id) || []).map((p) => peopleRow(ctx, p));
    const bIds = branches.map((b) => b.id);
    const pIds = (ctx.peopleByCollege.get(id) || []).map((p) => p.id);
    const fu = db.prepare(`SELECT * FROM followups WHERE (scope_type = 'college' AND scope_id = ?)
      OR (scope_type = 'branch' AND scope_id IN (SELECT CAST(id AS TEXT) FROM branches WHERE college_id = ?))
      OR (scope_type = 'person' AND scope_id IN (SELECT CAST(id AS TEXT) FROM people WHERE college_id = ?))
      ORDER BY status = 'done', due_date IS NULL, due_date`).all(id, id, id).map((f) => decorateFollowup(ctx, f));
    const audit = db.prepare(`SELECT * FROM audit_log WHERE (entity = 'college' AND entity_id = ?)
      OR (entity = 'branch' AND entity_id IN (SELECT CAST(id AS TEXT) FROM branches WHERE college_id = ?))
      OR (entity = 'exam' AND entity_id IN (SELECT CAST(id AS TEXT) FROM exams WHERE college_id = ?))
      OR (entity = 'contact' AND entity_id IN (SELECT CAST(id AS TEXT) FROM contacts WHERE college_id = ?))
      OR (entity = 'call' AND entity_id IN (SELECT CAST(id AS TEXT) FROM calls WHERE college_id = ?))
      ORDER BY id DESC LIMIT 20`).all(id, id, id, id, id).map(parseAudit);
    const callInfo = collegeCallInfo(ctx, c);
    return {
      college: { ...c, aliases: safeJson(c.aliases), city_name: ctx.cities.get(c.city_id)?.name ?? null, district_name: ctx.districts.get(c.district_id)?.name ?? null, ...verificationOf(c) },
      rollup: summary(ctx, sc),
      branches: branches.map((b) => ({
        ...b, active_ambassadors: activeAmbassadorCount(ctx, b.id), rollup: summary(ctx, { type: 'branch', id: String(b.id) }),
        people: (ctx.peopleOfBranch.get(b.id) || []).map((pid) => ctx.people.get(pid)).filter(Boolean).map(personLite),
      })),
      people,
      exams: ctx.examRows.get(id) || [],
      exam: ctx.exam.get(id),
      followups: fu,
      recent_activities: db.prepare('SELECT a.*, p.full_name AS person_name, b.code AS branch_code FROM activities a LEFT JOIN people p ON p.id = a.person_id LEFT JOIN branches b ON b.id = a.branch_id WHERE a.college_id = ? ORDER BY a.on_date DESC, a.id DESC LIMIT 20').all(id),
      recent_enrollments: db.prepare('SELECT e.*, p.full_name AS person_name, b.code AS branch_code, c.name AS course_name FROM enrollments e LEFT JOIN people p ON p.id = e.person_id LEFT JOIN branches b ON b.id = e.branch_id LEFT JOIN courses c ON c.id = e.course_id WHERE e.college_id = ? ORDER BY e.enrolled_on DESC, e.id DESC LIMIT 20').all(id),
      audit,
      contacts: (callsCtx(ctx).contactsByCollege.get(id) || []).map((k) => contactRow(ctx, k)),
      calls: db.prepare(`${callDetailSql} WHERE x.college_id = ? ORDER BY x.called_at DESC, x.id DESC LIMIT 100`).all(id),
      call_info: callInfo,
      funnel: funnelOut(ctx, sc),
      _ids: { branches: bIds, people: pIds },
    };
  }

  function branchDetail(id) {
    const ctx = getCtx();
    const b = ctx.branches.get(Number(id));
    if (!b) throw notFound(`Branch ${id} not found`);
    const c = ctx.colleges.get(b.college_id);
    return {
      branch: { ...b, college_name: c?.name, college_short_name: c?.short_name, active_ambassadors: activeAmbassadorCount(ctx, b.id) },
      rollup: summary(ctx, { type: 'branch', id: String(b.id) }),
      people: (ctx.peopleOfBranch.get(b.id) || []).map((pid) => ctx.people.get(pid)).filter(Boolean).map((p) => peopleRow(ctx, p)),
      followups: db.prepare("SELECT * FROM followups WHERE scope_type = 'branch' AND scope_id = ? ORDER BY status = 'done', due_date").all(String(b.id)).map((f) => decorateFollowup(ctx, f)),
      activities: db.prepare('SELECT a.*, p.full_name AS person_name FROM activities a LEFT JOIN people p ON p.id = a.person_id WHERE a.branch_id = ? ORDER BY on_date DESC, a.id DESC LIMIT 100').all(b.id),
      enrollments: db.prepare('SELECT e.*, p.full_name AS person_name, c.name AS course_name FROM enrollments e LEFT JOIN people p ON p.id = e.person_id LEFT JOIN courses c ON c.id = e.course_id WHERE e.branch_id = ? ORDER BY enrolled_on DESC, e.id DESC LIMIT 200').all(b.id),
    };
  }

  /** v4: tel / WhatsApp / mailto links for a person or contact. */
  const contactLinks = (phone, email) => {
    const n = phone ? normPhone(phone) : null;
    return { tel: n ? `tel:${n}` : null, whatsapp: n && isMobile(n) ? `https://wa.me/${n.slice(1)}` : null, mailto: email ? `mailto:${email}` : null };
  };
  function peopleRow(ctx, p) {
    const r = personRollup(ctx, p.id);
    const col = ctx.colleges.get(p.college_id);
    const mgr = p.reports_to != null ? ctx.people.get(p.reports_to) : null;
    const a = assignmentOf(ctx, p);
    const team = r.team; // non-inactive subtree block (or null)
    return {
      ...p, college_name: col?.name ?? null, college_short_name: col?.short_name ?? null, district_id: col?.district_id ?? null,
      branches: (ctx.branchesOfPerson.get(p.id) || []).map((id) => ctx.branches.get(id)).filter(Boolean).map(branchLite),
      branch_ids: ctx.branchesOfPerson.get(p.id) || [],
      reports_to_name: mgr?.full_name ?? null,
      reports: (ctx.reportsOf.get(p.id) || []).map(personLite),
      target: r.target, reached: r.reached, enrolled: r.enrolled, remaining: r.remaining, pct: r.pct, on_track: r.on_track,
      diagnosis: r.diagnosis, team_target: r.team_target, team_enrolled: r.team_enrolled, next_followup: r.next_followup,
      // v4 (R3, R6, R9)
      college: col ? { id: col.id, name: col.name, short_name: col.short_name, district_id: col.district_id } : null,
      lead: mgr ? { id: mgr.id, name: mgr.full_name, role: mgr.role, status: mgr.status } : null,
      assignment_status: a.assignment_status, assignment_issue: a.assignment_issue,
      phone_norm: p.phone ? normPhone(p.phone) : null, links: contactLinks(p.phone, p.email),
      team_size: r.team_size, actual_own: r.enrolled, actual_team: team ? team.actual : 0, actual_combined: r.enrolled + (team ? team.actual : 0),
      target_summary: { min: r.target_min, target: r.target, max: r.target_max, remaining: r.own.remaining, exceeded_by: r.own.exceeded_by, pct: r.own.pct, status: r.own.status },
    };
  }

  const PEOPLE_SORTS = ['name', 'college', 'role', 'status', 'joined_on', 'actual', 'pct', 'assignment'];
  const ROLE_ORDER = { college_lead: 0, ambassador_lead: 1, ambassador: 2 };
  function listPeople(q) {
    const ctx = getCtx();
    let rows = [...ctx.people.values()];
    const m = makeMatcher(q.get('q'));
    const roles = oneOf(q, 'role', ['college_lead', 'ambassador_lead', 'ambassador']); if (roles) rows = rows.filter((p) => roles.has(p.role));
    const col = q.get('college_id') || q.get('college');
    if (col) rows = rows.filter((p) => p.college_id === col);
    if (q.get('district')) rows = rows.filter((p) => ctx.colleges.get(p.college_id)?.district_id === q.get('district'));
    const ds = districtSet(q); if (ds) rows = rows.filter((p) => ds.has(ctx.colleges.get(p.college_id)?.district_id));
    if (q.get('branch')) rows = rows.filter((p) => (ctx.branchesOfPerson.get(p.id) || []).includes(Number(q.get('branch'))));
    const sts = oneOf(q, 'status', ['active', 'onboarding', 'inactive']); if (sts) rows = rows.filter((p) => sts.has(p.status));
    const rt = q.get('reports_to');
    if (rt) rows = rows.filter((p) => (rt === 'none' ? p.reports_to == null : String(p.reports_to) === rt));
    const asg = oneOf(q, 'assignment', ['assigned', 'unassigned', 'invalid_link']);
    if (asg) rows = rows.filter((p) => (sts || p.status !== 'inactive') && asg.has(assignmentOf(ctx, p).assignment_status));
    if (m) rows = rows.filter((p) => { const c = ctx.colleges.get(p.college_id); return phoneHit(p.phone, q.get('q')) || m.best([p.full_name, p.email, c?.short_name, c?.name]) > 0; });
    const paged = q.has('page') || q.has('page_size');
    const sortRaw = q.get('sort');
    if (!paged && !sortRaw) return rows.map((p) => peopleRow(ctx, p)); // v1 shape: plain array, name order
    let out = rows.map((p) => peopleRow(ctx, p));
    if (sortRaw) {
      const desc = sortRaw.startsWith('-'); const key = sortRaw.replace(/^-/, '');
      if (!PEOPLE_SORTS.includes(key)) throw bad({ sort: `Must be one of: ${PEOPLE_SORTS.join(', ')} (prefix - for descending)` });
      const v = (r) => ({ name: r.full_name, college: r.college_short_name || r.college_name || '', role: ROLE_ORDER[r.role], status: r.status, joined_on: r.joined_on || '',
        actual: r.actual_own, pct: r.target_summary.pct ?? -1, assignment: r.assignment_status || '' }[key]);
      out.sort((a, b) => { const x = v(a); const y = v(b); const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? '')); return (desc ? -c : c) || String(a.full_name).localeCompare(String(b.full_name)); });
    }
    if (!paged) return out;
    // v4.1 (F4/D9): counts follow the same rule as the assignment filter: inactive people are left out unless status= is given
    // (counts.inactive says how many were left out). A role segment that should match its count sends status=active,onboarding.
    const counts = { assigned: 0, unassigned: 0, invalid_link: 0, college_lead: 0, ambassador_lead: 0, ambassador: 0, inactive: 0 };
    for (const r of out) { if (!sts && r.status === 'inactive') { counts.inactive++; continue; } if (r.assignment_status) counts[r.assignment_status]++; counts[r.role]++; }
    const pageSize = lim(q.get('page_size'), 50, 200);
    const page = lim(q.get('page'), 1, 100000);
    return { items: out.slice((page - 1) * pageSize, page * pageSize), total: out.length, page, page_size: pageSize, counts };
  }
  function personDetail(id) {
    const ctx = getCtx();
    const p = ctx.people.get(Number(id));
    if (!p) throw notFound(`Person ${id} not found`);
    const row = peopleRow(ctx, p);
    return {
      person: row, college: ctx.colleges.get(p.college_id) || null,
      branches: row.branches, reports: (ctx.reportsOf.get(p.id) || []).map((x) => peopleRow(ctx, x)),
      rollup: personRollup(ctx, p.id),
      activities: db.prepare('SELECT a.*, b.code AS branch_code FROM activities a LEFT JOIN branches b ON b.id = a.branch_id WHERE a.person_id = ? ORDER BY on_date DESC, a.id DESC LIMIT 100').all(p.id),
      enrollments: db.prepare('SELECT e.*, b.code AS branch_code, c.name AS course_name FROM enrollments e LEFT JOIN branches b ON b.id = e.branch_id LEFT JOIN courses c ON c.id = e.course_id WHERE e.person_id = ? ORDER BY enrolled_on DESC, e.id DESC LIMIT 200').all(p.id),
      followups: db.prepare("SELECT * FROM followups WHERE (scope_type = 'person' AND scope_id = ?) OR owner_person_id = ? ORDER BY status = 'done', due_date").all(String(p.id), p.id).map((f) => decorateFollowup(ctx, f)),
    };
  }

  function search(q) {
    const ctx = getCtx();
    const m = makeMatcher(q.get('q'));
    if (!m) return [];
    const limit = lim(q.get('limit'), 20, 100);
    const score = m.score;
    const out = [];
    for (const d of ctx.districts.values()) {
      let s = Math.max(score(d.name), score(d.id)); let sub = 'District';
      if (!s && d.old_district && score(d.old_district) >= 60) { s = 45; sub = `District · formerly part of ${d.old_district}`; } // pre-2022 district names
      if (s) out.push({ type: 'district', id: d.id, label: d.name, sub, href: hrefFor(ctx, 'district', d.id), _s: s + 5 });
    }
    for (const c of ctx.cities.values()) { const s0 = score(c.name); const s = s0 >= 60 || m.allWords([c.name]) ? s0 || 30 : 0; if (s) out.push({ type: 'city', id: c.id, label: c.name, sub: `Town · ${ctx.districts.get(c.district_id)?.name ?? ''}`, href: hrefFor(ctx, 'city', c.id), _s: s + 3 }); }
    for (const c of ctx.colleges.values()) {
      const own = [c.name, c.short_name, ...aliasList(c.aliases)];
      let s = Math.max(...own.map(score), m.q === String(c.sno) || m.q === c.id ? 100 : 0);
      if (!s && m.tokens.length > 1 && m.allWords(collegeTexts(ctx, c))) s = 30; // e.g. "engineering guntur"
      if (s) out.push({ type: 'college', id: c.id, label: c.short_name ? `${c.short_name} — ${c.name}` : c.name, sub: [ctx.cities.get(c.city_id)?.name, ctx.districts.get(c.district_id)?.name].filter(Boolean).join(', '), href: hrefFor(ctx, 'college', c.id), _s: s + 4 });
    }
    for (const b of ctx.branches.values()) {
      const c = ctx.colleges.get(b.college_id);
      let s = Math.max(score(b.code), score(b.name));
      if (s < 60) s = m.tokens.length > 1 && m.allWords([b.code, b.name, c?.short_name, c?.name]) ? 30 : 0; // e.g. "cse vignan"
      if (s) out.push({ type: 'branch', id: b.id, label: `${b.code}${b.name ? ` · ${b.name}` : ''}`, sub: c?.short_name || c?.name || '', href: hrefFor(ctx, 'branch', b.id), _s: s });
    }
    for (const p of ctx.people.values()) {
      const c = ctx.colleges.get(p.college_id);
      let s = Math.max(score(p.full_name), phoneHit(p.phone, q.get('q')) ? 50 : 0, score(p.email));
      if (!s && m.tokens.length > 1 && m.allWords([p.full_name, c?.short_name, c?.name])) s = 25; // e.g. "anil kl"
      if (s) { const lead = p.reports_to != null ? ctx.people.get(p.reports_to)?.full_name : null; const tail = p.phone ? String(p.phone).replace(/D/g, '').slice(-4) : null;
        out.push({ type: 'person', id: p.id, label: p.full_name, sub: [`${p.role.replace(/_/g, ' ')} · ${c?.short_name || c?.name || ''}`, lead ? `reports to ${lead}` : null, tail ? `…${tail}` : null, p.status === 'inactive' ? 'inactive' : null].filter(Boolean).join(' · '), href: hrefFor(ctx, 'person', p.id), _s: s + 2 }); }
    }
    return out.sort((a, b) => b._s - a._s || String(a.label).localeCompare(String(b.label))).slice(0, limit).map(({ _s, ...r }) => r);
  }

  function leaderboard(q) {
    const ctx = getCtx();
    const level = q.get('level') || 'college';
    if (!['district', 'city', 'college', 'branch', 'person'].includes(level)) throw bad({ level: 'Must be district, city, college, branch or person' });
    const sc = scopeFromQuery(q);
    const limit = lim(q.get('limit'), 10, 500);
    let rows = [];
    const cols = scopeColleges(ctx, sc);
    if (level === 'district') {
      const ids = sc.type === 'state' ? [...ctx.districts.keys()].filter((id) => !sc.districts || sc.districts.has(id)) : [...new Set(cols.map((c) => c.district_id).filter(Boolean))];
      rows = ids.map((id) => lbRow(summary(ctx, { type: 'district', id }), 'district', id));
    } else if (level === 'city') {
      const ids = [...new Set(cols.map((c) => c.city_id).filter((id) => id && ctx.cities.has(id)))];
      rows = ids.map((id) => lbRow(summary(ctx, { type: 'city', id }), 'city', id));
    } else if (level === 'college') {
      rows = cols.map((c) => lbRow(summary(ctx, { type: 'college', id: c.id }), 'college', c.id));
    } else if (level === 'branch') {
      rows = scopeBranches(ctx, sc).map((b) => lbRow(summary(ctx, { type: 'branch', id: String(b.id) }), 'branch', b.id));
    } else {
      rows = scopePeople(ctx, sc).map((p) => { const r = personRollup(ctx, p.id); const c = ctx.colleges.get(p.college_id); return { ...lbRow(r, 'person', p.id), sub: `${p.role.replace('_', ' ')} · ${c?.short_name || c?.name || ''}`, role: p.role }; });
    }
    if (q.get('only_with_target') === '1') rows = rows.filter((r) => r.target);
    rows.sort((a, b) => (b.pct ?? -1) - (a.pct ?? -1) || b.enrolled - a.enrolled || b.reached - a.reached || String(a.label).localeCompare(String(b.label)));
    return rows.slice(0, limit).map((r, i) => ({ rank: i + 1, ...r }));
  }
  function lbRow(s, type, id) {
    return { type, id, label: s.label, href: s.href, target: s.target, target_source: s.target_source, enrolled: s.enrolled, reached: s.reached, remaining: s.remaining, pct: s.pct, on_track: s.on_track, diagnosis: s.diagnosis };
  }

  function attention(q) {
    const ctx = getCtx();
    const sc = scopeFromQuery(q);
    const limit = lim(q.get('limit'), 200, 1000);
    const SEV = { high: 3, medium: 2, low: 1 };
    const items = [];
    // Until the first college lead exists anywhere, 'no lead' on every targeted college is noise: report it once, grouped.
    const anyLead = [...ctx.people.values()].some((p) => p.role === 'college_lead' && p.status !== 'inactive');
    let noLead = 0;
    const anyAmb = [...ctx.people.values()].some((p) => p.role === 'ambassador' && p.status !== 'inactive');
    let noAmb = 0; let noAmbBranches = 0;
    for (const c of scopeColleges(ctx, sc)) {
      const s = summary(ctx, { type: 'college', id: c.id });
      const ex = ctx.exam.get(c.id);
      const reasons = []; let sev = null;
      const up = (lvl) => { if (!sev || SEV[lvl] > SEV[sev]) sev = lvl; };
      const active = c.targeted || s.target != null;
      if (s.on_track === false) { reasons.push(`Behind pace: ${num(s.enrolled)} of ${num(s.target)} enrolled (expected ~${num(Math.round(s.expected_now))} by now)`); up('high'); }
      if (s.followups_overdue) { reasons.push(`${s.followups_overdue} overdue follow-up${s.followups_overdue > 1 ? 's' : ''}`); up('high'); }
      if (active && s.branches_needing_ambassadors && !anyAmb) { noAmb++; noAmbBranches += s.branches_needing_ambassadors; } else if (active && s.branches_needing_ambassadors) { reasons.push(`${s.branches_needing_ambassadors} relevant branch${s.branches_needing_ambassadors > 1 ? 'es' : ''} without an active ambassador`); up('medium'); }
      if (active && c.op_status === 'operational' && s.college_leads === 0) { if (anyLead) { reasons.push('No college lead appointed'); up('medium'); } else noLead++; }
      if (active && ex.exam_state === 'exams_soon' && ex.next_exam) { reasons.push(`${ex.next_exam.semester} ${EXAM_KIND[ex.next_exam.kind] || ex.next_exam.kind} start ${dmy(ex.next_exam.start)}`); up('low'); }
      if (active && ex.exam_state === 'in_exams' && s.target != null) { reasons.push(ex.next_exam?.end ? `In exams until ${dmy(ex.next_exam.end)}` : 'In exams now'); up('low'); }
      if (reasons.length) items.push({ type: 'college', id: c.id, label: c.short_name || c.name, href: hrefFor(ctx, 'college', c.id), reasons, diagnosis: s.diagnosis, severity: sev, severity_rank: SEV[sev], exam_state: ex.exam_state, district_id: c.district_id });
    }
    for (const p of scopePeople(ctx, sc)) {
      const r = personRollup(ctx, p.id);
      if (r.on_track === false) items.push({ type: 'person', id: p.id, label: p.full_name, href: r.href, reasons: [`Behind pace: ${num(r.enrolled)} of ${num(r.target)} enrolled`], diagnosis: r.diagnosis, severity: 'medium', severity_rank: 2 });
    }
    if (noLead) items.push({ type: 'group', id: 'no_college_leads', label: 'No college leads appointed yet', href: '#/colleges?team=no_lead&targeted=1', reasons: [`${num(noLead)} targeted college${noLead === 1 ? '' : 's'} ${noLead === 1 ? 'has' : 'have'} no college lead. Appoint the first lead to start tracking them per college.`], diagnosis: null, severity: 'low', severity_rank: 1, count: noLead });
    if (noAmb) items.push({ type: 'group', id: 'no_ambassadors', label: 'No ambassadors appointed yet', href: '#/colleges?amb=gap&targeted=1', reasons: [`${num(noAmbBranches)} relevant branch${noAmbBranches === 1 ? '' : 'es'} across ${num(noAmb)} targeted college${noAmb === 1 ? '' : 's'} need an ambassador. Add ambassadors to start tracking gaps per college.`], diagnosis: 'ambassador_gap', severity: 'low', severity_rank: 1, count: noAmb, branches: noAmbBranches });
    items.sort((a, b) => b.severity_rank - a.severity_rank || b.reasons.length - a.reasons.length || String(a.label).localeCompare(String(b.label)));
    return items.slice(0, limit);
  }

  function decorateFollowup(ctx, f) {
    const sc = { type: f.scope_type, id: f.scope_id };
    let collegeId = null;
    if (f.scope_type === 'college') collegeId = f.scope_id;
    else if (f.scope_type === 'branch') collegeId = ctx.branches.get(Number(f.scope_id))?.college_id ?? null;
    else collegeId = ctx.people.get(Number(f.scope_id))?.college_id ?? null;
    return {
      ...f, scope_label: scopeExists(ctx, sc) ? scopeLabel(ctx, sc) : f.scope_id, href: hrefFor(ctx, f.scope_type, f.scope_id),
      college_id: collegeId, district_id: ctx.colleges.get(collegeId)?.district_id ?? null,
      overdue: f.status === 'open' && !!f.due_date && f.due_date < ctx.today,
      days_until_due: daysBetween(ctx.today, f.due_date),
    };
  }

  function listFollowups(q) {
    const ctx = getCtx();
    let rows = db.prepare('SELECT * FROM followups ORDER BY status = \'done\', due_date IS NULL, due_date, id').all().map((f) => decorateFollowup(ctx, f));
    if (q.get('status')) { if (!['open', 'done'].includes(q.get('status'))) throw bad({ status: 'Must be open or done' }); rows = rows.filter((f) => f.status === q.get('status')); }
    const due = q.get('due');
    if (due === 'overdue') rows = rows.filter((f) => f.overdue);
    else if (due === 'today') rows = rows.filter((f) => f.status === 'open' && f.due_date === ctx.today);
    else if (due === 'week') rows = rows.filter((f) => f.status === 'open' && f.due_date && f.due_date <= addDays(ctx.today, 7));
    else if (due === 'fortnight') rows = rows.filter((f) => f.status === 'open' && f.due_date && f.due_date <= addDays(ctx.today, 14));
    else if (due) throw bad({ due: 'Must be overdue, today, week or fortnight' });
    if (q.get('scope') && q.get('scope') !== 'state') {
      const sc = scopeFromQuery(q);
      if (sc.type === 'person') rows = rows.filter((f) => (f.scope_type === 'person' && f.scope_id === sc.id) || String(f.owner_person_id) === sc.id);
      else if (sc.type === 'branch') rows = rows.filter((f) => f.scope_type === 'branch' && f.scope_id === sc.id);
      else { const set = new Set(scopeColleges(ctx, sc).map((c) => c.id)); rows = rows.filter((f) => set.has(f.college_id)); }
    }
    const ds = districtSet(q); if (ds) rows = rows.filter((f) => ds.has(f.district_id));
    if (q.get('owner')) { const o = q.get('owner'); rows = rows.filter((f) => String(f.owner_person_id) === o || (f.owner_name || '').toLowerCase() === o.toLowerCase()); }
    if (q.get('issue')) rows = rows.filter((f) => f.issue === q.get('issue'));
    return rows;
  }

  function listExams(q) {
    const ctx = getCtx();
    let cols = [...ctx.colleges.values()];
    const ds = districtSet(q); if (ds) cols = cols.filter((c) => ds.has(c.district_id));
    if (q.get('district')) cols = cols.filter((c) => c.district_id === q.get('district'));
    if (q.get('targeted')) cols = cols.filter((c) => String(c.targeted) === q.get('targeted'));
    let rows = cols.map((c) => ({ college_id: c.id, sno: c.sno, name: c.name, short_name: c.short_name, district_id: c.district_id, city_id: c.city_id, targeted: c.targeted, op_status: c.op_status, ...ctx.exam.get(c.id), rows: ctx.examRows.get(c.id) || [] }));
    if (q.get('state')) { const s = new Set(q.get('state').split(',')); rows = rows.filter((r) => s.has(r.exam_state)); }
    return rows;
  }

  function timeseries(q) {
    const ctx = getCtx();
    const sc = scopeFromQuery(q);
    const days = Math.min(Math.max(Number(q.get('days')) || 60, 1), 730);
    const from = addDays(ctx.today, -(days - 1));
    let where = ''; let params = [];
    if (sc.type === 'branch') { where = 'AND branch_id = ?'; params = [Number(sc.id)]; }
    else if (sc.type === 'person') { where = 'AND person_id = ?'; params = [Number(sc.id)]; }
    else if (sc.type !== 'state' || sc.districts) { const ids = scopeColleges(ctx, sc).map((c) => c.id); where = ids.length ? `AND college_id IN (${ids.map(() => '?').join(',')})` : 'AND 0'; params = ids; }
    // confirmed enrollments only, on the date they were confirmed
    const e = new Map(db.prepare(`SELECT COALESCE(confirmed_on, enrolled_on) d, COUNT(*) n FROM enrollments WHERE stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) >= ? AND COALESCE(confirmed_on, enrolled_on) <= ? ${where} GROUP BY d`).all(from, ctx.today, ...params).map((r) => [r.d, Number(r.n)]));
    const a = new Map(db.prepare(`SELECT on_date d, SUM(students_reached) n FROM activities WHERE on_date >= ? AND on_date <= ? ${where} GROUP BY on_date`).all(from, ctx.today, ...params).map((r) => [r.d, Number(r.n)]));
    const out = []; let ce = 0; let cr = 0;
    for (let i = 0; i < days; i++) {
      const d = addDays(from, i); const en = e.get(d) || 0; const re = a.get(d) || 0; ce += en; cr += re;
      out.push({ date: d, enrolled: en, reached: re, cum_enrolled: ce, cum_reached: cr });
    }
    return out;
  }

  function quality(q) {
    const ctx = getCtx();
    const ds = districtSet(q);
    const cols = [...ctx.colleges.values()].filter((c) => !ds || ds.has(c.district_id));
    const m = (field, pred, label) => { const ids = cols.filter(pred).map((c) => c.id); return { field, label, count: ids.length, college_ids: ids }; };
    const brOf = (c) => ctx.branchesByCollege.get(c.id) || [];
    const missing = [
      m('location', (c) => c.geo_precision === 'pending' || c.geo_precision === 'district' || c.lat == null, 'Exact/town location pending'),
      m('city_id', (c) => !c.city_id, 'Town not set'),
      m('website', (c) => !c.website, 'Website missing'),
      m('phone', (c) => !c.phone, 'Phone missing'),
      m('email', (c) => !c.email, 'Email missing'),
      m('branches', (c) => c.op_status !== 'closed' && brOf(c).length === 0, 'No branches recorded'),
      m('intake', (c) => brOf(c).some((b) => b.intake_per_year == null), 'Branch intake unknown'),
      m('op_status', (c) => c.op_status === 'pending' || c.op_status === 'possibly_closed', 'Operating status unconfirmed'),
      m('op_2026_27', (c) => !c.op_2026_27 || c.op_2026_27 === 'unknown', '2026-27 admissions unconfirmed'),
      m('exams', (c) => ctx.exam.get(c.id).exam_state === 'unknown', 'Exam dates unknown'),
      m('college_lead', (c) => c.targeted && !(ctx.peopleByCollege.get(c.id) || []).some((p) => p.role === 'college_lead' && p.status !== 'inactive'), 'Targeted college without a lead'),
    ];
    const basis_counts = { verified: 0, estimated: 0, pending: 0 };
    const by_field = {};
    for (const b of ctx.branches.values()) {
      if (ds && !ds.has(ctx.colleges.get(b.college_id)?.district_id)) continue;
      for (const k of ['intake_basis', 'strength_basis', 'final_year_basis', 'eligible_basis']) {
        const v = b[k] || 'pending'; basis_counts[v] = (basis_counts[v] || 0) + 1;
        by_field[k] = by_field[k] || { verified: 0, estimated: 0, pending: 0 }; by_field[k][v]++;
      }
    }
    const geo = { exact: 0, town: 0, district: 0, pending: 0 };
    for (const c of cols) geo[c.geo_precision] = (geo[c.geo_precision] || 0) + 1;
    // v4 (R13): college verification state + data integrity checks (should all be 0)
    const verification = { verified: 0, partly: 0, unverified: 0 };
    for (const c of cols) verification[verificationOf(c).data_status]++;
    const contacts_basis = { verified: 0, pending: 0 };
    for (const k of callsCtx(ctx).contacts) if (!ds || ds.has(ctx.colleges.get(k.college_id)?.district_id)) contacts_basis[k.basis] = (contacts_basis[k.basis] || 0) + 1;
    return { missing, basis_counts, basis_by_field: by_field, geo_precision: geo, colleges: cols.length, branches: cols.reduce((s, c) => s + brOf(c).length, 0),
      districts_filter: ds ? [...ds] : null, verification, contacts_basis, integrity: integrity() };
  }

  function auditList(q) {
    const where = []; const p = [];
    if (q.get('entity')) { where.push('entity = ?'); p.push(q.get('entity')); }
    if (q.get('entity_id')) { where.push('entity_id = ?'); p.push(q.get('entity_id')); }
    if (q.get('actor')) { where.push('actor = ?'); p.push(q.get('actor')); }
    if (q.get('action')) { where.push('action = ?'); p.push(q.get('action')); }
    // from/to: inclusive YYYY-MM-DD bounds on the entry date; offset: paging through older entries
    if (q.get('from')) { if (!isDate(q.get('from'))) throw bad({ from: 'Use a date like 2026-11-01' }); where.push('at >= ?'); p.push(q.get('from')); }
    if (q.get('to')) { if (!isDate(q.get('to'))) throw bad({ to: 'Use a date like 2026-11-30' }); where.push('at < ?'); p.push(addDays(q.get('to'), 1)); }
    const limit = lim(q.get('limit'), 100, 1000);
    const offset = Math.max(Math.trunc(Number(q.get('offset'))) || 0, 0);
    return db.prepare(`SELECT * FROM audit_log ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY id DESC LIMIT ? OFFSET ?`).all(...p, limit, offset).map(parseAudit);
  }
  /** v4 (UI-30): distinct audit actors for the audit filter. */
  const auditActors = () => db.prepare('SELECT actor, COUNT(*) n, MAX(at) last_at FROM audit_log GROUP BY actor ORDER BY last_at DESC').all().map((r) => ({ actor: r.actor, n: Number(r.n), last_at: r.last_at }));

  /** v4: relationship integrity counters (all 0 on healthy data); shown in /api/quality and used by the self-test. */
  function integrity() {
    const n = (sql) => Number(db.prepare(sql).get().n);
    const link = 'FROM people p JOIN people m ON m.id = p.reports_to';
    return {
      reports_to_other_college: n(`SELECT COUNT(*) n ${link} WHERE m.college_id IS NOT p.college_id AND p.status <> 'inactive'`),
      reports_to_bad_role: n(`SELECT COUNT(*) n ${link} WHERE p.status <> 'inactive' AND (p.role = 'college_lead' OR (p.role = 'ambassador_lead' AND m.role <> 'college_lead') OR (p.role = 'ambassador' AND m.role NOT IN ('college_lead','ambassador_lead')))`),
      reports_to_inactive: n(`SELECT COUNT(*) n ${link} WHERE p.status <> 'inactive' AND m.status = 'inactive'`),
      multi_college_leads: n("SELECT COUNT(*) n FROM (SELECT college_id FROM people WHERE role = 'college_lead' AND status <> 'inactive' GROUP BY college_id HAVING COUNT(*) > 1)"),
      dup_people_phone: n("SELECT COUNT(*) n FROM (SELECT phone FROM people WHERE phone IS NOT NULL AND status <> 'inactive' GROUP BY phone HAVING COUNT(*) > 1)"),
      dup_people_email: n("SELECT COUNT(*) n FROM (SELECT email FROM people WHERE email IS NOT NULL AND status <> 'inactive' GROUP BY email HAVING COUNT(*) > 1)"),
      person_branch_wrong_college: n('SELECT COUNT(*) n FROM person_branches pb JOIN people p ON p.id = pb.person_id JOIN branches b ON b.id = pb.branch_id WHERE b.college_id <> p.college_id'),
      enroll_person_other_college: n('SELECT COUNT(*) n FROM enrollments e JOIN people p ON p.id = e.person_id WHERE p.college_id <> e.college_id'),
      targets_orphan_scope: n(`SELECT COUNT(*) n FROM targets t WHERE (t.scope_type = 'person' AND NOT EXISTS (SELECT 1 FROM people x WHERE CAST(x.id AS TEXT) = t.scope_id))
        OR (t.scope_type = 'branch' AND NOT EXISTS (SELECT 1 FROM branches x WHERE CAST(x.id AS TEXT) = t.scope_id))
        OR (t.scope_type = 'college' AND NOT EXISTS (SELECT 1 FROM colleges x WHERE x.id = t.scope_id))`),
      followups_orphan_scope: n(`SELECT COUNT(*) n FROM followups f WHERE (f.scope_type = 'person' AND NOT EXISTS (SELECT 1 FROM people x WHERE CAST(x.id AS TEXT) = f.scope_id))
        OR (f.scope_type = 'branch' AND NOT EXISTS (SELECT 1 FROM branches x WHERE CAST(x.id AS TEXT) = f.scope_id))
        OR (f.scope_type = 'college' AND NOT EXISTS (SELECT 1 FROM colleges x WHERE x.id = f.scope_id))`),
      followups_noncanonical_scope: n(`SELECT COUNT(*) n FROM followups WHERE (scope_type IN ('person','branch') AND scope_id <> CAST(CAST(scope_id AS INTEGER) AS TEXT))
        OR (scope_type = 'college' AND scope_id <> lower(trim(scope_id)))`),
      blank_names: n("SELECT (SELECT COUNT(*) FROM people WHERE trim(full_name) = '') + (SELECT COUNT(*) FROM colleges WHERE trim(name) = '') AS n"),
      future_confirmed: n(`SELECT COUNT(*) n FROM enrollments WHERE stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) > '${today()}'`),
    };
  }

  /**
   * Explicit (all-courses or ?course=) targets whose children's targets don't add up to them.
   * v4 (R11, TG-09): never the state/programme target, and only when EVERY child has a target (a partial sum is not a contradiction).
   */
  function unreconciled(q) {
    const ctx = getCtx();
    const course = q.get('course') ? String(Number(q.get('course'))) : '';
    const out = [];
    for (const t of ctx.targets.values()) {
      if (String(t.course_id ?? '') !== course || t.scope_type === 'person' || t.scope_type === 'state') continue;
      const sc = { type: t.scope_type, id: t.scope_id };
      if (!scopeExists(ctx, sc)) continue;
      const e = effectiveTarget(ctx, sc, course);
      // children that can carry a target: for a college only its relevant branches (allocation never targets the others)
      const kidsTotal = sc.type === 'college' ? (ctx.branchesByCollege.get(sc.id) || []).filter((b) => b.is_relevant).length : e.children_total;
      if (e.reconciled || !(e.children_target_sum > e.target || e.children_with_targets >= kidsTotal)) continue;
      out.push({ scope_type: sc.type, scope_id: sc.id, label: scopeLabel(ctx, sc), href: hrefFor(ctx, sc.type, sc.id),
        target: e.target, children_target_sum: e.children_target_sum, difference: e.target - e.children_target_sum, course_id: t.course_id ?? null,
        children_with_targets: e.children_with_targets, children_total: e.children_total });
    }
    const order = { state: 0, district: 1, city: 2, college: 3, branch: 4 };
    return out.sort((a, b) => order[a.scope_type] - order[b.scope_type] || String(a.label).localeCompare(String(b.label)));
  }

  function listBranches(q) {
    const ctx = getCtx();
    let rows = [...ctx.branches.values()];
    const m = makeMatcher(q.get('q'));
    const col = q.get('college') || q.get('college_id');
    if (col) rows = rows.filter((b) => b.college_id === col);
    if (q.get('district')) rows = rows.filter((b) => ctx.colleges.get(b.college_id)?.district_id === q.get('district'));
    const ds = districtSet(q); if (ds) rows = rows.filter((b) => ds.has(ctx.colleges.get(b.college_id)?.district_id));
    if (q.get('relevant') != null && q.get('relevant') !== '') { const want = ['1', 'true', 'yes'].includes(q.get('relevant')) ? 1 : 0; rows = rows.filter((b) => (b.is_relevant ? 1 : 0) === want); }
    if (q.get('intake_basis')) { const s = new Set(q.get('intake_basis').split(',')); rows = rows.filter((b) => s.has(b.intake_basis)); }
    if (q.get('category')) { const s = new Set(q.get('category').split(',')); rows = rows.filter((b) => s.has(b.category)); }
    if (q.get('code')) rows = rows.filter((b) => b.code.toUpperCase() === q.get('code').toUpperCase());
    if (m) rows = rows.filter((b) => { const c = ctx.colleges.get(b.college_id); return m.best([b.code, b.name, c?.name, c?.short_name]) > 0; });
    const limit = lim(q.get('limit'), 5000, 5000);
    return rows.slice(0, limit).map((b) => {
      const c = ctx.colleges.get(b.college_id);
      return { ...b, college_name: c?.name ?? null, college_short_name: c?.short_name ?? null, district_id: c?.district_id ?? null,
        active_ambassadors: activeAmbassadorCount(ctx, b.id), href: hrefFor(ctx, 'branch', b.id) };
    });
  }

  function simpleList(name, q) {
    const def = ENT[name];
    const filters = { college: 'college_id', branch: 'branch_id', person: 'person_id', course: 'course_id', scope_type: 'scope_type', scope_id: 'scope_id', semester: 'semester', college_id: 'college_id', stage: 'stage' };
    const where = []; const p = [];
    const cols = new Set(db.prepare(`PRAGMA table_info(${def.table})`).all().map((c) => c.name));
    for (const [k, col] of Object.entries(filters)) if (q.get(k) && cols.has(col)) { where.push(`${col} = ?`); p.push(q.get(k)); }
    // v4 (UI-13): districts= on enrollments / activities (by their college)
    const ds = districtSet(q);
    if (ds && cols.has('college_id')) { where.push(`college_id IN (SELECT id FROM colleges WHERE district_id IN (${[...ds].map(() => '?').join(',')}))`); p.push(...ds); }
    if (name === 'targets' && q.get('period')) {
      const pf = targetPeriodFields(getCtx(), q.get('period'));
      if (pf.error) throw bad({ period: pf.error });
      where.push("period = ? AND IFNULL(period_start, '') = IFNULL(?, '')"); p.push(pf.period, pf.period_start);
    }
    const limit = lim(q.get('limit'), 1000, 5000);
    const order = cols.has('enrolled_on') ? 'enrolled_on DESC, id DESC' : cols.has('on_date') ? 'on_date DESC, id DESC' : 'id';
    const rows = db.prepare(`SELECT * FROM ${def.table} ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY ${order} LIMIT ?`).all(...p, limit);
    return name === 'targets' ? rows.map(decorateTarget) : rows;
  }

  // ------------------------------------------------------------------ v4 team operations (R4, R5)
  const personOut = (id, side) => { const ctx = getCtx(); const p = ctx.people.get(Number(id)); const row = p ? peopleRow(ctx, p) : null; return { ...row, person: row, side_effects: side || newSide() }; };
  function patchPerson(id, body, actor) {
    const r = updateEntity('people', id, body, actor);
    const side = cur.side || newSide(); cur.side = null;
    return personOut(r.id, side);
  }
  function movePerson(id, body, actor) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw bad({ _body: 'Expected a JSON object' });
    if (!body.college_id) throw bad({ college_id: 'Required' });
    const b = { college_id: body.college_id };
    if (body.reports_to !== undefined) b.reports_to = body.reports_to;
    if (body.branch_ids !== undefined) b.branch_ids = body.branch_ids;
    if (body.allow_same_name !== undefined) b.allow_same_name = body.allow_same_name;
    const r = patchPerson(id, b, actor);
    return { person: r.person, side_effects: r.side_effects };
  }
  /** Update one person row directly (used by multi-row operations), audited. Returns the after row. */
  function setPerson(pid, upd, actor) {
    const before = ENT.people.snapshot(getRow(ENT.people, pid));
    const row = { ...upd };
    for (const k of Object.keys(row)) if (row[k] === before[k]) delete row[k];
    if (!Object.keys(row).length) return before;
    row.updated_at = nowIso(); row.updated_by = actor;
    updateRow('people', pid, row);
    const after = ENT.people.snapshot(getRow(ENT.people, pid));
    writeAudit(db, actor, 'update', 'person', pid, before, after);
    return after;
  }
  function replaceLead(id, body, actor) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw bad({ _body: 'Expected a JSON object' });
    const out = tx(db, () => {
      cur.actor = actor;
      const old = getRow(ENT.people, id);
      if (!old) throw notFound(`Person ${id} not found`);
      if (old.role !== 'college_lead') throw bad({ _body: `${old.full_name} is not a College Lead` }, `${old.full_name} is not a College Lead`);
      const nid = Number(body.new_lead_id);
      const nw = Number.isInteger(nid) && nid > 0 ? getRow(ENT.people, nid) : null;
      const f = {};
      if (!nw) f.new_lead_id = 'Choose the person who becomes the College Lead';
      else if (nw.id === old.id) f.new_lead_id = 'Choose someone else';
      else if (nw.college_id !== old.college_id) f.new_lead_id = 'The new lead must belong to the same college';
      else if (nw.status === 'inactive') f.new_lead_id = 'The new lead is inactive. Reactivate them first';
      if (!['ambassador_lead', 'inactive'].includes(body.old_lead_becomes)) f.old_lead_becomes = 'Must be ambassador_lead or inactive';
      if (Object.keys(f).length) throw bad(f);
      if (nw.phone || nw.email) {
        // reactivation never happens here, so duplicates cannot appear; nothing to check
      }
      const side = newSide();
      const keepReports = body.move_reports === false && body.old_lead_becomes === 'ambassador_lead';
      if (body.old_lead_becomes === 'inactive') setPerson(old.id, { status: 'inactive' }, actor);
      else setPerson(old.id, { role: 'ambassador_lead', reports_to: null }, actor);
      const newLead = setPerson(nw.id, { role: 'college_lead', reports_to: null, status: 'active' }, actor);
      if (body.old_lead_becomes === 'ambassador_lead') setPerson(old.id, { reports_to: nw.id }, actor);
      const oldNow = getRow(ENT.people, old.id);
      for (const r of db.prepare('SELECT * FROM people WHERE reports_to = ? AND id <> ?').all(old.id, nw.id)) {
        if (keepReports && !managerIssue(r, oldNow)) continue; // ambassadors stay with the old lead (now an Ambassador Lead)
        if (!managerIssue(r, newLead)) { setPerson(r.id, { reports_to: nw.id }, actor); side.reassigned.push(r.id); } else { setPerson(r.id, { reports_to: null }, actor); side.unassigned.push(r.id); }
      }
      changed();
      return side;
    });
    const ctx = getCtx();
    return { old_lead: peopleRow(ctx, ctx.people.get(Number(id))), new_lead: peopleRow(ctx, ctx.people.get(Number(body.new_lead_id))), side_effects: out };
  }
  function bulkAssign(body, actor) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw bad({ _body: 'Expected a JSON object' });
    const ids = body.person_ids;
    if (!Array.isArray(ids) || !ids.length || ids.length > 500) throw bad({ person_ids: 'Give a list of 1 to 500 person ids' });
    const to = body.reports_to == null || body.reports_to === '' ? null : Number(body.reports_to);
    return tx(db, () => {
      cur.actor = actor;
      const mgr = to == null ? null : getRow(ENT.people, to);
      if (to != null && !mgr) throw bad({ reports_to: 'Unknown person' });
      const errs = []; const rows = [];
      for (const raw of [...new Set(ids.map(Number))]) {
        const p = Number.isInteger(raw) ? getRow(ENT.people, raw) : null;
        if (!p) { errs.push(`${raw}: unknown person`); continue; }
        if (to != null) {
          if (p.id === to) errs.push(`${p.full_name}: cannot report to themselves`);
          else if (p.role === 'college_lead') errs.push(`${p.full_name}: a College Lead does not report to anyone`);
          else { const issue = managerIssue(p, mgr); if (issue) errs.push(`${p.full_name}: ${issueText(issue, p.role)}`); }
        }
        rows.push(p);
      }
      if (errs.length) throw bad({ person_ids: errs.join('; ') });
      const updated = []; const unchanged = [];
      for (const p of rows) { if ((p.reports_to ?? null) === to) unchanged.push(p.id); else { setPerson(p.id, { reports_to: to }, actor); updated.push(p.id); } }
      if (updated.length) changed();
      return { updated, unchanged };
    });
  }
  /** R13: mark college fields verified (with a source) or unverified. */
  function verifyCollege(id, body, actor) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw bad({ _body: 'Expected a JSON object' });
    return tx(db, () => {
      const c = getRow(ENT.colleges, id);
      if (!c) throw notFound(`College ${id} not found`);
      const fields = body.fields;
      if (!Array.isArray(fields) || !fields.length) throw bad({ fields: `Give a list of fields: ${VERIFIABLE.join(', ')}` });
      const unknown = fields.filter((k) => !VERIFIABLE.includes(k));
      if (unknown.length) throw bad({ fields: `Unknown field(s): ${unknown.join(', ')}` });
      const verified = body.verified !== false;
      let source = null;
      if (verified) {
        if (body.source == null || !String(body.source).trim()) throw bad({ source: 'Required: a link or a short note saying where this was checked' });
        source = checkSource('source', body.source);
        const empty = fields.filter((k) => c[k] == null || c[k] === '');
        if (empty.length) throw bad({ fields: `Nothing to verify (empty): ${empty.join(', ')}` });
      }
      const note = body.note == null ? null : String(body.note).trim().slice(0, 500) || null;
      let on = today();
      if (body.verified_on != null && body.verified_on !== '') {
        if (!isDate(String(body.verified_on))) throw bad({ verified_on: 'Use a date like 2026-11-07' });
        if (body.verified_on > today()) throw bad({ verified_on: 'Date is in the future' });
        on = body.verified_on;
      }
      const vf = parseObj(c.verified_fields);
      for (const k of fields) { if (verified) vf[k] = { source, verified_on: on, verified_by: actor, ...(note ? { note } : {}) }; else delete vf[k]; }
      const json = JSON.stringify(vf);
      if (json === (c.verified_fields || '{}')) return { ...c, ...verificationOf(c) };
      updateRow('colleges', c.id, { verified_fields: json, updated_at: nowIso(), updated_by: actor });
      const after = getRow(ENT.colleges, c.id);
      writeAudit(db, actor, 'update', 'college', c.id, { name: c.name, verified_fields: parseObj(c.verified_fields) }, { name: c.name, verified_fields: vf });
      changed();
      return { ...after, ...verificationOf(after) };
    });
  }
  function performanceOut(q) {
    const ctx = getCtx();
    const role = oneOf(q, 'role', ['college_lead', 'ambassador_lead', 'ambassador']);
    const level = q.get('level') || 'person';
    const sort = q.get('sort') || undefined;
    if (sort && !['pct', 'actual', 'name', 'remaining', 'target'].includes(sort.replace(/^-/, ''))) throw bad({ sort: 'Must be pct, actual, name, remaining or target (prefix - for descending)' });
    if (q.get('district') && !ctx.districts.has(q.get('district'))) throw bad({ district: 'Unknown district' });
    if (q.get('college_id') && !ctx.colleges.has(q.get('college_id'))) throw bad({ college_id: 'Unknown college' });
    const r = performance(ctx, { level, period: q.get('period') || 'programme', districts: districtSet(q), district: q.get('district') || null,
      college_id: q.get('college_id') || q.get('college') || null, role, include_inactive: q.get('include_inactive') === '1', only_with_target: q.get('only_with_target') === '1', sort });
    if (r.error) throw bad({ [r.field]: r.error });
    return r;
  }

  // ------------------------------------------------------------------ v4 auth (R14): sessions, passcodes, roles, lockout
  const SESSIONS = new Map(); // token -> {user, role, expires}
  const FAILS = new Map(); // ip -> [failure timestamps]
  const SESSION_MS = 12 * 3600 * 1000; const LOCK_WINDOW = 10 * 60 * 1000; const LOCK_AFTER = 5;
  const RESERVED_NAMES = new Set(['seed', 'import', 'import_research', 'system', 'demo']);
  const RESERVED_KEYS = new Set([...RESERVED_NAMES].map((n) => n.replace(/[^a-z0-9]/g, '')));
  const SESSION_CAP = 500; // v4.1 (SEC-13): oldest session evicted beyond this
  const authRequired = () => !!process.env.PORTAL_PASSCODE;
  const safeEq = (a, b) => { const x = Buffer.from(String(a)); const y = Buffer.from(String(b)); return x.length === y.length && crypto.timingSafeEqual(x, y); };
  const passRole = (p) => (p == null || p === '' ? null : process.env.PORTAL_PASSCODE && safeEq(p, process.env.PORTAL_PASSCODE) ? 'editor'
    : process.env.PORTAL_VIEWER_PASSCODE && safeEq(p, process.env.PORTAL_VIEWER_PASSCODE) ? 'viewer' : null);
  // Behind a reverse proxy (the Tech Drona LMS web app, or any other front proxy) every request comes from the proxy: with TRUST_PROXY=1 the client
  // address is the first X-Forwarded-For entry (so one wrong-passcode lockout never locks out everyone).
  const ipOf = (req) => (trustProxy() && firstHeader(req, 'x-forwarded-for')) || req.socket?.remoteAddress || 'unknown';
  function lockWait(ip) {
    const now = Date.now(); const a = (FAILS.get(ip) || []).filter((t) => now - t < LOCK_WINDOW);
    if (a.length) FAILS.set(ip, a); else FAILS.delete(ip);
    return a.length >= LOCK_AFTER ? Math.max(1, Math.ceil((a[0] + LOCK_WINDOW - now) / 1000)) : 0;
  }
  const noteFail = (ip) => { const a = FAILS.get(ip) || []; a.push(Date.now()); FAILS.set(ip, a); };
  const lockedErr = (wait) => new HttpError(429, `Too many wrong passcodes. Try again in ${Math.ceil(wait / 60)} minute(s).`, null, { code: 'locked', retry_after_s: wait });
  function cookieToken(req) {
    for (const part of String(req.headers.cookie || '').split(';')) {
      const i = part.indexOf('=');
      if (i > 0 && part.slice(0, i).trim() === cookieName() && /^[A-Za-z0-9_-]{20,}$/.test(part.slice(i + 1).trim())) return part.slice(i + 1).trim();
    }
    return null;
  }
  function sessionOf(req) {
    const t = cookieToken(req); if (!t) return null;
    const s = SESSIONS.get(t);
    if (!s || s.expires < Date.now()) { SESSIONS.delete(t); return null; }
    return { ...s, token: t };
  }
  /** {role:'editor'|'viewer', user|null}. Throws 401/429 when a passcode is configured and the caller is not signed in. */
  function authOf(req) {
    if (req.__tdProxy) return req.__tdProxy;
    const s = sessionOf(req);
    if (s) return { role: s.role, user: s.user };
    if (!authRequired()) return { role: 'editor', user: null };
    const hp = req.headers['x-passcode'];
    if (hp) {
      const ip = ipOf(req); const wait = lockWait(ip);
      if (wait) throw lockedErr(wait);
      const role = passRole(String(hp));
      if (role) return { role, user: null };
      noteFail(ip);
      throw new HttpError(401, 'Passcode required or incorrect', null, { code: 'bad_passcode' });
    }
    throw new HttpError(401, 'Please sign in with the team passcode', null, { code: 'auth_required' });
  }
  function cleanUser(raw, field = 'name') {
    let user = '';
    try { user = raw ? decodeURIComponent(String(raw)) : ''; } catch { user = String(raw); }
    // v4.1 (SEC-10): NFKC (full-width "ｓｅｅｄ" -> "seed"), invisible characters removed, spaces collapsed
    user = user.normalize('NFKC').replace(INVISIBLE, '').replace(/\s+/g, ' ').trim();
    if (!user) return '';
    if (user.length > 100) throw bad({ [field]: 'At most 100 characters' }, 'User name too long');
    const key = user.toLowerCase().replace(/[^\p{L}\p{N}]/gu, ''); // " S.E.E.D " / "seed." / "import-research" all match
    if (RESERVED_KEYS.has(key)) throw bad({ [field]: `"${user}" is reserved for the system. Use your own name.` });
    if (!/\p{L}/u.test(user)) throw bad({ [field]: 'Enter a name with letters' });
    return user;
  }
  function requireWriter(req, auth) {
    if (auth.role === 'viewer') throw new HttpError(403, 'You are signed in read-only. Ask for the editor passcode to make changes.', null, { code: 'read_only' });
    const user = auth.user || cleanUser(req.headers['x-user']);
    if (!user) throw new HttpError(401, 'Please enter your name (X-User header) before making changes', null, { code: 'user_required' });
    return user;
  }
  function sessionInfo(req) {
    if (req.__tdProxy) {
      return { required: true, auth_required: true, authenticated: true, role: req.__tdProxy.role, user: req.__tdProxy.user, sso: true,
        sso_provider: 'Tech Drona LMS', login_url: LMS_LOGIN_URL, expires_at: null, viewer_enabled: false };
    }
    const s = sessionOf(req);
    return { required: authRequired(), auth_required: authRequired(), authenticated: !!s, role: s ? s.role : (authRequired() ? null : 'editor'), user: s?.user ?? null,
      expires_at: s ? new Date(s.expires).toISOString() : null, viewer_enabled: !!process.env.PORTAL_VIEWER_PASSCODE };
  }
  // v4.1 (SEC-13): Secure when the request came over https (directly, or via a proxy that says so)
  // X-Forwarded-Proto is trusted only with TRUST_PROXY=1 (the LMS / Caddy terminate TLS in front of the server)
  const isHttps = (req) => !!req?.socket?.encrypted || (trustProxy() && String(firstHeader(req, 'x-forwarded-proto')).toLowerCase() === 'https');
  const sessionCookie = (t, maxAge, req) => `${cookieName()}=${t}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAge}${isHttps(req) ? '; Secure' : ''}`;
  async function sessionApi(req, m) {
    if (m === 'GET') return sessionInfo(req);
    if (req.__tdProxy) {
      // proxy mode: the LMS session is the only sign-in; there is no portal cookie to create or clear
      if (m === 'DELETE') return { ok: true };
      if (m === 'POST') { if (!req.readableEnded) req.resume(); throw new HttpError(409, 'You are signed in through the Tech Drona LMS', null, { code: 'sso' }); }
      throw new HttpError(405, 'Use GET, POST or DELETE /api/session');
    }
    if (m === 'DELETE') {
      const t = cookieToken(req); if (t) SESSIONS.delete(t);
      return { __status: 200, body: { ok: true }, headers: { 'Set-Cookie': sessionCookie('x'.repeat(20), 0, req) } };
    }
    if (m !== 'POST') throw new HttpError(405, 'Use GET, POST or DELETE /api/session');
    const body = await readBody(req);
    // v4.1 (SEC-12): the name is a string of at most 80 characters
    if (body?.name != null && typeof body.name !== 'string') throw bad({ name: 'Must be text' });
    if (typeof body?.name === 'string' && body.name.trim().length > 80) throw bad({ name: 'At most 80 characters' });
    const name = cleanUser(body?.name);
    if (!name) throw bad({ name: 'Required: your name (it is written next to every change you make)' });
    let role = 'editor';
    if (authRequired()) {
      const ip = ipOf(req); const wait = lockWait(ip);
      if (wait) throw lockedErr(wait);
      role = passRole(body?.passcode == null ? '' : String(body.passcode));
      if (!role) { noteFail(ip); throw new HttpError(401, 'Wrong passcode', { passcode: 'Wrong passcode' }, { code: 'bad_passcode' }); }
      FAILS.delete(ip);
    }
    for (const [k, v] of SESSIONS) if (v.expires < Date.now()) SESSIONS.delete(k);
    const token = crypto.randomBytes(32).toString('base64url');
    const expires = Date.now() + SESSION_MS;
    while (SESSIONS.size >= SESSION_CAP) SESSIONS.delete(SESSIONS.keys().next().value);
    SESSIONS.set(token, { user: name, role, expires });
    return { __status: 200, body: { role, user: name, expires_at: new Date(expires).toISOString(), auth_required: authRequired() }, headers: { 'Set-Cookie': sessionCookie(token, SESSION_MS / 1000, req) } };
  }

  // ------------------------------------------------------------------ v4.1 idempotency (R6, F1, SEC-07)
  // Only SUCCESSFUL (2xx) results are remembered, for 10 min. Fingerprint = method + path + actor + SHA-256 of the JSON body: the same key
  // with the same request replays the first result (Idempotent-Replay: true); the same key with any other request -> 422. Errors are never
  // stored, so fixing the form and saving again with the same key runs the request for real.
  const IDEM = new Map(); const IDEM_MS = 10 * 60 * 1000; const IDEM_CAP = 5000;
  const idemFp = (m, p, actor, body) => `${m}|${p}|${actor}|${crypto.createHash('sha256').update(JSON.stringify(body ?? null)).digest('hex')}`;
  function idemLookup(key, fp) {
    const now = Date.now();
    for (const [k, v] of IDEM) if (now - v.at > IDEM_MS) IDEM.delete(k);
    const hit = IDEM.get(key);
    if (!hit) return null;
    if (hit.fp !== fp) throw new HttpError(422, 'Idempotency-Key reused with a different request', null, { code: 'idempotency_key_reused' });
    return { __status: hit.status, body: hit.body, headers: { 'Idempotent-Replay': 'true' } };
  }

  // ------------------------------------------------------------------ live official-source data (server/live.js)
  //   GET  /api/live[?refresh=1]          status of every source (+ starts a background refresh of stale ones)
  //   GET  /api/live/college/:id          what the official sources say about one college (+ diffs vs our record)
  //   GET  /api/live/announcements        JNTUK notices (?category=&q=&limit=&since=)
  //   POST /api/live/refresh {source?}    editor: refresh now, ignoring the cache age
  async function liveApi(req, m, auth, id, sub, q) {
    if (m === 'GET' || m === 'HEAD') {
      if (!id) { if (q.get('refresh') === '1' && process.env.LIVE_DISABLED !== '1') live.refresh(); return live.status(); }
      if (id === 'college' && sub) { const out = live.college(sub); if (!out) throw notFound(`College ${sub} not found`); return out; }
      if (id === 'announcements') {
        const category = q.get('category') || null;
        if (category && !['exam', 'result', 'calendar', 'holiday', 'admission', 'other'].includes(category)) throw bad({ category: 'Unknown category' });
        const since = q.get('since') || null;
        if (since && !/^\d{4}-\d{2}-\d{2}$/.test(since)) throw bad({ since: 'Use a date like 2026-11-01' });
        return live.announcements({ category, q: q.get('q') || null, limit: lim(q.get('limit'), 100, 500), since });
      }
      throw notFound('Unknown endpoint');
    }
    if (m === 'POST' && id === 'refresh' && !sub) {
      requireWriter(req, auth);
      const body = await readBody(req);
      const source = body && body.source != null ? String(body.source) : null;
      if (source && !LIVE_SOURCES[source]) throw bad({ source: `Unknown source. Use one of: ${Object.keys(LIVE_SOURCES).join(', ')}` });
      live.refresh({ force: true, source });
      return live.status();
    }
    throw new HttpError(405, 'Method not allowed');
  }

  async function handleApi(req, url) {
    let parts;
    try { parts = url.pathname.replace(/^\/api\/?/, '').split('/').filter(Boolean).map(decodeURIComponent); } catch { throw new HttpError(400, 'Bad path'); }
    const q = url.searchParams;
    const m = req.method;
    const [res, id, sub] = parts;
    // endpoints that never need a sign-in
    if (res === 'health' && (m === 'GET' || m === 'HEAD')) return { ok: true, today: today(), version: 'v4', auth_required: authRequired() };
    if (res === 'session' && !id) return sessionApi(req, m);
    const auth = authOf(req);
    if (res === 'live') return liveApi(req, m, auth, id, sub, q);
    if (m === 'GET') {
      if (q.has('districts')) districtsFromQuery(q); // v4.1 (F8): 400 on an unknown id, whatever the endpoint
      if (q.get('district') && !getCtx().districts.has(q.get('district'))) throw bad({ district: `Unknown district: ${q.get('district')}` });
      switch (res) {
        case 'meta': return { ...meta(), auth: sessionInfo(req) };
        case 'summary': { const sc = scopeFromQuery(q); return sc.type === 'person' ? personRollup(getCtx(), sc.id) : summary(getCtx(), sc); }
        case 'program': if (id) throw notFound(`Unknown endpoint /api/${parts.join('/')}`); return programOut();
        case 'plan': if (id) throw notFound(`Unknown endpoint /api/${parts.join('/')}`); return planOut(q);
        case 'performance': if (id) throw notFound(`Unknown endpoint /api/${parts.join('/')}`); return performanceOut(q);
        case 'colleges': return id ? collegeDetail(id) : listColleges(q);
        case 'branches': if (id) return branchDetail(id); return listBranches(q);
        case 'people': return id ? personDetail(id) : listPeople(q);
        case 'search': return search(q);
        case 'leaderboard': return leaderboard(q);
        case 'attention': return attention(q);
        case 'followups': if (id) { const f = db.prepare('SELECT * FROM followups WHERE id = ?').get(Number(id)); if (!f) throw notFound(`Follow-up ${id} not found`); return decorateFollowup(getCtx(), f); } return listFollowups(q);
        case 'exams': if (id) { const e = db.prepare('SELECT * FROM exams WHERE id = ?').get(Number(id)); if (!e) throw notFound(`Exam row ${id} not found`); return e; } return listExams(q);
        case 'timeseries': return timeseries(q);
        case 'contacts': return id ? contactDetail(id) : listContacts(q);
        case 'calls':
          if (id === 'queue') return callQueue(q);
          if (id) { const r = db.prepare(`${callDetailSql} WHERE x.id = ?`).get(Number(id)); if (!r) throw notFound(`Call ${id} not found`); return r; }
          return listCalls(q);
        case 'funnel': { const sc = scopeFromQuery(q); return funnelOut(getCtx(), sc); }
        case 'target-dashboard': { const sc = scopeFromQuery(q); const d = districtsFromQuery(q); return targetDashboard(getCtx(), sc, d.present ? programBlock(d) : null); }
        case 'quality': return quality(q);
        case 'audit': if (id === 'actors') return auditActors(); if (id) throw notFound(`Unknown endpoint /api/${parts.join('/')}`); return auditList(q);
        case 'settings': return getSettings(db);
        case 'districts': return meta().districts;
        case 'cities': return meta().cities.filter((c) => !q.get('district') || c.district_id === q.get('district'));
        case 'targets':
          if (id === 'unreconciled') return unreconciled(q);
          if (id) { const r = getRow(ENT.targets, id); if (!r) throw notFound(`Target ${id} not found`); return decorateTarget(r); }
          if (q.get('scope')) {
            const sc = parseScope(q.get('scope'));
            let rows = db.prepare('SELECT * FROM targets WHERE scope_type = ? AND scope_id = ?').all(sc?.type, sc?.id);
            if (q.get('period')) { const pf = targetPeriodFields(getCtx(), q.get('period')); if (pf.error) throw bad({ period: pf.error }); rows = rows.filter((t) => t.period === pf.period && (t.period_start ?? null) === pf.period_start); }
            return rows.map(decorateTarget);
          }
          return simpleList(res, q);
        case 'courses': case 'enrollments': case 'activities':
          if (id) { const r = getRow(ENT[res], id); if (!r) throw notFound(`${ENTITY_LABEL[ENT[res].entity]} ${id} not found`); return r; }
          return simpleList(res, q);
        default: throw notFound(`Unknown endpoint /api/${parts.join('/')}`);
      }
    }
    if (!['POST', 'PATCH', 'PUT', 'DELETE'].includes(m)) throw new HttpError(405, 'Method not allowed');
    const actor = requireWriter(req, auth);
    const ikey = req.headers['idempotency-key'];
    if (ikey != null && String(ikey).length > 100) throw bad({ 'Idempotency-Key': 'At most 100 characters' });
    const body = m === 'DELETE' ? null : await readBody(req);
    // from here on everything is synchronous, so the lookup and the store below cannot interleave with another request
    let fp = null;
    if (ikey != null && ikey !== '') {
      fp = idemFp(m, url.pathname, actor, body);
      const replay = idemLookup(String(ikey), fp);
      if (replay) return replay;
    }
    if (!fp) return dispatchWrite(m, res, id, sub, parts, body, actor, q);
    {
      const out = dispatchWrite(m, res, id, sub, parts, body, actor, q); // v4.1 (F1): errors propagate and are never remembered
      const st = out?.__status || 200;
      if (st >= 200 && st < 300) {
        while (IDEM.size >= IDEM_CAP) IDEM.delete(IDEM.keys().next().value);
        IDEM.set(String(ikey), { at: Date.now(), fp, status: st, body: out?.__status ? out.body : (out ?? {}) });
      }
      return out;
    }
  }

  function dispatchWrite(m, res, id, sub, parts, body, actor, q) {
    if (res === 'targets' && id === 'allocate' && m === 'POST') return allocate(body || {}, actor);
    if (res === 'targets' && !id && m === 'PUT') return upsertTarget(body, actor);
    if (res === 'settings') {
      if (m === 'DELETE') throw new HttpError(405, 'Settings cannot be deleted');
      if (id) return saveSettings({ [id]: body && 'value' in body ? body.value : body }, actor);
      if (body && typeof body.key === 'string' && 'value' in body && Object.keys(body).length === 2) return saveSettings({ [body.key]: body.value }, actor);
      return saveSettings(body, actor);
    }
    if (res === 'districts' && id && (m === 'PATCH' || m === 'PUT')) return patchDistrict(id, body, actor);
    if (res === 'program') {
      if (id || (m !== 'PATCH' && m !== 'PUT')) throw new HttpError(405, 'Use PATCH /api/program');
      return patchProgram(body, actor);
    }
    if (res === 'calls') {
      if (sub) throw notFound();
      if (m === 'POST' && !id) return { __status: 201, body: createCall(body, actor) };
      if (!id) throw new HttpError(405, `${m} needs an id: /api/calls/:id`);
      if (m === 'PATCH' || m === 'PUT') return patchCall(id, body, actor);
      if (m === 'DELETE') return deleteCall(id, actor);
    }
    // v4 team operations
    if (res === 'people' && id === 'bulk-assign' && !sub && m === 'POST') return bulkAssign(body, actor);
    if (res === 'people' && id && sub === 'move' && m === 'POST') return movePerson(id, body, actor);
    if (res === 'people' && id && sub === 'replace-lead' && m === 'POST') return replaceLead(id, body, actor);
    if (res === 'colleges' && id && sub === 'verify' && m === 'POST') return verifyCollege(id, body, actor);
    if (!Object.hasOwn(ENT, res)) throw notFound(`Unknown endpoint /api/${parts.join('/')}`); // v4.1 (SEC-05): /api/constructor -> 404
    if (sub) throw notFound(`Unknown endpoint /api/${parts.join('/')}`);
    if (m === 'POST' && !id) {
      const r = createEntity(res, body, actor);
      if (res === 'people') { const ctx = getCtx(); cur.side = null; return { __status: 201, body: peopleRow(ctx, ctx.people.get(r.id)) }; }
      return { __status: 201, body: res === 'targets' ? r : r };
    }
    if (!id) throw new HttpError(405, `${m} needs an id: /api/${res}/:id`);
    if (m === 'PATCH' || m === 'PUT') {
      if (res === 'people') return patchPerson(id, body, actor);
      const r = updateEntity(res, id, body, actor);
      return res === 'targets' ? decorateTarget(r) : r;
    }
    if (m === 'DELETE') return deleteEntity(res, id, actor, q);
    throw new HttpError(405, 'Method not allowed');
  }

  function patchDistrict(id, body, actor) {
    return tx(db, () => {
      const before = db.prepare('SELECT * FROM districts WHERE id = ?').get(id);
      if (!before) throw notFound('District not found');
      const row = validate({ targeted: { type: 'bool' }, name: T(100) }, body, { create: false, table: 'districts' });
      for (const k of Object.keys(row)) if (row[k] === before[k]) delete row[k];
      if (!Object.keys(row).length) return before;
      row.updated_at = nowIso(); row.updated_by = actor;
      const cols = Object.keys(row);
      db.prepare(`UPDATE districts SET ${cols.map((c) => `${c} = ?`).join(', ')} WHERE id = ?`).run(...cols.map((c) => row[c]), id);
      const after = db.prepare('SELECT * FROM districts WHERE id = ?').get(id);
      writeAudit(db, actor, 'update', 'district', id, before, after);
      changed();
      return after;
    });
  }

  // ------------------------------------------------------------------ program (district scope + 400 target) and plan
  // The program target IS the explicit state target row (targets state:ap, all courses) when it exists; settings
  // program_target / program_deadline mirror it (and are the fallback when no state row exists). PATCH writes both.
  function programTarget(ctx) {
    const st = ctx.targets.get('state:ap:') || null;
    return {
      target: st ? Number(st.target) : (ctx.settings.program_target ?? null),
      deadline: st?.deadline || ctx.settings.program_deadline || ctx.settings.state_target_deadline || null,
      target_source: st ? 'state_target' : 'settings', state_target_id: st ? st.id : null,
      start: programStart(ctx), // v4: pace is measured from here
    };
  }
  function targetGroups(ctx) {
    const g = ctx.settings.target_district_groups;
    return g && typeof g === 'object' && !Array.isArray(g) ? g : {};
  }
  const targetDistrictIds = (ctx) => [...new Set(Object.values(targetGroups(ctx)).flat())].filter((id) => ctx.districts.has(id));
  function groupOf(ctx, districtId) {
    for (const [name, ids] of Object.entries(targetGroups(ctx))) if (Array.isArray(ids) && ids.includes(districtId)) return name;
    return null;
  }
  /** The `program` block of /api/target-dashboard?districts=… */
  function programBlock(d) {
    const ctx = getCtx();
    const pt = programTarget(ctx);
    const def = targetDistrictIds(ctx);
    const sel = d.ids ? [...d.ids].sort() : [...ctx.districts.keys()].sort();
    // v4.1 (D2): the programme target covers the target districts; a selection that misses one of them gets target null + target_reason
    const applies = stateRowApplies(ctx, d.ids ? { districts: new Set(d.ids) } : null);
    return { target: applies ? pt.target : null, programme_target: pt.target, applies, target_reason: applies || pt.target == null ? null : programmeTargetReason(ctx),
      target_districts: programmeDistricts(ctx), deadline: pt.deadline, target_source: pt.target_source, selected_districts: sel, all_districts: !d.ids,
      is_default_selection: !!d.ids && sel.length === def.length && [...def].sort().every((x, i) => x === sel[i]) };
  }
  function planCounts() {
    const v = latestPlanVersion();
    const m = new Map();
    if (!v) return m;
    for (const r of db.prepare('SELECT college_id, in_plan, targeted FROM college_plan WHERE research_version = ?').all(v)) m.set(r.college_id, r);
    return m;
  }
  function programOut() {
    const ctx = getCtx();
    const pt = programTarget(ctx);
    const plan = planCounts();
    const ids = targetDistrictIds(ctx);
    return {
      ...pt,
      target_district_groups: targetGroups(ctx),
      target_district_ids: ids,
      default_district_ids: ids,
      note: 'Guntur, Krishna and West Godavari are the old (pre-2022) districts; they include the districts formed in 2022: Palnadu, Bapatla, NTR and Eluru.',
      districts: [...ctx.districts.values()].map((d) => {
        const cols = ctx.collegesByDistrict.get(d.id) || [];
        return {
          id: d.id, name: d.name, old_district: d.old_district, group: groupOf(ctx, d.id), is_target: ids.includes(d.id), targeted: d.targeted,
          colleges_total: cols.length, colleges_operational: cols.filter((c) => c.op_status === 'operational').length,
          colleges_targeted: cols.filter((c) => c.targeted).length,
          plan_colleges: cols.filter((c) => plan.get(c.id)?.in_plan).length, plan_targeted: cols.filter((c) => plan.get(c.id)?.targeted).length,
        };
      }),
    };
  }
  /** write one settings key (audited) when it changed */
  function putSetting(k, v, actor) {
    const cur = getSettings(db)[k];
    if (JSON.stringify(cur) === JSON.stringify(v)) return false;
    db.prepare('INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(k, JSON.stringify(v));
    writeAudit(db, actor, 'update', 'setting', k, { [k]: cur ?? null }, { [k]: v });
    return true;
  }
  function patchProgram(body, actor) {
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw bad({ _body: 'Expected a JSON object' }, 'Expected a JSON object');
    const ctx = getCtx();
    const fields = {};
    const allowed = ['target', 'deadline', 'target_district_groups', 'start'];
    for (const k of Object.keys(body)) if (!allowed.includes(k)) fields[k] = `Unknown field (allowed: ${allowed.join(', ')})`;
    let target; let deadline; let groups; let start;
    if (body.start !== undefined) { if (typeof body.start !== 'string' || !isDate(body.start)) fields.start = 'Use a date like 2026-11-03'; else start = body.start; }
    if (body.target !== undefined) {
      const n = Number(body.target);
      if (body.target === null || body.target === '' || !Number.isInteger(n) || n < 1 || n > 1000000) fields.target = 'Must be a whole number from 1 to 10,00,000';
      else target = n;
    }
    if (body.deadline !== undefined) {
      if (typeof body.deadline !== 'string' || !isDate(body.deadline)) fields.deadline = 'Use a date like 2026-12-31';
      else deadline = body.deadline;
    }
    if (body.target_district_groups !== undefined) {
      const g = body.target_district_groups;
      if (!g || typeof g !== 'object' || Array.isArray(g)) fields.target_district_groups = 'Must be an object of group name: [district ids]';
      else {
        const seen = new Map(); const errs = [];
        const names = Object.keys(g);
        if (!names.length) errs.push('add at least one group');
        if (names.length > 12) errs.push('at most 12 groups');
        for (const name of names) {
          const ids = g[name];
          if (!name.trim() || name.length > 60) errs.push(`group name "${name}" must be 1-60 characters`);
          if (!Array.isArray(ids) || !ids.length) { errs.push(`${name}: list at least one district id`); continue; }
          for (const id of ids) {
            if (typeof id !== 'string' || !ctx.districts.has(id)) errs.push(`${name}: unknown district ${id}`);
            else if (seen.has(id) && seen.get(id) !== name) errs.push(`${id} is in both ${seen.get(id)} and ${name}`);
            else seen.set(id, name);
          }
        }
        if (errs.length) fields.target_district_groups = errs.join('; ');
        else groups = Object.fromEntries(names.map((n) => [n.trim(), [...new Set(g[n])]]));
      }
    }
    // v4.1 (SEC-09): the programme cannot start after its deadline
    if (!Object.keys(fields).length) {
      const pt0 = programTarget(ctx); const st0 = start ?? pt0.start; const dl0 = deadline ?? pt0.deadline;
      if (st0 && dl0 && st0 > dl0) fields[start !== undefined ? 'start' : 'deadline'] = `The programme start (${st0}) must be on or before the deadline (${dl0})`;
    }
    if (Object.keys(fields).length) throw bad(fields);
    tx(db, () => {
      let any = false;
      if (groups !== undefined) any = putSetting('target_district_groups', groups, actor) || any;
      if (start !== undefined) any = putSetting('program_start', start, actor) || any;
      if (target !== undefined || deadline !== undefined) {
        const pt = programTarget(getCtx());
        const t = target ?? pt.target; const dl = deadline ?? pt.deadline;
        if (target !== undefined) any = putSetting('program_target', t, actor) || any;
        if (deadline !== undefined) any = putSetting('program_deadline', dl, actor) || any;
        if (t != null) { upsertTargetRow({ scope_type: 'state', scope_id: 'ap', target: t, deadline: dl ?? undefined }, actor, {}, { internal: true }); any = true; }
      }
      if (any) changed();
    });
    return programOut();
  }
  /** keep settings program_target / program_deadline in sync with the explicit state target row */
  function syncProgramFromStateTarget(row, actor) {
    if (!row || row.scope_type !== 'state' || row.course_id != null || (row.period || 'programme') !== 'programme') return;
    putSetting('program_target', Number(row.target), actor);
    if (row.deadline) putSetting('program_deadline', row.deadline, actor);
  }

  const latestPlanVersion = () => db.prepare('SELECT research_version FROM college_plan ORDER BY imported_at DESC, research_version DESC LIMIT 1').get()?.research_version ?? null;
  // Research model defaults (scratchpad compute_v2.py, unchanged formulas). The planner reproduces the research totals with these.
  const PLAN_DEFAULTS = {
    formula: 'V[i] = round(K[type][i] x access_x x (rates.final_year[i] x F + rates.third_year[i] x T x year_weight.third_year + rates.second_year[i] x S x year_weight.second_year)) for i = min, avg, max; '
      + 'then min >= min_floor.value when F > 0 and access_x >= min_floor.access_x_at_least; avg >= min; max >= avg. A college is targeted only when min > 0 (status_final active, in scope). '
      + 'F = it_fy.value, T = it_3rd.value, S = it_2nd.value; a null value counts as 0 (F null -> 0/0/0). round = floor(x + 0.5).',
    year_groups: { final_year: true, third_year: true, second_year: true },
    rates: { final_year: [0.0075, 0.0125, 0.02], third_year: [0.00375, 0.00625, 0.01], second_year: [0.0015, 0.0025, 0.005] },
    year_weight: { final_year: 1, third_year: 0.5, second_year: 0.5 },
    type_multiplier: { a: [0.8, 1.0, 1.2], b: [1.0, 1.0, 1.0], c: [0.8, 0.9, 1.0], d: [0.9, 1.0, 1.1] },
    type_labels: { a: 'deemed university / top autonomous', b: 'Tier 1-2 college', c: 'other college', d: 'fill-risk / special case' },
    access_x: { tpo_contact: 1.0, other_contact: 0.8, no_contact: 0.6 },
    min_floor: { value: 2, access_x_at_least: 0.8 },
    buffer_on_min: 1.2,
    paid_per_active_ambassador: 5, active_share: 0.5, paid_per_recruited_ambassador: 2.5,
    ambassadors_formula: 'ambassadors = max(min_ambassadors_per_college, ceil(ceil(buffer_on_min x min) / paid_per_recruited_ambassador)); standby = ceil(ambassadors x standby_ratio)',
    min_ambassadors_per_college: 3, standby_ratio: 0.25,
    per_ambassador_targets: { min: 3, standard: 5, stretch: 15 },
    college_lead: {
      own_lead_min_ambassadors: 4, max_ambassadors_per_lead: 7, ambassador_leads_when_over_capacity: 2,
      shared_lead_pair_size: 2, district_coordinator_per_college_leads: 6,
      rule: 'ambassadors >= 4 -> own College Lead (+ 2 ambassador_leads when ambassadors > 7); colleges with < 4 ambassadors are paired by rank within the same town cluster and share one lead (0.5 each; an unpaired one gets its own). District coordinators = ceil(college leads in old district group / 6).',
    },
    mou_coverage: [0.30, 0.50, 0.80],
    rag_400: 'GREEN when avg >= 400; AMBER when max + 0.5 x (F + T + S) >= 400 and type a or b; else RED',
    priority_levels: 'P1 >= 65, P2 >= 45, else P3 (priority_score); Hold = not targeted',
    program_target: null, // filled per response from /api/program
  };
  const emptyStages = () => Object.fromEntries(STAGES.map((k) => [k, 0]));
  const emptyActual = () => ({ colleges: 0, college_leads: 0, ambassador_leads: 0, ambassadors: 0, active_ambassadors: 0, confirmed: 0, calls: 0, leads_by_stage: emptyStages() });
  /**
   * v4.1 (D1): totals_actual counts the people / confirmed / calls of EVERY college in scope (districts= or the whole state), also colleges
   * outside the research plan; in_plan (the plan colleges listed in out.colleges) and outside_plan split it. Same rules as the plan rows:
   * leads = not-inactive people, active_ambassadors = status active.
   */
  function fillActualTotals(ctx, out, ds, inPlan) {
    const K = callsCtx(ctx);
    const tot = emptyActual(); const ip = emptyActual(); const op = emptyActual();
    for (const c of ctx.colleges.values()) {
      if (ds && !ds.has(c.district_id)) continue;
      const people = ctx.peopleByCollege.get(c.id) || []; const act = people.filter((p) => p.status !== 'inactive');
      const v = { colleges: 1, college_leads: act.filter((p) => p.role === 'college_lead').length, ambassador_leads: act.filter((p) => p.role === 'ambassador_lead').length,
        ambassadors: act.filter((p) => p.role === 'ambassador').length, active_ambassadors: people.filter((p) => p.role === 'ambassador' && p.status === 'active').length,
        confirmed: ctx.aggCollege.get(c.id)?.enrolled || 0, calls: (K.callsByCollege.get(c.id) || []).length };
      for (const T of [tot, inPlan.has(c.id) ? ip : op]) {
        for (const k of Object.keys(v)) T[k] += v[k];
        for (const k of STAGES) T.leads_by_stage[k] += ctx.funnelCollege.get(c.id)?.[k] || 0;
      }
    }
    out.totals_actual = { ...tot, in_plan: ip, outside_plan: op };
  }
  function planOut(q) {
    const ctx = getCtx();
    const d = districtsFromQuery(q);
    const ds = d.ids ? new Set(d.ids) : null;
    const version = q.get('version') || latestPlanVersion();
    const pt = programTarget(ctx);
    const out = {
      generated_at: nowIso(), research_version: version || 'v2 2026-11-07', imported: !!version,
      source_report: 'reports/Krishna Guntur West Godavari colleges 2.md',
      source_files: ['research_notes/Krishna Guntur West Godavari colleges 2/master_colleges_v2.csv', 'research_notes/Krishna Guntur West Godavari colleges 2/master_branches_v2.csv'],
      program: { target: pt.target, deadline: pt.deadline, target_source: pt.target_source },
      districts_filter: ds ? [...ds] : null,
      defaults: { ...PLAN_DEFAULTS, program_target: pt.target },
      colleges: [], excluded: [], colleges_without_research: [],
      totals_research: { colleges: 0, targeted: 0, min: 0, avg: 0, max: 0, ambassadors: 0, college_leads: 0 },
      totals_actual: { college_leads: 0, ambassador_leads: 0, ambassadors: 0, active_ambassadors: 0, confirmed: 0, calls: 0, leads_by_stage: emptyStages() },
    };
    if (!version) {
      out.message = 'No research imported yet. Ask an admin to import the research plan.';
      fillActualTotals(ctx, out, ds, new Set());
      return out;
    }
    const rows = db.prepare('SELECT * FROM college_plan WHERE research_version = ?').all(version);
    const brs = new Map();
    for (const b of db.prepare('SELECT * FROM college_plan_branches WHERE research_version = ? ORDER BY college_id, seq').all(version)) {
      const a = brs.get(b.college_id) || []; a.push(b); brs.set(b.college_id, a);
    }
    const K = callsCtx(ctx);
    const planned = new Set();
    for (const r of rows) {
      const c = ctx.colleges.get(r.college_id);
      if (!c) continue;
      planned.add(c.id);
      if (ds && !ds.has(c.district_id)) continue;
      let y; try { y = JSON.parse(r.payload); } catch { continue; }
      const live = { name: c.name, short_name: c.short_name, district_id: c.district_id, district_name: ctx.districts.get(c.district_id)?.name ?? null,
        target_group: groupOf(ctx, c.district_id), city: ctx.cities.get(c.city_id)?.name ?? y.research_city ?? null, city_id: c.city_id,
        website: c.website || y.website || null, op_status: c.op_status, portal_targeted: !!c.targeted, lat: c.lat, lng: c.lng, geo_precision: c.geo_precision };
      if (!r.in_plan) {
        out.excluded.push({ college_id: c.id, ...live, research_name: y.research_name, status_final: y.status_final, final_decision: y.final_decision, duplicate_of: y.duplicate_of, hold_reason: y.hold_reason });
        continue;
      }
      const people = (ctx.peopleByCollege.get(c.id) || []);
      const act = people.filter((p) => p.status !== 'inactive');
      const calls = K.callsByCollege.get(c.id) || [];
      const stages = { ...emptyStages(), ...Object.fromEntries(STAGES.map((k) => [k, ctx.funnelCollege.get(c.id)?.[k] || 0])) };
      const actual = {
        college_leads: act.filter((p) => p.role === 'college_lead').length,
        ambassador_leads: act.filter((p) => p.role === 'ambassador_lead').length,
        ambassadors: act.filter((p) => p.role === 'ambassador').length,
        active_ambassadors: people.filter((p) => p.role === 'ambassador' && p.status === 'active').length,
        leads_by_stage: stages, confirmed: ctx.aggCollege.get(c.id)?.enrolled || 0,
        calls: calls.length, last_call_at: calls.length ? calls[calls.length - 1].called_at : null,
        people: act.map((p) => ({ id: p.id, full_name: p.full_name, role: p.role, status: p.status, reports_to: p.reports_to ?? null })),
      };
      const pc = {
        college_id: c.id, ...y, ...live, targeted: !!r.targeted, hold_reason: r.hold_reason,
        actual,
        branches: (brs.get(c.id) || []).map((b) => ({ name: b.name, is_it: !!b.is_it, intake_2023_24: b.intake_2023_24, intake_latest: b.intake_latest,
          intake_latest_year: b.intake_latest_year, intake_latest_basis: b.intake_latest_basis, basis: b.basis, source: b.source, confidence: b.confidence,
          counted: !!b.counted, final_decision: b.final_decision, notes: b.notes })),
      };
      out.colleges.push(pc);
      const T = out.totals_research; T.colleges++;
      if (pc.targeted) {
        T.targeted++;
        T.min += pc.research_target?.min || 0; T.avg += pc.research_target?.avg || 0; T.max += pc.research_target?.max || 0;
        T.ambassadors += pc.ambassadors_research || 0; T.college_leads += pc.college_leads_research || 0;
      }
    }
    fillActualTotals(ctx, out, ds, new Set(out.colleges.map((pc) => pc.college_id)));
    out.colleges.sort((a, b) => (b.targeted - a.targeted) || ((a.rank ?? 1e9) - (b.rank ?? 1e9)) || String(a.name).localeCompare(String(b.name)));
    const scopeIds = ds || new Set(targetDistrictIds(ctx));
    out.colleges_without_research = [...ctx.colleges.values()].filter((c) => scopeIds.has(c.district_id) && !planned.has(c.id))
      .map((c) => ({ college_id: c.id, name: c.name, short_name: c.short_name, district_id: c.district_id, op_status: c.op_status, portal_targeted: !!c.targeted }));
    return out;
  }

  const isJsonType = (ct) => /^application\/json\s*(;|$)/i.test(String(ct || '').trim());
  function readBody(req) {
    return new Promise((resolve, reject) => {
      // v4 (BE-16): over 1 MB -> keep draining the upload (so the client receives the reply) and answer 413 at the end
      let size = 0; let tooBig = false; const chunks = [];
      req.on('data', (c) => { size += c.length; if (size > 1e6) { tooBig = true; chunks.length = 0; } else if (!tooBig) chunks.push(c); });
      req.on('end', () => {
        if (tooBig) return reject(new HttpError(413, 'Request body too large (max 1 MB)'));
        const txt = Buffer.concat(chunks).toString('utf8');
        if (!txt.trim()) return resolve({});
        // v4.1 (SEC-01): a body must be sent as JSON (text/plain and form posts are what cross-site pages can send without a preflight)
        if (!isJsonType(req.headers['content-type'])) return reject(new HttpError(415, 'Send the request body as JSON (Content-Type: application/json)', null, { code: 'json_required' }));
        try { resolve(JSON.parse(txt)); } catch { reject(new HttpError(400, 'Body is not valid JSON')); }
      });
      req.on('error', reject);
    });
  }

  // v4 (R14): security headers on every response; a CSP on HTML pages (inline scripts allowed by their sha256 hash only)
  // Referrer-Policy: map tile servers (OSM) require a Referer; strict-origin-when-cross-origin sends only the origin cross-site.
  // Proxy mode (PORTAL_PROXY_SECRET): the page is framed by the Tech Drona LMS admin dashboard on the same origin, so framing is
  // allowed for the same origin only (SAMEORIGIN / frame-ancestors 'self'); standalone keeps DENY / 'none'. Decided per request.
  const secHeaders = () => ({ 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': proxyMode() ? 'SAMEORIGIN' : 'DENY', 'Referrer-Policy': 'strict-origin-when-cross-origin' });
  const cspCache = new Map();
  function cspFor(file, mtimeMs) {
    const framed = proxyMode();
    const hit = cspCache.get(file);
    if (hit && hit.m === mtimeMs && hit.framed === framed) return hit.csp;
    let hashes = [];
    try {
      const html = fs.readFileSync(file, 'utf8');
      hashes = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map((x) => `'sha256-${crypto.createHash('sha256').update(x[1], 'utf8').digest('base64')}'`);
    } catch { /* unreadable: no inline scripts allowed */ }
    const tiles = 'https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com';
    const csp = [`default-src 'self'`, `script-src 'self' ${hashes.join(' ')}`.trim(), `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com`,
      `font-src 'self' data: https://fonts.gstatic.com`, `img-src 'self' data: blob: ${tiles}`, `connect-src 'self'`, `object-src 'none'`,
      `base-uri 'self'`, `form-action 'self'`, framed ? `frame-ancestors 'self'` : `frame-ancestors 'none'`].join('; ');
    cspCache.set(file, { m: mtimeMs, framed, csp });
    return csp;
  }

  function send(req, res, status, obj, extra = null) {
    let buf = Buffer.from(JSON.stringify(obj));
    const headers = { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...secHeaders(), ...(extra || {}) };
    if (buf.length > 1024 && /\bgzip\b/.test(req.headers['accept-encoding'] || '')) { buf = zlib.gzipSync(buf); headers['Content-Encoding'] = 'gzip'; headers.Vary = 'Accept-Encoding'; }
    headers['Content-Length'] = buf.length;
    res.writeHead(status, headers);
    res.end(buf);
  }

  function serveStatic(req, res, url) {
    let rel;
    try { rel = decodeURIComponent(url.pathname); } catch { return send(req, res, 400, { error: 'Bad path' }); }
    if (rel.includes('\0')) return send(req, res, 400, { error: 'Bad path' });
    if (rel === '/favicon.ico') rel = '/assets/favicon.svg'; // browsers request it regardless of <link rel=icon>
    let file = path.resolve(PUBLIC_DIR, `.${path.posix.normalize(`/${rel}`)}`);
    if (file !== PUBLIC_DIR && !file.startsWith(PUBLIC_DIR + path.sep)) return send(req, res, 403, { error: 'Forbidden' });
    fs.stat(file, (err, st) => {
      if (!err && st.isDirectory()) { file = path.join(file, 'index.html'); }
      fs.stat(file, (err2, st2) => {
        if (err2 || !st2.isFile()) {
          res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8', ...secHeaders() });
          return res.end('Not found');
        }
        const type = MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
        const headers = { 'Content-Type': type, 'Cache-Control': 'no-cache', ...secHeaders(), 'Last-Modified': st2.mtime.toUTCString() };
        if (type.startsWith('text/html') && process.env.PORTAL_CSP !== 'off') headers['Content-Security-Policy'] = cspFor(file, st2.mtimeMs);
        if (req.headers['if-modified-since'] && new Date(req.headers['if-modified-since']) >= new Date(st2.mtime.toUTCString())) { res.writeHead(304, headers); return res.end(); }
        const compress = /^(text|application\/(json|geo\+json|javascript))|image\/svg/.test(type) && st2.size > 1024 && /\bgzip\b/.test(req.headers['accept-encoding'] || '');
        if (compress) { headers['Content-Encoding'] = 'gzip'; headers.Vary = 'Accept-Encoding'; }
        else headers['Content-Length'] = st2.size;
        res.writeHead(200, headers);
        if (req.method === 'HEAD') return res.end();
        const stream = fs.createReadStream(file);
        (compress ? stream.pipe(zlib.createGzip()) : stream).pipe(res);
      });
    });
  }

  // v4.1 (F9, SEC-04, BE-21): Host allow-list ALWAYS on (DNS rebinding): localhost, IP literals (a rebinding page always uses a DNS name),
  // the HOST env value, and PORTAL_ALLOWED_HOSTS / ALLOWED_HOSTS (comma list, e.g. portal.local). Any port. Else 403 {code:'bad_host'}.
  const allowedHosts = () => `${process.env.PORTAL_ALLOWED_HOSTS || ''},${process.env.ALLOWED_HOSTS || ''},${process.env.HOST || ''}`.split(',').map((x) => hostName(x.trim())).filter(Boolean);
  const hostOk = (h) => { const n = hostName(h); return !!n && (isIpLiteral(n) || n === 'localhost' || allowedHosts().includes(n)); };
  /** the host the browser used: X-Forwarded-Host (only with TRUST_PROXY=1, e.g. behind the LMS proxy), else Host */
  const publicHost = (req) => (trustProxy() && firstHeader(req, 'x-forwarded-host')) || req.headers.host;
  // v4.1 (SEC-01): a state-changing request must come from this origin: Sec-Fetch-Site (when sent) is same-origin/none, and Origin (when sent)
  // has exactly this request's Host. Cross-site and same-site (another localhost port) pages are refused with 403 {code:'cross_origin'}.
  function originOk(req) {
    const sfs = req.headers['sec-fetch-site'];
    if (sfs && !['same-origin', 'none'].includes(String(sfs).toLowerCase())) return false;
    const o = req.headers.origin;
    if (o == null) return true;
    let u; try { u = new URL(String(o)); } catch { return false; }
    if (u.host.toLowerCase() === String(publicHost(req) || '').toLowerCase() && hostOk(u.host)) return true;
    // behind a trusted proxy the page's origin may differ from the Host the proxy sends: accept only explicitly allowed hosts
    return trustProxy() && u.protocol === 'https:' && allowedHosts().includes(hostName(u.host));
  }
  /**
   * Proxy mode: every request must carry x-td-proxy-secret (except GET/HEAD /api/health for container health checks). A verified request
   * gets req.__tdProxy = {role, user} from x-td-proxy-role / x-td-proxy-user (the LMS admin session), used instead of the passcode sign-in.
   * Returns true when the request was answered (refused) here.
   */
  function proxyGate(req, res) {
    if (!proxyMode()) return false;
    const p = String(req.url || '').split('?')[0];
    if ((req.method === 'GET' || req.method === 'HEAD') && p === '/api/health') return false;
    const secret = proxySecret(); const given = req.headers['x-td-proxy-secret'];
    if (!secret || given == null || Array.isArray(given) || !safeEq(given, secret)) {
      if (!req.readableEnded) req.resume();
      send(req, res, 401, { error: 'This portal is only reachable through the Tech Drona LMS', code: 'proxy_required' });
      return true;
    }
    let user = '';
    try { const raw = req.headers['x-td-proxy-user']; user = cleanUser(Array.isArray(raw) ? raw[0] : String(raw || '')); } catch { user = ''; }
    const role = firstHeader(req, 'x-td-proxy-role').toLowerCase() === 'editor' ? 'editor' : 'viewer';
    req.__tdProxy = { role, user: user || 'LMS admin' };
    return false;
  }
  async function handler(req, res) {
    if (proxyGate(req, res)) return;
    const viaProxy = !!req.__tdProxy; // the LMS proxy checks Host/Origin itself; Host is an internal name such as college-portal:4173
    if (!viaProxy && !hostOk(req.headers.host) && !(trustProxy() && hostOk(firstHeader(req, 'x-forwarded-host')))) { if (!req.readableEnded) req.resume(); return send(req, res, 403, { error: 'Unknown host', code: 'bad_host' }); }
    let url;
    try { url = new URL(req.url, 'http://localhost'); } catch { return send(req, res, 400, { error: 'Bad path' }); }
    if (url.pathname.startsWith('/api/') || url.pathname === '/api') {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) {
        if (!viaProxy && !originOk(req)) { req.resume(); return send(req, res, 403, { error: 'This change must come from the portal page itself (cross-origin request refused)', code: 'cross_origin' }); }
        const ct = req.headers['content-type'];
        if (ct != null && String(ct).trim() !== '' && !isJsonType(ct)) { req.resume(); return send(req, res, 415, { error: 'Send the request body as JSON (Content-Type: application/json)', code: 'json_required' }); }
      }
      try {
        const out = await handleApi(req, url);
        if (out && out.__status) return send(req, res, out.__status, out.body, out.headers);
        return send(req, res, 200, out ?? {});
      } catch (e) {
        if (!req.readableEnded) req.resume(); // an early error (401/403/429) leaves the body unread: drain it so the keep-alive socket stays usable
        if (e instanceof HttpError) return send(req, res, e.status, { error: e.message, ...(e.fields ? { fields: e.fields } : {}), ...(e.extra || {}) }, e.status === 429 && e.extra?.retry_after_s ? { 'Retry-After': String(e.extra.retry_after_s) } : null);
        const msg = String(e?.message || e);
        // v4 (BE-17): plain-language messages, no table or constraint names
        if (/FOREIGN KEY constraint failed/i.test(msg)) return send(req, res, 409, { error: 'This record is still linked to other records (people, enrollments, activities...). Remove those first.', code: 'linked_records' });
        if (/UNIQUE constraint failed/i.test(msg)) {
          const col = /UNIQUE constraint failed:\s*\w+\.(\w+)/i.exec(msg)?.[1];
          return send(req, res, 409, { error: 'This already exists (duplicate).', code: 'duplicate', ...(col ? { fields: { [col]: 'Already used' } } : {}) });
        }
        const nn = /NOT NULL constraint failed:\s*\w+\.(\w+)/i.exec(msg); // safety net; validate() normally catches these first
        if (nn) return send(req, res, 400, { error: `Please fix this field — ${fieldLabel(nn[1])}: required`, fields: { [nn[1]]: 'Required' } });
        if (/CHECK constraint failed/i.test(msg)) return send(req, res, 400, { error: 'One of the values is not allowed. Please check the form.', code: 'invalid_value' });
        console.error(e);
        return send(req, res, 500, { error: 'Internal server error' });
      }
    }
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(req, res, 405, { error: 'Method not allowed' });
    return serveStatic(req, res, url);
  }

  return { handler, db, getCtx };
}

/** Proxy mode (Tech Drona LMS): PORTAL_PROXY_SECRET is set. The LMS mounts the portal at /college-portal/ and asserts the admin's identity. */
const proxyMode = () => !!process.env.PORTAL_PROXY_SECRET;
/** the proxy secret when it is long enough (>= 32 characters), else null (requests are then refused: fail closed) */
const proxySecret = () => { const s = process.env.PORTAL_PROXY_SECRET || ''; return s.length >= 32 ? s : null; };
/** where the portal sends the browser when the LMS session is gone (top window) */
const LMS_LOGIN_URL = '/login?next=%2Fadmin%2Fcollege-data';
/** TRUST_PROXY=1: the server runs behind a reverse proxy (the Tech Drona LMS web app) whose X-Forwarded-* headers are trusted. */
const trustProxy = () => process.env.TRUST_PROXY === '1';
/** first comma-separated value of a request header ('' when absent) */
const firstHeader = (req, name) => String(req?.headers?.[name] || '').split(',')[0].trim();
/** Session cookie name for standalone passcode sign-in (proxy mode sets no cookie). Default "__session". */
const cookieName = () => (/^[A-Za-z0-9_]{1,40}$/.test(process.env.SESSION_COOKIE || '') ? process.env.SESSION_COOKIE : '__session');

// Display helpers for server-written sentences (attention reasons): en-IN numbers, "3 Nov 2026" dates.
const num = (n) => (n == null ? '—' : Number(n).toLocaleString('en-IN'));
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dmy = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : (iso ?? '?'); };
const EXAM_KIND = { endsem: 'end-sem exams', mid: 'mid exams', lab: 'lab exams' };

function safeJson(s) { if (s == null) return null; try { return JSON.parse(s); } catch { return s; } }
function parseAudit(r) { return { ...r, before: safeJson(r.before), after: safeJson(r.after) }; }

/** v4 (R14): loopback addresses. Anything else exposes the portal to the network. */
export const isLoopback = (h) => ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(String(h).toLowerCase()) || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(String(h));
/** v4.1: host name of a Host header / host value ("[::1]:4173" -> "::1", "Localhost:80" -> "localhost"). */
const hostName = (h) => String(h || '').trim().toLowerCase().replace(/^\[([^\]]+)\](:\d+)?$/, '$1').replace(/^([^:]+):\d+$/, '$1').replace(/\.$/, '');
/** v4.1: an IPv4 dotted quad or an IPv6 literal (as hostName returns it). */
const isIpLiteral = (n) => /^\d{1,3}(\.\d{1,3}){3}$/.test(n) || (n.includes(':') && /^[0-9a-f:.]+$/.test(n));
/**
 * Start the HTTP server. v4 (R14): binds loopback (127.0.0.1 + ::1) unless HOST is set; a non-loopback host (e.g. 0.0.0.0 for the LAN)
 * refuses to start without PORTAL_PASSCODE, because every read and write would then be open to the network.
 */
/** null when it is safe to listen on `host`, else an Error (code INSECURE_HOST). */
export function hostGuard(host) {
  // proxy mode: the container binds 0.0.0.0 on the internal network, but every request must carry the LMS proxy secret
  if (isLoopback(host) || process.env.PORTAL_PASSCODE || proxySecret()) return null;
  const e = new Error(`Refusing to listen on ${host} without PORTAL_PASSCODE: the portal would be open to everyone on the network. Set PORTAL_PASSCODE (and optionally PORTAL_VIEWER_PASSCODE), or use HOST=127.0.0.1.`);
  e.code = 'INSECURE_HOST';
  return e;
}
/**
 * With no HOST (env or argument) the portal listens on BOTH loopback addresses, 127.0.0.1 and ::1, on the same port:
 * on Windows `localhost` resolves to ::1 first, and an IPv4-only listener made browser loads wait for the fallback.
 * The ::1 listener is best effort (skipped when IPv6 is unavailable). `server.close()` closes both.
 */
export function startServer({ port = Number(process.env.PORT) || 4173, host = process.env.HOST || '', db } = {}) {
  const dual = !host;
  if (dual) host = '127.0.0.1';
  if (proxyMode() && !proxySecret()) {
    const e = new Error('PORTAL_PROXY_SECRET must be at least 32 characters long (it is the shared secret between the Tech Drona LMS proxy and this portal).');
    e.code = 'WEAK_PROXY_SECRET';
    return Promise.reject(e);
  }
  const guard = hostGuard(host);
  if (guard) return Promise.reject(guard);
  const app = createApp({ db });
  const onRequest = (req, res) => { app.handler(req, res).catch((e) => { console.error(e); try { res.writeHead(500); res.end(); } catch { /* ignore */ } }); };
  const server = http.createServer(onRequest);
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      const bound = server.address().port;
      const hosts = [host];
      const done = () => resolve({ server, app, port: bound, host, hosts });
      if (!dual) return done();
      const v6 = http.createServer(onRequest);
      v6.once('error', done); // no IPv6 (or ::1 port taken): IPv4 only
      v6.listen(bound, '::1', () => {
        const closeV4 = server.close.bind(server);
        server.close = (cb) => { v6.close(); return closeV4(cb); };
        server.v6 = v6;
        hosts.push('::1');
        done();
      });
    });
  });
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const { port, host, hosts } = await startServer().catch((e) => {
    console.error(e.code === 'EADDRINUSE' ? `Port ${e.port} is already in use. Stop the other server or run with PORT=<other port>.` : (['INSECURE_HOST', 'WEAK_PROXY_SECRET'].includes(e.code) ? e.message : e));
    process.exit(1);
  });
  for (const k of ['PORTAL_PASSCODE', 'PORTAL_VIEWER_PASSCODE']) if (process.env[k] && process.env[k].length < 6) console.warn(`Warning: ${k} is shorter than 6 characters; use a longer passcode.`);
  const shown = isLoopback(host) ? 'localhost' : host;
  if (proxyMode()) console.log('Proxy mode: requests are accepted only from the Tech Drona LMS (x-td-proxy-secret); sign-in comes from the LMS session.');
  console.log(`Tech Drona portal running at http://${shown}:${port}  (listening on ${hosts.join(' and ')}${isLoopback(host) ? ', this computer only; set HOST=0.0.0.0 and PORTAL_PASSCODE to share on the LAN' : ', reachable from the network'})`
    + `${process.env.PORTAL_PASSCODE ? ' — sign-in with the passcode required' : ''}`);
}
