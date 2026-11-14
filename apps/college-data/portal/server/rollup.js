// Rollup engine: targets, progress, pace, diagnosis and exam state (CONTRACT.md "Rollup semantics").
// A context is built from a handful of grouped queries (no N+1) and then every scope is computed in memory.
import { today as todayFn, getSettings } from './db.js';

const DAY = 86400000;
/**
 * THE date parser: every date consumer goes through it. Returns 'YYYY-MM-DD' only for a strict, real
 * calendar date (optionally followed by a time, e.g. an ISO timestamp); anything else (free text like
 * "before 2026-12-09 (inferred)", "Nov 2026", "2026-02-31") returns null. Never throws.
 */
export function parseIsoDate(v) {
  if (v == null) return null;
  const m = /^\s*(\d{4})-(\d{2})-(\d{2})(?:[T ][0-9:.]+Z?)?\s*$/.exec(String(v));
  if (!m) return null;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  if (Number.isNaN(d.getTime()) || d.getUTCMonth() !== +m[2] - 1 || d.getUTCDate() !== +m[3]) return null;
  return `${m[1]}-${m[2]}-${m[3]}`;
}
const toDate = (s) => { const iso = parseIsoDate(s); return iso ? new Date(`${iso}T00:00:00Z`) : null; };
/** Whole days from a to b; null if either is not a valid date. */
export const daysBetween = (a, b) => { const x = toDate(a); const y = toDate(b); return x && y ? Math.round((y - x) / DAY) : null; };
/** iso + n days; null if iso is not a valid date. Never throws. */
export function addDays(iso, n) {
  const d = toDate(iso);
  if (!d) return null;
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

const UNKNOWN_EXAM_STATUS = new Set(['unverified', 'no current exams found']);
const STUDENT_AGG_EXCLUDED_OPS = new Set(['closed', 'possibly_closed']);

// ---------------------------------------------------------------------------------------------
// Exams
// ---------------------------------------------------------------------------------------------
const RANGE_RE = /(\d{4}-\d{2}-\d{2})\s*(?:to|–|—|-|until|till)\s*(\d{4}-\d{2}-\d{2})/gi;

/** Kept for compatibility: same strict parse (free text -> null, i.e. an unknown window). */
export const isoIn = parseIsoDate;

/** Parse exam windows from one exams row: end-sem dates + mid_window text ranges. */

export function examWindows(row) {
  const out = [];
  // windows only from plain ISO dates; qualified text ("before 2026-12-09", "after 2026-11-07; no dates") is not a window
  const es = parseIsoDate(row.endsem_start); const ee = parseIsoDate(row.endsem_end);
  if (es || ee) {
    const start = es || ee; const end = ee && ee >= start ? ee : start;
    out.push({ semester: row.semester, kind: 'endsem', start, end });
  }
  const txt = row.mid_window ? String(row.mid_window) : '';
  if (txt) {
    let m; let found = false;
    RANGE_RE.lastIndex = 0;
    while ((m = RANGE_RE.exec(txt))) {
      found = true;
      const x = parseIsoDate(m[1]); const y = parseIsoDate(m[2]);
      if (!x || !y) continue;
      const [a, b] = x <= y ? [x, y] : [y, x];
      out.push({ semester: row.semester, kind: 'mid', start: a, end: b });
    }
    if (!found) {
      const from = parseIsoDate(/\bfrom\s+(\d{4}-\d{2}-\d{2})/i.exec(txt)?.[1]);
      const ends = parseIsoDate(/\brunning\b.*?\bends\s+(\d{4}-\d{2}-\d{2})/i.exec(txt)?.[1]);
      if (ends) {
        const start = [parseIsoDate(row.notice_date), parseIsoDate(row.verified_on)].filter(Boolean).filter((d) => d <= ends).sort()[0] || ends;
        out.push({ semester: row.semester, kind: 'mid', start, end: ends });
      } else if (from) {
        out.push({ semester: row.semester, kind: 'mid', start: from, end: from });
      }
    }
  }
  return out;
}

/** Exam state for one college given its exam rows. */
export function examState(rows, today) {
  if (!rows || !rows.length) return { exam_state: 'unknown', next_exam: null, outreach_from: null };
  const wins = [];
  for (const r of rows) { try { wins.push(...examWindows(r)); } catch { /* unparseable row = unknown window */ } }
  const soonLimit = addDays(today, 14) || today;
  let state;
  if (wins.some((w) => w.start <= today && today <= w.end)) state = 'in_exams';
  else if (wins.some((w) => w.start > today && w.start <= soonLimit)) state = 'exams_soon';
  else if (rows.every((r) => UNKNOWN_EXAM_STATUS.has(String(r.status || '').toLowerCase()))) state = 'unknown';
  else state = 'clear';
  const upcoming = wins.filter((w) => w.end >= today).sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
  const next = upcoming[0] || null;
  const ends41 = rows.filter((r) => r.semester === '4-1').map((r) => parseIsoDate(r.endsem_end) || parseIsoDate(r.endsem_start)).filter(Boolean).sort();
  return {
    exam_state: state,
    next_exam: next ? { semester: next.semester, kind: next.kind, start: next.start, end: next.end } : null,
    outreach_from: ends41.length ? addDays(ends41[ends41.length - 1], 1) : null,
  };
}

// ---------------------------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------------------------
function push(map, k, v) { let a = map.get(k); if (!a) map.set(k, (a = [])); a.push(v); }
/** Enrollment funnel stages, in order. Only 'confirmed' counts as enrolled (targets, pace, leaderboards, revenue). */
export const STAGES = ['lead', 'interested', 'registered', 'applied', 'confirmed', 'dropped'];
const emptyFunnel = () => ({ lead: 0, interested: 0, registered: 0, applied: 0, confirmed: 0, dropped: 0 });
function bumpFunnel(map, k, stage, n) { let o = map.get(k); if (!o) map.set(k, (o = emptyFunnel())); o[stage] = (o[stage] || 0) + n; }
function bump(map, k, field, by) { let o = map.get(k); if (!o) map.set(k, (o = { enrolled: 0, reached: 0, revenue: 0, activities: 0 })); o[field] += by; }

export function buildContext(db) {
  const T = todayFn();
  const settings = getSettings(db);
  const ctx = { db, today: T, settings, memo: new Map() };
  ctx.districts = new Map(db.prepare('SELECT * FROM districts ORDER BY name').all().map((r) => [r.id, r]));
  ctx.cities = new Map(db.prepare('SELECT * FROM cities ORDER BY name').all().map((r) => [r.id, r]));
  ctx.colleges = new Map(db.prepare('SELECT * FROM colleges ORDER BY sno').all().map((r) => [r.id, r]));
  ctx.branches = new Map(db.prepare('SELECT * FROM branches ORDER BY college_id, code').all().map((r) => [r.id, r]));
  ctx.people = new Map(db.prepare('SELECT * FROM people ORDER BY full_name').all().map((r) => [r.id, r]));
  ctx.courses = db.prepare('SELECT * FROM courses ORDER BY id').all();

  ctx.branchesByCollege = new Map(); for (const b of ctx.branches.values()) push(ctx.branchesByCollege, b.college_id, b);
  ctx.collegesByCity = new Map(); ctx.collegesByDistrict = new Map(); ctx.orphansByDistrict = new Map();
  for (const c of ctx.colleges.values()) {
    if (c.district_id) push(ctx.collegesByDistrict, c.district_id, c);
    if (c.city_id && ctx.cities.has(c.city_id)) push(ctx.collegesByCity, c.city_id, c);
    else if (c.district_id) push(ctx.orphansByDistrict, c.district_id, c);
  }
  ctx.citiesByDistrict = new Map(); for (const c of ctx.cities.values()) push(ctx.citiesByDistrict, c.district_id, c);
  ctx.peopleByCollege = new Map(); ctx.reportsOf = new Map();
  for (const p of ctx.people.values()) {
    push(ctx.peopleByCollege, p.college_id, p);
    if (p.reports_to != null) push(ctx.reportsOf, p.reports_to, p);
  }
  ctx.branchesOfPerson = new Map(); ctx.peopleOfBranch = new Map();
  for (const r of db.prepare('SELECT person_id, branch_id FROM person_branches').all()) {
    push(ctx.branchesOfPerson, r.person_id, r.branch_id);
    push(ctx.peopleOfBranch, r.branch_id, r.person_id);
  }

  // grouped aggregates
  ctx.aggCollege = new Map(); ctx.aggBranch = new Map(); ctx.aggPerson = new Map(); ctx.aggCourse = new Map(); // aggCourse key `${level}:${id}:${course}`
  // Funnel: every row is one student record at exactly one stage, so stage counts never double count.
  ctx.funnelCollege = new Map(); ctx.funnelBranch = new Map(); ctx.funnelPerson = new Map();
  for (const r of db.prepare('SELECT college_id, branch_id, person_id, stage, COUNT(*) AS n FROM enrollments GROUP BY college_id, branch_id, person_id, stage').all()) {
    const n = Number(r.n); const st = STAGES.includes(r.stage) ? r.stage : 'confirmed';
    bumpFunnel(ctx.funnelCollege, r.college_id, st, n);
    if (r.branch_id != null) bumpFunnel(ctx.funnelBranch, r.branch_id, st, n);
    if (r.person_id != null) bumpFunnel(ctx.funnelPerson, r.person_id, st, n);
  }
  // enrolled / revenue: confirmed enrollments only, confirmed on or before today (R9: a future-dated record never counts yet)
  const enr = db.prepare(`SELECT e.college_id, e.branch_id, e.person_id, e.course_id, COUNT(*) AS n,
      SUM(COALESCE(e.amount_inr, c.price_inr, 0)) AS rev
    FROM enrollments e LEFT JOIN courses c ON c.id = e.course_id
    WHERE e.stage = 'confirmed' AND COALESCE(e.confirmed_on, e.enrolled_on) <= ?
    GROUP BY e.college_id, e.branch_id, e.person_id, e.course_id`).all(T);
  // v4: every counted confirmed record with its achievement date, for period actuals (/api/performance)
  ctx.confirmed = db.prepare(`SELECT id, college_id, branch_id, person_id, COALESCE(confirmed_on, enrolled_on) AS d FROM enrollments
    WHERE stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) <= ?`).all(T);
  for (const r of enr) {
    const n = Number(r.n); const rev = Number(r.rev || 0);
    bump(ctx.aggCollege, r.college_id, 'enrolled', n); bump(ctx.aggCollege, r.college_id, 'revenue', rev);
    if (r.branch_id != null) { bump(ctx.aggBranch, r.branch_id, 'enrolled', n); bump(ctx.aggBranch, r.branch_id, 'revenue', rev); }
    if (r.person_id != null) { bump(ctx.aggPerson, r.person_id, 'enrolled', n); bump(ctx.aggPerson, r.person_id, 'revenue', rev); }
    if (r.course_id != null) {
      for (const k of [`college:${r.college_id}`, r.branch_id != null ? `branch:${r.branch_id}` : null]) {
        if (!k) continue;
        bump(ctx.aggCourse, `${k}:${r.course_id}`, 'enrolled', n); bump(ctx.aggCourse, `${k}:${r.course_id}`, 'revenue', rev);
      }
    }
  }
  const act = db.prepare(`SELECT college_id, branch_id, person_id, SUM(students_reached) AS reached, COUNT(*) AS n
    FROM activities GROUP BY college_id, branch_id, person_id`).all();
  for (const r of act) {
    const v = Number(r.reached || 0); const n = Number(r.n);
    bump(ctx.aggCollege, r.college_id, 'reached', v); bump(ctx.aggCollege, r.college_id, 'activities', n);
    if (r.branch_id != null) { bump(ctx.aggBranch, r.branch_id, 'reached', v); bump(ctx.aggBranch, r.branch_id, 'activities', n); }
    if (r.person_id != null) { bump(ctx.aggPerson, r.person_id, 'reached', v); bump(ctx.aggPerson, r.person_id, 'activities', n); }
  }

  // open follow-ups by scope
  ctx.openFollowups = db.prepare("SELECT * FROM followups WHERE status = 'open' ORDER BY due_date IS NULL, due_date").all();
  ctx.followupsByScope = new Map();
  for (const f of ctx.openFollowups) push(ctx.followupsByScope, `${f.scope_type}:${f.scope_id}`, f);

  // targets
  // ctx.targets: programme-period rows (every pre-v4 consumer), key `${type}:${id}:${course}`.
  // ctx.periodTargets (v4): month / week rows, all-courses only, key `${type}:${id}:${period}:${period_start}`.
  ctx.targets = new Map(); ctx.periodTargets = new Map();
  for (const t of db.prepare('SELECT * FROM targets').all()) {
    if ((t.period || 'programme') === 'programme') ctx.targets.set(`${t.scope_type}:${t.scope_id}:${t.course_id ?? ''}`, t);
    else if (t.course_id == null) ctx.periodTargets.set(`${t.scope_type}:${t.scope_id}:${t.period}:${t.period_start}`, t);
  }

  // exam state per college
  ctx.examRows = new Map(); for (const e of db.prepare('SELECT * FROM exams ORDER BY college_id, semester').all()) push(ctx.examRows, e.college_id, e);
  ctx.exam = new Map();
  for (const c of ctx.colleges.values()) ctx.exam.set(c.id, examState(ctx.examRows.get(c.id) || [], T));
  return ctx;
}

// ---------------------------------------------------------------------------------------------
// Scopes
// ---------------------------------------------------------------------------------------------
export function parseScope(s) {
  if (!s || s === 'state') return { type: 'state', id: 'ap' };
  const i = String(s).indexOf(':');
  if (i < 0) return null;
  const type = s.slice(0, i); const id = s.slice(i + 1);
  if (!['state', 'district', 'city', 'college', 'branch', 'person'].includes(type) || !id) return null;
  return { type, id: type === 'state' ? 'ap' : id };
}

/**
 * District filter (`districts=` query param): a scope may carry `districts` (a Set of district ids) and `dkey` (its
 * canonical string). Colleges of the scope are then limited to those districts; for 'state' the target children are
 * limited to the selected districts too. `withDistricts(sc, null)` returns the scope unchanged.
 */
export function withDistricts(sc, ids) {
  if (!sc || !ids) return sc;
  const list = [...new Set(ids)].sort();
  return { ...sc, districts: new Set(list), dkey: list.join(',') };
}
const dk = (sc) => (sc.dkey != null ? `|D:${sc.dkey}` : '');
const inDistricts = (sc, c) => !sc.districts || sc.districts.has(c.district_id);

export function scopeExists(ctx, sc) {
  if (!sc) return false;
  switch (sc.type) {
    case 'state': return true;
    case 'district': return ctx.districts.has(sc.id);
    case 'city': return ctx.cities.has(sc.id);
    case 'college': return ctx.colleges.has(sc.id);
    case 'branch': return ctx.branches.has(Number(sc.id));
    case 'person': return ctx.people.has(Number(sc.id));
    default: return false;
  }
}

export function scopeLabel(ctx, sc) {
  switch (sc.type) {
    case 'state': {
      if (!sc.districts) return 'Andhra Pradesh';
      const names = [...sc.districts].map((id) => ctx.districts.get(id)?.name ?? id);
      return names.length <= 3 ? names.join(', ') : `${names.length} selected districts`;
    }
    case 'district': return ctx.districts.get(sc.id)?.name ?? sc.id;
    case 'city': return ctx.cities.get(sc.id)?.name ?? sc.id;
    case 'college': { const c = ctx.colleges.get(sc.id); return c ? (c.short_name || c.name) : sc.id; }
    case 'branch': { const b = ctx.branches.get(Number(sc.id)); if (!b) return sc.id; const c = ctx.colleges.get(b.college_id); return `${b.code} · ${c?.short_name || c?.name || b.college_id}`; }
    case 'person': return ctx.people.get(Number(sc.id))?.full_name ?? sc.id;
    default: return sc.id;
  }
}

export function hrefFor(ctx, type, id) {
  switch (type) {
    case 'state': return '#/';
    case 'district': return `#/d/${id}`;
    case 'city': { const c = ctx.cities.get(id); return c ? `#/d/${c.district_id}/${id}` : '#/'; }
    case 'college': return `#/college/${id}`;
    case 'branch': { const b = ctx.branches.get(Number(id)); return b ? `#/college/${b.college_id}?tab=branches&branch=${b.id}` : '#/'; }
    case 'person': return `#/person/${id}`;
    default: return '#/';
  }
}

/** Colleges in a geo/college/branch scope (limited to sc.districts when a district filter is set). */
export function scopeColleges(ctx, sc) {
  const all = scopeCollegesAll(ctx, sc);
  return sc.districts ? all.filter((c) => inDistricts(sc, c)) : all;
}
function scopeCollegesAll(ctx, sc) {
  switch (sc.type) {
    case 'state': return [...ctx.colleges.values()];
    case 'district': return ctx.collegesByDistrict.get(sc.id) || [];
    case 'city': return ctx.collegesByCity.get(sc.id) || [];
    case 'college': return ctx.colleges.has(sc.id) ? [ctx.colleges.get(sc.id)] : [];
    case 'branch': { const b = ctx.branches.get(Number(sc.id)); return b && ctx.colleges.has(b.college_id) ? [ctx.colleges.get(b.college_id)] : []; }
    case 'person': { const p = ctx.people.get(Number(sc.id)); return p && ctx.colleges.has(p.college_id) ? [ctx.colleges.get(p.college_id)] : []; }
    default: return [];
  }
}

export function scopeBranches(ctx, sc) {
  const okB = (b) => !sc.districts || inDistricts(sc, ctx.colleges.get(b.college_id) || {});
  if (sc.type === 'branch') { const b = ctx.branches.get(Number(sc.id)); return b && okB(b) ? [b] : []; }
  if (sc.type === 'person') return (ctx.branchesOfPerson.get(Number(sc.id)) || []).map((id) => ctx.branches.get(id)).filter((b) => b && okB(b));
  return scopeColleges(ctx, sc).flatMap((c) => ctx.branchesByCollege.get(c.id) || []);
}

export function scopePeople(ctx, sc) {
  const okP = (p) => !sc.districts || inDistricts(sc, ctx.colleges.get(p.college_id) || {});
  if (sc.type === 'branch') return (ctx.peopleOfBranch.get(Number(sc.id)) || []).map((id) => ctx.people.get(id)).filter((p) => p && okP(p));
  if (sc.type === 'person') { const p = ctx.people.get(Number(sc.id)); return p && okP(p) ? [p] : []; }
  return scopeColleges(ctx, sc).flatMap((c) => ctx.peopleByCollege.get(c.id) || []);
}

function parentOf(ctx, sc) {
  switch (sc.type) {
    case 'branch': { const b = ctx.branches.get(Number(sc.id)); return b ? { type: 'college', id: b.college_id } : { type: 'state', id: 'ap' }; }
    case 'college': {
      const c = ctx.colleges.get(sc.id);
      if (c?.city_id && ctx.cities.has(c.city_id)) return { type: 'city', id: c.city_id };
      if (c?.district_id) return { type: 'district', id: c.district_id };
      return { type: 'state', id: 'ap' };
    }
    case 'city': { const c = ctx.cities.get(sc.id); return c ? { type: 'district', id: c.district_id } : { type: 'state', id: 'ap' }; }
    case 'district': return { type: 'state', id: 'ap' };
    case 'person': {
      const p = ctx.people.get(Number(sc.id));
      if (p?.reports_to != null && ctx.people.has(p.reports_to)) return { type: 'person', id: String(p.reports_to) };
      const bs = ctx.branchesOfPerson.get(Number(sc.id)) || [];
      if (bs.length === 1) return { type: 'branch', id: String(bs[0]) };
      return p?.college_id ? { type: 'college', id: p.college_id } : { type: 'state', id: 'ap' };
    }
    default: return null;
  }
}

function childrenOf(ctx, sc) {
  switch (sc.type) {
    case 'state': return [...ctx.districts.keys()].filter((id) => !sc.districts || sc.districts.has(id)).map((id) => ({ type: 'district', id }));
    case 'district': return [
      ...(ctx.citiesByDistrict.get(sc.id) || []).map((c) => ({ type: 'city', id: c.id })),
      ...(ctx.orphansByDistrict.get(sc.id) || []).map((c) => ({ type: 'college', id: c.id })),
    ];
    case 'city': return (ctx.collegesByCity.get(sc.id) || []).map((c) => ({ type: 'college', id: c.id }));
    case 'college': return (ctx.branchesByCollege.get(sc.id) || []).map((b) => ({ type: 'branch', id: String(b.id) }));
    default: return [];
  }
}

// ---------------------------------------------------------------------------------------------
// Targets
// ---------------------------------------------------------------------------------------------
const dateOnly = (s) => parseIsoDate(s);

/** Effective target for a scope and course key ('' = all courses). Memoised per context. */
export function effectiveTarget(ctx, sc, course = '') {
  const key = `T|${sc.type}:${sc.id}:${course}${sc.type === 'state' ? dk(sc) : ''}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  // v4.1 (D2): a state row (the programme target) only applies when the district selection covers every programme district
  const stateRowSkipped = sc.type === 'state' && !stateRowApplies(ctx, sc);
  const row = stateRowSkipped ? null : (ctx.targets.get(`${sc.type}:${sc.id}:${course}`) || null);
  let childSum = null; let childStart = null; let childCount = 0; let childrenComplete = true;
  if (sc.type !== 'person' && sc.type !== 'branch') {
    for (const ch of childrenOf(ctx, sc)) {
      const t = effectiveTarget(ctx, ch, course);
      if (t.target != null) {
        childSum = (childSum ?? 0) + t.target; childCount++;
        if (t.complete === false) childrenComplete = false;
        if (t.start && (!childStart || t.start < childStart)) childStart = t.start;
      } else childrenComplete = false;
    }
  }
  // v4 (R10): pace starts at the programme start, never at the row's updated_at (re-saving a target no longer resets the clock)
  const start = programStart(ctx);
  let out;
  if (row) {
    out = { target: Number(row.target), target_source: 'explicit', children_target_sum: childSum,
      reconciled: childSum == null || childSum === Number(row.target), start, row, complete: true };
  } else if (childSum != null) {
    // v4.1 (F3, TG-01): complete only when EVERY child has a target and each of those is itself complete
    out = { target: childSum, target_source: 'sum_of_children', children_target_sum: childSum, reconciled: true, start: childStart && start, row: null, complete: childrenComplete };
  } else {
    out = { target: null, target_source: 'none', children_target_sum: null, reconciled: true, start: null, row: null, complete: null };
  }
  out.target_reason = stateRowSkipped && ctx.targets.get(`state:ap:${course}`) ? programmeTargetReason(ctx) : null;
  out.children_with_targets = childCount;
  out.children_total = sc.type !== 'person' && sc.type !== 'branch' ? childrenOf(ctx, sc).length : 0;
  ctx.memo.set(key, out);
  return out;
}

/** Confirmed (counted) enrollments of a geo/college/branch scope (R9). Memoised. */
export function enrolledOf(ctx, sc) {
  const key = `E|${sc.type}:${sc.id}${dk(sc)}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const n = sc.type === 'branch' ? sumAgg(ctx.aggBranch, scopeBranches(ctx, sc).map((b) => b.id)).enrolled
    : sc.type === 'person' ? (ctx.aggPerson.get(Number(sc.id))?.enrolled || 0)
      : sumAgg(ctx.aggCollege, scopeColleges(ctx, sc).map((c) => c.id)).enrolled;
  ctx.memo.set(key, n);
  return n;
}
/**
 * v4 (R10): the actual a target is compared with. Explicit target -> the scope's whole actual. Rolled-up target (sum of children)
 * -> only the actual of the children that have a target, with covers {with_target, total}. No target -> actual null.
 */
export function againstTarget(ctx, sc) {
  const key = `A|${sc.type}:${sc.id}${sc.type === 'state' ? dk(sc) : ''}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const t = effectiveTarget(ctx, sc);
  let out;
  if (t.target_source === 'explicit') out = { actual: enrolledOf(ctx, sc), covers: null };
  else if (t.target_source === 'sum_of_children') {
    let a = 0; let w = 0; const kids = childrenOf(ctx, sc);
    for (const ch of kids) { const ct = effectiveTarget(ctx, ch); if (ct.target != null) { a += againstTarget(ctx, ch).actual ?? 0; w++; } }
    out = { actual: a, covers: { with_target: w, total: kids.length, complete: t.complete !== false } };
  } else out = { actual: null, covers: null };
  ctx.memo.set(key, out);
  return out;
}

/** Deadline: the scope's own target deadline, else the nearest ancestor's, else settings.state_target_deadline. */
export function deadlineFor(ctx, sc, course = '') {
  let cur = sc; let guard = 0;
  while (cur && guard++ < 12) {
    const row = ctx.targets.get(`${cur.type}:${cur.id}:${course}`) || (course ? ctx.targets.get(`${cur.type}:${cur.id}:`) : null);
    if (row?.deadline) return row.deadline;
    if (cur.type === 'state') break;
    cur = parentOf(ctx, cur);
  }
  return ctx.settings.state_target_deadline || null;
}

/**
 * v4.1 (D2): the programme's target districts (settings.target_district_groups; all districts when none are configured).
 * The state target row (the programme target, e.g. 400) applies to a state scope only when its district selection
 * includes all of them (no selection = whole state = applies).
 */
export function programmeDistricts(ctx) {
  const key = 'PD|';
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const g = ctx.settings.target_district_groups;
  const ids = g && typeof g === 'object' && !Array.isArray(g) ? [...new Set(Object.values(g).flat())].filter((id) => ctx.districts.has(id)) : [];
  const out = ids.length ? ids : [...ctx.districts.keys()];
  ctx.memo.set(key, out);
  return out;
}
export const stateRowApplies = (ctx, sc) => !sc?.districts || programmeDistricts(ctx).every((id) => sc.districts.has(id));
export const programmeTargetReason = (ctx) => {
  const ids = programmeDistricts(ctx);
  return `The programme target covers the ${ids.length} target district${ids.length === 1 ? '' : 's'} (${ids.map((id) => ctx.districts.get(id)?.name ?? id).join(', ')}); this selection does not include all of them.`;
};
/** v4: the programme start date (settings.program_start, default 2026-11-03). */
export const programStart = (ctx) => parseIsoDate(ctx.settings.program_start) || '2026-11-03';
/** A period is "too early to judge" for its first 7 days (or its first quarter when it is shorter than 4 weeks, e.g. a week: 2 days). */
const tooEarlyDays = (total) => Math.min(7, Math.max(1, Math.ceil(total * 0.25)));
const round1 = (x) => Math.round(x * 10) / 10;

/**
 * v4 (R10) — THE target judgement used everywhere: remaining, exceeded_by, pct (percent, 1 decimal) and status
 * (no_target | zero_target | exceeded | met | too_early | behind | on_track) for an actual against a target over [start, end].
 * expected = target × elapsed / total, elapsed = days from start to today counting today (1 on the first day), total = days in the period
 * (inclusive). behind = actual < 0.8 × expected. Never divides by zero.
 */
export function judge(ctx, { target, actual, start, end, covers = null }) {
  const t = target == null ? null : Number(target);
  const a = Number(actual || 0);
  const s = parseIsoDate(start); const e = parseIsoDate(end);
  const total = s && e ? (daysBetween(s, e) ?? 0) + 1 : null;
  let expected = null; let frac = null;
  // elapsed days count today (inclusive), like period.days_elapsed and "days left incl. today"
  const el = total == null ? 0 : Math.min(Math.max(total, 0), Math.max(0, (daysBetween(s, ctx.today) ?? -1) + 1));
  if (t != null && t > 0 && total != null) {
    frac = total <= 0 ? 1 : el / total;
    expected = t * frac;
  }
  let status;
  // v4.1 (F2/F3/D2/D5): a target that does not cover the whole population is never judged (no %, remaining or status)
  const partial = t != null && !!covers && (covers.complete === false || covers.with_target < covers.total);
  if (partial) {
    return { status: 'partial_target', expected: null, elapsed_frac: frac == null ? null : Math.round(frac * 1000) / 1000, remaining: null, exceeded_by: null, pct: null };
  }
  if (t == null) status = 'no_target';
  else if (t === 0) status = 'zero_target';
  else if (a > t) status = 'exceeded';
  else if (a === t) status = 'met';
  else if (total == null || ctx.today < s || el < tooEarlyDays(total)) status = 'too_early';
  else status = a < 0.8 * expected ? 'behind' : 'on_track';
  return {
    status, expected: expected == null ? null : round1(expected), elapsed_frac: frac == null ? null : Math.round(frac * 1000) / 1000,
    remaining: t == null ? null : Math.max(t - a, 0), exceeded_by: t == null ? null : Math.max(a - t, 0),
    pct: t ? round1((a / t) * 100) : null,
  };
}

/** Legacy pace block (v1 fields) on top of judge(): on_track is null while too early / without a usable target. */
export function pace(ctx, target, enrolled, start, deadline, covers = null) {
  const j = judge(ctx, { target, actual: enrolled, start: start || programStart(ctx), end: deadline, covers });
  const on_track = j.status === 'behind' ? false : ['on_track', 'met', 'exceeded'].includes(j.status) ? true : null;
  return { expected_now: j.expected, elapsed_frac: j.elapsed_frac, on_track, pace_status: j.status };
}

export function diagnose(ctx, { on_track, gap, reached, enrolled, target, elapsed_frac, eligible }) {
  if (on_track !== false) return null;
  if (gap > 0) return 'ambassador_gap';
  if (reached < 3 * target * elapsed_frac) return 'low_outreach';
  const minConv = Number(ctx.settings.min_conversion ?? 0.05);
  if (reached > 0 && enrolled / reached < minConv) return 'low_conversion';
  if (eligible != null && target > 0.5 * eligible) return 'unrealistic_target';
  return 'behind_pace';
}

// ---------------------------------------------------------------------------------------------
// Aggregation helpers
// ---------------------------------------------------------------------------------------------
/** Sum values with provenance. basis: pending if nothing known; verified if all known+verified; else estimated. */
export function sumBasis(items, valKey, basisKey) {
  let value = null; let known = 0; let verified = 0; let missing = 0;
  for (const it of items) {
    const v = it[valKey];
    if (v == null || it[basisKey] === 'pending') { missing++; continue; }
    value = (value ?? 0) + Number(v); known++;
    if (it[basisKey] === 'verified') verified++;
  }
  const basis = known === 0 ? 'pending' : verified === known && missing === 0 ? 'verified' : 'estimated';
  return { value, basis, known, missing };
}

const isActive = (p) => p.status === 'active';
const notInactive = (p) => p.status !== 'inactive';
const AMB_ROLES = new Set(['ambassador', 'ambassador_lead']);

export function activeAmbassadorCount(ctx, branchId) {
  return (ctx.peopleOfBranch.get(branchId) || []).map((id) => ctx.people.get(id)).filter((p) => p && AMB_ROLES.has(p.role) && isActive(p)).length;
}

function sumAgg(map, ids) {
  const o = { enrolled: 0, reached: 0, revenue: 0, activities: 0 };
  for (const id of ids) { const a = map.get(id); if (a) { o.enrolled += a.enrolled; o.reached += a.reached; o.revenue += a.revenue; o.activities += a.activities; } }
  return o;
}

/** Funnel counts (one per student record, at its current stage) for a list of ids in a funnel map. */
export function sumFunnel(map, ids) {
  const o = emptyFunnel();
  for (const id of ids) { const f = map.get(id); if (f) for (const k of STAGES) o[k] += f[k] || 0; }
  o.total = STAGES.reduce((s, k) => s + o[k], 0);
  o.active = o.total - o.dropped - o.confirmed; // still in the pipeline
  return o;
}
export function scopeFunnel(ctx, sc) {
  if (sc.type === 'branch') return sumFunnel(ctx.funnelBranch, scopeBranches(ctx, sc).map((b) => b.id));
  if (sc.type === 'person') return sumFunnel(ctx.funnelPerson, [Number(sc.id)]);
  return sumFunnel(ctx.funnelCollege, scopeColleges(ctx, sc).map((c) => c.id));
}

function followupsIn(ctx, colleges, branches, people) {
  const out = [];
  for (const c of colleges) out.push(...(ctx.followupsByScope.get(`college:${c.id}`) || []));
  for (const b of branches) out.push(...(ctx.followupsByScope.get(`branch:${b.id}`) || []));
  for (const p of people) out.push(...(ctx.followupsByScope.get(`person:${p.id}`) || []));
  return out;
}

// ---------------------------------------------------------------------------------------------
// Summary (the rollup) for state / district / city / college / branch
// ---------------------------------------------------------------------------------------------
export function summary(ctx, sc) {
  const key = `S|${sc.type}:${sc.id}${dk(sc)}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const colleges = scopeColleges(ctx, sc);
  const branches = scopeBranches(ctx, sc);
  const people = scopePeople(ctx, sc);
  const geo = ['state', 'district', 'city'].includes(sc.type);

  const studentBranches = geo ? branches.filter((b) => !STUDENT_AGG_EXCLUDED_OPS.has(ctx.colleges.get(b.college_id)?.op_status)) : branches;
  const relevant = branches.filter((b) => b.is_relevant);
  const relevantStudent = studentBranches.filter((b) => b.is_relevant);
  const ambCount = new Map(relevant.map((b) => [b.id, activeAmbassadorCount(ctx, b.id)]));
  const withAmb = relevant.filter((b) => ambCount.get(b.id) > 0).length;
  // a "gap" only counts where we intend to work: targeted colleges (or the college/branch being viewed)
  const gapBranches = relevant.filter((b) => ambCount.get(b.id) === 0 && (!geo || ctx.colleges.get(b.college_id)?.targeted));

  const agg = sc.type === 'branch' ? sumAgg(ctx.aggBranch, branches.map((b) => b.id)) : sumAgg(ctx.aggCollege, colleges.map((c) => c.id));
  const t = effectiveTarget(ctx, sc);
  const deadline = deadlineFor(ctx, sc);
  // v4 (R10, TG-01): a rolled-up target is compared only with the actual of the children that have a target
  const at = againstTarget(ctx, sc);
  const cmp = at.actual ?? agg.enrolled;
  // v4.1 (F3): a rolled-up target that does not cover every child is shown with covers, but never judged (pct/remaining/status)
  const partial = t.target != null && t.target_source === 'sum_of_children' && (t.complete === false);
  const p = pace(ctx, t.target, cmp, t.start, deadline, t.target_source === 'sum_of_children' ? { ...at.covers, complete: t.complete !== false } : null);
  const eligible = sumBasis(studentBranches, 'eligible_estimate', 'eligible_basis');
  const diagnosis = diagnose(ctx, { on_track: p.on_track, gap: gapBranches.length, reached: agg.reached, enrolled: agg.enrolled, target: t.target, elapsed_frac: p.elapsed_frac, eligible: eligible.value });

  const fu = followupsIn(ctx, sc.type === 'branch' ? [] : colleges, branches, people);
  const exams = { in_exams: 0, exams_soon: 0, clear: 0, unknown: 0 };
  for (const c of colleges) exams[ctx.exam.get(c.id).exam_state]++;

  const leads = people.filter((x) => x.role === 'college_lead' && notInactive(x));
  const byCourse = ctx.courses.map((c) => {
    const ct = effectiveTarget(ctx, sc, String(c.id));
    let enrolled = 0; let revenue = 0;
    const keys = sc.type === 'branch' ? branches.map((b) => `branch:${b.id}`) : colleges.map((x) => `college:${x.id}`);
    for (const k of keys) { const a = ctx.aggCourse.get(`${k}:${c.id}`); if (a) { enrolled += a.enrolled; revenue += a.revenue; } }
    return { course_id: c.id, name: c.name, price_inr: c.price_inr, active: c.active, target: ct.target, target_source: ct.target_source, enrolled, revenue_inr: revenue };
  });

  const out = {
    scope: sc.type === 'state' ? 'state' : `${sc.type}:${sc.id}`,
    scope_type: sc.type, scope_id: sc.id, districts_filter: sc.districts ? [...sc.districts] : null,
    label: scopeLabel(ctx, sc), href: hrefFor(ctx, sc.type, sc.id),
    colleges: colleges.length,
    targeted_colleges: colleges.filter((c) => c.targeted).length,
    operational_colleges: colleges.filter((c) => c.op_status === 'operational').length,
    cities: new Set(colleges.map((c) => c.city_id).filter(Boolean)).size,
    districts: new Set(colleges.map((c) => c.district_id).filter(Boolean)).size,
    branches: branches.length,
    branches_relevant: relevant.length,
    branches_with_ambassadors: withAmb,
    branches_needing_ambassadors: gapBranches.length,
    strength: pickVB(sumBasis(studentBranches, 'strength_total', 'strength_basis')),
    relevant_students: pickVB(sumBasis(relevantStudent, 'strength_total', 'strength_basis')),
    final_year: pickVB(sumBasis(studentBranches, 'final_year', 'final_year_basis')),
    eligible: pickVB(eligible),
    college_leads: leads.length,
    colleges_with_lead: new Set(leads.map((x) => x.college_id)).size,
    ambassador_leads: people.filter((x) => x.role === 'ambassador_lead' && notInactive(x)).length,
    ambassadors: people.filter((x) => x.role === 'ambassador' && notInactive(x)).length,
    target: t.target, target_source: t.target_source, reconciled: t.reconciled, children_target_sum: t.children_target_sum,
    enrolled: agg.enrolled, reached: agg.reached, revenue_inr: agg.revenue, activities: agg.activities,
    actual_against_target: t.target == null ? null : cmp, covers: at.covers ? { ...at.covers, complete: t.complete !== false } : null,
    target_complete: t.target == null ? null : !partial, target_reason: t.target_reason ?? null,
    remaining: t.target == null || partial ? null : Math.max(t.target - cmp, 0),
    exceeded_by: t.target == null || partial ? null : Math.max(cmp - t.target, 0),
    pct: t.target && !partial ? cmp / t.target : null,
    deadline, target_start: t.start, expected_now: p.expected_now, elapsed_frac: p.elapsed_frac,
    on_track: p.on_track, pace_status: p.pace_status, diagnosis,
    followups_open: fu.length,
    followups_overdue: fu.filter((f) => f.due_date && f.due_date < ctx.today).length,
    exams,
    by_course: byCourse,
    funnel: scopeFunnel(ctx, sc),
  };
  ctx.memo.set(key, out);
  return out;
}

function pickVB(s) { return { value: s.value, basis: s.basis, missing: s.missing }; }

// ---------------------------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------------------------
export function personRollup(ctx, personId) {
  const id = Number(personId);
  const key = `P|${id}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const p = ctx.people.get(id);
  if (!p) return null;
  const sc = { type: 'person', id: String(id) };
  const row = ctx.targets.get(`person:${id}:`) || null;
  const target = row ? Number(row.target) : null;
  const agg = ctx.aggPerson.get(id) || { enrolled: 0, reached: 0, revenue: 0, activities: 0 };
  const deadline = deadlineFor(ctx, sc);
  const start = programStart(ctx);
  const pc = pace(ctx, target, agg.enrolled, start, deadline);
  const reports = ctx.reportsOf.get(id) || [];
  // v4 (R9, TG-04): team = the whole non-inactive subtree below the person (cycle-safe), not just direct reports
  const team = subtreeOf(ctx, id);
  let teamTarget = null; let teamEnrolled = 0; let teamReached = 0;
  const members = [];
  for (const r of team) {
    const rt = ctx.targets.get(`person:${r.id}:`);
    if (rt) teamTarget = (teamTarget ?? 0) + Number(rt.target);
    const ra = ctx.aggPerson.get(r.id); if (ra) { teamEnrolled += ra.enrolled; teamReached += ra.reached; }
    members.push({ target: rt ? Number(rt.target) : null, actual: ra?.enrolled || 0 });
  }
  const block = (t, a) => ({ target: t, actual: a, ...judge(ctx, { target: t, actual: a, start, end: deadline }) });
  const tc = teamBlocks((t, a, covers) => judge(ctx, { target: t, actual: a, start, end: deadline, covers }), target, agg.enrolled, members);
  const myBranches = (ctx.branchesOfPerson.get(id) || []).map((b) => ctx.branches.get(b)).filter(Boolean);
  const gap = p.role === 'ambassador' ? 0 : myBranches.filter((b) => b.is_relevant && activeAmbassadorCount(ctx, b.id) === 0).length;
  const eligible = sumBasis(myBranches, 'eligible_estimate', 'eligible_basis').value;
  const fu = (ctx.followupsByScope.get(`person:${id}`) || []).concat(ctx.openFollowups.filter((f) => f.owner_person_id === id && !(f.scope_type === 'person' && Number(f.scope_id) === id)));
  const out = {
    scope: `person:${id}`, label: p.full_name, href: hrefFor(ctx, 'person', id),
    target, target_min: row?.target_min ?? null, target_max: row?.target_max ?? null,
    target_source: row ? 'explicit' : 'none', deadline, target_start: start,
    enrolled: agg.enrolled, reached: agg.reached, revenue_inr: agg.revenue, activities: agg.activities,
    remaining: target == null ? null : Math.max(target - agg.enrolled, 0),
    exceeded_by: target == null ? null : Math.max(agg.enrolled - target, 0),
    pct: target ? agg.enrolled / target : null,
    expected_now: pc.expected_now, elapsed_frac: pc.elapsed_frac, on_track: pc.on_track, pace_status: pc.pace_status,
    diagnosis: diagnose(ctx, { on_track: pc.on_track, gap, reached: agg.reached, enrolled: agg.enrolled, target, elapsed_frac: pc.elapsed_frac, eligible: myBranches.length ? eligible : null }),
    team_target: team.length ? teamTarget : null, team_enrolled: team.length ? teamEnrolled : null, team_reached: team.length ? teamReached : null,
    reports_count: reports.length, team_size: team.length,
    // v4: own / team / combined, never merged silently (pct in these blocks is a PERCENT, 1 decimal)
    // v4.1 (F2/F5/D5): own = own target vs own actual; team = Σ members' targets vs ALL members' actual, judged only when every member
    // has a target (else status 'partial_target', covers{with_target,total}); combined = own + team target vs own + team actual, same rule.
    own: block(target, agg.enrolled),
    team: tc.team, combined: tc.combined,
    funnel: sumFunnel(ctx.funnelPerson, [id]),
    followups_open: fu.length, followups_overdue: fu.filter((f) => f.due_date && f.due_date < ctx.today).length,
    next_followup: fu.filter((f) => f.due_date).sort((a, b) => a.due_date.localeCompare(b.due_date))[0] || null,
  };
  ctx.memo.set(key, out);
  return out;
}

/**
 * v4.1 (F2, F5, D5): team and combined blocks of a lead. members = [{target|null, actual}] (the non-inactive subtree).
 * team.target = Σ members' targets (null when none has one), team.actual = Σ ALL members' actual, actual_with_target = Σ actual of
 * members that have a target, covers = {with_target, total, complete}. combined adds the person's own target/actual (covers counts them too).
 * A block is judged (pct, remaining, status) only when its coverage is complete, else status 'partial_target'.
 */
export function teamBlocks(J, ownTarget, ownActual, members) {
  if (!members.length) return { team: null, combined: null };
  let t = null; let a = 0; let aw = 0; let w = 0;
  for (const m of members) { a += m.actual; if (m.target != null) { t = (t ?? 0) + m.target; aw += m.actual; w++; } }
  const tcov = { with_target: w, total: members.length, complete: w === members.length };
  const team = { size: members.length, target: t, actual: a, actual_with_target: aw, covers: tcov, ...J(t, a, tcov) };
  const cw = w + (ownTarget != null ? 1 : 0); const ctot = members.length + 1;
  const ct = ownTarget == null && t == null ? null : (ownTarget ?? 0) + (t ?? 0);
  const ccov = { with_target: cw, total: ctot, complete: cw === ctot };
  const combined = { target: ct, actual: ownActual + a, covers: ccov, ...J(ct, ownActual + a, ccov) };
  return { team, combined };
}

/** v4: every non-inactive person below `id` (recursive through non-inactive managers; cycle-safe). Memoised. */
export function subtreeOf(ctx, id) {
  const key = `ST|${id}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const out = []; const seen = new Set([Number(id)]); const queue = [Number(id)];
  while (queue.length) {
    for (const r of ctx.reportsOf.get(queue.shift()) || []) {
      if (seen.has(r.id) || r.status === 'inactive') continue;
      seen.add(r.id); out.push(r); queue.push(r.id);
    }
  }
  ctx.memo.set(key, out);
  return out;
}

/** v4 (R2): which manager roles a role may report to. */
export const MANAGER_ROLES = { ambassador: ['college_lead', 'ambassador_lead'], ambassador_lead: ['college_lead'], college_lead: [] };
/**
 * v4 (R2/R3): what is wrong with person p reporting to manager m (m = the manager row or null/undefined when missing).
 * Returns null when the link is valid, else an issue code: lead_missing | lead_inactive | lead_other_college | lead_wrong_role.
 */
export function managerIssue(p, m) {
  if (!m) return 'lead_missing';
  if (m.status === 'inactive') return 'lead_inactive';
  if (m.college_id !== p.college_id) return 'lead_other_college';
  if (!(MANAGER_ROLES[p.role] || []).includes(m.role)) return 'lead_wrong_role';
  return null;
}
/** v4 (R3): {assignment_status: assigned|unassigned|invalid_link|null, assignment_issue}. College leads -> null. */
export function assignmentOf(ctx, p) {
  if (p.role === 'college_lead') return { assignment_status: null, assignment_issue: null };
  if (p.reports_to == null) return { assignment_status: 'unassigned', assignment_issue: 'no_lead' };
  const issue = managerIssue(p, ctx.people.get(p.reports_to));
  return issue ? { assignment_status: 'invalid_link', assignment_issue: issue } : { assignment_status: 'assigned', assignment_issue: null };
}

// ---------------------------------------------------------------------------------------------
// v4 periods and performance (/api/performance)
// ---------------------------------------------------------------------------------------------
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dmyLabel = (iso) => `${Number(iso.slice(8, 10))} ${MONTH_NAMES[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;
/** The programme deadline: the explicit state target's deadline, else settings. */
export const programDeadline = (ctx) => ctx.targets.get('state:ap:')?.deadline || ctx.settings.program_deadline || ctx.settings.state_target_deadline || null;
/**
 * Parse a period key: 'programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD' (a Monday). Returns
 * {key, type, period_start (DB value; null for programme), start, end, from (lower bound for actuals; null = none), label,
 *  days_total, days_elapsed, today} or {error}.
 */
export function periodOf(ctx, raw) {
  const k = String(raw || 'programme').trim();
  let type; let start; let end; let from; let periodStart; let label;
  if (k === 'programme' || k === 'program') {
    type = 'programme'; start = programStart(ctx); end = programDeadline(ctx) || start; from = null; periodStart = null;
    label = `Programme (${dmyLabel(start)} – ${dmyLabel(end)})`;
  } else if (/^month:\d{4}-\d{2}$/.test(k)) {
    type = 'month'; start = parseIsoDate(`${k.slice(6)}-01`);
    if (!start) return { error: 'Use month:YYYY-MM, e.g. month:2026-11' };
    const d = new Date(`${start}T00:00:00Z`); d.setUTCMonth(d.getUTCMonth() + 1); d.setUTCDate(0);
    end = d.toISOString().slice(0, 10); from = start; periodStart = start;
    label = `${MONTH_NAMES[Number(start.slice(5, 7)) - 1]} ${start.slice(0, 4)}`;
  } else if (/^week:\d{4}-\d{2}-\d{2}$/.test(k)) {
    type = 'week'; start = parseIsoDate(k.slice(5));
    if (!start) return { error: 'Use week:YYYY-MM-DD (a Monday), e.g. week:2026-11-02' };
    if (new Date(`${start}T00:00:00Z`).getUTCDay() !== 1) return { error: `week: ${start} is not a Monday` };
    end = addDays(start, 6); from = start; periodStart = start;
    label = `Week of ${dmyLabel(start)}`;
  } else return { error: 'period must be programme, month:YYYY-MM or week:YYYY-MM-DD (a Monday)' };
  const key = type === 'programme' ? 'programme' : `${type}:${type === 'month' ? start.slice(0, 7) : start}`;
  const days_total = (daysBetween(start, end) ?? 0) + 1;
  const days_elapsed = Math.min(days_total, Math.max(0, (daysBetween(start, ctx.today) ?? 0) + 1));
  return { key, type, period_start: periodStart, start, end, from, label, days_total, days_elapsed, today: ctx.today };
}
/** Canonical DB period fields for a target body value ('programme' | 'month:YYYY-MM' | 'week:YYYY-MM-DD' | {period, period_start}). */
export function targetPeriodFields(ctx, period, periodStart) {
  if (period == null || period === '' || period === 'programme' || period === 'program') return { period: 'programme', period_start: null };
  let key = String(period);
  if ((key === 'month' || key === 'week') && periodStart) key = key === 'month' ? `month:${String(periodStart).slice(0, 7)}` : `week:${periodStart}`;
  if (key === 'month' && periodStart == null) return { error: 'Give period_start (YYYY-MM-01) or use month:YYYY-MM' };
  if (key.startsWith('month:') && periodStart && !/^\d{4}-\d{2}-01$/.test(String(periodStart))) return { error: 'A month target starts on the 1st (period_start YYYY-MM-01)' };
  const p = periodOf(ctx, key);
  if (p.error) return { error: p.error };
  return { period: p.type, period_start: p.period_start };
}

/** Counted confirmed enrollments within a period (from..min(end, today)), grouped by college / person / branch. Memoised per period. */
function periodActuals(ctx, P) {
  const key = `PA|${P.key}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  const out = { college: new Map(), person: new Map(), branch: new Map(), uncredited: new Map() };
  const inc = (m, k) => m.set(k, (m.get(k) || 0) + 1);
  for (const e of ctx.confirmed) {
    if ((P.from && e.d < P.from) || e.d > P.end) continue;
    inc(out.college, e.college_id);
    if (e.person_id != null) inc(out.person, e.person_id); else inc(out.uncredited, e.college_id);
    if (e.branch_id != null) inc(out.branch, e.branch_id);
  }
  ctx.memo.set(key, out);
  return out;
}
const periodTargetRow = (ctx, P, type, id) => (P.type === 'programme' ? ctx.targets.get(`${type}:${id}:`) : ctx.periodTargets.get(`${type}:${id}:${P.type}:${P.period_start}`)) || null;
/** Geo/college actual in a period. */
function periodActualOf(ctx, P, sc) {
  const A = periodActuals(ctx, P);
  if (sc.type === 'branch') return A.branch.get(Number(sc.id)) || 0;
  if (sc.type === 'person') return A.person.get(Number(sc.id)) || 0;
  return scopeColleges(ctx, sc).reduce((s, c) => s + (A.college.get(c.id) || 0), 0);
}
/** Effective target of a geo/college/branch scope in a period: explicit row, else the sum of children that have one (with covers). */
function periodTargetOf(ctx, P, sc) {
  const key = `PT|${P.key}|${sc.type}:${sc.id}${sc.type === 'state' ? dk(sc) : ''}`;
  if (ctx.memo.has(key)) return ctx.memo.get(key);
  // v4.1 (D2): the state row applies only when the district selection covers every programme district
  const skipped = sc.type === 'state' && !stateRowApplies(ctx, sc);
  const row = skipped ? null : periodTargetRow(ctx, P, sc.type, sc.id);
  let out;
  const kids = sc.type === 'branch' ? [] : childrenOf(ctx, sc);
  let t = null; let a = 0; let w = 0; let nested = true;
  for (const ch of kids) { const c = periodTargetOf(ctx, P, ch); if (c.target != null) { t = (t ?? 0) + c.target; a += c.against; w++; if (c.complete === false) nested = false; } }
  // always returned (children that have a target in this period); complete = every child has one and each of those is complete
  const covers = { with_target: w, total: kids.length, complete: w === kids.length && nested };
  if (row) out = { target: Number(row.target), min: row.target_min ?? null, max: row.target_max ?? null, target_source: 'explicit', against: periodActualOf(ctx, P, sc), covers, complete: true };
  else {
    out = t == null ? { target: null, min: null, max: null, target_source: 'none', against: null, covers, complete: null }
      : { target: t, min: null, max: null, target_source: 'sum_of_children', against: a, covers, complete: covers.complete };
  }
  out.target_reason = skipped && periodTargetRow(ctx, P, 'state', 'ap') ? programmeTargetReason(ctx) : null;
  ctx.memo.set(key, out);
  return out;
}

