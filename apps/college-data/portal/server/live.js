// Live official-source data: automates the sources the Nov 2026 research used, so the portal shows the latest
// published data instead of only the one-time research snapshot.
//
//   eapcet               AP EAPCET counselling college list (APSCHE/APCFSS CAP public API, JSON)
//   ecet                 AP ECET (lateral entry) counselling college list (same API, JSON)
//   jntuk_affiliated     JNTUK affiliated-colleges tables per district (www.jntuk.edu.in/examinations, HTML)
//   jntuk_notifications  JNTUK "Notifications and Circulars" (+ Important Note, Live Scrollings) (HTML)
//   websites             each college's own website: reachable or not (HTTP)
//
// Model: stale-while-revalidate. Every source has a TTL; GET /api/live?refresh=1 (sent by the app when a user opens
// it) starts a background refresh of each stale source and returns at once. A failed fetch never deletes the last
// good copy: the API keeps serving it, marked using_fallback with the time it was fetched. Nothing here overwrites
// the researched college record; differences are reported as `diffs` for an editor to accept (existing PATCH flow).
// Storage: SQLite tables below, in the portal database (part of the Tech Drona LMS stack's backups).
import crypto from 'node:crypto';

export const UA = 'TechDronaPortal/1.0 (Tech Drona LMS college data portal; outreach research)';
const CAP = 'https://api.cap.apcfss.in/oamreadapi/oam-public';

export const SOURCES = {
  eapcet: { name: 'AP EAPCET counselling list', url: `${CAP}/eapcet-clg-home-page-details`, ttl_min: 360,
    provides: 'Colleges in B.Tech counselling, branches, counselling (convener-quota) seats, seats still empty, fees, college office phone/email/website, affiliation' },
  ecet: { name: 'AP ECET counselling list', url: `${CAP}/ecet-clg-home-page-details`, ttl_min: 360,
    provides: 'Colleges in lateral-entry (2nd-year) counselling, branches, seats, seats still empty' },
  jntuk_affiliated: { name: 'JNTUK affiliated colleges', url: 'https://www.jntuk.edu.in/examinations', ttl_min: 1440,
    provides: 'Colleges currently listed as JNTUK-affiliated (by district), college code (CC), courses offered' },
  jntuk_notifications: { name: 'JNTUK notifications', url: 'https://www.jntuk.edu.in/notifications', ttl_min: 30,
    provides: 'Official circulars: exam timetables, results, academic calendar, holidays, admissions' },
  websites: { name: 'College websites', url: null, ttl_min: 1440,
    provides: 'Whether each college website is up (HTTP check)' },
};
const RETRY_AFTER_FAIL_MIN = 15;

/** What can and cannot be automated — shown to users verbatim (GET /api/live → automation). */
export const AUTOMATION = [
  { topic: 'College list & active status', status: 'automatic', source: 'AP EAPCET + ECET lists, JNTUK affiliated list, website check',
    how: 'Checked every 6–24 h and on site open', note: 'A college missing from every official list is flagged, never auto-closed — closure needs a person to confirm.' },
  { topic: 'Branches & seats (current year)', status: 'automatic', source: 'AP EAPCET / ECET counselling lists',
    how: 'Every 6 h', note: 'Counselling (convener-quota) seats and seats still empty, not the total sanctioned intake.' },
  { topic: 'College phone, email, website, affiliation', status: 'automatic', source: 'AP EAPCET counselling list',
    how: 'Every 6 h; differences from our record are shown for one-click approval', note: 'These are principal/office lines, not TPO contacts.' },
  { topic: 'Exam schedules & results', status: 'partial', source: 'JNTUK notifications',
    how: 'Every 30 min: new circulars are pulled and sorted (exams, results…)', note: 'Dates live inside PDF timetables; per-college exam dates still need a person to enter them. Autonomous colleges publish their own.' },
  { topic: 'Academic calendar & holidays', status: 'partial', source: 'JNTUK notifications',
    how: 'Every 30 min (circulars mentioning calendar/holidays)', note: 'State holiday lists and college-specific holidays are not published as data.' },
  { topic: 'Official announcements', status: 'partial', source: 'JNTUK notifications',
    how: 'Every 30 min', note: 'University-level only. College-website news has no common format and is not scraped.' },
  { topic: 'Student strength (enrolled students)', status: 'manual', source: 'NIRF data files, AICTE approval letters (yearly PDFs)',
    how: 'Research team, once a year', note: 'No live official feed exists; nirfindia.org and the AICTE dashboard block automated requests. Seats from counselling are shown as a live proxy.' },
  { topic: 'Placements', status: 'manual', source: 'NIRF data files, college placement pages',
    how: 'Research team, once a year', note: 'Published yearly as PDFs; numbers are self-reported by colleges.' },
  { topic: 'TPO / staff contacts', status: 'manual', source: 'Calls, college websites',
    how: 'Verified by the calling team', note: 'Not in any official feed.' },
];

const SCHEMA = `
CREATE TABLE IF NOT EXISTS live_sources (
  id TEXT PRIMARY KEY, last_attempt_at TEXT, last_success_at TEXT, last_status TEXT NOT NULL DEFAULT 'never',
  last_error TEXT, http_status INTEGER, item_count INTEGER, content_hash TEXT, changed_at TEXT, duration_ms INTEGER);
CREATE TABLE IF NOT EXISTS live_snapshots (source TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_announcements (
  uid TEXT PRIMARY KEY, source TEXT NOT NULL, date TEXT, title TEXT NOT NULL, dept TEXT, section TEXT, category TEXT NOT NULL,
  attachments TEXT, url TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_live_ann_date ON live_announcements(date DESC);
CREATE TABLE IF NOT EXISTS live_web (
  college_id TEXT PRIMARY KEY, url TEXT, ok INTEGER, http_status INTEGER, final_url TEXT, error TEXT, checked_at TEXT, last_ok_at TEXT);
CREATE TABLE IF NOT EXISTS live_changes (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, source TEXT NOT NULL, college_id TEXT, summary TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_live_changes_at ON live_changes(at DESC);
`;