/**
 * GET /api/performance. opts: {level: person|college|district|state, period (key), districts (Set|null), district, college_id, role (Set|null),
 * include_inactive, only_with_target, sort}. Returns {level, period, rows, totals, programme} or {error, field}.
 */
export function performance(ctx, opts) {
  const P = periodOf(ctx, opts.period);
  if (P.error) return { error: P.error, field: 'period' };
  const level = opts.level || 'person';
  const ds = opts.districts || null;
  const inD = (did) => (!ds || ds.has(did)) && (!opts.district || did === opts.district);
  const J = (target, actual, covers = null) => judge(ctx, { target, actual, start: P.start, end: P.end, covers });
  const dRef = (did) => (did ? { id: did, name: ctx.districts.get(did)?.name ?? did } : null);
  const A = periodActuals(ctx, P);
  let rows = [];
  if (level === 'person') {
    for (const p of ctx.people.values()) {
      const c = ctx.colleges.get(p.college_id);
      if (!inD(c?.district_id)) continue;
      if (opts.college_id && p.college_id !== opts.college_id) continue;
      if (opts.role && !opts.role.has(p.role)) continue;
      if (!opts.include_inactive && p.status === 'inactive') continue;
      const row = periodTargetRow(ctx, P, 'person', String(p.id));
      const target = row ? Number(row.target) : null;
      const own = A.person.get(p.id) || 0;
      const team = subtreeOf(ctx, p.id);
      let teamActual = 0; const members = [];
      for (const m of team) {
        const mt = periodTargetRow(ctx, P, 'person', String(m.id));
        const ma = A.person.get(m.id) || 0; teamActual += ma;
        members.push({ target: mt ? Number(mt.target) : null, actual: ma });
      }
      const j = J(target, own);
      const tb = teamBlocks((t, a, covers) => judge(ctx, { target: t, actual: a, start: P.start, end: P.end, covers }), target, own, members);
      rows.push({
        id: p.id, name: p.full_name, href: hrefFor(ctx, 'person', p.id), level: 'person', role: p.role, person_status: p.status,
        college: c ? { id: c.id, name: c.short_name || c.name } : null, district: dRef(c?.district_id),
        min: row?.target_min ?? null, target, max: row?.target_max ?? null, target_source: row ? 'explicit' : 'none',
        actual: own, actual_own: own, actual_team: teamActual, actual_combined: own + teamActual, actual_against_target: target == null ? null : own,
        ...j, below_min: row?.target_min != null && own < row.target_min, above_max: row?.target_max != null && own > row.target_max,
        covers: null,
        team: tb.team, combined: tb.combined, // v4.1 (F2/F5/D5): see teamBlocks
      });
    }
  } else if (level === 'college') {
    for (const c of ctx.colleges.values()) {
      if (!inD(c.district_id)) continue;
      if (opts.college_id && c.id !== opts.college_id) continue;
      const sc = { type: 'college', id: c.id };
      const t = periodTargetOf(ctx, P, sc);
      const actual = A.college.get(c.id) || 0;
      const cmp = t.target == null ? actual : t.against;
      rows.push({
        id: c.id, name: c.short_name || c.name, full_name: c.name, href: hrefFor(ctx, 'college', c.id), level: 'college',
        college: { id: c.id, name: c.short_name || c.name }, district: dRef(c.district_id), targeted: !!c.targeted, op_status: c.op_status,
        min: t.min, target: t.target, max: t.max, target_source: t.target_source,
        actual: cmp, actual_own: actual, actual_team: null, actual_combined: actual, actual_against_target: t.target == null ? null : t.against,
        ...J(t.target, cmp, t.target_source === 'sum_of_children' ? t.covers : null), target_reason: t.target_reason ?? null, below_min: t.min != null && cmp < t.min, above_max: t.max != null && cmp > t.max,
        covers: t.covers, team: null, combined: null,
        not_credited: A.uncredited.get(c.id) || 0,
      });
    }
  } else if (level === 'district' || level === 'state') {
    const scopes = level === 'state' ? [{ type: 'state', id: 'ap', ...(ds ? { districts: ds, dkey: [...ds].sort().join(',') } : {}) }]
      : [...ctx.districts.keys()].filter(inD).map((id) => ({ type: 'district', id }));
    for (const sc of scopes) {
      const t = periodTargetOf(ctx, P, sc);
      const actual = periodActualOf(ctx, P, sc);
      const cmp = t.target == null ? actual : t.against;
      rows.push({
        id: sc.type === 'state' ? 'ap' : sc.id, name: scopeLabel(ctx, sc), href: hrefFor(ctx, sc.type, sc.id), level: sc.type,
        college: null, district: sc.type === 'district' ? dRef(sc.id) : null,
        min: t.min, target: t.target, max: t.max, target_source: t.target_source,
        actual: cmp, actual_own: actual, actual_team: null, actual_combined: actual, actual_against_target: t.target == null ? null : t.against,
        ...J(t.target, cmp, t.target_source === 'sum_of_children' ? t.covers : null), target_reason: t.target_reason ?? null, below_min: t.min != null && cmp < t.min, above_max: t.max != null && cmp > t.max,
        covers: t.covers, team: null, combined: null,
        colleges: scopeColleges(ctx, sc).length,
      });
    }
  } else return { error: 'level must be person, college, district or state', field: 'level' };
  if (opts.only_with_target) rows = rows.filter((r) => r.target != null);
  const sort = opts.sort || '-pct';
  const desc = sort.startsWith('-'); const sk = sort.replace(/^-/, '');
  const val = (r) => (sk === 'name' ? String(r.name || '') : sk === 'actual' ? r.actual : sk === 'remaining' ? (r.remaining ?? -1) : sk === 'target' ? (r.target ?? -1) : (r.pct ?? -1));
  rows.sort((a, b) => { const x = val(a); const y = val(b); const c = typeof x === 'string' ? x.localeCompare(y) : x - y; return (desc ? -c : c) || b.actual - a.actual || String(a.name).localeCompare(String(b.name)); });
  // v4.1: totals only add rows that are judged (a partial_target row has no remaining / pct)
  const wt = rows.filter((r) => r.target != null && r.status !== 'partial_target');
  const tSum = wt.reduce((s, r) => s + r.target, 0); const aT = wt.reduce((s, r) => s + r.actual, 0);
  const by_status = {}; for (const r of rows) by_status[r.status] = (by_status[r.status] || 0) + 1;
  const totals = {
    rows: rows.length, with_target: wt.length, target: wt.length ? tSum : null, actual: rows.reduce((s, r) => s + r.actual, 0),
    actual_against_target: wt.length ? aT : null, remaining: wt.length ? wt.reduce((s, r) => s + r.remaining, 0) : null,
    exceeded_by: wt.length ? wt.reduce((s, r) => s + r.exceeded_by, 0) : null, pct: tSum ? round1((aT / tSum) * 100) : null, by_status,
    partial_target: rows.filter((r) => r.status === 'partial_target').length,
  };
  // the programme goal (state target, e.g. 400 by 31 Dec), with the actual for the selected districts
  const pst = ctx.targets.get('state:ap:');
  // v4.1 (D2): the programme target covers the programme districts; a selection that misses one of them gets target null + a reason
  const pApplies = stateRowApplies(ctx, ds ? { districts: ds } : null);
  const pTarget0 = pst ? Number(pst.target) : (ctx.settings.program_target ?? null);
  const pTarget = pApplies ? pTarget0 : null;
  const PP = periodOf(ctx, 'programme');
  const pAct = [...ctx.colleges.values()].filter((c) => !ds || ds.has(c.district_id)).reduce((s, c) => s + (periodActuals(ctx, PP).college.get(c.id) || 0), 0);
  const programme = { target: pTarget, deadline: PP.end, start: PP.start, districts_filter: ds ? [...ds] : null, actual: pAct,
    programme_target: pTarget0, target_reason: !pApplies && pTarget0 != null ? programmeTargetReason(ctx) : null, target_districts: programmeDistricts(ctx),
    ...judge(ctx, { target: pTarget, actual: pAct, start: PP.start, end: PP.end }) };
  return { level, period: { key: P.key, type: P.type, start: P.start, end: P.end, label: P.label, days_total: P.days_total, days_elapsed: P.days_elapsed, today: P.today }, rows, totals, programme };
}