// ------------------------------------------------------------------ text helpers
const decodeEntities = (s) => String(s ?? '')
  .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
  .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
  .replace(/&rsquo;|&lsquo;/g, "'").replace(/&ndash;|&mdash;/g, '-').replace(/&nbsp;/g, ' ').replace(/&quot;/g, '"').replace(/&#039;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const textOf = (html) => decodeEntities(String(html ?? '').replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ').trim();
const sha = (s) => crypto.createHash('sha256').update(s).digest('hex');
const clean = (v) => { if (v == null) return null; const s = String(v).trim(); return s === '' || /^(null|na|nil|-)$/i.test(s) ? null : s; };
const MONTH = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

const ABBR = [[/\bengg\b|\bengineerig\b/g, 'engineering'], [/\binstt?\b|\binstitue\b/g, 'institute'], [/\bjntuk\b/g, 'jntu kakinada'], [/\bnara?saraopeta?\b/g, 'narasaraopet'], [/\btech\b/g, 'technology'], [/\bsci\b|\bsciences\b/g, 'science'],
  [/\bcoll\b/g, 'college'], [/\bpharm\b|\bpharmaceutical\b|\bpharma\b/g, 'pharmacy'], [/\bmgmt\b/g, 'management'], [/\bwomens\b/g, 'women'], [/\bsri\b|\bshri\b|\bsree\b/g, 'sri']];
const STOP = new Set(['of', 'and', 'the', 'for', 'college', 'colleges', 'engineering', 'technology', 'technological', 'institute', 'institution',
  'institutions', 'science', 'sciences', 'group', 'in', 'at', 'a', 'educational', 'society', 'research', 'management', 'studies', 'campus', 'dt', 'dist', 'district', 'mandal', 'post', 'po']);
const WEAK = new Set(['sri', 'shri', 'sree', 'women', 'st', 'dr', 'new', 'govt', 'government', 'national', 'international', 'india', 'andhra', 'pradesh']); // too common to identify a college
const GLUE = new Set(['of', 'and', 'the', 'for', 'in', 'at', 'a']);
/** nameTokens(s, true): keep generic words too (used only to break ties: 'Engineering College' vs 'Institute of Technology') */
export function nameTokens(s, full = false) {
  let t = decodeEntities(String(s ?? '')).toLowerCase().replace(/&/g, ' and ').replace(/\([^)]*\)/g, (m) => ` ${m.slice(1, -1)} `);
  // dotted initials become one word ("B.V.C." -> "bvc", "A.M.Reddy" -> "am reddy"); other dots separate words ("PHARM.SCI.")
  t = t.replace(/\b(?:[a-z]\.\s?){2,}/g, (m) => `${m.replace(/[.\s]/g, '')} `).replace(/['’`]/g, '').replace(/[^a-z0-9]+/g, ' ');
  for (const [re, to] of ABBR) t = t.replace(re, to);
  return new Set(t.split(' ').filter((w) => w.length > 1 && !(full ? GLUE : STOP).has(w)));
}
const jaccard = (a, b) => { if (!a.size || !b.size) return 0; let i = 0; for (const x of a) if (b.has(x)) i++; return i / (a.size + b.size - i); };
/** containment score: share of the smaller name's tokens found in the other (handles "NIMRA COLLEGE OF ENGG., JUPUDI" vs "Nimra CE") */
const contain = (a, b) => { if (!a.size || !b.size) return 0; let i = 0; for (const x of a) if (b.has(x)) i++; return i / Math.min(a.size, b.size); };
const nameScore = (a, b) => Math.max(jaccard(a, b), 0.85 * contain(a, b) * (Math.min(a.size, b.size) >= 2 ? 1 : 0.6));

export const hostOf = (u) => { const s = clean(u); if (!s) return null; try { return new URL(/^https?:\/\//i.test(s) ? s : `http://${s}`).hostname.toLowerCase().replace(/^www\./, ''); } catch { return null; } };
const digits = (p) => String(p ?? '').replace(/\D/g, '').replace(/^(91|0)+/, '');

// ------------------------------------------------------------------ parsers (pure; covered by tests with saved real responses)
/** CAP EAPCET / ECET JSON → [{code, name, …, branches:[…], totals}] */
export function parseCap(json) {
  const j = typeof json === 'string' ? JSON.parse(json) : json;
  if (!j || !Array.isArray(j.data)) throw new Error('Unexpected response: no data array');
  return j.data.map((r) => {
    let br = [];
    try { br = typeof r.courses_offered_arr === 'string' ? JSON.parse(r.courses_offered_arr) : (r.courses_offered_arr || []); } catch { br = []; }
    const branches = (Array.isArray(br) ? br : []).map((b) => {
      const seats = Number(b.total_seats) || 0; const left = Number(b.left_over_seats) || 0;
      return { code: clean(b.branch_code), name: clean(b.branch_name), course_type: clean(b.course_type), total_seats: seats, left_over_seats: left,
        filled: Math.max(0, seats - left), fee: b.fee_with_no_exemption == null ? null : Number(b.fee_with_no_exemption) };
    }).sort((a, b) => String(a.code).localeCompare(String(b.code)));
    const totals = branches.reduce((t, b) => ({ seats: t.seats + b.total_seats, left_over: t.left_over + b.left_over_seats, filled: t.filled + b.filled }), { seats: 0, left_over: 0, filled: 0 });
    return {
      code: clean(r.inst_code), name: clean(r.inst_name), place: clean(r.place), district: clean(r.district_id ?? r.dist_name),
      affiliated_to: clean(r.affiliated_to), college_type: clean(r.college_type), co_educ: clean(r.co_educ), aid_unaid: clean(r.aid_unaid),
      year_of_estab: r.year_of_estab == null ? null : Number(r.year_of_estab), phone: clean(r.ph_no), ao_mobile: clean(r.ao_mobile_no),
      email: clean(r.e_mail), website: clean(r.website), entry_date: clean(r.entry_date), minority: clean(r.minority),
      address: [r.address1, r.address2, r.address3].map(clean).filter(Boolean).join(', ') || null,
      branches, totals,
    };
  }).filter((r) => r.code).sort((a, b) => a.code.localeCompare(b.code));
}

/** JNTUK examinations page → [{district, cc, name, courses}] from the per-district affiliated-college tables */
export function parseJntukAffiliated(html) {
  const s = String(html);
  const out = [];
  const re = /<h3>([^<]{2,60})<\/h3>\s*<div class="content-text">\s*<table>([\s\S]*?)<\/table>/g;
  for (const m of s.matchAll(re)) {
    const district = textOf(m[1]);
    for (const tr of m[2].matchAll(/<tr>([\s\S]*?)<\/tr>/g)) {
      const cells = [...tr[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((c) => textOf(c[1]));
      if (cells.length < 4) continue;
      out.push({ district, cc: cells[1] || null, name: cells[2], courses: cells[3] || null });
    }
  }
  if (!out.length) throw new Error('Unexpected page layout: no affiliated-college tables found');
  return out;
}

const NOTICE_SECTIONS = ['Notifications and Circulars', 'Important Note', 'Live Scrollings'];
export const CATEGORIES = [
  ['exam', 'Exams & timetables'], ['result', 'Results'], ['calendar', 'Academic calendar'], ['holiday', 'Holidays'],
  ['admission', 'Admissions'], ['other', 'Other circulars'],
];
export function categorize(title) {
  const t = String(title).toLowerCase();
  if (/holiday|vacation|declared .*closed|sankranthi|sankranti|dasara|dussehra|deepavali|diwali|christmas|pongal/.test(t)) return 'holiday';
  if (/academic calend|almanac|calendar of events|calendar/.test(t)) return 'calendar';
  if (/result|revaluation|recounting|re-?verification|marks memo/.test(t)) return 'result';
  if (/exam|examination|time ?-?table|hall ?ticket|practical|mid ?term|sem(ester)?\b.*(reg|supply)|supplementary|fee notification|jumbling|clustering/.test(t)) return 'exam';
  if (/admission|counsell?ing|spot|certificates? verification|eapcet|ecet|pgecet|icet|lateral|convener|seat/.test(t)) return 'admission';
  return 'other';
}
/** JNTUK notifications page → [{uid, date, title, dept, section, category, attachments:[{name,url}]}] */
export function parseJntukNotifications(html, base = 'https://www.jntuk.edu.in/') {
  const s = String(html);
  const abs = (h) => { try { return new URL(decodeEntities(h), base).href; } catch { return null; } };
  // attachments live in hidden "att_row_*" blocks after the tables
  const att = new Map();
  for (const m of s.matchAll(/<div id="(att_row_[\w]+)" class="att-store-item">([\s\S]*?)(?=<div id="att_row_|<\/section|<footer|$)/g)) {
    const items = [];
    for (const it of m[2].matchAll(/<div class="att-name">([\s\S]*?)<\/div>[\s\S]*?<a href="([^"]+)"/g)) {
      const url = abs(it[2]); if (url && /^https?:/.test(url)) items.push({ name: textOf(it[1]), url });
    }
    att.set(m[1], items);
  }
  // sections: <h2 class="event-title"> NAME </h2> … <table … id="table_N"> … </table>
  const out = [];
  const heads = [...s.matchAll(/<h2 class="event-title">([\s\S]*?)<\/h2>/g)].map((m) => ({ name: textOf(m[1]), at: m.index }));
  heads.forEach((hd, i) => {
    if (!NOTICE_SECTIONS.includes(hd.name)) return;
    const seg = s.slice(hd.at, i + 1 < heads.length ? heads[i + 1].at : undefined);
    for (const m of seg.matchAll(/<tr class="notif-row[^"]*"([^>]*)>([\s\S]*?)<\/tr>/g)) {
      const attId = /data-att-id="([^"]+)"/.exec(m[1])?.[1] || null;
      const row = m[2];
      const title = textOf(/<div class="notif-title">([\s\S]*?)<\/div>/.exec(row)?.[1]);
      if (!title) continue;
      const mon = MONTH[textOf(/nd-mon">([^<]*)</.exec(row)?.[1]).slice(0, 3).toLowerCase()];
      const day = Number(textOf(/nd-day">([^<]*)</.exec(row)?.[1])); const yr = Number(textOf(/nd-yr">([^<]*)</.exec(row)?.[1]));
      const date = mon && day && yr ? `${yr}-${String(mon).padStart(2, '0')}-${String(day).padStart(2, '0')}` : null;
      const dept = textOf(/<span class="notif-dept">([\s\S]*?)<\/span>/.exec(row)?.[1]) || null;
      const direct = /<a href="([^"]+)"/.exec(row)?.[1];
      const attachments = attId && att.has(attId) ? att.get(attId) : (direct && abs(direct) ? [{ name: title, url: abs(direct) }] : []);
      const uid = `jntuk:${sha(`${date}|${title.toLowerCase()}`).slice(0, 20)}`; // same notice in two sections = one item
      out.push({ uid, date, title, dept, section: hd.name, category: categorize(title), attachments });
    }
  });
  if (!out.length) throw new Error('Unexpected page layout: no notification rows found');
  const seen = new Set();
  return out.filter((n) => (seen.has(n.uid) ? false : seen.add(n.uid)));
}

// ------------------------------------------------------------------ linking our colleges to source records
const JNTUK_DISTRICTS = { krishna: ['krishna', 'ntr'], guntur: ['guntur', 'palnadu', 'bapatla'], 'west godavari': ['west-godavari', 'eluru', 'polavaram'],
  'east godavari': ['east-godavari', 'kakinada', 'konaseema'], prakasam: ['prakasam', 'bapatla'] }; // Bapatla district (2022) took Chirala/Vetapalem from Prakasam
const CAP_DISTRICTS = { KRISHNA: JNTUK_DISTRICTS.krishna, GUNTUR: JNTUK_DISTRICTS.guntur, 'WEST GODAVARI': JNTUK_DISTRICTS['west godavari'], 'EAST GODAVARI': JNTUK_DISTRICTS['east godavari'] };

/** research codes: "CAP 2026 code KITS/CSE" in branch notes, "EAPCET: KHIT" in college notes */
function researchCodes(db) {
  const m = new Map();
  const add = (cid, code) => { if (!m.has(cid)) m.set(cid, new Set()); m.get(cid).add(code); };
  for (const r of db.prepare("SELECT college_id, notes FROM branches WHERE notes LIKE '%CAP 2026 code %'").all()) {
    for (const x of String(r.notes).matchAll(/CAP 2026 code ([A-Z0-9]{3,8})\//g)) add(r.college_id, x[1]);
  }
  for (const r of db.prepare("SELECT id, notes FROM colleges WHERE notes LIKE '%EAPCET: %'").all()) {
    const x = /EAPCET: ([A-Z0-9]{3,8})\b/.exec(r.notes || ''); if (x) add(r.id, x[1]);
  }
  return m;
}
function collegeKeys(db) {
  return db.prepare('SELECT c.id, c.name, c.short_name, c.aliases, c.district_id, c.website, ci.name AS city FROM colleges c LEFT JOIN cities ci ON ci.id = c.city_id').all().map((c) => {
    let aliases = []; try { aliases = JSON.parse(c.aliases || '[]'); } catch { /* ignore */ }
    const names = [c.name, c.short_name, ...(Array.isArray(aliases) ? aliases : [])].filter(Boolean);
    const sets = names.map((n) => nameTokens(n)).filter((t) => t.size);
    const full = names.map((n) => nameTokens(n, true)).filter((t) => t.size);
    return { ...c, sets, full, city_t: nameTokens(c.city), host: hostOf(c.website) };
  });
}
/**
 * Link each college to at most one record of a source. Research codes win; otherwise a name match that is clearly the
 * best (score ≥ 0.6 and ≥ 0.12 ahead of the runner-up, district-compatible when the source gives one, website host
 * agreeing when both have one). Ambiguous → not linked (shown as "not linked", never guessed).
 */
export function linkColleges(colleges, records, { codeOf, nameOf, placeOf, districtsOf, hostOfRec, research }) {
  const links = new Map(); // college_id -> {key, basis, score}
  const byCode = new Map(records.map((r) => [codeOf(r), r]));
  const taken = new Set();
  if (research) {
    for (const c of colleges) {
      const codes = [...(research.get(c.id) || [])].filter((k) => byCode.has(k));
      if (codes.length) { links.set(c.id, { key: codes[0], basis: 'research_code', score: 1, also: codes.slice(1) }); codes.forEach((k) => taken.add(k)); }
    }
  }
  const recT = records.map((r) => ({ r, t: nameTokens(nameOf(r)), f: nameTokens(nameOf(r), true), p: nameTokens(placeOf ? placeOf(r) : ''), d: districtsOf ? districtsOf(r) : null, h: hostOfRec ? hostOfRec(r) : null }));
  for (const c of colleges) {
    if (links.has(c.id) || !c.sets.length) continue;
    const scored = [];
    for (const x of recT) {
      if (taken.has(codeOf(x.r))) continue;
      const districtOk = !!(x.d && x.d.length && c.district_id && x.d.includes(c.district_id));
      if (x.d && x.d.length && c.district_id && !districtOk) continue;
      // a pharmacy / women's college is never the same institution as a non-pharmacy / co-ed one
      const ours = new Set(c.sets.flatMap((t) => [...t]));
      if (['pharmacy', 'pharmaceutical', 'pharma'].some((w) => x.t.has(w)) && !['pharmacy', 'pharmaceutical', 'pharma'].some((w) => ours.has(w))) continue;
      let s = 0; let shared = []; // best-scoring name variant and the words it shares
      for (const t of c.sets) { const sc = nameScore(t, x.t); if (sc > s) { s = sc; shared = [...t].filter((w) => x.t.has(w)); } }
      if (x.t.has('women') !== ours.has('women')) s -= 0.25;
      s += 0.3 * Math.max(0, ...(c.full || []).map((t) => jaccard(t, x.f))); // tie-break on the full wording
      const placeHit = x.p.size && c.city_t.size && [...x.p].some((w) => c.city_t.has(w));
      const hostHit = !!(x.h && c.host && x.h === c.host);
      if (placeHit) s += 0.1;
      if (x.h && c.host) s += hostHit ? 0.3 : -0.2;
      // one shared word ("Chaitanya", "BVC") is not enough on its own: it needs the same town, the same website,
      // or a known-matching district and a distinctive (≥ 6 letters) word
      const strong = shared.filter((w) => !WEAK.has(w));
      const exact = (c.full || []).some((t) => jaccard(t, x.f) === 1); // identical wording to one of our names
      const gate = exact || strong.length >= 2 || placeHit || hostHit || (districtOk && strong.some((w) => w.length >= 6));
      if (gate && s > 0.3) scored.push({ key: codeOf(x.r), s });
    }
    scored.sort((a, b) => b.s - a.s);
    const [best, second] = scored;
    if (best && best.s >= 0.6 && (!second || best.s - second.s >= 0.12)) links.set(c.id, { key: best.key, basis: 'name_match', score: Math.round(Math.min(best.s, 1) * 100) / 100, raw: best.s });
  }
  // one record ↔ one college: if two colleges claimed the same record by name, keep neither (ambiguous)
  const claims = new Map();
  for (const [cid, l] of links) if (l.basis === 'name_match') { if (!claims.has(l.key)) claims.set(l.key, []); claims.get(l.key).push([cid, l.raw]); }
  for (const list of claims.values()) {
    if (list.length < 2) continue;
    list.sort((a, b) => b[1] - a[1]);
    const keepWinner = list[0][1] - list[1][1] >= 0.1;
    list.forEach(([cid], i) => { if (i > 0 || !keepWinner) links.delete(cid); });
  }
  for (const l of links.values()) delete l.raw;
  return links;
}

// ------------------------------------------------------------------ HTTP
async function fetchText(fetchImpl, url, { timeoutMs = 30000, maxBytes = 8 * 1024 * 1024, accept = '*/*' } = {}) {
  const res = await fetchImpl(url, { headers: { 'User-Agent': UA, Accept: accept }, redirect: 'follow', signal: AbortSignal.timeout(timeoutMs) });
  const status = res.status;
  if (!res.ok) { try { await res.body?.cancel(); } catch { /* ignore */ } const e = new Error(`HTTP ${status}`); e.http_status = status; throw e; }
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > maxBytes) throw new Error(`Response too large (${buf.length} bytes)`);
  return { status, text: buf.toString('utf8'), final_url: res.url || url };
}
/** reachability: any HTTP answer below 500 means the site is up (403 = up but blocks robots) */
async function probe(fetchImpl, url, timeoutMs = 12000) {
  const u = /^https?:\/\//i.test(url) ? url : `https://${url}`;
  const tryOnce = async (target) => {
    const res = await fetchImpl(target, { headers: { 'User-Agent': UA, Accept: 'text/html,*/*' }, redirect: 'follow', signal: AbortSignal.timeout(timeoutMs) });
    try { await res.body?.cancel(); } catch { /* ignore */ }
    return { http_status: res.status, final_url: res.url || target, ok: res.status < 500 && res.status !== 404 && res.status !== 410 };
  };
  try { return await tryOnce(u); } catch (e) {
    if (/^https:/i.test(u)) { try { return await tryOnce(u.replace(/^https:/i, 'http:')); } catch { /* fall through */ } }
    return { http_status: null, final_url: null, ok: false, error: String(e?.cause?.code || e?.name === 'TimeoutError' ? (e?.cause?.code || 'Timed out') : (e?.message || e)).slice(0, 200) };
  }
}
async function pool(items, n, fn) { let i = 0; await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => { while (i < items.length) { const k = i++; await fn(items[k], k); } })); }

// ------------------------------------------------------------------ the service
export function createLive(db, { fetchImpl = globalThis.fetch, now = () => new Date(), log = (...a) => console.log('[live]', ...a) } = {}) {
  db.exec(SCHEMA);
  const iso = () => now().toISOString();
  const running = new Map(); // source id -> promise
  const getRow = (id) => db.prepare('SELECT * FROM live_sources WHERE id = ?').get(id) || { id, last_status: 'never' };
  const snapshot = (id) => { const r = db.prepare('SELECT fetched_at, data FROM live_snapshots WHERE source = ?').get(id); if (!r) return null; try { return { fetched_at: r.fetched_at, data: JSON.parse(r.data) }; } catch { return null; } };
  const snapCache = new Map(); // id -> {fetched_at, data, links?}
  const snap = (id) => {
    const r = db.prepare('SELECT fetched_at FROM live_snapshots WHERE source = ?').get(id);
    if (!r) return null;
    const c = snapCache.get(id);
    if (c && c.fetched_at === r.fetched_at) return c;
    const s = snapshot(id); if (!s) return null;
    snapCache.set(id, s); return s;
  };
  const note = (source, college_id, summary) => db.prepare('INSERT INTO live_changes(at, source, college_id, summary) VALUES (?,?,?,?)').run(iso(), source, college_id, summary);
  const mark = (id, fields) => {
    const cur = getRow(id);
    const row = { ...cur, ...fields, id };
    db.prepare(`INSERT INTO live_sources(id, last_attempt_at, last_success_at, last_status, last_error, http_status, item_count, content_hash, changed_at, duration_ms)
      VALUES (@id,@last_attempt_at,@last_success_at,@last_status,@last_error,@http_status,@item_count,@content_hash,@changed_at,@duration_ms)
      ON CONFLICT(id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at, last_success_at=excluded.last_success_at, last_status=excluded.last_status,
        last_error=excluded.last_error, http_status=excluded.http_status, item_count=excluded.item_count, content_hash=excluded.content_hash,
        changed_at=excluded.changed_at, duration_ms=excluded.duration_ms`).run({
      id, last_attempt_at: row.last_attempt_at ?? null, last_success_at: row.last_success_at ?? null, last_status: row.last_status ?? 'never', last_error: row.last_error ?? null,
      http_status: row.http_status ?? null, item_count: row.item_count ?? null, content_hash: row.content_hash ?? null, changed_at: row.changed_at ?? null, duration_ms: row.duration_ms ?? null });
  };
  const colleges = () => collegeKeys(db);
  const nameOfCollege = (id) => db.prepare('SELECT name FROM colleges WHERE id = ?').get(id)?.name ?? null;

  // ---- links (recomputed when the snapshot or the college list changes)
  let linkCache = { key: null, links: {} };
  function links() {
    const ver = db.prepare("SELECT group_concat(source || fetched_at) v FROM live_snapshots").get()?.v || '';
    const cv = db.prepare('SELECT count(*) n, max(updated_at) u FROM colleges').get();
    const key = `${ver}|${cv.n}|${cv.u}`;
    if (linkCache.key === key) return linkCache.links;
    const cs = colleges(); const research = researchCodes(db); const out = {};
    for (const id of ['eapcet', 'ecet']) {
      const s = snap(id); if (!s) continue;
      out[id] = linkColleges(cs, s.data, { codeOf: (r) => r.code, nameOf: (r) => r.name, placeOf: (r) => r.place,
        districtsOf: (r) => CAP_DISTRICTS[String(r.district || '').toUpperCase()] || null, hostOfRec: (r) => hostOf(r.website), research });
    }
    const ja = snap('jntuk_affiliated');
    if (ja) {
      // district tables (B.Tech rows only) and the "Autonomous Colleges" table ("Name, Place [GTR]"); a college can be in both,
      // so they are linked separately and the autonomous entry wins (it also tells us the college is autonomous)
      const TAG = { EG: 'east godavari', WG: 'west godavari', KRI: 'krishna', GTR: 'guntur', PKS: 'prakasam' };
      const opts = { codeOf: (r) => r.key, nameOf: (r) => String(r.name).replace(/\[[A-Z]+\]/, '').split(',')[0],
        placeOf: (r) => String(r.name).replace(/\[[A-Z]+\]/, '').split(',').slice(1).join(' '),
        districtsOf: (r) => JNTUK_DISTRICTS[(r.district === 'Autonomous Colleges' ? TAG[String(r.courses || '').trim().toUpperCase()] : String(r.district).toLowerCase()) || ''] || null };
      const withKey = (r) => ({ ...r, key: `${r.district}|${r.cc}` });
      const auto = linkColleges(cs, ja.data.filter((r) => r.district === 'Autonomous Colleges').map(withKey), opts);
      const dist = linkColleges(cs, ja.data.filter((r) => r.district !== 'Autonomous Colleges' && /b\.?\s?tech/i.test(r.courses || '')).map(withKey), opts);
      out.jntuk_affiliated = new Map([...dist, ...auto]);
    }
    linkCache = { key, links: out };
    return out;
  }

  // ---- fetchers: each returns {data, item_count, http_status}; diff() records meaningful changes
  const FETCH = {
    async eapcet() { const r = await fetchText(fetchImpl, SOURCES.eapcet.url, { accept: 'application/json' }); const data = parseCap(r.text); return { data, http_status: r.status, item_count: data.length }; },
    async ecet() { const r = await fetchText(fetchImpl, SOURCES.ecet.url, { accept: 'application/json' }); const data = parseCap(r.text); return { data, http_status: r.status, item_count: data.length }; },
    async jntuk_affiliated() { const r = await fetchText(fetchImpl, SOURCES.jntuk_affiliated.url); const data = parseJntukAffiliated(r.text); return { data, http_status: r.status, item_count: data.length }; },
    async jntuk_notifications() { const r = await fetchText(fetchImpl, SOURCES.jntuk_notifications.url); const data = parseJntukNotifications(r.text, r.final_url); return { data, http_status: r.status, item_count: data.length }; },
    async websites() {
      const list = db.prepare("SELECT id, website FROM colleges WHERE website IS NOT NULL AND trim(website) <> ''").all();
      const results = [];
      await pool(list, 8, async (c) => { results.push({ college_id: c.id, url: c.website, ...(await probe(fetchImpl, c.website)) }); });
      if (list.length && !results.some((r) => r.http_status)) throw new Error('No college website answered (network problem on our side?)');
      results.sort((a, b) => a.college_id.localeCompare(b.college_id));
      return { data: results, http_status: null, item_count: results.length };
    },
  };
  function applyChanges(id, prev, data) {
    const at = iso();
    if (id === 'eapcet' || id === 'ecet') {
      if (!prev) return;
      const label = id === 'eapcet' ? 'EAPCET' : 'ECET';
      const pm = new Map(prev.map((r) => [r.code, r])); const nm = new Map(data.map((r) => [r.code, r]));
      const linked = new Map([...(links()[id] || new Map())].map(([cid, l]) => [l.key, cid]));
      for (const [code, r] of nm) {
        const p = pm.get(code); const cid = linked.get(code) || null;
        if (!p) note(id, cid, `${r.name} (${code}) added to the ${label} counselling list`);
        else if (p.totals.seats !== r.totals.seats || p.totals.left_over !== r.totals.left_over) {
          if (cid) note(id, cid, `${label} seats for ${r.name}: ${p.totals.seats} → ${r.totals.seats}, left over ${p.totals.left_over} → ${r.totals.left_over}`);
        }
      }
      for (const [code, p] of pm) if (!nm.has(code)) note(id, linked.get(code) || null, `${p.name} (${code}) is no longer in the ${label} counselling list`);
    } else if (id === 'jntuk_affiliated') {
      if (!prev) return;
      const k = (r) => `${r.district}|${r.cc}|${r.name}`;
      const pk = new Set(prev.map(k)); const nk = new Set(data.map(k));
      for (const r of data) if (!pk.has(k(r))) note(id, null, `JNTUK list (${r.district}): added ${r.name} (CC ${r.cc}, ${r.courses})`);
      for (const r of prev) if (!nk.has(k(r))) note(id, null, `JNTUK list (${r.district}): removed ${r.name} (CC ${r.cc})`);
    } else if (id === 'jntuk_notifications') {
      const ins = db.prepare(`INSERT INTO live_announcements(uid, source, date, title, dept, section, category, attachments, url, first_seen_at, last_seen_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET last_seen_at = excluded.last_seen_at, attachments = excluded.attachments, category = excluded.category`);
      let fresh = 0;
      for (const n of data) {
        const had = db.prepare('SELECT 1 FROM live_announcements WHERE uid = ?').get(n.uid);
        ins.run(n.uid, id, n.date, n.title, n.dept, n.section, n.category, JSON.stringify(n.attachments), n.attachments[0]?.url ?? SOURCES[id].url, at, at);
        if (!had) fresh++;
      }
      if (prev && fresh) note(id, null, `${fresh} new JNTUK notice${fresh > 1 ? 's' : ''}`);
    } else if (id === 'websites') {
      const pm = new Map((prev || []).map((r) => [r.college_id, r]));
      const up = db.prepare(`INSERT INTO live_web(college_id, url, ok, http_status, final_url, error, checked_at, last_ok_at) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(college_id) DO UPDATE SET url=excluded.url, ok=excluded.ok, http_status=excluded.http_status, final_url=excluded.final_url, error=excluded.error,
        checked_at=excluded.checked_at, last_ok_at=COALESCE(excluded.last_ok_at, live_web.last_ok_at)`);
      for (const r of data) {
        up.run(r.college_id, r.url, r.ok ? 1 : 0, r.http_status ?? null, r.final_url ?? null, r.error ?? null, at, r.ok ? at : null);
        const p = pm.get(r.college_id);
        if (p && p.ok !== r.ok) note(id, r.college_id, `Website ${r.url} is ${r.ok ? 'back up' : 'not reachable'}${r.ok ? '' : ` (${r.error || `HTTP ${r.http_status}`})`}`);
      }
    }
  }

  async function runSource(id) {
    if (running.has(id)) return running.get(id);
    const p = (async () => {
      const t0 = Date.now(); const startedAt = iso();
      mark(id, { last_attempt_at: startedAt, last_status: 'running' });
      try {
        const out = await FETCH[id]();
        const json = JSON.stringify(out.data);
        const hash = sha(json);
        const cur = getRow(id);
        const prev = snapshot(id)?.data ?? null;
        const changedAt = cur.content_hash === hash ? (cur.changed_at || startedAt) : startedAt;
        db.exec('BEGIN IMMEDIATE');
        try {
          if (cur.content_hash !== hash) applyChanges(id, prev, out.data);
          else if (id === 'websites' || id === 'jntuk_notifications') applyChanges(id, prev, out.data); // refresh checked/last_seen times
          db.prepare('INSERT INTO live_snapshots(source, fetched_at, data) VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET fetched_at=excluded.fetched_at, data=excluded.data').run(id, iso(), json);
          mark(id, { last_status: 'ok', last_success_at: iso(), last_error: null, http_status: out.http_status ?? null, item_count: out.item_count, content_hash: hash, changed_at: changedAt, duration_ms: Date.now() - t0 });
          db.exec('COMMIT');
        } catch (e) { try { db.exec('ROLLBACK'); } catch { /* ignore */ } throw e; }
        log(`${id}: ok, ${out.item_count} items, ${Date.now() - t0} ms${cur.content_hash === hash ? ' (unchanged)' : ' (changed)'}`);
      } catch (e) {
        const msg = e?.name === 'TimeoutError' || e?.cause?.code === 'UND_ERR_CONNECT_TIMEOUT' ? 'Timed out — source did not answer'
          : (e?.cause?.code ? `Network error: ${e.cause.code}` : String(e?.message || e)).slice(0, 300);
        mark(id, { last_status: 'error', last_error: msg, http_status: e?.http_status ?? null, duration_ms: Date.now() - t0 });
        log(`${id}: FAILED — ${msg}`);
      } finally { running.delete(id); }
    })();
    running.set(id, p);
    return p;
  }

  const ageMin = (t) => (t ? (now().getTime() - Date.parse(t)) / 60000 : Infinity);
  function isStale(id) {
    const r = getRow(id);
    if (r.last_status === 'error') return ageMin(r.last_attempt_at) >= Math.min(RETRY_AFTER_FAIL_MIN, SOURCES[id].ttl_min);
    return ageMin(r.last_success_at) >= SOURCES[id].ttl_min && ageMin(r.last_attempt_at) >= 1;
  }
  /** start background refresh of stale (or all, when force) sources; never awaits them */
  function refresh({ force = false, source = null } = {}) {
    const ids = source ? [source] : Object.keys(SOURCES);
    const started = [];
    for (const id of ids) if (!running.has(id) && (force || isStale(id))) { runSource(id); started.push(id); }
    return started;
  }
  async function refreshAndWait(opts) { refresh(opts); await Promise.all([...running.values()]); }

  function status() {
    const L = links();
    const sources = Object.entries(SOURCES).map(([id, s]) => {
      const r = getRow(id);
      const fresh = r.last_success_at ? ageMin(r.last_success_at) < s.ttl_min : false;
      return { id, name: s.name, url: s.url, provides: s.provides, ttl_min: s.ttl_min,
        last_attempt_at: r.last_attempt_at ?? null, last_success_at: r.last_success_at ?? null,
        last_status: running.has(id) ? 'running' : (r.last_status === 'running' ? 'error' : r.last_status), // 'running' left over from a crash = failed
        last_error: r.last_error ?? null, item_count: r.item_count ?? null, changed_at: r.changed_at ?? null, fresh,
        using_fallback: r.last_status === 'error' && !!r.last_success_at };
    });
    const nCol = db.prepare('SELECT count(*) n FROM colleges').get().n;
    const web = db.prepare('SELECT count(*) n, sum(ok) ok FROM live_web').get();
    return {
      now: iso(), refreshing: running.size > 0, running: [...running.keys()], sources,
      coverage: { colleges: nCol, linked_eapcet: L.eapcet?.size ?? 0, linked_ecet: L.ecet?.size ?? 0, linked_jntuk: L.jntuk_affiliated?.size ?? 0,
        website_checked: web.n || 0, website_ok: web.ok || 0 },
      automation: AUTOMATION,
      recent_changes: db.prepare(`SELECT x.at, x.source, x.college_id, c.name AS college_name, x.summary FROM live_changes x LEFT JOIN colleges c ON c.id = x.college_id
        ORDER BY x.id DESC LIMIT 50`).all().map((r) => ({ ...r })),
    };
  }
  const srcMeta = (id) => { const r = getRow(id); return { id, name: SOURCES[id].name, url: SOURCES[id].url, last_success_at: r.last_success_at ?? null,
    using_fallback: r.last_status === 'error' && !!r.last_success_at, last_error: r.last_status === 'error' ? r.last_error : null }; };

  function college(id) {
    const c = db.prepare('SELECT id, name, short_name, website, phone, email, affiliation FROM colleges WHERE id = ?').get(id);
    if (!c) return null;
    const L = links();
    const capPart = (sid) => {
      const s = snap(sid); if (!s) return null;
      const l = L[sid]?.get(id);
      const rec = l ? s.data.find((r) => r.code === l.key) : null;
      return { source: srcMeta(sid), link: l ? { code: l.key, basis: l.basis, score: l.score, also: l.also || [] } : null, record: rec || null };
    };
    const eapcet = capPart('eapcet'); const ecet = capPart('ecet');
    let jntuk = null;
    const ja = snap('jntuk_affiliated');
    if (ja) {
      const l = L.jntuk_affiliated?.get(id);
      const rec = l ? ja.data.find((r) => `${r.district}|${r.cc}` === l.key) : null;
      jntuk = { source: srcMeta('jntuk_affiliated'), link: l ? { cc: rec?.cc ?? null, basis: l.basis, score: l.score } : null, record: rec || null };
    }
    const w = db.prepare('SELECT * FROM live_web WHERE college_id = ?').get(id);
    const website = w ? { url: w.url, ok: !!w.ok, http_status: w.http_status, final_url: w.final_url, error: w.error, checked_at: w.checked_at, last_ok_at: w.last_ok_at } : null;
    // presence: null when unknown (source never fetched, or college not linked by research code and no name match)
    const pres = (part) => (!part ? null : !!part.record); // null = source never fetched; false = fetched, college not found in it
    const presence = { eapcet: pres(eapcet), ecet: pres(ecet), jntuk_affiliated: pres(jntuk), website: website ? website.ok : null };
    const anyListed = presence.eapcet || presence.ecet || presence.jntuk_affiliated;
    const allChecked = eapcet && ecet && jntuk;
    const signal = anyListed ? 'listed' : (allChecked ? 'not_found_anywhere' : 'unknown');
    const signal_text = anyListed
      ? `Listed in: ${[presence.eapcet && 'AP EAPCET counselling', presence.ecet && 'AP ECET counselling', presence.jntuk_affiliated && 'JNTUK affiliated list'].filter(Boolean).join(', ')}.`
      : (allChecked ? 'Not matched in any official list we check (EAPCET, ECET, JNTUK). It may be closed, renamed, affiliated elsewhere (e.g. a university), or listed under a different name — confirm by phone before changing its status.'
        : 'Official lists have not been fetched yet.');
    // diffs vs our stored record (from the strongest link: EAPCET, then ECET)
    const diffs = [];
    const best = (eapcet?.record && eapcet.link?.basis === 'research_code') ? eapcet : (eapcet?.record ? eapcet : (ecet?.record ? ecet : null));
    if (best?.record) {
      const r = best.record; const meta = { source_id: best.source.id, source_name: best.source.name, checked_at: best.source.last_success_at };
      if (r.website && hostOf(r.website) && hostOf(r.website) !== hostOf(c.website)) {
        // our website answering today is strong evidence the feed's entry is the outdated one
        const ourUp = !!(website?.ok && hostOf(c.website));
        const note = ourUp ? `Our website ${hostOf(c.website)} is up; the counselling list may be outdated — keep ours unless you know it changed.` : null;
        diffs.push({ field: 'website', label: 'Website', ours: c.website, live: /^https?:\/\//i.test(r.website) ? r.website : `https://${r.website}`, note,
          note_checked_at: ourUp ? website.checked_at : null, ...meta });
      }
      if (r.affiliated_to && String(r.affiliated_to).toLowerCase() !== String(c.affiliation || '').toLowerCase()) diffs.push({ field: 'affiliation', label: 'Affiliation', ours: c.affiliation, live: r.affiliated_to, ...meta });
      if (!clean(c.phone) && r.phone) diffs.push({ field: 'phone', label: 'College phone', ours: c.phone, live: r.phone, ...meta });
      if (!clean(c.email) && r.email) diffs.push({ field: 'email', label: 'College email', ours: c.email, live: r.email, ...meta });
    }
    // notices that name this college (rare, but cheap to show)
    const words = [c.short_name, eapcet?.link?.code].filter((x) => x && String(x).length >= 4);
    const announcements = words.length ? db.prepare(`SELECT * FROM live_announcements WHERE ${words.map(() => 'instr(lower(title), ?) > 0').join(' OR ')} ORDER BY date DESC LIMIT 10`)
      .all(...words.map((x) => String(x).toLowerCase())).map((r) => annOut(r)) : [];
    const checked = [eapcet?.source.last_success_at, ecet?.source.last_success_at, jntuk?.source.last_success_at, website?.checked_at].filter(Boolean).sort().pop() || null;
    return { college_id: id, checked_at: checked, presence, signal, signal_text, eapcet, ecet, jntuk, website, diffs, announcements };
  }

  // the first batch ever fetched is the baseline: those notices are not "new"; only ones that appear later are
  const baselineAt = () => db.prepare('SELECT min(first_seen_at) t FROM live_announcements').get()?.t ?? null;
  function annOut(r, base = baselineAt()) {
    let attachments = []; try { attachments = JSON.parse(r.attachments || '[]'); } catch { /* ignore */ }
    return { uid: r.uid, source: r.source, source_name: SOURCES[r.source]?.name ?? r.source, date: r.date, title: r.title, dept: r.dept, category: r.category,
      section: r.section, attachments, url: r.url, first_seen_at: r.first_seen_at, is_new: r.first_seen_at !== base && ageMin(r.first_seen_at) < 48 * 60 };
  }
  function announcements({ category = null, q = null, limit = 100, since = null } = {}) {
    const where = []; const args = [];
    if (category) { where.push('category = ?'); args.push(category); }
    if (q) { where.push('instr(lower(title), ?) > 0'); args.push(String(q).toLowerCase().slice(0, 100)); }
    if (since) { where.push('date >= ?'); args.push(since); }
    const sql = `SELECT * FROM live_announcements ${where.length ? `WHERE ${where.join(' AND ')}` : ''} ORDER BY date DESC, first_seen_at DESC LIMIT ?`;
    const counts = new Map(db.prepare('SELECT category, count(*) n FROM live_announcements GROUP BY category').all().map((r) => [r.category, r.n]));
    return { checked_at: getRow('jntuk_notifications').last_success_at ?? null, source: status().sources.find((s) => s.id === 'jntuk_notifications'),
      categories: CATEGORIES.map(([cid, label]) => ({ id: cid, label, count: counts.get(cid) || 0 })),
      items: (() => { const base = baselineAt(); return db.prepare(sql).all(...args, Math.max(1, Math.min(500, Number(limit) || 100))).map((r) => annOut(r, base)); })() };
  }

  return { refresh, refreshAndWait, runSource, status, college, announcements, links, isStale };
}