// ---------------------------------------------------------------------------------------------
// College list row (/api/colleges)
// ---------------------------------------------------------------------------------------------
export function collegeRow(ctx, c) {
  const s = summary(ctx, { type: 'college', id: c.id });
  const people = ctx.peopleByCollege.get(c.id) || [];
  const lead = people.find((p) => p.role === 'college_lead' && p.status === 'active') || people.find((p) => p.role === 'college_lead' && notInactive(p)) || null;
  const ex = ctx.exam.get(c.id);
  const fu = followupsIn(ctx, [c], ctx.branchesByCollege.get(c.id) || [], []);
  const next = fu.filter((f) => f.due_date).sort((a, b) => a.due_date.localeCompare(b.due_date))[0] || null;
  return {
    id: c.id, sno: c.sno, name: c.name, short_name: c.short_name, district_id: c.district_id, city_id: c.city_id,
    lat: c.lat, lng: c.lng, geo_precision: c.geo_precision, op_status: c.op_status, targeted: c.targeted,
    tier: c.tier, autonomous: c.autonomous, is_demo: c.is_demo,
    branches: s.branches, branches_relevant: s.branches_relevant,
    strength: s.strength, eligible: s.eligible,
    college_lead: lead ? lead.full_name : null, college_lead_id: lead ? lead.id : null,
    // v4: team block for the colleges list (R3)
    lead: lead ? { id: lead.id, name: lead.full_name, phone: lead.phone ?? null, status: lead.status } : null,
    ambassador_count: people.filter((p) => AMB_ROLES.has(p.role) && notInactive(p)).length,
    unassigned_count: people.filter((p) => AMB_ROLES.has(p.role) && notInactive(p) && assignmentOf(ctx, p).assignment_status !== 'assigned').length,
    exceeded_by: s.exceeded_by, pace_status: s.pace_status,
    ambassador_leads: s.ambassador_leads, ambassadors: s.ambassadors,
    branches_needing_ambassadors: s.branches_needing_ambassadors,
    target: s.target, target_source: s.target_source, enrolled: s.enrolled, reached: s.reached, remaining: s.remaining, pct: s.pct,
    on_track: s.on_track, diagnosis: s.diagnosis,
    exam_state: ex.exam_state, next_exam: ex.next_exam, outreach_from: ex.outreach_from,
    followups_open: s.followups_open,
    next_followup: next ? { id: next.id, title: next.title, due_date: next.due_date, overdue: next.due_date < ctx.today } : null,
  };
}

/** progress bucket for filters / map pins */
export function progressBucket(row) {
  if (row.target == null || row.target === 0) return 'no_target';
  if (row.pace_status === 'partial_target') return 'partial_target'; // v4.1: never counted as on track
  return row.on_track === false ? 'behind' : 'on_track';
}
