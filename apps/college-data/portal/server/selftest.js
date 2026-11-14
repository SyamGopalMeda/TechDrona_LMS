// Self-test: runs against a temporary copy of the DB with TODAY=2026-11-03, seeds reference + demo data,
// exercises every endpoint and asserts the key invariants. Usage: node server/selftest.js
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { DEFAULT_DB_PATH } from './db.js';

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'techdrona-selftest-'));
const dbPath = path.join(tmpDir, 'test.db');
if (fs.existsSync(DEFAULT_DB_PATH)) {
  // copy the live DB (main file + WAL) so the test also proves seeding is safe on real data
  fs.copyFileSync(DEFAULT_DB_PATH, dbPath);
  if (fs.existsSync(`${DEFAULT_DB_PATH}-wal`)) fs.copyFileSync(`${DEFAULT_DB_PATH}-wal`, `${dbPath}-wal`);
}
process.env.DB_PATH = dbPath;
process.env.TODAY = '2026-11-03';
delete process.env.PORTAL_PASSCODE;
delete process.env.PORTAL_PROXY_SECRET; // standalone mode (proxy mode is covered by server/proxy.test.js)

const { openDb } = await import('./db.js');
const { seedReference, seedDemo, clearDemo } = await import('./seed.js');
const { startServer, hostGuard, isLoopback } = await import('./server.js');

const results = [];
const CALL_ST = ['not_called', 'attempted_no_answer', 'follow_up_due', 'contacted', 'interested', 'participation_confirmed', 'enrolled'];
function check(name, cond, detail = '') {
  results.push({ name, ok: !!cond, detail });
}
async function step(name, fn) {
  try { await fn(); } catch (e) { results.push({ name: `${name} (threw)`, ok: false, detail: e.stack || String(e) }); }
}

const db = openDb(dbPath);
const quiet = () => {};
// The live DB may already hold real operational data (an explicit state target, imported contacts).
// Rollup tests assume no explicit targets, so the test copy starts without them; contact tests count only the rows they create.
db.exec('DELETE FROM targets');
// v4: pace is measured from settings.program_start. The test day (2026-11-03) is the real programme start, which would make every
// pace "too early"; start the test programme a month earlier so the pace/diagnosis tests stay meaningful.
db.prepare("INSERT INTO settings(key, value) VALUES ('program_start', '\"2026-10-01\"') ON CONFLICT(key) DO UPDATE SET value = excluded.value").run();
const peopleBefore = db.prepare('SELECT COUNT(*) n FROM people WHERE is_demo = 0').get().n;
const s1 = seedReference(db, { log: quiet });
const s2 = seedReference(db, { log: quiet });
check('seed: loads 170 colleges', db.prepare('SELECT COUNT(*) n FROM colleges').get().n >= 170);
check('seed: 26 fixed districts present', db.prepare('SELECT COUNT(*) n FROM districts').get().n >= 26);
check('seed: re-run is idempotent (no inserts/updates on second run)', s2.colleges.insert === 0 && s2.colleges.update === 0 && s2.exams.insert === 0 && s2.exams.update === 0, JSON.stringify(s2));
check('seed: exams loaded', db.prepare('SELECT COUNT(*) n FROM exams').get().n >= 200, JSON.stringify(s1.exams));
const demo = seedDemo(db);
check('demo: 6 colleges flagged', demo.colleges.length === 6 && demo.colleges.includes('c6'));

// ---------------------------------------------------------------- research import (target planner), on this temp copy
const { importResearch, parseCsv, DEFAULT_CSV_DIR } = await import('./import_research.js');
let researchStats = null;
{
  const p = parseCsv('a,b,c\r\n1,"x, ""y""\nz",3\n\n4,,"6"\n');
  check('import: CSV parser handles quoted commas, quotes and newlines', p.rows.length === 2 && p.rows[0].b === 'x, "y"\nz' && p.rows[1].b === '' && p.rows[1].c === '6');
  if (!fs.existsSync(DEFAULT_CSV_DIR)) {
    check('import: research CSVs present (research_notes/... colleges 2)', false, DEFAULT_CSV_DIR);
  } else {
    const snap = () => JSON.stringify([
      db.prepare('SELECT * FROM colleges ORDER BY id').all().filter((c) => c.updated_by !== 'import_research'),
      db.prepare('SELECT * FROM branches ORDER BY id').all().filter((b) => b.updated_by !== 'import_research'),
    ]);
    const before = snap();
    const planBefore = db.prepare('SELECT COUNT(*) n FROM college_plan').get().n;
    const dry = importResearch(db, { dryRun: true, log: quiet });
    check('import --dry-run writes nothing', db.prepare('SELECT COUNT(*) n FROM college_plan').get().n === planBefore && snap() === before);
    researchStats = importResearch(db, { log: quiet });
    const t = researchStats.totals;
    check('import: targeted research totals = 377 / 655 / 1,143, ambassadors 299, college leads 64 (84 targeted)', t.min === 377 && t.avg === 655 && t.max === 1143 && t.ambassadors === 299 && t.college_leads === 64 && researchStats.targeted === 84, JSON.stringify(researchStats.totals));
    check('import: 122 colleges in plan, 8 excluded (out of scope / duplicate), none skipped', researchStats.in_plan === 122 && researchStats.excluded === 8 && researchStats.skipped.length === 0 && dry.in_plan === 122, JSON.stringify(researchStats.skipped));
    check('import: existing colleges and branches unchanged (op_status included)', snap() === before);
    const anr = db.prepare("SELECT * FROM colleges WHERE aliases LIKE '%new-ANRG%'").all();
    check('import: ANR CET Gudivada present exactly once (operational, Krishna, targeted, sourced note)', anr.length === 1 && anr[0].op_status === 'operational' && anr[0].district_id === 'krishna' && anr[0].targeted === 1 && /research import/i.test(anr[0].notes) && !!anr[0].op_status_source, JSON.stringify(anr.map((c) => c.id)));
    const again = importResearch(db, { log: quiet });
    check('import: re-run is a no-op (0 insert / update / delete, no new college)', again.plan.insert === 0 && again.plan.update === 0 && again.plan.delete === 0 && again.new_colleges.length === 0 && again.plan.same === 130, JSON.stringify(again.plan));
    check('import: plan tables filled (130 college rows, branches)', db.prepare('SELECT COUNT(*) n FROM college_plan').get().n >= 130 && db.prepare('SELECT COUNT(*) n FROM college_plan_branches').get().n >= 600);
  }
}

const { server, port } = await startServer({ port: 0, host: '127.0.0.1', db });
const base = `http://127.0.0.1:${port}`;
const USER = 'Self Test ✓';
async function api(method, p, body, headers = {}) {
  const h = { ...headers };
  if (body !== undefined) h['Content-Type'] = 'application/json';
  const r = await fetch(base + p, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) });
  const txt = await r.text();
  let data = null; try { data = txt ? JSON.parse(txt) : null; } catch { data = txt; }
  return { status: r.status, data };
}
const W = { 'X-User': encodeURIComponent(USER) };
const get = (p) => api('GET', p);
const auditCount = () => db.prepare('SELECT COUNT(*) n FROM audit_log').get().n;

await step('meta', async () => {
  const r = await get('/api/meta');
  check('GET /api/meta 200 with districts/cities/settings', r.status === 200 && r.data.districts.length >= 26 && r.data.cities.length > 0 && r.data.settings.org_name === 'Tech Drona');
  check('meta.demo is true while demo rows exist', r.data.demo === true);
  check('settings defaults (relevance_factors.circuit = 0.6, min_conversion 0.05, deadline 2026-12-31)', r.data.settings.relevance_factors.circuit === 0.6 && r.data.settings.min_conversion === 0.05 && r.data.settings.state_target_deadline === '2026-12-31');
});

await step('summary + rollup invariants', async () => {
  const st = (await get('/api/summary?scope=state')).data;
  check('state summary has all contract keys', ['colleges', 'targeted_colleges', 'operational_colleges', 'cities', 'districts', 'branches', 'branches_relevant', 'branches_with_ambassadors', 'branches_needing_ambassadors', 'strength', 'relevant_students', 'final_year', 'eligible', 'college_leads', 'colleges_with_lead', 'ambassador_leads', 'ambassadors', 'target', 'target_source', 'reconciled', 'children_target_sum', 'enrolled', 'reached', 'remaining', 'pct', 'deadline', 'on_track', 'diagnosis', 'followups_open', 'followups_overdue', 'exams', 'by_course'].every((k) => k in st));
  check('state target = sum of children (no explicit state target)', st.target_source === 'sum_of_children' && st.target === st.children_target_sum, `${st.target_source} ${st.target} vs ${st.children_target_sum}`);
  const meta = (await get('/api/meta')).data;
  let sumD = 0;
  for (const d of meta.districts) { const s = (await get(`/api/summary?scope=district:${d.id}`)).data; sumD += s.target ?? 0; }
  check('state target equals sum of district summaries', st.target === sumD, `${st.target} vs ${sumD}`);
  const c6 = (await get('/api/summary?scope=college:c6')).data;
  check('college remaining = max(target - enrolled, 0)', c6.remaining === Math.max(c6.target - c6.enrolled, 0) && c6.target_source === 'explicit');
  check('college pct = enrolled/target', Math.abs(c6.pct - c6.enrolled / c6.target) < 1e-9);
  check('deadline falls back to settings.state_target_deadline', c6.deadline === '2026-12-31');
  check('on_track is boolean when a target exists', typeof c6.on_track === 'boolean');
  check('diagnosis is null when on track, a known code otherwise', c6.on_track ? c6.diagnosis === null : ['ambassador_gap', 'low_outreach', 'low_conversion', 'unrealistic_target', 'behind_pace'].includes(c6.diagnosis), `${c6.on_track} ${c6.diagnosis}`);
  check('basis values present on aggregates', ['verified', 'estimated', 'pending'].includes(st.strength.basis));
  check('by_course lists the demo course with target + enrolled', st.by_course.length >= 1 && st.by_course.some((c) => c.target != null));
  const bad = await get('/api/summary?scope=district:nowhere');
  check('unknown scope -> 400 JSON error', bad.status === 400 && typeof bad.data.error === 'string');
});

await step('exams', async () => {
  const ex = (await get('/api/exams')).data;
  const c6 = ex.find((r) => r.college_id === 'c6');
  check('exam_state for Amrita c6 is in_exams on 2026-11-03', c6 && c6.exam_state === 'in_exams', JSON.stringify(c6 && { s: c6.exam_state, n: c6.next_exam }));
  check('c6 outreach_from = day after last 4-1 end-sem (2026-11-05)', c6 && c6.outreach_from === '2026-11-05', c6?.outreach_from);
  check('exam states all valid', ex.every((r) => ['in_exams', 'exams_soon', 'clear', 'unknown'].includes(r.exam_state)));
  const f = (await get('/api/exams?state=in_exams')).data;
  check('exams ?state filter', f.length > 0 && f.every((r) => r.exam_state === 'in_exams'));
});

await step('colleges', async () => {
  const all = (await get('/api/colleges')).data;
  check('GET /api/colleges returns 170 rows', all.length >= 170);
  const keys = ['id', 'sno', 'name', 'short_name', 'district_id', 'city_id', 'lat', 'lng', 'geo_precision', 'op_status', 'targeted', 'tier', 'autonomous', 'branches', 'strength', 'eligible', 'college_lead', 'ambassador_leads', 'ambassadors', 'branches_needing_ambassadors', 'target', 'enrolled', 'remaining', 'pct', 'on_track', 'diagnosis', 'exam_state', 'next_exam', 'followups_open', 'next_followup'];
  check('college rows have all contract keys', keys.every((k) => k in all[0]), keys.filter((k) => !(k in all[0])).join(','));
  const g = (await get('/api/colleges?district=guntur')).data;
  check('?district filter', g.length > 0 && g.every((r) => r.district_id === 'guntur'));
  const beh = (await get('/api/colleges?progress=no_target')).data;
  check('?progress filter', beh.every((r) => r.target == null || r.target === 0));
  const gap = (await get('/api/colleges?amb=gap')).data;
  check('?amb=gap filter', gap.every((r) => r.branches_needing_ambassadors > 0));
  const q = (await get('/api/colleges?q=amrita')).data;
  check('?q filter', q.some((r) => r.id === 'c6'));
  const d = (await get('/api/colleges/c6')).data;
  check('GET /api/colleges/:id shape', d.college?.id === 'c6' && d.rollup && Array.isArray(d.branches) && Array.isArray(d.people) && Array.isArray(d.exams) && Array.isArray(d.followups) && Array.isArray(d.recent_activities) && Array.isArray(d.recent_enrollments) && Array.isArray(d.audit));
  check('branch entries carry rollup + people', d.branches.length > 0 && d.branches.every((b) => b.rollup && Array.isArray(b.people)));
  const nf = await get('/api/colleges/c9999');
  check('unknown college -> 404', nf.status === 404 && nf.data.error);
  const b = d.branches[0];
  const bd = (await get(`/api/branches/${b.id}`)).data;
  check('GET /api/branches/:id shape', bd.branch?.id === b.id && bd.rollup && Array.isArray(bd.people) && Array.isArray(bd.activities) && Array.isArray(bd.enrollments) && Array.isArray(bd.followups));
  const c6s = (await get('/api/summary?scope=college:c6')).data;
  check('college target_source/children_target_sum consistent', c6s.children_target_sum === null || typeof c6s.children_target_sum === 'number');
});

await step('people', async () => {
  const ppl = (await get('/api/people')).data;
  check('GET /api/people returns demo people', ppl.length >= 6 * 4);
  const al = ppl.find((p) => p.role === 'ambassador_lead' && p.reports.length);
  const pd = (await get(`/api/people/${al.id}`)).data;
  const sumReports = pd.reports.reduce((s, r) => s + (r.target ?? 0), 0);
  check('lead team_target = sum of reports\' targets', pd.rollup.team_target === sumReports, `${pd.rollup.team_target} vs ${sumReports}`);
  check('person target only from explicit row (lead has none)', pd.rollup.target === null);
  const amb = ppl.find((p) => p.role === 'ambassador' && p.target != null);
  check('ambassador remaining = target - enrolled', amb.remaining === Math.max(amb.target - amb.enrolled, 0));
  const f = (await get('/api/people?role=ambassador&college=c6')).data;
  check('people filters role+college', f.length > 0 && f.every((p) => p.role === 'ambassador' && p.college_id === 'c6'));
});

await step('search', async () => {
  const r = (await get('/api/search?q=amrita')).data;
  check('search finds a college (Amrita -> c6)', r.some((x) => x.type === 'college' && x.id === 'c6' && x.href === '#/college/c6'));
  const d = (await get('/api/search?q=guntur')).data;
  check('search finds a district', d.some((x) => x.type === 'district' && x.id === 'guntur'));
  const p = (await get('/api/search?q=DEMO%20Lead')).data;
  check('search finds a person', p.some((x) => x.type === 'person'));
});

await step('leaderboard/attention/followups/timeseries/quality', async () => {
  for (const level of ['district', 'city', 'college', 'branch', 'person']) {
    const r = await get(`/api/leaderboard?level=${level}&limit=5`);
    check(`leaderboard level=${level}`, r.status === 200 && Array.isArray(r.data) && r.data.length <= 5 && r.data.every((x) => 'target' in x && 'enrolled' in x && 'pct' in x));
  }
  const att = (await get('/api/attention')).data;
  check('attention returns prioritised items with reasons', att.length > 0 && att.every((a) => a.reasons.length && ['high', 'medium', 'low'].includes(a.severity)));
  const od = (await get('/api/followups?due=overdue')).data;
  check('followups ?due=overdue all overdue', od.length > 0 && od.every((f) => f.overdue && f.due_date < '2026-11-03'));
  const sc = (await get('/api/followups?scope=college:c6')).data;
  check('followups ?scope', sc.length > 0 && sc.every((f) => f.college_id === 'c6'));
  const ts = (await get('/api/timeseries?scope=state&days=60')).data;
  const totalE = db.prepare("SELECT COUNT(*) n FROM enrollments WHERE enrolled_on BETWEEN date('2026-11-03','-59 day') AND '2026-11-03'").get().n;
  check('timeseries 60 days, enrolled sums match DB', ts.length === 60 && ts.at(-1).date === '2026-11-03' && ts.reduce((s, x) => s + x.enrolled, 0) === totalE);
  const q = (await get('/api/quality')).data;
  check('quality has missing[] and basis_counts', Array.isArray(q.missing) && q.missing.every((m) => 'field' in m && 'count' in m && Array.isArray(m.college_ids)) && 'verified' in q.basis_counts);
});

await step('writes + validation + audit', async () => {
  const noUser = await api('POST', '/api/courses', { name: 'X' });
  check('write without X-User -> 401', noUser.status === 401 && noUser.data.error);
  const a0 = auditCount();
  const course = await api('POST', '/api/courses', { name: 'Selftest Course', price_inr: 9999 }, W);
  check('POST course -> 201 with saved row', course.status === 201 && course.data.id && course.data.name === 'Selftest Course');
  const inv = await api('POST', '/api/people', { college_id: 'c6', role: 'boss', full_name: '', email: 'nope' }, W);
  check('invalid person -> 400 with fields', inv.status === 400 && inv.data.fields && inv.data.fields.role && inv.data.fields.full_name && inv.data.fields.email);
  const ref = await api('POST', '/api/people', { college_id: 'c99999', role: 'ambassador', full_name: 'X' }, W);
  check('unknown reference -> 400', ref.status === 400 && ref.data.fields?.college_id);
  const det = (await get('/api/colleges/c6')).data;
  const br = det.branches[0];
  const p = await api('POST', '/api/people', { college_id: 'c6', role: 'ambassador', full_name: 'Selftest Ambassador', phone: '+91 90000 00000', branch_ids: [br.id] }, W);
  check('POST person with branch_ids', p.status === 201 && p.data.branch_ids?.includes(br.id), JSON.stringify(p.data));
  const patched = await api('PATCH', `/api/people/${p.data.id}`, { status: 'onboarding', branch_ids: [] }, W);
  check('PATCH person branch_ids + status', patched.status === 200 && patched.data.status === 'onboarding' && patched.data.branch_ids.length === 0);
  const en = await api('POST', '/api/enrollments', { branch_id: br.id, person_id: p.data.id, course_id: course.data.id, student_name: 'Test Student', enrolled_on: '2026-11-02', amount_inr: 9999 }, W);
  check('POST enrollment infers college from branch', en.status === 201 && en.data.college_id === 'c6');
  const fut = await api('POST', '/api/enrollments', { college_id: 'c6', enrolled_on: '2027-05-01' }, W);
  check('future enrollment date rejected', fut.status === 400 && fut.data.fields?.enrolled_on);
  const ac = await api('POST', '/api/activities', { college_id: 'c6', type: 'session', students_reached: 55 }, W);
  check('POST activity defaults on_date to today', ac.status === 201 && ac.data.on_date === '2026-11-03');
  const fu = await api('POST', '/api/followups', { scope_type: 'college', scope_id: 'c6', title: 'Call TPO', due_date: '2026-11-05', issue: 'exams' }, W);
  check('POST followup', fu.status === 201 && fu.data.status === 'open');
  const done = await api('PATCH', `/api/followups/${fu.data.id}`, { status: 'done' }, W);
  check('PATCH followup done sets done_at', done.data.status === 'done' && !!done.data.done_at);
  const t1 = await api('POST', '/api/targets', { scope_type: 'branch', scope_id: String(br.id), target: 7 }, W);
  const t2 = await api('POST', '/api/targets', { scope_type: 'branch', scope_id: String(br.id), target: 9, deadline: '2026-12-15' }, W);
  check('POST targets upserts on (scope_type, scope_id, course_id)', t1.data.id === t2.data.id && t2.data.target === 9 && t2.data.deadline === '2026-12-15');
  const bs = (await get(`/api/summary?scope=branch:${br.id}`)).data;
  check('branch deadline from its own target', bs.deadline === '2026-12-15' && bs.target === 9);
  const tBad = await api('POST', '/api/targets', { scope_type: 'college', scope_id: 'c99999', target: 5 }, W);
  check('target on unknown scope -> 400', tBad.status === 400);
  const bp = await api('PATCH', `/api/branches/${br.id}`, { intake_per_year: 90, intake_basis: 'verified' }, W);
  const f = (await get('/api/meta')).data.settings.relevance_factors[bp.data.category];
  check('PATCH branch intake re-derives estimates (strength=intake*4, eligible=final_year*factor)', bp.status === 200 && (bp.data.strength_basis === 'verified' || bp.data.strength_total === 360) && (bp.data.eligible_basis === 'verified' || bp.data.eligible_estimate === Math.round(bp.data.final_year * f)), JSON.stringify(bp.data));
  const nb = await api('POST', '/api/branches', { college_id: 'c6', code: 'ST-CSM', name: 'CSE (AI & ML)', category: 'it_allied' }, W);
  check('POST branch with unknown intake -> pending basis, relevant by category', nb.status === 201 && nb.data.is_relevant === 1 && nb.data.strength_total === null && nb.data.strength_basis === 'pending');
  const dup = await api('POST', '/api/branches', { college_id: 'c6', code: 'ST-CSM' }, W);
  check('duplicate branch code -> 409', dup.status === 409);
  const sset = await api('PATCH', '/api/settings', { min_conversion: 0.07 }, W);
  check('PATCH settings', sset.status === 200 && sset.data.min_conversion === 0.07);
  const sbad = await api('PATCH', '/api/settings', { min_conversion: 7 }, W);
  check('invalid setting -> 400 fields', sbad.status === 400 && sbad.data.fields?.min_conversion);
  const cp = await api('PATCH', '/api/colleges/c1', { website: 'https://selftest.kluniversity.in', targeted: true }, W);
  check('PATCH college', cp.status === 200 && cp.data.website === 'https://selftest.kluniversity.in' && cp.data.updated_by === USER);
  const ex = db.prepare("SELECT id FROM exams WHERE college_id = 'c6' AND semester = '4-1'").get();
  const ep = await api('PATCH', `/api/exams/${ex.id}`, { notes: 'Checked by selftest' }, W);
  check('PATCH exam', ep.status === 200 && ep.data.notes === 'Checked by selftest');
  const del = await api('DELETE', `/api/activities/${ac.data.id}`, undefined, W);
  check('DELETE activity', del.status === 200 && del.data.ok);
  const del2 = await api('DELETE', `/api/activities/${ac.data.id}`, undefined, W);
  check('DELETE missing -> 404', del2.status === 404);
  const a1 = auditCount();
  check('audit rows written for every create/update/delete', a1 - a0 >= 15, `${a1 - a0} new audit rows`);
  const au = (await get(`/api/audit?entity=person&entity_id=${p.data.id}`)).data;
  check('audit has before/after JSON + actor (URL-decoded X-User)', au.length >= 2 && au.some((r) => r.action === 'update' && r.before && r.after && r.before.status === 'active' && r.after.status === 'onboarding') && au.every((r) => r.actor === USER));
  // reseed keeps manual edits and never touches people
  const pc = db.prepare('SELECT COUNT(*) n FROM people').get().n;
  seedReference(db, { log: quiet });
  check('reseed keeps user-edited college fields', db.prepare("SELECT website FROM colleges WHERE id = 'c1'").get().website === 'https://selftest.kluniversity.in');
  check('reseed keeps user-edited exam rows', db.prepare('SELECT notes FROM exams WHERE id = ?').get(ex.id).notes === 'Checked by selftest');
  check('reseed never touches people', db.prepare('SELECT COUNT(*) n FROM people').get().n === pc && peopleBefore === db.prepare('SELECT COUNT(*) n FROM people WHERE is_demo = 0').get().n - 1);
});

await step('passcode', async () => {
  process.env.PORTAL_PASSCODE = 'secret-pass';
  let r1; let r2;
  try {
    r1 = await api('POST', '/api/courses', { name: 'Pass test' }, W);
    r2 = await api('POST', '/api/courses', { name: 'Pass test' }, { ...W, 'X-Passcode': 'secret-pass' });
  } finally { delete process.env.PORTAL_PASSCODE; }
  check('PORTAL_PASSCODE enforced (401 without, 201 with)', r1.status === 401 && r2.status === 201);
});

await step('allocate', async () => {
  const a = (await api('POST', '/api/targets/allocate', { parent_type: 'state', total: 1000, method: 'eligible', dry_run: true }, W)).data;
  check('allocate state->districts: sum == total', a.sum === 1000 && a.rows.reduce((s, r) => s + r.proposed, 0) === 1000 && a.rows.every((r) => r.scope_type === 'district'));
  const c = (await api('POST', '/api/targets/allocate', { parent_type: 'college', parent_id: 'c6', total: 37, method: 'strength' }, W)).data;
  check('allocate college->relevant branches: sum == total', c.sum === 37 && c.rows.every((r) => r.scope_type === 'branch'));
  const ambBranch = db.prepare("SELECT pb.branch_id FROM person_branches pb JOIN people p ON p.id = pb.person_id WHERE p.role = 'ambassador' AND p.status <> 'inactive' LIMIT 1").get();
  const b = (await api('POST', '/api/targets/allocate', { parent_type: 'branch', parent_id: String(ambBranch.branch_id), total: 11, method: 'equal' }, W)).data;
  check('allocate branch->ambassadors: sum == total', b.sum === 11 && b.rows.every((r) => r.scope_type === 'person'));
  const e = (await api('POST', '/api/targets/allocate', { parent_type: 'district', parent_id: 'guntur', total: 3, method: 'equal' }, W)).data;
  check('allocate largest remainder with tiny totals still sums', e.sum === 3);
  // pick a city with no explicit targets anywhere inside it
  const city = db.prepare(`SELECT ci.id FROM cities ci WHERE EXISTS (SELECT 1 FROM colleges c WHERE c.city_id = ci.id AND c.targeted = 1)
    AND NOT EXISTS (SELECT 1 FROM targets t JOIN colleges c ON t.scope_type = 'college' AND t.scope_id = c.id WHERE c.city_id = ci.id)
    AND NOT EXISTS (SELECT 1 FROM targets t JOIN branches b ON t.scope_type = 'branch' AND t.scope_id = CAST(b.id AS TEXT) JOIN colleges c ON c.id = b.college_id WHERE c.city_id = ci.id)
    ORDER BY (SELECT COUNT(*) FROM colleges c WHERE c.city_id = ci.id) DESC LIMIT 1`).get();
  const a0 = auditCount();
  const w = await api('POST', '/api/targets/allocate', { parent_type: 'city', parent_id: city.id, total: 50, method: 'equal', dry_run: false, deadline: '2026-12-20' }, W);
  check('allocate dry_run:false writes targets', w.status === 200 && w.data.sum === 50);
  check('one audit entry per written row', auditCount() - a0 === w.data.rows.length, `${auditCount() - a0} vs ${w.data.rows.length}`);
  const cs = (await get(`/api/summary?scope=city:${city.id}`)).data;
  check('rollup: city target = sum of children when no explicit target', cs.target_source === 'sum_of_children' && cs.target === 50 && cs.children_target_sum === 50 && cs.reconciled === true);
  // v4.1 (F3): allocation only targets the city's TARGETED colleges, so the roll-up may not cover every college: then it is partial_target
  // (remaining/pct null); when it does cover all, remaining = target - actual against target.
  check('rollup: remaining = target - enrolled (or null when the roll-up is partial)', cs.target_complete === false ? (cs.remaining === null && cs.pct === null && cs.pace_status === 'partial_target') : cs.remaining === Math.max(cs.target - cs.actual_against_target, 0), JSON.stringify({ c: cs.covers, r: cs.remaining }));
  const kid = (await get(`/api/summary?scope=college:${w.data.rows[0].scope_id}`)).data;
  check('allocated deadline applied to children', kid.deadline === '2026-12-20');
  const inv = await api('POST', '/api/targets/allocate', { parent_type: 'galaxy', total: -1 }, W);
  check('allocate validation -> 400 fields', inv.status === 400 && inv.data.fields.parent_type && inv.data.fields.total);
  // explicit parent target that disagrees -> reconciled false
  await api('POST', '/api/targets', { scope_type: 'city', scope_id: city.id, target: 60 }, W);
  const cs2 = (await get(`/api/summary?scope=city:${city.id}`)).data;
  check('explicit target vs children: reconciled=false when they differ', cs2.target_source === 'explicit' && cs2.target === 60 && cs2.children_target_sum === 50 && cs2.reconciled === false);
});

await step('static', async () => {
  const raw = (p) => new Promise((resolve) => {
    http.get({ host: '127.0.0.1', port, path: p }, (res) => { let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => resolve({ status: res.statusCode, body: b, type: res.headers['content-type'] })); });
  });
  const js = await raw('/js/api.js');
  check('static file served with JS MIME type', js.status === 200 && /text\/javascript/.test(js.type));
  const t1 = await raw('/../server/db.js');
  const t2 = await raw('/%2e%2e/%2e%2e/server/db.js');
  const t3 = await raw('/..%5c..%5cserver%5cdb.js');
  check('no directory traversal', [t1, t2, t3].every((r) => r.status >= 400 && !r.body.includes('DatabaseSync')), [t1, t2, t3].map((r) => r.status).join(','));
  const unk = await get('/api/nope');
  check('unknown API route -> 404 JSON', unk.status === 404 && unk.data.error);
});

await step('regression: free-text exam dates never crash', async () => {
  const { parseIsoDate, addDays, daysBetween, examState } = await import('./rollup.js');
  check('parseIsoDate rejects free text / impossible dates, accepts ISO + timestamps',
    parseIsoDate('before 2026-12-09 (inferred)') === null && parseIsoDate('Nov 2026 (no dates)') === null && parseIsoDate('2026-02-31') === null
    && parseIsoDate('2026-11-03') === '2026-11-03' && parseIsoDate('2026-11-03T09:00:00.000Z') === '2026-11-03' && parseIsoDate(undefined) === null);
  check('addDays/daysBetween return null (not throw) on bad input', addDays('Nov 2026', 1) === null && daysBetween('x', '2026-11-03') === null);
  // exact strings from the real seed, written by a separate connection (like seed.js would)
  const other = openDb(dbPath);
  const bad = [
    ['c2', '3-1', null, 'before 2026-12-09 (inferred)'], ['c2', '4-1', null, 'before 2026-12-09 (inferred)'],
    ['c104', '3-1', 'Nov/Dec 2026 (no date)', null], ['c107', '4-1', 'Nov 2026 (snippet; no dates)', null],
    ['c118', '3-1', 'Nov 2026 (after 2026-11-07; no dates)', null],
  ];
  for (const [cid, sem, s, e] of bad) {
    const ex = other.prepare('SELECT id FROM exams WHERE college_id = ? AND semester = ?').get(cid, sem);
    if (ex) other.prepare('UPDATE exams SET endsem_start = ?, endsem_end = ?, notice_date = ? WHERE id = ?').run(s, e, '2026-10 (upload; PDF undated)', ex.id);
    else other.prepare('INSERT INTO exams(college_id, semester, status, endsem_start, endsem_end, notice_date, updated_by) VALUES (?,?,?,?,?,?,?)').run(cid, sem, 'Upcoming', s, e, '2026-10 (upload; PDF undated)', 'seed');
  }
  other.close();
  const st = examState([{ semester: '4-1', status: 'Upcoming', endsem_start: 'Nov 2026 (no dates)', endsem_end: 'before 2026-12-09 (inferred)', mid_window: 'Mid-II 2026-13-40 to 2026-11-07' }], '2026-11-03');
  check('examState treats free-text rows as an unknown window', st.next_exam === null && st.outreach_from === null && st.exam_state === 'clear', JSON.stringify(st));
  const r1 = await get('/api/summary?scope=state');
  const r2 = await get('/api/colleges');
  const r3 = await get('/api/exams');
  check('/api/summary, /api/colleges, /api/exams return 200 with free-text exam dates', r1.status === 200 && r2.status === 200 && r3.status === 200, `${r1.status} ${r2.status} ${r3.status}`);
  const c2 = r3.data.find((r) => r.college_id === 'c2');
  check('c2 (endsem_end "before 2026-12-09 (inferred)") has no fabricated window', c2 && (c2.next_exam === null || c2.next_exam.kind === 'mid') && c2.outreach_from === null, JSON.stringify(c2 && { s: c2.exam_state, n: c2.next_exam, o: c2.outreach_from }));
  const ex = db.prepare("SELECT id FROM exams WHERE college_id = 'c6' AND semester = '3-1'").get();
  const p1 = await api('PATCH', `/api/exams/${ex.id}`, { endsem_start: 'Nov 2026 (no dates)', endsem_end: 'before 2026-12-09 (inferred)' }, W);
  check('PATCH exams accepts free-text end-sem dates', p1.status === 200 && p1.data.endsem_start === 'Nov 2026 (no dates)');
  const p2 = await api('POST', '/api/exams', { college_id: 'c7', semester: '4-1', endsem_start: 'Dec 2026 (tentative)', endsem_end: '2026-12-20' }, W);
  check('POST exams accepts free-text end-sem dates', p2.status === 201);
  const c6 = (await get('/api/exams')).data.find((r) => r.college_id === 'c6');
  check('c6 still in_exams via its 4-1 window after 3-1 became free text', c6.exam_state === 'in_exams');
});

await step('regression: cache sees writes made outside the server', async () => {
  const before = (await get('/api/colleges/c9')).data.college.name;
  const other = openDb(dbPath);
  other.prepare("UPDATE colleges SET name = name || ' [ext]' WHERE id = 'c9'").run();
  other.prepare("INSERT INTO targets(scope_type, scope_id, target, updated_at, updated_by) VALUES ('college', 'c9', 33, '2026-11-01T00:00:00Z', 'ext')").run();
  other.close();
  const after = (await get('/api/colleges/c9')).data;
  check('external UPDATE visible without restart (PRAGMA data_version)', after.college.name === `${before} [ext]`);
  check('external target visible in rollup without restart', after.rollup.target === 33 && after.rollup.target_source === 'explicit');
  await api('PATCH', '/api/colleges/c9', { name: before }, W);
  check('API write invalidates immediately', (await get('/api/colleges/c9')).data.college.name === before);
});

await step('ops additions', async () => {
  const w = await api('POST', '/api/targets/allocate', { parent_type: 'college', parent_id: 'c9', total: 10, method: 'equal', dry_run: false }, W);
  check('allocate dry_run:false without deadline -> 200 (undefined bound as null)', w.status === 200 && w.data.sum === 10, JSON.stringify(w.data).slice(0, 200));
  const fn = (await get('/api/followups?due=fortnight')).data;
  check('followups ?due=fortnight (open, due within 14 days)', Array.isArray(fn) && fn.length > 0 && fn.every((f) => f.status === 'open' && f.due_date <= '2026-11-17'));
  const badDue = await get('/api/followups?due=someday');
  check('followups bad ?due -> 400', badDue.status === 400);
  const un = await get('/api/targets/unreconciled');
  check('GET /api/targets/unreconciled lists explicit targets that differ from children', un.status === 200 && un.data.length > 0
    && un.data.every((r) => ['scope_type', 'scope_id', 'label', 'href', 'target', 'children_target_sum'].every((k) => k in r) && r.target !== r.children_target_sum)
    && un.data.some((r) => r.scope_type === 'college' && r.scope_id === 'c9'), JSON.stringify(un.data).slice(0, 300));
  const st0 = await api('POST', '/api/targets', { scope_type: 'state', target: 5000 }, W);
  check('v4 R11: a state (programme) target via /api/targets without confirm_programme -> 409 programme_target_protected', st0.status === 409 && st0.data.code === 'programme_target_protected');
  const st1 = await api('POST', '/api/targets', { scope_type: 'state', target: 5000, confirm_programme: true }, W);
  const st2 = await api('POST', '/api/targets', { scope_type: 'state', scope_id: 'ap', target: 5001, confirm_programme: true }, W);
  check("state target uses scope_id 'ap' (omitted or explicit)", st1.status === 201 && st1.data.scope_id === 'ap' && st2.data.id === st1.data.id && st2.data.target === 5001);
  const s = (await get('/api/summary?scope=state')).data;
  check('state summary picks up explicit state target', s.target === 5001 && s.target_source === 'explicit');
  const noSid = await api('POST', '/api/targets', { scope_type: 'college', target: 5 }, W);
  check('non-state target without scope_id -> 400', noSid.status === 400 && noSid.data.fields?.scope_id);
  const bl = await get('/api/branches?college=c6&relevant=1');
  check('GET /api/branches?college=&relevant= with college name', bl.status === 200 && bl.data.length > 0 && bl.data.every((b) => b.college_id === 'c6' && b.is_relevant === 1 && b.college_name));
  const bp = (await get('/api/branches?intake_basis=pending')).data;
  check('GET /api/branches?intake_basis=', bp.every((b) => b.intake_basis === 'pending'));
  const bq = (await get('/api/branches?q=amrita')).data;
  check('GET /api/branches?q= matches college name', bq.some((b) => b.college_id === 'c6') && bq.every((b) => [b.code, b.name, b.college_name, b.college_short_name].some((v) => v && v.toLowerCase().includes('amrita'))));
});

await step('api ux fixes (search, messages, no-op audit, delete guards, audit paging)', async () => {
  const s = async (q) => (await get(`/api/search?q=${encodeURIComponent(q)}&limit=50`)).data;
  check('search ignores punctuation: "K.L." finds KL University', (await s('K.L.')).some((r) => r.id === 'c1'));
  check('search ignores apostrophes: "vignans" finds Vignan\'s colleges', (await s('vignans')).filter((r) => r.type === 'college').length >= 3);
  check('search compact match: "aids" and "AI&DS" find AI-DS branches', (await s('aids')).some((r) => r.type === 'branch' && r.label.startsWith('AI-DS')) && (await s('AI&DS')).some((r) => r.type === 'branch' && r.label.startsWith('AI-DS')));
  check('search is accent-insensitive', (await s('gúntur')).some((r) => r.type === 'district' && r.id === 'guntur'));
  check('multi-word search across fields: "engineering guntur"', (await s('engineering guntur')).some((r) => r.type === 'college' && r.sub.endsWith('Guntur')));
  check('multi-word branch search: "cse vignan" finds VFSTR CSE', (await s('cse vignan')).some((r) => r.type === 'branch' && r.sub === 'VFSTR' && r.label.startsWith('CSE')));
  check('search "9" does not match every phone number', (await s('9')).every((r) => r.type !== 'person'));
  check('pre-2022 district name finds the new district', (await s('nellore')).some((r) => r.id === 'tirupati' && /formerly/.test(r.sub)));
  const byDistrict = (await get('/api/colleges?q=palnadu')).data;
  check('GET /api/colleges?q= matches district name', byDistrict.length > 0 && byDistrict.every((c) => c.district_id === 'palnadu'), byDistrict.map((c) => `${c.id}:${c.district_id}:${c.name}`).join(' | '));
  check('GET /api/colleges?q=<sno> is exact, not substring', (await get('/api/colleges?q=9')).data.map((c) => c.id).join() === 'c9');
  const pq = (await get('/api/people?q=demo%20lead%20kl')).data;
  check('GET /api/people?q= multi-word incl. college', pq.length > 0 && pq.every((p) => p.college_id === 'c1'));

  const v = await api('POST', '/api/people', {}, W);
  check('400 message names the fields, fields{} unchanged', v.status === 400 && /Full name: required/.test(v.data.error) && v.data.fields.full_name === 'Required');
  const nf = await api('PATCH', '/api/followups/999999', { title: 'x' }, W);
  check('404 message names the entity', nf.status === 404 && nf.data.error === 'Follow-up 999999 not found');
  const dup = await api('POST', '/api/branches', { college_id: 'c6', code: 'CSE' }, W);
  check('duplicate branch code -> 409 with fields.code', dup.status === 409 && dup.data.fields?.code && /already has a branch with code CSE/.test(dup.data.error), JSON.stringify(dup.data));

  const a0 = auditCount();
  const t1 = await api('POST', '/api/targets', { scope_type: 'college', scope_id: 'c12', target: 40 }, W);
  const a1 = auditCount();
  const t2 = await api('POST', '/api/targets', { scope_type: 'college', scope_id: 'c12', target: 40 }, W);
  check('re-saving an identical target writes no audit entry and keeps updated_at', a1 === a0 + 1 && auditCount() === a1 && t2.data.updated_at === t1.data.updated_at);
  await api('PATCH', '/api/districts/guntur', { targeted: true }, W);
  const a2 = auditCount();
  await api('PATCH', '/api/districts/guntur', { targeted: true }, W);
  check('no-op district PATCH writes no audit entry', auditCount() === a2);
  const t0 = performance.now();
  const al = await api('POST', '/api/targets/allocate', { parent_type: 'state', total: 3000, dry_run: false }, W);
  const ms = performance.now() - t0;
  check('allocate dry_run:false writes rows in one batch (< 1500 ms; timing is only a smoke check)', al.status === 200 && ms < 1500, `${ms.toFixed(0)} ms`);
  const st = (await get('/api/summary?scope=district:guntur')).data;
  check('allocation is visible right after the batch', st.target === al.data.rows.find((r) => r.scope_id === 'guntur').proposed, `${st.target}`);

  const courseId = (await get('/api/courses')).data.find((c) => c.name.startsWith('DEMO'))?.id;
  const dc = await api('DELETE', `/api/courses/${courseId}`, undefined, W);
  check('DELETE course with enrollments -> 409 with a hint (no silent cascade)', dc.status === 409 && /inactive/.test(dc.data.error), JSON.stringify(dc.data));
  const dcol = await api('DELETE', '/api/colleges/c48', undefined, W);
  check('DELETE college with branches -> 409 (branches/exams would cascade unaudited)', dcol.status === 409 && /branches/.test(dcol.data.error), JSON.stringify(dcol.data));
  const boss = (await api('POST', '/api/people', { college_id: 'c48', role: 'ambassador_lead', full_name: 'Selftest Boss' }, W)).data;
  const rep = (await api('POST', '/api/people', { college_id: 'c48', role: 'ambassador', full_name: 'Selftest Rep', reports_to: boss.id }, W)).data;
  const a3 = auditCount();
  const dp = await api('DELETE', `/api/people/${boss.id}`, undefined, W);
  const repAfter = (await get(`/api/people/${rep.id}`)).data.person;
  check('DELETE person audits the cleared reports_to of their reports', dp.status === 200 && repAfter.reports_to === null && auditCount() === a3 + 2);

  const page1 = (await get('/api/audit?limit=2')).data;
  const page2 = (await get('/api/audit?limit=2&offset=2')).data;
  check('GET /api/audit?offset= pages through older entries', page1.length === 2 && page2.length === 2 && page2[0].id < page1[1].id);
  const day = (await get('/api/audit?from=2026-11-03&to=2026-11-03')).data;
  check('GET /api/audit?from=&to= filters by date', day.length > 0 && day.every((r) => r.at.startsWith('2026-11-03')));
  check('GET /api/audit bad from -> 400 field error', (await get('/api/audit?from=3-11-2026')).data.fields?.from);
  const reasons = (await get('/api/attention')).data.flatMap((x) => x.reasons);
  check('attention reasons use readable dates ("9 Nov 2026"), never raw ISO', reasons.length > 0 && reasons.every((t) => !/\d{4}-\d{2}-\d{2}/.test(t)), reasons.filter((t) => /\d{4}-\d{2}/.test(t)).slice(0, 3).join(' | '));
  const all = (await get('/api/colleges')).data;
  const dxs = [...new Set(all.map((c) => c.diagnosis).filter(Boolean))];
  const dxRows = (await get(`/api/colleges?diagnosis=${dxs.join(',')}`)).data;
  check('GET /api/colleges?diagnosis= returns exactly that subset', dxs.length > 0 && dxRows.length === all.filter((c) => dxs.includes(c.diagnosis)).length && dxRows.every((c) => dxs.includes(c.diagnosis)), dxs.join());
  check('GET /api/colleges bad diagnosis -> 400', (await get('/api/colleges?diagnosis=sleepy')).data.fields?.diagnosis);
  const att = (await get('/api/attention')).data;
  check('attention lists per-college "No college lead" once any lead exists', att.some((x) => x.type === 'college' && x.reasons.includes('No college lead appointed')) && !att.some((x) => x.type === 'group'));
  const nb1 = await api('POST', '/api/branches', { college_id: 'c48', code: 'ST-NOCAT', category: '' }, W);
  check('POST branch with empty category -> 201 with default category other (was 500)', nb1.status === 201 && nb1.data.category === 'other', JSON.stringify(nb1.data).slice(0, 200));
  const pb = await api('PATCH', `/api/branches/${nb1.data.id}`, { category: null }, W);
  check('PATCH branch category null -> 400 fields.category (was 500)', pb.status === 400 && pb.data.fields?.category === 'Required', JSON.stringify(pb.data));
  const nn = [['PATCH', '/api/colleges/c48', { name: '', op_status: null }, ['name', 'op_status']], ['PATCH', '/api/people/' + rep.id, { status: '' }, ['status']],
    ['PATCH', '/api/districts/guntur', { name: '' }, ['name']], ['PATCH', `/api/branches/${nb1.data.id}`, { code: '', intake_basis: null }, ['code', 'intake_basis']]];
  let nnOk = true; const nnBad = [];
  for (const [m, p, b, keys] of nn) { const r = await api(m, p, b, W); if (r.status !== 400 || !keys.every((k) => r.data.fields?.[k])) { nnOk = false; nnBad.push(`${p} ${r.status}`); } }
  check('blank NOT NULL fields on PATCH -> 400 per field, never 500', nnOk, nnBad.join(', '));
  const act = await api('POST', '/api/activities', { college_id: 'c48', type: 'call', on_date: null, students_reached: null }, W);
  check('POST activity with null on_date/students_reached uses defaults (today, 0)', act.status === 201 && act.data.on_date === '2026-11-03' && act.data.students_reached === 0, JSON.stringify(act.data));
  await api('DELETE', `/api/activities/${act.data.id}`, undefined, W);
  await api('DELETE', `/api/branches/${nb1.data.id}`, undefined, W);
  check('GET /api/followups bad status -> 400', (await get('/api/followups?status=closed')).status === 400);
});

await step('calling system: contacts', async () => {
  const cid = db.prepare("SELECT id FROM colleges WHERE op_status = 'operational' AND id NOT IN (SELECT college_id FROM enrollments) AND id NOT IN (SELECT college_id FROM people) ORDER BY sno LIMIT 1").get().id;
  globalThis.__callCollege = cid;
  const a0 = auditCount();
  const k1 = await api('POST', '/api/contacts', { college_id: cid, role: 'tpo', name: 'ST TPO', phone: '098765-43210', email: 'TPO@Example.edu.in', basis: 'verified' }, W);
  check('POST contact normalises phone (+91) and email, status untested, audited', k1.status === 201 && k1.data.phone === '+919876543210' && k1.data.email === 'tpo@example.edu.in' && k1.data.status === 'untested' && auditCount() === a0 + 1, JSON.stringify(k1.data));
  const dup = await api('POST', '/api/contacts', { college_id: cid, role: 'office', phone: '+91 98765 43210' }, W);
  check('duplicate phone for the same college -> 409 with fields.phone and existing_id', dup.status === 409 && dup.data.fields?.phone && dup.data.existing_id === k1.data.id, JSON.stringify(dup.data));
  const dupE = await api('POST', '/api/contacts', { college_id: cid, email: 'tpo@EXAMPLE.edu.in' }, W);
  check('duplicate email (case-insensitive) -> 409', dupE.status === 409 && dupE.data.fields?.email);
  check('invalid phone -> 400 fields.phone', (await api('POST', '/api/contacts', { college_id: cid, phone: '12345' }, W)).data.fields?.phone);
  check('contact without phone or email -> 400', (await api('POST', '/api/contacts', { college_id: cid, name: 'Nobody' }, W)).status === 400);
  check('contact with unknown role -> 400', (await api('POST', '/api/contacts', { college_id: cid, phone: '9876500001', role: 'boss' }, W)).data.fields?.role);
  const otherBranch = db.prepare('SELECT id FROM branches WHERE college_id <> ? LIMIT 1').get(cid).id;
  check('contact branch from another college -> 400', (await api('POST', '/api/contacts', { college_id: cid, phone: '9876500002', branch_id: otherBranch }, W)).data.fields?.branch_id);
  const k2 = (await api('POST', '/api/contacts', { college_id: cid, role: 'principal', phone: '0863 2344700' }, W)).data;
  const k3 = (await api('POST', '/api/contacts', { college_id: cid, role: 'office', phone: '9876500003' }, W)).data;
  const k4 = (await api('POST', '/api/contacts', { college_id: cid, role: 'hod', phone: '9876500004' }, W)).data;
  check('landline with STD code normalised', k2.phone === '+918632344700');
  const same = await api('POST', '/api/contacts', { college_id: 'c6', phone: '9876543210' }, W);
  check('same number at a different college is allowed', same.status === 201);
  const pa = await api('PATCH', `/api/contacts/${k3.id}`, { phone: '98765 00003' }, W);
  check('PATCH contact with the same number (other format) is a no-op', pa.status === 200 && pa.data.updated_at === k3.updated_at);
  const pd = await api('PATCH', `/api/contacts/${k3.id}`, { phone: '9876543210' }, W);
  check('PATCH contact to a duplicate number -> 409', pd.status === 409);
  const lst = (await get(`/api/contacts?college=${cid}`)).data;
  check('GET /api/contacts?college= lists them with call counts', (() => { const mine = lst.filter((k) => [k1.data?.id ?? k1.id, k2.id, k3.id, k4.id].includes(k.id)); return mine.length === 4 && mine.every((k) => k.calls_total === 0); })());
  check('GET /api/contacts bad status -> 400', (await get('/api/contacts?status=great')).status === 400);
  globalThis.__k = { k1: k1.data, k2, k3, k4 };
});

await step('calling system: calls, statuses, follow-ups, queue', async () => {
  const cid = globalThis.__callCollege; const { k1, k2, k3, k4 } = globalThis.__k;
  const q0 = (await get('/api/calls/queue?filter=all&limit=1000')).data;
  const r0 = q0.rows.find((r) => r.college_id === cid);
  check('queue: college with contacts but no calls is not_called with an untested best contact (verified TPO first)', r0 && r0.call_status === 'not_called' && r0.best_contact?.id === k1.id, JSON.stringify(r0?.best_contact));
  check('queue: priority has score, tier and a 5-part "why" breakdown summing to the score', r0.priority.parts.length === 5 && r0.priority.parts.reduce((s, p) => s + p.points, 0) === r0.priority.score && ['high', 'medium', 'low'].includes(r0.priority.tier));
  check('queue: counts per filter chip', ['all', 'working', 'high', 'pending', 'invalid', 'interested', 'confirmed'].every((k) => typeof q0.counts[k] === 'number') && q0.counts.all === q0.total);
  check('queue: bad filter -> 400', (await get('/api/calls/queue?filter=hot')).status === 400);
  const sorted = q0.rows.every((r, i) => i === 0 || q0.rows[i - 1].priority.score >= r.priority.score);
  check('queue: sorted by priority (highest first)', sorted);

  const na = await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'no_answer', called_at: '2026-11-02T10:00' }, W);
  check('POST call infers college from contact; caller = X-User', na.status === 201 && na.data.college_id === cid && na.data.caller === USER, JSON.stringify(na.data).slice(0, 300));
  let row = (await get(`/api/calls/queue?limit=1000`)).data.rows.find((r) => r.college_id === cid);
  check('no answer -> college attempted_no_answer, contact stays untested', row.call_status === 'attempted_no_answer' && (await get(`/api/contacts/${k1.id}`)).data.contact.status === 'untested');
  const a0 = auditCount();
  const ci = await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'connected_interested', notes: 'Wants a session', next_action_at: '2026-11-05' }, W);
  check('connected call with next action creates a follow-up and is audited (call + follow-up + contact)', ci.status === 201 && ci.data.followup?.status === 'open' && ci.data.followup?.due_date === '2026-11-05' && ci.data.followup?.scope_id === cid && auditCount() === a0 + 3, `${auditCount() - a0} ${JSON.stringify(ci.data.followup)}`);
  check('connected -> contact working (status_source calls)', ci.data.contact?.status === 'working' && ci.data.contact?.status_source === 'calls');
  row = (await get(`/api/calls/queue?limit=1000`)).data.rows.find((r) => r.college_id === cid);
  check('connected_interested -> college interested, next action = the follow-up', row.call_status === 'interested' && row.next_action?.due_date === '2026-11-05' && row.contact_counts.working === 1);
  const fuList = (await get('/api/followups?status=open')).data;
  check('call follow-up appears in /api/followups', fuList.some((f) => f.id === ci.data.followup.id));
  const cb = await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'connected_callback', next_action_at: '2026-11-03' }, W);
  const oldFu = (await get(`/api/followups/${ci.data.followup.id}`)).data;
  check('a newer call to the same contact closes its earlier open call-back (audited)', oldFu.status === 'done' && cb.data.closed_followups?.includes(ci.data.followup.id));
  row = (await get(`/api/calls/queue?limit=1000`)).data.rows.find((r) => r.college_id === cid);
  check('call-back due today -> follow_up_due', row.call_status === 'follow_up_due' && row.next_action?.due === true, row.call_status);
  const wn = (await api('POST', '/api/calls', { contact_id: k2.id, outcome: 'wrong_number' }, W)).data;
  const dc = (await api('POST', '/api/calls', { contact_id: k3.id, outcome: 'disconnected' }, W)).data;
  check('wrong number -> contact invalid; disconnected -> non_working', wn.contact?.status === 'invalid' && dc.contact?.status === 'non_working');
  await api('PATCH', '/api/settings', { unreachable_after_attempts: 3 }, W);
  for (const o of ['no_answer', 'busy']) await api('POST', '/api/calls', { contact_id: k4.id, outcome: o }, W);
  check('2 unanswered (threshold 3) -> still untested', (await get(`/api/contacts/${k4.id}`)).data.contact.status === 'untested');
  const sw = (await api('POST', '/api/calls', { contact_id: k4.id, outcome: 'switched_off' }, W)).data;
  check('3 unanswered in a row (setting unreachable_after_attempts=3) -> non_working', sw.contact?.status === 'non_working');
  check('settings: bad unreachable_after_attempts -> 400', (await api('PATCH', '/api/settings', { unreachable_after_attempts: -1 }, W)).status === 400);
  await api('PATCH', '/api/settings', { unreachable_after_attempts: 6 }, W);
  check('POST call bad outcome -> 400; future date -> 400; next action before call -> 400',
    (await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'maybe' }, W)).data.fields?.outcome
    && (await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'busy', called_at: '2027-01-01' }, W)).data.fields?.called_at
    && (await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'busy', called_at: '2026-11-03', next_action_at: '2026-11-01' }, W)).data.fields?.next_action_at);
  check('POST call without contact or college -> 400', (await api('POST', '/api/calls', { outcome: 'busy' }, W)).data.fields?.college_id);
  check('POST call needs X-User -> 401', (await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'busy' })).status === 401);
  check('confirms_participation on an unanswered call -> 400', (await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'no_answer', confirms_participation: true }, W)).data.fields?.confirms_participation);
  const pc = await api('POST', '/api/calls', { contact_id: k1.id, outcome: 'connected_interested', confirms_participation: true, notes: 'Principal agreed' }, W);
  const col = (await get(`/api/colleges/${cid}`)).data;
  check('participation confirmed on a call sets the college field (audited) -> participation_confirmed', pc.status === 201 && col.college.participation_confirmed_on === '2026-11-03' && col.call_info.call_status === 'participation_confirmed'
    && col.audit.some((x) => x.entity === 'college' && x.after?.participation_confirmed_on));
  check('GET /api/colleges/:id has contacts[], calls[], call_info, funnel', Array.isArray(col.contacts) && col.contacts.length >= 4 && col.calls.length >= 8 && col.call_info && col.funnel?.stages?.length === 6);
  const lc = (await get(`/api/calls?college=${cid}`)).data;
  check('GET /api/calls?college= newest first with contact names', lc.length === col.calls.length && lc[0].called_at >= lc[lc.length - 1].called_at && lc.some((x) => x.contact_name === 'ST TPO'));
  check('GET /api/calls bad outcome -> 400', (await get('/api/calls?outcome=meh')).status === 400);
  const pt = await api('PATCH', `/api/calls/${wn.id}`, { outcome: 'busy' }, W);
  check('PATCH call outcome refused (only notes are editable) -> 400', pt.status === 400);
  check('PATCH call notes -> 200', (await api('PATCH', `/api/calls/${wn.id}`, { notes: 'fixed typo' }, W)).data.notes === 'fixed typo');
  check('DELETE contact with logged calls -> 409 with a hint', /non-working or invalid/.test((await api('DELETE', `/api/contacts/${k2.id}`, undefined, W)).data.error || ''));
  await api('DELETE', `/api/calls/${wn.id}`, undefined, W);
  check('DELETE the only decisive call -> contact status recomputed (back to untested)', (await get(`/api/contacts/${k2.id}`)).data.contact.status === 'untested');
  const man = await api('PATCH', `/api/contacts/${k2.id}`, { status: 'invalid' }, W);
  check('manual contact status is kept (status_source manual)', man.data.status === 'invalid' && man.data.status_source === 'manual');

  // filters on /api/colleges
  const all = (await get('/api/colleges')).data;
  check('/api/colleges rows carry call_status + contact_counts (no priority field)', all.every((r) => CALL_ST.includes(r.call_status) && r.contact_counts && !('priority' in r)));
  const pcRows = (await get('/api/colleges?call_status=participation_confirmed')).data;
  check('/api/colleges?call_status= returns exactly that subset', pcRows.some((r) => r.id === cid) && pcRows.length === all.filter((r) => r.call_status === 'participation_confirmed').length);
  const wk = (await get('/api/colleges?contact=working')).data; const none = (await get('/api/colleges?contact=none')).data; const nw = (await get('/api/colleges?contact=non_working')).data;
  check('/api/colleges?contact=working|none|non_working', wk.some((r) => r.id === cid) && !none.some((r) => r.id === cid) && nw.some((r) => r.id === cid) && none.length === all.filter((r) => r.contact_counts.total === 0).length);
  const hi = (await get('/api/colleges?priority=high')).data;
  const qhi = (await get('/api/calls/queue?filter=high&include_closed=1&limit=1000')).data.rows;
  check('/api/colleges?priority=high matches the queue high tier', hi.length === qhi.length && hi.every((r) => qhi.some((x) => x.college_id === r.id)), `${hi.length} vs ${qhi.length}`);
  check('/api/colleges bad call_status / contact / priority -> 400', (await get('/api/colleges?call_status=x')).data.fields?.call_status && (await get('/api/colleges?contact=x')).data.fields?.contact && (await get('/api/colleges?priority=top')).data.fields?.priority);
  const qf = async (f) => (await get(`/api/calls/queue?filter=${f}&limit=1000`)).data.rows.map((r) => r.college_id);
  check('queue filters: working / invalid / confirmed include the test college; pending does not', (await qf('working')).includes(cid) && (await qf('invalid')).includes(cid) && (await qf('confirmed')).includes(cid) && !(await qf('pending')).includes(cid));
  const meta = (await get('/api/meta')).data;
  check('meta.counts has contacts, calls, enrollments_confirmed', meta.counts.contacts === db.prepare('SELECT COUNT(*) n FROM contacts').get().n && meta.counts.calls === db.prepare('SELECT COUNT(*) n FROM calls').get().n && 'enrollments_confirmed' in meta.counts);
});

await step('enrollment funnel: stages, no double counting, target dashboard', async () => {
  const stSql = () => Object.fromEntries(db.prepare("SELECT stage, COUNT(*) n FROM enrollments WHERE college_id = 'c6' GROUP BY stage").all().map((r) => [r.stage, r.n]));
  const before = (await get('/api/summary?scope=college:c6')).data;
  const confBefore = db.prepare("SELECT COUNT(*) n FROM enrollments WHERE college_id = 'c6' AND stage = 'confirmed'").get().n;
  check('existing (pre-funnel) enrollments are confirmed and enrolled == confirmed count', before.enrolled === confBefore && db.prepare("SELECT COUNT(*) n FROM enrollments WHERE stage IS NULL OR stage = ''").get().n === 0);
  const mk = (stage, i) => api('POST', '/api/enrollments', { college_id: 'c6', stage, student_name: `ST Funnel ${i}`, student_contact: `98480${String(10000 + i)}`, enrolled_on: '2026-10-20' }, W);
  const made = [];
  for (const [i, s] of ['lead', 'interested', 'registered', 'applied', 'applied', 'dropped'].entries()) made.push((await mk(s, i)).data);
  check('POST enrollment with a stage stamps that stage date', made[1].stage === 'interested' && made[1].interested_on === '2026-10-20' && made[5].dropped_on === '2026-10-20');
  const after = (await get('/api/summary?scope=college:c6')).data;
  check('non-confirmed stages do NOT count as enrolled', after.enrolled === before.enrolled && after.remaining === before.remaining);
  const sq = stSql();
  check('summary.funnel stage counts equal SQL counts (each record once)', ['lead', 'interested', 'registered', 'applied', 'confirmed', 'dropped'].every((k) => (after.funnel[k] || 0) === (sq[k] || 0)) && after.funnel.total === Object.values(sq).reduce((a, b) => a + b, 0), JSON.stringify([after.funnel, sq]));
  const fn = (await get('/api/funnel?scope=college:c6')).data;
  check('GET /api/funnel stages in order with only confirmed counting toward target', fn.stages.map((x) => x.stage).join() === 'lead,interested,registered,applied,confirmed,dropped' && fn.stages.filter((x) => x.counts_toward_target).map((x) => x.stage).join() === 'confirmed');
  const dupS = await mk('lead', 0);
  check('same student mobile + course again -> 409 with existing_id (no duplicate record)', dupS.status === 409 && dupS.data.existing_id === made[0].id && dupS.data.fields?.student_contact);
  const mv = await api('PATCH', `/api/enrollments/${made[3].id}`, { stage: 'confirmed' }, W);
  const after2 = (await get('/api/summary?scope=college:c6')).data;
  check('PATCH stage applied -> confirmed moves the record: enrolled +1, funnel total unchanged, confirmed_on = today', mv.data.stage === 'confirmed' && mv.data.confirmed_on === '2026-11-03' && mv.data.applied_on === '2026-10-20'
    && after2.enrolled === before.enrolled + 1 && after2.funnel.total === after.funnel.total && after2.funnel.applied === after.funnel.applied - 1);
  const ts = (await get('/api/timeseries?scope=college:c6&days=60')).data;
  const tsSql = db.prepare("SELECT COUNT(*) n FROM enrollments WHERE college_id = 'c6' AND stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) BETWEEN '2026-09-05' AND '2026-11-03'").get().n;
  check('timeseries counts confirmed only, on their confirmation date', ts.reduce((s, x) => s + x.enrolled, 0) === tsSql && ts.at(-1).enrolled >= 1);
  check('bad stage -> 400', (await api('PATCH', `/api/enrollments/${made[0].id}`, { stage: 'paid' }, W)).data.fields?.stage);
  check('GET /api/enrollments?stage= filters', (await get('/api/enrollments?college=c6&stage=applied')).data.every((e) => e.stage === 'applied'));

  const td = (await get('/api/target-dashboard?scope=state')).data;
  const confAll = db.prepare("SELECT COUNT(*) n FROM enrollments WHERE stage = 'confirmed'").get().n;
  const st = (await get('/api/summary?scope=state')).data;
  check('target-dashboard: confirmed == SQL confirmed == summary.enrolled; remaining/pct consistent', td.confirmed === confAll && st.enrolled === confAll && td.remaining === Math.max(td.target - td.confirmed, 0) && Math.abs(td.pct - td.confirmed / td.target) < 1e-9, `${td.confirmed} ${confAll} ${st.enrolled}`);
  const recentSql = db.prepare("SELECT COUNT(*) n FROM enrollments WHERE stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) BETWEEN '2026-10-21' AND '2026-11-03'").get().n;
  check('target-dashboard: current pace = confirmed in the last 14 days / 14', td.confirmed_last_14d === recentSql && Math.abs(td.current_daily - recentSql / 14) < 1e-9);
  check('target-dashboard: required pace = remaining / days left (incl. today)', td.days_left === 59 && Math.abs(td.required_daily - td.remaining / 59) < 1e-9 && Math.abs(td.required_weekly - td.remaining / (59 / 7)) < 1e-9);
  const expDate = recentSql > 0 ? new Date(Date.parse('2026-11-03T00:00:00Z') + Math.ceil(td.remaining / (recentSql / 14)) * 86400000).toISOString().slice(0, 10) : null;
  check('target-dashboard: projected date = today + remaining / recent pace', recentSql > 0 ? td.projection.date === expDate : td.projection.date === null && td.projection.explanation, JSON.stringify(td.projection));
  check('target-dashboard: funnel, contacts, calls, pending calls, people', td.funnel.stages.length === 6 && td.contacts.total === db.prepare('SELECT COUNT(*) n FROM contacts').get().n
    && td.calls.total === db.prepare('SELECT COUNT(*) n FROM calls').get().n && td.calls.today === db.prepare("SELECT COUNT(*) n FROM calls WHERE substr(called_at,1,10) = '2026-11-03'").get().n
    && typeof td.pending_calls.callbacks_due === 'number' && Array.isArray(td.people) && td.people.every((p, i) => i === 0 || td.people[i - 1].confirmed >= p.confirmed));
  const nq = (await get('/api/calls/queue?limit=1000')).data;
  check('target-dashboard: pending_calls.never_called == default calling queue rows with no call', td.pending_calls.never_called === nq.rows.filter((r) => !r.calls_total).length, `${td.pending_calls.never_called} vs ${nq.rows.filter((r) => !r.calls_total).length}`);
  const tc = (await get(`/api/target-dashboard?scope=college:${globalThis.__callCollege}`)).data;
  check('target-dashboard without a target: projection explains why (no invented numbers)', tc.target === null && tc.projection.date === null && tc.projection.status === 'no_target' && tc.required_daily === null);
  check('target-dashboard bad scope -> 400', (await get('/api/target-dashboard?scope=planet:x')).status === 400);
  // leaderboard counts confirmed only
  const lb = (await get('/api/leaderboard?level=college&limit=500')).data.find((r) => r.id === 'c6');
  check('leaderboard enrolled = confirmed only', lb.enrolled === after2.enrolled);
});

await step('seed: contacts.json import', async () => {
  const { seedContacts } = await import('./seed.js');
  const cid = globalThis.__callCollege;
  const rows = [{ college_sno: Number(cid.slice(1)), role: 'TPO', name: 'Seeded TPO', phone: '+91 98765 43210', source_url: 'https://example.invalid/a', basis: 'verified' },
    { college_id: cid, role: 'admissions', phone: '9440012345', email: 'adm@example.invalid' }, { college_id: 'c99999', phone: '9440012346' }, { college_id: cid, phone: '123' }];
  const s1 = seedContacts(db, { log: quiet, rows });
  const s2 = seedContacts(db, { log: quiet, rows });
  check('seedContacts: dedupes against existing contacts, skips unknown college / bad phone', s1.insert === 1 && s1.skipped === 2, JSON.stringify(s1));
  check('seedContacts: re-run is idempotent', s2.insert === 0 && s2.update === 0, JSON.stringify(s2));
  const k = db.prepare("SELECT * FROM contacts WHERE college_id = ? AND phone = '+919876543210'").get(cid);
  check('seedContacts: never overwrites a user-edited contact', k.name === 'ST TPO' && k.status === 'working');
  const hasFiles = fs.existsSync(path.join(path.dirname(DEFAULT_DB_PATH), 'seed')) && fs.readdirSync(path.join(path.dirname(DEFAULT_DB_PATH), 'seed')).some((f) => f === 'contacts.json' || /^contacts_.+\.json$/i.test(f));
  check('seedContacts: reads data/seed/contacts.json + contacts_*.json only when present', seedContacts(db, { log: quiet }).file === hasFiles);
  // research-team shape: numeric college_id (S.No), extra fields, several numbers in one field, website, in-file duplicates
  const noSite = db.prepare("SELECT id, sno FROM colleges WHERE (website IS NULL OR website = '') AND id NOT IN (SELECT college_id FROM contacts) ORDER BY sno LIMIT 1").get();
  const rr = [
    { college_id: noSite.sno, college_name: 'x', role: 'tpo', name: 'R TPO', phone: '0866-2469679 / +91 7013293572', email: 'tpo@r.example', website: 'https://r.example/', source_url: 'https://r.example/tp', basis: 'verified', confidence: 'High', notes: 'as seen' },
    { college_id: `c${noSite.sno}`, role: 'principal', name: 'R Principal', phone: '(+91) 0866 – 2469679', email: null, basis: 'pending', confidence: 'Low' },
    { college_id: noSite.sno, role: 'office', name: null, phone: null, email: null, basis: 'verified' },
  ];
  const r1 = seedContacts(db, { log: quiet, rows: rr });
  const r2 = seedContacts(db, { log: quiet, rows: rr });
  const got = db.prepare('SELECT * FROM contacts WHERE college_id = ? ORDER BY id').all(noSite.id);
  check('seedContacts (research shape): one contact per valid number, S.No ids, row without phone/email skipped, in-file duplicate kept once',
    r1.insert === 2 && r1.skipped === 1 && r1.duplicate_in_files === 1 && got.length === 2 && got[0].phone === '+918662469679' && got[1].phone === '+917013293572' && got[0].email === 'tpo@r.example' && got[1].email === null && /Phone as listed/.test(got[0].notes), JSON.stringify(r1));
  check('seedContacts (research shape): re-run idempotent; website filled only because the college had none', r2.insert === 0 && r2.update === 0 && r1.websites_filled === 1 && r2.websites_filled === 0
    && db.prepare('SELECT website FROM colleges WHERE id = ?').get(noSite.id).website === 'https://r.example/');
  const s3 = seedReference(db, { log: quiet });
  check('reseeding colleges keeps a website filled from contacts files (no flip-flop)', s3.colleges.update === 0 && db.prepare('SELECT website FROM colleges WHERE id = ?').get(noSite.id).website === 'https://r.example/', JSON.stringify(s3.colleges));
});

// ---------------------------------------------------------------- district scope (districts=) on every scoped endpoint
const DEF7 = ['guntur', 'palnadu', 'bapatla', 'krishna', 'ntr', 'west-godavari', 'eluru'];
await step('districts filter', async () => {
  const D = DEF7.join(',');
  const inSel = (id) => DEF7.includes(id);
  const distOf = new Map(db.prepare('SELECT id, district_id FROM colleges').all().map((c) => [c.id, c.district_id]));
  const sqlConfirmed = (ids) => db.prepare(`SELECT COUNT(*) n FROM enrollments e JOIN colleges c ON c.id = e.college_id WHERE e.stage = 'confirmed' ${ids ? `AND c.district_id IN (${ids.map(() => '?').join(',')})` : ''}`).get(...(ids || [])).n;
  // every scoped endpoint: unknown id -> 400 with fields.districts; `all` = same as no filter
  const eps = ['/api/colleges', '/api/calls/queue', '/api/summary?scope=state', '/api/funnel?scope=state', '/api/target-dashboard?scope=state', '/api/leaderboard?level=district',
    '/api/attention', '/api/followups', '/api/exams', '/api/timeseries', '/api/people', '/api/branches', '/api/contacts', '/api/calls', '/api/plan'];
  const size = (d) => (Array.isArray(d) ? d.length : d.rows ? d.total : d.colleges ?? d.total ?? 0);
  for (const ep of eps) {
    const j = ep.includes('?') ? '&' : '?';
    const badR = await get(`${ep}${j}districts=guntur,nowhere`);
    const plain = await get(ep); const all = await get(`${ep}${j}districts=all`); const sel = await get(`${ep}${j}districts=${D}`);
    check(`districts on ${ep}: unknown id -> 400; all = no filter; selection <= all`, badR.status === 400 && /nowhere/.test(badR.data.fields?.districts || '') && plain.status === 200 && all.status === 200 && sel.status === 200
      && (ep === '/api/plan' || JSON.stringify(size(plain.data)) === JSON.stringify(size(all.data))) && size(sel.data) <= size(all.data), `${badR.status} ${size(plain.data)} ${size(all.data)} ${size(sel.data)}`);
  }
  const cols = (await get(`/api/colleges?districts=${D}`)).data;
  check('colleges?districts= returns only colleges in the selection, and all of them', cols.length > 0 && cols.every((c) => inSel(c.district_id)) && cols.length === [...distOf.values()].filter(inSel).length);
  const qd = (await get(`/api/calls/queue?districts=${D}&include_closed=1`)).data;
  check('calls/queue?districts= rows only in the selection', qd.rows.length > 0 && qd.rows.every((r) => inSel(r.district_id)) && qd.districts_filter.length === 7);
  for (const ep of ['/api/exams', '/api/branches', '/api/contacts', '/api/people']) {
    const rows = (await get(`${ep}?districts=${D}`)).data;
    check(`${ep}?districts= rows only in the selection`, rows.every((r) => inSel(r.district_id ?? distOf.get(r.college_id))));
  }
  const one = ['guntur'];
  const s1 = (await get('/api/summary?scope=state&districts=guntur')).data;
  const s7 = (await get(`/api/summary?scope=state&districts=${D}`)).data;
  const sAll = (await get('/api/summary?scope=state')).data;
  check('summary?districts=: colleges and confirmed enrollments counted only in the selection', s1.colleges === [...distOf.values()].filter((d) => d === 'guntur').length && s1.enrolled === sqlConfirmed(one)
    && s7.enrolled === sqlConfirmed(DEF7) && sAll.enrolled === sqlConfirmed(null) && s1.districts === 1 && s7.districts_filter.length === 7 && sAll.districts_filter === null, `${s1.enrolled} vs ${sqlConfirmed(one)}`);
  check('summary?districts=: a sum-of-children state target sums only the selected districts', s7.target_source !== 'sum_of_children' || s7.target === (await Promise.all(DEF7.map((d) => get(`/api/summary?scope=district:${d}`)))).reduce((a, r) => a + (r.data.target ?? 0), 0));
  const f7 = (await get(`/api/funnel?scope=state&districts=${D}`)).data;
  check('funnel?districts=: confirmed only in the selection', f7.confirmed === sqlConfirmed(DEF7));
  const td = (await get(`/api/target-dashboard?scope=state&districts=${D}`)).data;
  const td0 = (await get('/api/target-dashboard?scope=state')).data;
  const pg = (await get('/api/program')).data;
  check('target-dashboard?districts=: program block {target, deadline, selected_districts, is_default_selection} and confirmed only in the selection',
    td.program && td.program.target === pg.target && td.program.deadline === pg.deadline && td.program.is_default_selection === true && td.program.selected_districts.length === 7
    && td.confirmed === sqlConfirmed(DEF7) && td.program.confirmed === td.confirmed && td.target === pg.target && td.target_source === 'program' && !('program' in td0), JSON.stringify(td.program));
  const tdG = (await get('/api/target-dashboard?scope=state&districts=guntur')).data;
  const tdA = (await get('/api/target-dashboard?scope=state&districts=all')).data;
  check('target-dashboard: a partial selection is not the default; all = every district', tdG.program.is_default_selection === false && tdA.program.all_districts === true && tdA.program.selected_districts.length === pg.districts.length && tdA.confirmed === sqlConfirmed(null));
  const lb = (await get(`/api/leaderboard?level=district&scope=state&limit=100&districts=${D}`)).data;
  check('leaderboard level=district?districts= lists only selected districts', lb.length === 7 && lb.every((r) => inSel(r.id)));
  const ts = (await get('/api/timeseries?scope=state&days=730&districts=guntur')).data;
  check('timeseries?districts=: confirmed only in the selection', ts[ts.length - 1].cum_enrolled === db.prepare("SELECT COUNT(*) n FROM enrollments e JOIN colleges c ON c.id = e.college_id WHERE e.stage = 'confirmed' AND c.district_id = 'guntur' AND COALESCE(e.confirmed_on, e.enrolled_on) >= ? AND COALESCE(e.confirmed_on, e.enrolled_on) <= ?").get(ts[0].date, ts[ts.length - 1].date).n);
  const att = (await get(`/api/attention?districts=${D}`)).data;
  check('attention?districts= college items only in the selection', att.filter((a) => a.type === 'college').every((a) => inSel(a.district_id)));
  const fu = (await get(`/api/followups?districts=${D}`)).data;
  check('followups?districts= only in the selection', fu.every((f) => inSel(f.district_id)));
});

const STAGES6 = ['lead', 'interested', 'registered', 'applied', 'confirmed', 'dropped'];
await step('target planner: /api/plan', async () => {
  const p = (await get('/api/plan')).data;
  check('/api/plan shape', p.imported === true && p.research_version === 'v2 2026-11-07' && /colleges 2\.md$/.test(p.source_report) && p.defaults && Array.isArray(p.defaults.rates.final_year) && Array.isArray(p.colleges) && Array.isArray(p.excluded) && p.totals_research && p.totals_actual && p.program.target === (await get('/api/program')).data.target);
  const T = p.totals_research;
  check('/api/plan totals_research (no filter) = research totals 377 / 655 / 1,143, 299 ambassadors, 64 college leads', T.min === 377 && T.avg === 655 && T.max === 1143 && T.ambassadors === 299 && T.college_leads === 64 && T.targeted === 84, JSON.stringify(T));
  const keys = ['college_id', 'name', 'short_name', 'district_id', 'city', 'website', 'op_status', 'status_final', 'targeted', 'hold_reason', 'it_branches', 'it_branch_count', 'total_students', 'fy_pool', 'it_fy', 'it_3rd', 'it_2nd',
    'access_x', 'type', 'priority_score', 'rank', 'p_level', 'research_target', 'rag_400', 'mou', 'ambassadors_research', 'college_leads_research', 'lead_assignment', 'lead_offer', 'placement_tier', 'verify_flag', 'exam_4_1_end', 'contact', 'actual', 'branches'];
  const missingKeys = p.colleges.flatMap((c) => keys.filter((k) => !(k in c)).map((k) => `${c.college_id}.${k}`));
  check('/api/plan every PlanCollege has the contract keys', p.colleges.length === 122 && missingKeys.length === 0, missingKeys.slice(0, 5).join(' '));
  // provenance: every {value, basis} carries a basis; unavailable <=> null; never a bare value
  const BASES = new Set(['verified', 'estimated', 'unavailable']);
  const bad = [];
  const walk = (o, at) => {
    if (!o || typeof o !== 'object') return;
    if (Array.isArray(o)) { o.forEach((x, i) => walk(x, `${at}[${i}]`)); return; }
    if ('value' in o || 'basis' in o) {
      if (!BASES.has(o.basis)) bad.push(`${at}: basis ${o.basis}`);
      else if ((o.basis === 'unavailable') !== (o.value == null)) bad.push(`${at}: value ${o.value} with basis ${o.basis}`);
    }
    for (const [k, v] of Object.entries(o)) if (k !== 'actual' && k !== 'branches') walk(v, `${at}.${k}`); // branches are checked below
  };
  for (const c of p.colleges) {
    walk(c, c.college_id);
    for (const k of ['total_students', 'fy_pool', 'it_fy', 'it_3rd', 'it_2nd']) if (!c[k] || !('basis' in c[k])) bad.push(`${c.college_id}.${k}: no {value, basis}`);
    for (const b of c.branches) {
      if (!BASES.has(b.basis) || (b.basis === 'unavailable') !== (b.intake_2023_24 == null)) bad.push(`${c.college_id} branch ${b.name}: intake_2023_24 ${b.intake_2023_24} basis ${b.basis}`);
      if (!BASES.has(b.intake_latest_basis) || (b.intake_latest_basis === 'unavailable') !== (b.intake_latest == null)) bad.push(`${c.college_id} branch ${b.name}: intake_latest basis`);
    }
    if (c.targeted && (c.it_fy.value == null || (!c.it_fy.source && !c.it_fy.note))) bad.push(`${c.college_id}: targeted without a sourced IT final-year pool`);
    if (!c.targeted && !c.hold_reason) bad.push(`${c.college_id}: not targeted without hold_reason`);
  }
  check('/api/plan provenance: no value without a basis (verified / estimated / unavailable; unavailable = null)', bad.length === 0, bad.slice(0, 6).join(' | '));
  const a = p.colleges.find((c) => c.research_id === 'new-ANRG');
  check('/api/plan: ANR CET listed, not targeted, hold reason "no final-year batch until 2028-29"', a && a.targeted === false && /2028-29/.test(a.hold_reason) && a.district_id === 'krishna');
  const c1 = p.colleges[0];
  check('/api/plan actual{} block from people / enrollments / calls', c1.actual && ['college_leads', 'ambassador_leads', 'ambassadors', 'active_ambassadors', 'confirmed', 'calls', 'last_call_at', 'people'].every((k) => k in c1.actual)
    && STAGES6.every((k) => k in c1.actual.leads_by_stage) && p.totals_actual.confirmed === p.colleges.reduce((s, c) => s + c.actual.confirmed, 0));
  const D = DEF7.join(',');
  const p7 = (await get(`/api/plan?districts=${D}`)).data;
  const sum = (k) => p7.colleges.filter((c) => c.targeted).reduce((s, c) => s + (c.research_target[k] || 0), 0);
  check('/api/plan?districts= filters by present-day district and recomputes totals', p7.colleges.every((c) => DEF7.includes(c.district_id)) && p7.colleges.length < p.colleges.length + 1
    && p7.totals_research.min === sum('min') && p7.totals_research.avg === sum('avg') && p7.totals_research.max === sum('max') && p7.excluded.every((e) => DEF7.includes(e.district_id)), JSON.stringify(p7.totals_research));
  const pe = (await get('/api/plan?districts=guntur,xx'));
  check('/api/plan?districts=unknown -> 400', pe.status === 400 && !!pe.data.fields?.districts);
});

await step('clear demo', async () => {
  const n = clearDemo(db);
  const m = (await get('/api/meta')).data;
  check('--clear-demo removes demo rows (meta.demo false)', m.demo === false && n.people > 0);
  // simulate a fresh team: deactivate the people this test created (the API write also refreshes the server's cache,
  // which clearDemo bypassed by writing on the same connection)
  for (const p of (await get('/api/people')).data) await api('PATCH', `/api/people/${p.id}`, { status: 'inactive' }, W);
  await api('POST', '/api/courses', { name: 'Selftest cache bump' }, W);
  const att = (await get('/api/attention')).data;
  const g = att.find((x) => x.type === 'group' && x.id === 'no_college_leads');
  const ga = att.find((x) => x.type === 'group' && x.id === 'no_ambassadors');
  check('attention groups ambassador gaps into one item while no ambassadors exist', ga && ga.count > 0 && ga.branches >= ga.count && ga.href === '#/colleges?amb=gap&targeted=1' && !att.some((x) => x.reasons.some((r) => /without an active ambassador/.test(r))), JSON.stringify(ga));
  check('attention groups "no college lead" into one item while no leads exist', g && g.count > 0 && g.href === '#/colleges?team=no_lead&targeted=1' && g.severity === 'low' && !att.some((x) => x.reasons.includes('No college lead appointed')), JSON.stringify(g));
});

// ================================================================================================================
// v4 scenario tests (CONTRACT.md "v4"): rules R1–R15. Every record is created here (test colleges in a district chosen
// at run time), so the checks hold whatever the live DB copy contains.
// ================================================================================================================
async function apiH(method, p, body, headers = {}) {
  const h = { ...headers };
  if (body !== undefined) h['Content-Type'] = 'application/json';
  const r = await fetch(base + p, { method, headers: h, body: body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)) });
  const txt = await r.text();
  let data = null; try { data = txt ? JSON.parse(txt) : null; } catch { data = txt; }
  return { status: r.status, data, headers: r.headers };
}
const V4 = {};
const T0 = '2026-11-03';
// a district with no district/city targets and no enrollments, so district numbers are fully determined by this scenario
V4.district = db.prepare(`SELECT d.id FROM districts d WHERE NOT EXISTS (SELECT 1 FROM targets t WHERE t.scope_type = 'district' AND t.scope_id = d.id)
  AND NOT EXISTS (SELECT 1 FROM targets t JOIN cities ci ON ci.id = t.scope_id WHERE t.scope_type = 'city' AND ci.district_id = d.id)
  AND NOT EXISTS (SELECT 1 FROM enrollments e JOIN colleges c ON c.id = e.college_id WHERE c.district_id = d.id)
  AND NOT EXISTS (SELECT 1 FROM targets t JOIN colleges c ON c.id = t.scope_id WHERE t.scope_type = 'college' AND c.district_id = d.id)
  ORDER BY d.id LIMIT 1`).get()?.id;
const mkCollege = async (name) => (await api('POST', '/api/colleges', { name, district_id: V4.district, city_name: 'V4 Selftest Town', op_status: 'operational' }, W));
const person = async (body, h = W) => api('POST', '/api/people', body, h);

await step('v4 colleges: create, duplicates, read-only sno, phone/email/url validation, verification', async () => {
  check('v4: a clean district exists for the scenario', !!V4.district, 'no district without targets/enrollments');
  const a = await mkCollege('V4 Selftest College A');
  const b = await mkCollege('V4 Selftest College B');
  V4.A = a.data?.id; V4.B = b.data?.id;
  check('POST /api/colleges without sno -> 201, id c<next sno>, district + town set', a.status === 201 && /^c\d+$/.test(V4.A) && a.data.sno === Number(V4.A.slice(1)) && a.data.city_id === `${V4.district}--v4-selftest-town`, JSON.stringify(a.data).slice(0, 200));
  const dup = await mkCollege('v4 selftest  college a');
  check('same college name (case/space-insensitive) in the same district -> 409 duplicate_college', dup.status === 409 && dup.data.code === 'duplicate_college' && dup.data.existing_id === V4.A);
  const noCity = await api('POST', '/api/colleges', { name: 'V4 No Town', district_id: V4.district }, W);
  check('POST /api/colleges without a town -> 400 fields.city_id', noCity.status === 400 && noCity.data.fields?.city_id);
  const sno = await api('PATCH', `/api/colleges/${V4.A}`, { sno: 9999 }, W);
  check('PATCH college sno -> 400 (read-only, BE-07)', sno.status === 400 && sno.data.fields?.sno);
  const ph = await api('PATCH', `/api/colleges/${V4.A}`, { phone: 'call me maybe' }, W);
  const em = await api('PATCH', `/api/colleges/${V4.A}`, { email: 'not-an-email' }, W);
  const ph2 = await api('PATCH', `/api/colleges/${V4.A}`, { phone: '0863 2344700 / 98765 43210' }, W);
  check('college phone/email validated (several numbers allowed)', ph.status === 400 && em.status === 400 && ph2.status === 200 && ph2.data.phone === '0863 2344700 / 98765 43210');
  const js1 = await api('PATCH', `/api/colleges/${V4.A}`, { op_status_source: 'javascript:alert(document.cookie)' }, W);
  const js2 = await api('PATCH', `/api/colleges/${V4.A}`, { website: ' JaVa\tScRiPt:alert(1)' }, W);
  const js3 = await api('PATCH', `/api/colleges/${V4.A}`, { geo_source: 'data:text/html,<script>alert(1)</script>' }, W);
  const okSrc = await api('PATCH', `/api/colleges/${V4.A}`, { geo_source: 'OSM https://www.openstreetmap.org/way/1 (campus)', website: 'https://example.edu' }, W);
  check('javascript:/data: links refused on every link field; http(s) and plain notes accepted', js1.status === 400 && js1.data.fields?.op_status_source && js2.status === 400 && js3.status === 400 && okSrc.status === 200);
  const bl = await api('PATCH', `/api/colleges/${V4.A}`, { name: '    ' }, W);
  check('whitespace-only college name -> 400 Required', bl.status === 400 && bl.data.fields?.name === 'Required');
  const boolBad = await api('PATCH', `/api/colleges/${V4.A}`, { targeted: 'maybe' }, W);
  check('bool "maybe" -> 400 (strict booleans)', boolBad.status === 400 && boolBad.data.fields?.targeted);
  // verification (R13)
  const v1 = await api('PATCH', `/api/colleges/${V4.A}`, { website: 'https://a.example.edu', sources: { website: 'https://aicte.example/list' } }, W);
  const d1 = (await get(`/api/colleges/${V4.A}`)).data.college;
  check('PATCH with sources.{field} stamps verified_fields (source, date, who) and field_status verified', v1.status === 200 && d1.verified_fields.website?.source === 'https://aicte.example/list' && d1.verified_fields.website.verified_on === T0 && d1.verified_fields.website.verified_by === USER && d1.field_status.website === 'verified');
  await api('PATCH', `/api/colleges/${V4.A}`, { website: 'https://b.example.edu' }, W);
  const d2 = (await get(`/api/colleges/${V4.A}`)).data.college;
  check('changing a verified field without a source makes it unverified', !d2.verified_fields.website && d2.field_status.website === 'unverified' && d2.field_status.email === 'missing');
  const ver = await api('POST', `/api/colleges/${V4.A}/verify`, { fields: ['name', 'website'], source: 'https://jntuk.example/affiliated', note: 'checked list' }, W);
  const verOn = await api('POST', `/api/colleges/${V4.A}/verify`, { fields: ['district_id'], source: 'https://x.example', verified_on: '2026-10-15' }, W);
  const verFut = await api('POST', `/api/colleges/${V4.A}/verify`, { fields: ['district_id'], source: 'https://x.example', verified_on: '2026-11-04' }, W);
  const vAudit = db.prepare("SELECT after FROM audit_log WHERE entity = 'college' AND entity_id = ? ORDER BY id DESC LIMIT 1").get(V4.A);
  check('verify accepts a past verified_on, refuses a future one; the audit row names the college', verOn.data.verified_fields?.district_id?.verified_on === '2026-10-15' && verFut.status === 400 && JSON.parse(vAudit.after).name === 'V4 Selftest College A');
  const verBad = await api('POST', `/api/colleges/${V4.A}/verify`, { fields: ['name'] }, W);
  const verJs = await api('POST', `/api/colleges/${V4.A}/verify`, { fields: ['name'], source: 'javascript:alert(1)' }, W);
  check('POST /colleges/:id/verify stamps fields; source required; javascript: refused', ver.status === 200 && ver.data.verified_fields.name?.note === 'checked list' && ver.data.field_status.name === 'verified' && verBad.status === 400 && verJs.status === 400);
  const list = (await get(`/api/colleges?districts=${V4.district}&verified=partly`)).data;
  check('GET /api/colleges?verified=partly + data_status on rows', list.some((c) => c.id === V4.A) && list.every((c) => c.data_status === 'partly'));
});

await step('v4 people: R1/R2 relationships, R3 assignment status', async () => {
  const br = await api('POST', '/api/branches', { college_id: V4.A, code: 'CSE', name: 'Computer Science', category: 'it_core', intake_per_year: 120 }, W);
  V4.brA = br.data?.id;
  check('typed intake without basis/source is "estimated", not auto-verified (BE-19)', br.status === 201 && br.data.intake_basis === 'estimated');
  const la = await person({ college_id: V4.A, role: 'college_lead', full_name: 'V4 Lead A', phone: '97000 40001' });
  V4.LA = la.data?.id;
  check('create College Lead -> 201, assignment_status null, phone normalised', la.status === 201 && la.data.assignment_status === null && la.data.phone === '+919700040001' && la.data.links?.tel === 'tel:+919700040001' && la.data.links.whatsapp === 'https://wa.me/919700040001');
  const la2 = await person({ college_id: V4.A, role: 'college_lead', full_name: 'V4 Second Lead' });
  check('second active College Lead at the same college -> 409 lead_exists with existing_id', la2.status === 409 && la2.data.code === 'lead_exists' && la2.data.existing_id === V4.LA);
  const lb = await person({ college_id: V4.B, role: 'college_lead', full_name: 'V4 Lead B' });
  V4.LB = lb.data?.id;
  const a1 = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Amb A1', reports_to: V4.LA, branch_ids: [V4.brA] });
  V4.A1 = a1.data?.id;
  check('ambassador -> College Lead of the same college: 201 assigned', a1.status === 201 && a1.data.assignment_status === 'assigned' && a1.data.lead?.id === V4.LA);
  const x1 = await person({ college_id: V4.B, role: 'ambassador', full_name: 'V4 Cross', reports_to: V4.LA });
  check('ambassador -> lead of ANOTHER college: 400 fields.reports_to', x1.status === 400 && /another college/.test(x1.data.fields?.reports_to || ''));
  const x2 = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Amb under amb', reports_to: V4.A1 });
  check('ambassador -> ambassador: 400', x2.status === 400 && x2.data.fields?.reports_to);
  const al = await person({ college_id: V4.A, role: 'ambassador_lead', full_name: 'V4 AmbLead A', reports_to: V4.LA });
  V4.AL = al.data?.id;
  const a2 = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Amb A2', reports_to: V4.AL });
  V4.A2 = a2.data?.id;
  const al2 = await person({ college_id: V4.A, role: 'ambassador_lead', full_name: 'V4 AmbLead under AmbLead', reports_to: V4.AL });
  check('ambassador_lead -> College Lead ok; ambassador -> ambassador_lead ok; ambassador_lead -> ambassador_lead 400', al.status === 201 && a2.status === 201 && al2.status === 400);
  const lr = await api('PATCH', `/api/people/${V4.LA}`, { reports_to: V4.A1 }, W);
  check('College Lead with a reports_to (would be a loop) -> 400', lr.status === 400 && lr.data.fields?.reports_to);
  const self = await api('PATCH', `/api/people/${V4.A1}`, { reports_to: V4.A1 }, W);
  check('self-reporting -> 400', self.status === 400);
  const dz = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Designation D', designation: '  3rd-year CSE student ', responsibility: 'Runs the CSE WhatsApp group' });
  const dzLong = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Designation Long', designation: 'x'.repeat(121) });
  const a0d = auditCount();
  const dzp = await api('PATCH', `/api/people/${dz.data?.id}`, { responsibility: 'Seminar logistics', designation: '   ' }, W);
  const dzAudit = JSON.parse(db.prepare("SELECT after FROM audit_log WHERE entity = 'person' AND entity_id = ? ORDER BY id DESC LIMIT 1").get(String(dz.data?.id)).after);
  const dzList = (await get(`/api/people?college_id=${V4.A}`)).data.find((p) => p.id === dz.data?.id);
  const dzDet = (await get(`/api/people/${dz.data?.id}`)).data.person;
  check('designation/responsibility: trimmed, max 120 / 500, blank clears, returned in list + detail, audited', dz.status === 201 && dz.data.designation === '3rd-year CSE student' && dzLong.status === 400 && dzLong.data.fields?.designation
    && dzp.status === 200 && dzp.data.designation === null && dzp.data.responsibility === 'Seminar logistics' && auditCount() === a0d + 1 && dzAudit.responsibility === 'Seminar logistics'
    && dzList?.responsibility === 'Seminar logistics' && dzDet.responsibility === 'Seminar logistics', JSON.stringify([dz.status, dzLong.status, dzp.data?.designation]));
  await api('PATCH', `/api/people/${dz.data?.id}`, { status: 'inactive' }, W);
  const u = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Unassigned U' });
  V4.U = u.data?.id;
  const ua = (await get(`/api/people?college_id=${V4.A}&assignment=unassigned`)).data;
  check('GET /api/people?assignment=unassigned lists the ambassador without a lead (R3)', Array.isArray(ua) && ua.some((p) => p.id === V4.U && p.assignment_issue === 'no_lead') && ua.every((p) => p.assignment_status === 'unassigned'));
  const pg = (await get(`/api/people?college_id=${V4.A}&page=1&page_size=2&sort=-name`)).data;
  check('GET /api/people paging envelope {items,total,page,page_size,counts} + sort', pg.items?.length === 2 && pg.total >= 5 && pg.page === 1 && pg.page_size === 2 && pg.counts.college_lead === 1
    && pg.items[0].full_name.localeCompare(pg.items[1].full_name) >= 0);
  const plain = (await get(`/api/people?college_id=${V4.A}`)).data;
  check('GET /api/people without page stays a plain array (v1 shape) with v4 fields', Array.isArray(plain) && plain.every((p) => 'assignment_status' in p && 'college' in p && 'target_summary' in p && 'actual_combined' in p));
  const cr = (await get(`/api/colleges?districts=${V4.district}&team=has_unassigned`)).data;
  const rowA = cr.find((c) => c.id === V4.A);
  check('GET /api/colleges?team=has_unassigned: lead{}, ambassador_count, unassigned_count', !!rowA && rowA.lead?.id === V4.LA && rowA.ambassador_count === 4 && rowA.unassigned_count === 1);
  const nl = (await get(`/api/colleges?districts=${V4.district}&team=no_lead`)).data;
  check('GET /api/colleges?team=no_lead excludes colleges with a lead', !nl.some((c) => c.id === V4.A || c.id === V4.B));
  const hl = (await get(`/api/colleges?districts=${V4.district}&team=has_lead`)).data;
  check('GET /api/colleges?team=has_lead = exactly the complement of no_lead (Reports "colleges with a lead" link)', hl.length > 0 && hl.every((c) => !!c.lead) && hl.some((c) => c.id === V4.A)
    && hl.length + nl.length === (await get(`/api/colleges?districts=${V4.district}`)).data.length);
  const ints = (await get('/api/quality')).data.integrity;
  check('integrity counters after valid writes: no cross-college / bad-role / multi-lead / duplicate links', ints && ints.reports_to_other_college === 0 && ints.reports_to_bad_role === 0 && ints.multi_college_leads === 0 && ints.person_branch_wrong_college === 0, JSON.stringify(ints));
});

await step('v4 duplicates, whitespace, dates, idempotency (R6/R7)', async () => {
  const p1 = await person({ college_id: V4.B, role: 'ambassador', full_name: 'V4 Phone One', phone: '97000 41210', email: 'Dup.Person@Example.com' });
  const p2 = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Phone Two', phone: '+91-97000-41210' });
  const p3 = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Phone Three', phone: '0 97000 41210' });
  const p4 = await person({ college_id: V4.A, role: 'ambassador', full_name: 'V4 Email Two', email: 'dup.person@example.com' });
  check('same phone in other formats anywhere -> 409 duplicate_person (existing id/name/college)', p1.status === 201 && p1.data.phone === '+919700041210' && p2.status === 409 && p2.data.code === 'duplicate_person' && p2.data.existing_id === p1.data.id && p2.data.existing_college_id === V4.B && p3.status === 409, JSON.stringify([p1, p2.status, p2.data, p3.status]).slice(0, 500));
  check('same email in another case -> 409; stored lower-case', p1.data.email === 'dup.person@example.com' && p4.status === 409 && p4.data.fields?.email);
  const bad = await Promise.all(['12345', '0123456789', '12345678901234', '+1 202 555 0100'].map((ph, i) => person({ college_id: V4.B, role: 'ambassador', full_name: `V4 Bad Phone ${i}`, phone: ph })));
  check('invalid people phones -> 400 with a 10-digit hint', bad.every((r) => r.status === 400 && /10-digit/.test(r.data.fields?.phone || '')));
  const sameName = await person({ college_id: V4.B, role: 'ambassador', full_name: '  v4 phone   ONE ' });
  const sameNameOk = await person({ college_id: V4.B, role: 'ambassador', full_name: 'V4 Phone One', allow_same_name: true });
  check('same name at the same college -> 409 possible_duplicate_name; allow_same_name overrides', sameName.status === 409 && sameName.data.code === 'possible_duplicate_name' && sameNameOk.status === 201, JSON.stringify([sameName, sameNameOk]).slice(0, 400));
  const ws = await person({ college_id: V4.B, role: 'ambassador', full_name: '    ' });
  const ws2 = await person({ college_id: '   ', role: 'ambassador', full_name: 'V4 X' });
  check('whitespace-only required fields -> 400 Required (never an empty name)', ws.status === 400 && ws.data.fields?.full_name === 'Required' && ws2.status === 400 && ws2.data.fields?.college_id === 'Required');
  const d1 = await person({ college_id: V4.B, role: 'ambassador', full_name: 'V4 Date', joined_on: '2026-02-31' });
  const d2 = await person({ college_id: V4.B, role: 'ambassador', full_name: 'V4 Date2', joined_on: '2099-01-01' });
  const d3 = await api('POST', '/api/followups', { scope_type: 'college', scope_id: V4.B, title: 'x', due_date: '2026-13-01' }, W);
  const d4 = await api('POST', '/api/enrollments', { college_id: V4.B, enrolled_on: '2026-02-30', stage: 'lead' }, W);
  check('impossible dates (2026-02-31, month 13, Feb 30) and future joined_on -> 400', d1.status === 400 && d1.data.fields?.joined_on && d2.status === 400 && d3.status === 400 && d4.status === 400);
  // idempotency: 3 identical concurrent submits with one key -> one row, same response
  const key = `selftest-${Date.now()}`;
  const body = { college_id: V4.B, role: 'ambassador', full_name: 'V4 Double Click', phone: '97000 40099' };
  const rs = await Promise.all([1, 2, 3].map(() => apiH('POST', '/api/people', body, { ...W, 'Idempotency-Key': key })));
  const n = db.prepare("SELECT COUNT(*) n FROM people WHERE full_name = 'V4 Double Click'").get().n;
  check('3 concurrent POSTs with the same Idempotency-Key -> 1 row, 3× the same 201 body, replays flagged', n === 1 && rs.every((r) => r.status === 201 && r.data.id === rs[0].data.id) && rs.filter((r) => r.headers.get('idempotent-replay') === 'true').length === 2);
  const reuse = await apiH('PATCH', `/api/people/${rs[0].data.id}`, { notes: 'x' }, { ...W, 'Idempotency-Key': key });
  // v4.1 (F1): a reused key with a different request is now 422 (was 409), see CONTRACT v4.1
  check('same Idempotency-Key on another method/path -> 422 idempotency_key_reused', reuse.status === 422 && reuse.data.code === 'idempotency_key_reused');
  const body2 = { college_id: V4.B, role: 'ambassador', full_name: 'V4 No Key', phone: '97000 40098' };
  const rs2 = await Promise.all([1, 2, 3].map(() => api('POST', '/api/people', body2, W)));
  check('3 concurrent POSTs without a key -> 1 created, 2 refused as duplicates (409)', rs2.filter((r) => r.status === 201).length === 1 && rs2.filter((r) => r.status === 409 && r.data.code === 'duplicate_person').length === 2);
  const reserved = await api('POST', '/api/courses', { name: 'x' }, { 'X-User': 'Seed' });
  const reserved2 = await api('POST', '/api/courses', { name: 'x' }, { 'X-User': 'import_research' });
  check('reserved actor names (seed, import_research…) -> 400', reserved.status === 400 && reserved2.status === 400);
});

await step('v4 move, deactivate, replace lead, bulk assign (R4/R5)', async () => {
  const mv = await api('POST', `/api/people/${V4.A1}/move`, { college_id: V4.B }, W);
  check('move: reports_to cleared, old-college branch links removed, both reported', mv.status === 200 && mv.data.person.college_id === V4.B && mv.data.person.reports_to === null
    && mv.data.side_effects.cleared_reports_to === true && mv.data.side_effects.removed_branches.includes(V4.brA) && mv.data.person.branch_ids.length === 0);
  const mv2 = await api('POST', `/api/people/${V4.A1}/move`, { college_id: V4.A, reports_to: V4.LA }, W);
  check('move back with a valid lead of the new college -> assigned', mv2.status === 200 && mv2.data.person.reports_to === V4.LA && mv2.data.person.assignment_status === 'assigned');
  const mvBad = await api('POST', `/api/people/${V4.A1}/move`, { college_id: V4.B, reports_to: V4.LA }, W);
  check('move with a lead of the OLD college -> 400', mvBad.status === 400 && mvBad.data.fields?.reports_to);
  const a0 = auditCount();
  const de = await api('PATCH', `/api/people/${V4.AL}`, { status: 'inactive' }, W);
  const a2 = (await get(`/api/people/${V4.A2}`)).data.person;
  check('deactivating a lead unassigns its reports in the same write (side_effects.unassigned, audited)', de.status === 200 && de.data.side_effects.unassigned.includes(V4.A2) && a2.reports_to === null && a2.assignment_status === 'unassigned' && auditCount() >= a0 + 2);
  check('PATCH person keeps the v1 row fields at top level (backward compatible) + person + side_effects', de.data.id === V4.AL && de.data.status === 'inactive' && de.data.person?.id === V4.AL);
  const re = await api('PATCH', `/api/people/${V4.AL}`, { status: 'active' }, W);
  check('reactivating works (no duplicate)', re.status === 200 && re.data.status === 'active');
  // replace lead: A1 (ambassador) becomes College Lead; LA becomes an Ambassador Lead under A1; LA's reports move to A1
  const before = db.prepare('SELECT id FROM people WHERE reports_to = ? AND id <> ?').all(V4.LA, V4.A1).map((r) => r.id);
  const rl = await api('POST', `/api/people/${V4.LA}/replace-lead`, { new_lead_id: V4.A1, old_lead_becomes: 'ambassador_lead' }, W);
  const pA = (await get(`/api/people?college_id=${V4.A}`)).data;
  const by = Object.fromEntries(pA.map((p) => [p.id, p]));
  check('replace-lead: new lead is the only College Lead, old lead reports to them, reports reassigned', rl.status === 200 && by[V4.A1].role === 'college_lead' && by[V4.LA].role === 'ambassador_lead' && by[V4.LA].reports_to === V4.A1
    && before.every((id) => rl.data.side_effects.reassigned.includes(id) && by[id].reports_to === V4.A1) && pA.filter((p) => p.role === 'college_lead' && p.status !== 'inactive').length === 1, JSON.stringify(rl.data.side_effects));
  const rlBad = await api('POST', `/api/people/${V4.LA}/replace-lead`, { new_lead_id: V4.LB, old_lead_becomes: 'inactive' }, W);
  check('replace-lead with a person of another college / a non-lead -> 400', rlBad.status === 400);
  const ba = await api('POST', '/api/people/bulk-assign', { person_ids: [V4.U, V4.A2], reports_to: V4.LA }, W);
  check('bulk-assign to an Ambassador Lead of the same college -> updated', ba.status === 200 && ba.data.updated.length === 2);
  const baBad = await api('POST', '/api/people/bulk-assign', { person_ids: [V4.U, V4.LB], reports_to: V4.A1 }, W);
  check('bulk-assign is all-or-nothing (a College Lead / other college in the list -> 400, nothing changed)', baBad.status === 400 && db.prepare('SELECT reports_to FROM people WHERE id = ?').get(V4.U).reports_to === V4.LA);
  const ints = (await get('/api/quality')).data.integrity;
  check('integrity after move / deactivate / replace: all relationship counters 0', ints.reports_to_other_college === 0 && ints.reports_to_bad_role === 0 && ints.reports_to_inactive === 0 && ints.multi_college_leads === 0 && ints.person_branch_wrong_college === 0, JSON.stringify(ints));
});

await step('v4 enrollments (R7/R8): cross-college credit, dates, contacts, duplicates', async () => {
  const cc = await api('POST', '/api/enrollments', { college_id: V4.B, person_id: V4.A2, student_name: 'X', stage: 'lead' }, W);
  check('enrollment credited to a person of another college -> 400 fields.person_id', cc.status === 400 && /another college/.test(cc.data.fields?.person_id || ''));
  const fut = await api('POST', '/api/enrollments', { college_id: V4.A, enrolled_on: '2026-11-04', stage: 'lead' }, W);
  const ord = await api('POST', '/api/enrollments', { college_id: V4.A, enrolled_on: '2026-11-02', confirmed_on: '2026-11-01', stage: 'confirmed' }, W);
  check('future date (tomorrow) and a stage date before the lead date -> 400', fut.status === 400 && ord.status === 400 && ord.data.fields?.confirmed_on);
  const junk = await api('POST', '/api/enrollments', { college_id: V4.A, student_contact: '+91 90000000undefined', stage: 'lead' }, W);
  const land = await api('POST', '/api/enrollments', { college_id: V4.A, student_contact: '040 2344 7000', stage: 'lead' }, W);
  check('student_contact must be a mobile or an email (junk / landline -> 400)', junk.status === 400 && land.status === 400, JSON.stringify([junk, land]).slice(0, 400));
  const n1 = await api('POST', '/api/enrollments', { college_id: V4.A, student_name: 'Same Student', enrolled_on: '2026-11-02', stage: 'lead' }, W);
  const n2 = await api('POST', '/api/enrollments', { college_id: V4.A, student_name: ' same student ', enrolled_on: '2026-11-02', stage: 'lead' }, W);
  const n3 = await api('POST', '/api/enrollments', { college_id: V4.A, student_name: 'Same Student', enrolled_on: '2026-11-02', stage: 'lead', force: true }, W);
  check('no-contact record with the same name + college + date -> 409 possible_duplicate; force:true accepts', n1.status === 201 && n2.status === 409 && n2.data.code === 'possible_duplicate' && n2.data.existing_id === n1.data.id && n3.status === 201);
});

await step('v4 targets (R10/R11): min/max, periods, canonical ids, person rules', async () => {
  const t = (body) => api('PUT', '/api/targets', body, W);
  const mn = await t({ scope_type: 'person', scope_id: String(V4.A1), min: 6, target: 5 });
  const mx = await t({ scope_type: 'person', scope_id: String(V4.A1), target: 5, max: 4 });
  check('min > target and max < target -> 400', mn.status === 400 && mn.data.fields?.min && mx.status === 400 && mx.data.fields?.max);
  const p = await t({ scope_type: 'person', scope_id: `0${V4.A1}`, min: 3, target: 5, max: 15 });
  check('PUT /api/targets programme row: min/target/max saved, "0<id>" stored canonically', p.status === 200 && p.data.scope_id === String(V4.A1) && p.data.min === 3 && p.data.max === 15 && p.data.period === 'programme' && p.data.period_key === 'programme');
  const mo = await t({ scope_type: 'person', scope_id: String(V4.A1), period: 'month:2026-11', target: 2 });
  const wk = await t({ scope_type: 'person', scope_id: String(V4.A1), period: 'week:2026-11-02', target: 1 });
  const wkBad = await t({ scope_type: 'person', scope_id: String(V4.A1), period: 'week:2026-11-03', target: 1 });
  const moAlt = await api('POST', '/api/targets', { scope_type: 'person', scope_id: String(V4.A1), period: 'month', period_start: '2026-11-01', target: 3 }, W);
  check('month and week targets coexist with the programme one; week must start on a Monday', mo.status === 200 && mo.data.period === 'month' && mo.data.period_start === '2026-11-01' && wk.status === 200 && wk.data.period_start === '2026-11-02'
    && wkBad.status === 400 && moAlt.data?.id === mo.data.id && moAlt.data.target === 3);
  const rows = (await get(`/api/targets?scope=person:${V4.A1}`)).data;
  const rowsW = (await get(`/api/targets?scope=person:${V4.A1}&period=week:2026-11-02`)).data;
  check('GET /api/targets?scope= lists all periods (period_key); &period= filters', rows.length === 3 && rows.map((r) => r.period_key).sort().join() === 'month:2026-11,programme,week:2026-11-02' && rowsW.length === 1);
  const crs = db.prepare('SELECT id FROM courses ORDER BY id LIMIT 1').get();
  if (crs) { const pc = await t({ scope_type: 'person', scope_id: String(V4.A1), target: 2, course_id: crs.id }); check('person target with a course -> 400 (all courses only)', pc.status === 400 && pc.data.fields?.course_id); }
  const inact = await t({ scope_type: 'person', scope_id: String(V4.AL), target: 2 });
  check('target for an Ambassador Lead is accepted', inact.status === 200);
  const st = await t({ scope_type: 'state', target: 1 });
  check('PUT state programme target without confirm_programme -> 409 (the 400 goal is protected, R11)', st.status === 409 && st.data.code === 'programme_target_protected');
  const del = await api('DELETE', `/api/targets/${db.prepare("SELECT id FROM targets WHERE scope_type = 'state' AND period = 'programme' AND course_id IS NULL").get()?.id ?? 0}`, undefined, W);
  check('DELETE of the programme target without ?confirm_programme=1 -> 409 (or 404 when none exists)', del.status === 409 || del.status === 404);
  const un = (await get('/api/targets/unreconciled')).data;
  check('unreconciled never lists the state/programme target', un.every((r) => r.scope_type !== 'state'));
});

await step('v4 performance vs an independent SQL computation (zero / missing / exceeded targets, 2-level team)', async () => {
  // Scenario on two fresh colleges C (lead L) and D (lead M) in the clean district.
  const C = (await mkCollege('V4 Perf College C')).data.id; const D = (await mkCollege('V4 Perf College D')).data.id;
  const P = async (b) => (await person({ ...b, allow_same_name: true })).data.id;
  const L = await P({ college_id: C, role: 'college_lead', full_name: 'V4P Lead L' });
  const AL = await P({ college_id: C, role: 'ambassador_lead', full_name: 'V4P AmbLead', reports_to: L });
  const X = await P({ college_id: C, role: 'ambassador', full_name: 'V4P Amb X', reports_to: AL });
  const Y = await P({ college_id: C, role: 'ambassador', full_name: 'V4P Amb Y', reports_to: L });
  const Z = await P({ college_id: C, role: 'ambassador', full_name: 'V4P Amb Z', reports_to: L });
  const M = await P({ college_id: D, role: 'college_lead', full_name: 'V4P Lead M' });
  const Wp = await P({ college_id: D, role: 'ambassador', full_name: 'V4P Amb W', reports_to: M });
  const tgt = (scope_type, scope_id, target, extra = {}) => api('PUT', '/api/targets', { scope_type, scope_id: String(scope_id), target, ...extra }, W);
  await tgt('person', L, 10, { min: 6, max: 14 }); await tgt('person', AL, 0); await tgt('person', X, 5); await tgt('person', Wp, 4); await tgt('college', C, 15);
  await tgt('person', X, 2, { period: 'month:2026-11' }); await tgt('person', X, 1, { period: 'week:2026-11-02' });
  let n = 0;
  const enr = async (college_id, person_id, d, stage = 'confirmed') => { n++; return api('POST', '/api/enrollments', { college_id, person_id, student_name: `V4P S${n}`, enrolled_on: d, stage, force: true }, W); };
  for (const d of ['2026-10-05', '2026-10-12', '2026-10-20', '2026-10-28', '2026-11-01', '2026-11-02', '2026-11-03']) await enr(C, X, d); // X: 7 (exceeds 5)
  await enr(C, L, '2026-10-15'); await enr(C, L, '2026-11-02'); // L own 2
  await enr(C, Y, '2026-10-30'); // Y 1, no target
  await enr(C, Z, '2026-10-10'); await enr(C, Z, '2026-10-11'); // Z 2, then deactivated (leaves the team)
  await enr(C, null, '2026-11-01'); // C, credited to nobody
  await enr(D, Wp, '2026-10-20'); await enr(D, Wp, '2026-11-03');
  const dr = await enr(D, Wp, '2026-10-21'); await api('PATCH', `/api/enrollments/${dr.data.id}`, { stage: 'dropped' }, W); // dropped never counts
  await enr(D, Wp, '2026-10-22', 'applied'); // pipeline, never counts
  await api('PATCH', `/api/people/${Z}`, { status: 'inactive' }, W);
  const tz = await tgt('person', Z, 3);
  check('a new target for an inactive person -> 400', tz.status === 400 && tz.data.fields?.scope_id);
  // a future-dated confirmed record written straight to the DB (the API refuses it): must not count (R9)
  db.prepare("INSERT INTO enrollments(college_id, person_id, student_name, enrolled_on, stage, confirmed_on, created_by) VALUES (?, ?, 'V4P future', '2026-11-05', 'confirmed', '2026-11-05', 'selftest')").run(C, X);

  // ---- independent expectations from raw SQL
  const own = (pid, from = null, to = T0) => Number(db.prepare(`SELECT COUNT(*) n FROM enrollments WHERE person_id = ? AND stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) <= ? ${from ? 'AND COALESCE(confirmed_on, enrolled_on) >= ?' : ''}`).get(pid, to, ...(from ? [from] : [])).n);
  const team = (pid) => db.prepare(`WITH RECURSIVE t(id) AS (SELECT id FROM people WHERE reports_to = ? AND status <> 'inactive'
      UNION SELECT p.id FROM people p JOIN t ON p.reports_to = t.id WHERE p.status <> 'inactive') SELECT id FROM t`).all(pid).map((r) => r.id);
  const ptarget = (pid, period = 'programme', ps = null) => db.prepare("SELECT target, target_min, target_max FROM targets WHERE scope_type = 'person' AND scope_id = ? AND period = ? AND IFNULL(period_start,'') = IFNULL(?, '') AND course_id IS NULL").get(String(pid), period, ps) || null;
  const progStart = '2026-10-01'; const progEnd = '2026-12-31';
  const dayN = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
  const expectStatus = (target, actual, start, end) => {
    if (target == null) return 'no_target'; if (target === 0) return 'zero_target'; if (actual > target) return 'exceeded'; if (actual === target) return 'met';
    const total = dayN(start, end) + 1; const el = Math.min(total, Math.max(0, dayN(start, T0) + 1)); // inclusive of today
    if (T0 < start || el < Math.min(7, Math.max(1, Math.ceil(total * 0.25)))) return 'too_early';
    return actual < 0.8 * target * (el / total) ? 'behind' : 'on_track';
  };
  const perf = (await get(`/api/performance?level=person&college_id=${C}`)).data;
  const rowOf = (id) => perf.rows.find((r) => r.id === id);
  let okAll = true; const diffs = [];
  for (const pid of [L, AL, X, Y]) {
    const r = rowOf(pid); const t = ptarget(pid); const o = own(pid); const tm = team(pid);
    const teamActual = tm.reduce((s, id) => s + own(id), 0);
    const tt = tm.map((id) => ptarget(id)).filter(Boolean).reduce((s, x) => (s ?? 0) + x.target, null);
    const exp = { actual_own: o, target: t?.target ?? null, min: t?.target_min ?? null, max: t?.target_max ?? null, remaining: t ? Math.max(t.target - o, 0) : null, exceeded_by: t ? Math.max(o - t.target, 0) : null,
      pct: t && t.target ? Math.round((o / t.target) * 1000) / 10 : null, status: expectStatus(t?.target ?? null, o, progStart, progEnd), actual_team: teamActual, actual_combined: o + teamActual, team_size: tm.length, team_target: tm.length ? tt : undefined };
    const got = { actual_own: r?.actual_own, target: r?.target, min: r?.min, max: r?.max, remaining: r?.remaining, exceeded_by: r?.exceeded_by, pct: r?.pct, status: r?.status, actual_team: r?.actual_team, actual_combined: r?.actual_combined,
      team_size: r?.team?.size ?? 0, team_target: r?.team ? r.team.target : undefined };
    if (JSON.stringify(exp) !== JSON.stringify(got)) { okAll = false; diffs.push({ pid, exp, got }); }
  }
  check('performance person rows = independent SQL (own, team subtree, combined, min/target/max, remaining, exceeded_by, pct, status)', okAll && perf.rows.length === 4, JSON.stringify(diffs).slice(0, 600));
  const rx = rowOf(X); const rl = rowOf(L); const ral = rowOf(AL); const ry = rowOf(Y);
  check('exceeded target: X 7 of 5 -> exceeded_by 2, remaining 0, pct 140 (the future-dated record does not count)', rx.actual_own === 7 && rx.exceeded_by === 2 && rx.remaining === 0 && rx.pct === 140 && rx.status === 'exceeded');
  check('zero target -> status zero_target, pct null (never "achieved" / divide by zero)', ral.target === 0 && ral.status === 'zero_target' && ral.pct === null);
  check('missing target -> no_target with null remaining / pct', ry.target === null && ry.status === 'no_target' && ry.remaining === null && ry.pct === null);
  check('2-level team: L team = AmbLead + X (under AmbLead) + Y; inactive Z excluded; combined = own + team', rl.team.size === 3 && rl.actual_team === 8 && rl.actual_combined === 10 && rl.team.target === 5 && rl.combined.target === 15 && rl.below_min === true);
  check('performance totals reconcile with the rows', perf.totals.actual === perf.rows.reduce((s, r) => s + r.actual, 0) && perf.totals.with_target === 3 && perf.totals.target === 15 && perf.totals.actual_against_target === 9);
  const inc = (await get(`/api/performance?level=person&college_id=${C}&include_inactive=1`)).data;
  check('include_inactive=1 adds the inactive member (with their own credit)', inc.rows.length === 5 && inc.rows.find((r) => r.id === Z)?.actual_own === 2);
  // periods
  const mo = (await get(`/api/performance?level=person&college_id=${C}&period=month:2026-11`)).data;
  const wk = (await get(`/api/performance?level=person&college_id=${C}&period=week:2026-11-02`)).data;
  const mx = mo.rows.find((r) => r.id === X); const wx = wk.rows.find((r) => r.id === X);
  check('month period: actual counts 1 Nov..today only; target is the month row', mx.actual_own === own(X, '2026-11-01') && mx.actual_own === 3 && mx.target === 2 && mx.status === 'exceeded' && mo.period.start === '2026-11-01' && mo.period.end === '2026-11-30');
  check('week period (Mon 2 Nov): actual 2, target 1; bad week -> 400', wx.actual_own === own(X, '2026-11-02') && wx.actual_own === 2 && wx.target === 1 && (await get('/api/performance?period=week:2026-11-03')).status === 400);
  // college + district
  const pc = (await get(`/api/performance?level=college&districts=${V4.district}`)).data;
  const rc = pc.rows.find((r) => r.id === C); const rd = pc.rows.find((r) => r.id === D);
  const colAct = (cid) => Number(db.prepare("SELECT COUNT(*) n FROM enrollments WHERE college_id = ? AND stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) <= ?").get(cid, T0).n);
  check('college rows: C explicit 15 vs all confirmed at C (incl. not credited); D no target', rc.target === 15 && rc.actual === colAct(C) && rc.actual === 13 && rc.not_credited === 1 && rc.remaining === 2 && rd.target === null && rd.actual === colAct(D) && rd.actual === 2 && rd.status === 'no_target');
  const pd = (await get(`/api/performance?level=district&districts=${V4.district}`)).data.rows[0];
  const pdw = (await get(`/api/performance?level=district&districts=${V4.district}&period=week:2026-11-02`)).data.rows[0];
  check('covers is returned even for a district with no target in the period', pdw.target === null && pdw.covers && pdw.covers.with_target === 0 && pdw.covers.total > 0 && pc.rows.every((r) => r.covers && Number.isInteger(r.covers.total)));
  const sumT = Number(db.prepare("SELECT COALESCE(SUM(t.target), 0) n FROM targets t JOIN colleges c ON c.id = t.scope_id WHERE t.scope_type = 'college' AND t.period = 'programme' AND t.course_id IS NULL AND c.district_id = ?").get(V4.district).n);
  const allAct = Number(db.prepare("SELECT COUNT(*) n FROM enrollments e JOIN colleges c ON c.id = e.college_id WHERE c.district_id = ? AND e.stage = 'confirmed' AND COALESCE(e.confirmed_on, e.enrolled_on) <= ?").get(V4.district, T0).n);
  check('district: rolled-up target = Σ college targets; compared only with colleges that have one (covers), actual_own = all', pd.target === sumT && pd.target_source === 'sum_of_children' && pd.actual_own === allAct && pd.actual === colAct(C) && pd.covers?.with_target === 1
    // v4.1 (F3): only 1 of the district's colleges has a target -> partial_target, no pct/remaining (was: pct over the covered college)
    && pd.covers.complete === false && pd.status === 'partial_target' && pd.pct === null && pd.remaining === null, JSON.stringify(pd).slice(0, 300));
  const sum = (await get(`/api/summary?scope=district:${V4.district}`)).data;
  check('summary of the district agrees (actual_against_target, covers, pct not inflated by colleges without a target)', sum.actual_against_target === colAct(C) && sum.enrolled === allAct && sum.covers.with_target >= 1
    && sum.pct === null && sum.pace_status === 'partial_target' && sum.target === sumT, JSON.stringify({ p: sum.pct, s: sum.pace_status, c: sum.covers })); // v4.1 (F3): partial roll-up is not judged
  const pr = (await get(`/api/people/${L}`)).data.rollup;
  check('person rollup: team_target / team_enrolled cover the whole subtree; own/team/combined blocks', pr.team_target === 5 && pr.team_enrolled === 8 && pr.team.size === 3 && pr.combined.actual === 10 && pr.own.pct === 20);
  const td = (await get(`/api/target-dashboard?scope=person:${AL}`)).data;
  check('target-dashboard: explicit target 0 -> projection zero_target (not "achieved")', td.projection?.status === 'zero_target');
  const bad = await Promise.all(['level=team', 'period=month:2026-13', 'sort=zzz', 'districts=nowhere'].map((x) => get(`/api/performance?${x}`)));
  check('performance validation (bad level / period / sort / district) -> 400', bad.every((r) => r.status === 400));
  const st = (await get('/api/performance?level=state')).data;
  check('performance level=state + programme block', st.rows.length === 1 && st.programme && 'target' in st.programme && st.period.key === 'programme');
  V4.perf = { C, D, L };
});

await step('v4 districts= on every list / rollup endpoint', async () => {
  const eps = ['/api/colleges', '/api/people', '/api/branches', '/api/contacts', '/api/calls', '/api/calls/queue', '/api/followups', '/api/exams', '/api/enrollments', '/api/activities',
    '/api/summary', '/api/leaderboard', '/api/attention', '/api/timeseries', '/api/funnel', '/api/target-dashboard', '/api/performance', '/api/plan', '/api/quality'];
  const okD = []; const badD = [];
  for (const e of eps) {
    const g = await get(`${e}?districts=${V4.district}`); if (g.status !== 200) okD.push(`${e} ${g.status}`);
    const b = await get(`${e}?districts=nowhere`); if (b.status !== 400) badD.push(`${e} ${b.status}`);
  }
  check('every list/rollup endpoint accepts districts= (200) and rejects an unknown district (400)', !okD.length && !badD.length, `${okD.join(', ')} | ${badD.join(', ')}`);
  const ppl = (await get(`/api/people?districts=${V4.district}`)).data;
  const enr = (await get(`/api/enrollments?districts=${V4.district}`)).data;
  check('districts= actually filters people and enrollments', ppl.length > 0 && ppl.every((p) => p.district_id === V4.district) && enr.length > 0 && enr.every((e) => [V4.A, V4.B, V4.perf.C, V4.perf.D].includes(e.college_id)));
});

await step('v4 deletes (R15), contacts verification, limits, paths, body size, headers, search', async () => {
  const E = (await mkCollege('V4 Delete Me')).data.id;
  await api('POST', '/api/followups', { scope_type: 'college', scope_id: E, title: 'call them' }, W);
  const del = await api('DELETE', `/api/colleges/${E}`, undefined, W);
  check('deleting a college with an open follow-up -> 409 (no orphan follow-ups)', del.status === 409 && /follow-up/.test(del.data.error) && del.data.code === 'linked_records');
  const pz = await person({ college_id: V4.B, role: 'ambassador', full_name: 'V4 Has Followup', allow_same_name: true });
  const fpz = await api('POST', '/api/followups', { scope_type: 'person', scope_id: String(pz.data.id), title: 'check' }, W);
  const dpz = await api('DELETE', `/api/people/${pz.data.id}`, undefined, W);
  check('deleting a person with a follow-up -> 409 linked_records (R15: block with a clear message, never orphan it); person still there', dpz.status === 409 && dpz.data.code === 'linked_records' && /follow-up/.test(dpz.data.error) && dpz.data.linked?.['follow-up'] === 1 && (await get(`/api/people/${pz.data.id}`)).status === 200, JSON.stringify([fpz, dpz]).slice(0, 700));
  const k = await api('POST', '/api/contacts', { college_id: V4.B, phone: '0863 2300001', role: 'office' }, W);
  const kv = await api('PATCH', `/api/contacts/${k.data.id}`, { basis: 'verified' }, W);
  const kp = await api('PATCH', `/api/contacts/${k.data.id}`, { basis: 'pending' }, W);
  const kd = await api('PATCH', `/api/contacts/${k.data.id}`, { basis: 'verified', verified_on: '2026-10-30' }, W);
  const kf = await api('PATCH', `/api/contacts/${k.data.id}`, { basis: 'pending' }, W) && await api('PATCH', `/api/contacts/${k.data.id}`, { basis: 'verified', verified_on: '2026-12-01' }, W);
  check('contact verified_on may be given (past date) but never in the future', kd.data.verified_on === '2026-10-30' && kf.status === 400);
  const kjs = await api('POST', '/api/contacts', { college_id: V4.B, phone: '0863 2300002', source_url: 'javascript:alert(1)' }, W);
  check('contact verified -> verified_by + verified_on stamped; pending clears them; javascript: source refused', kv.data.verified_by === USER && kv.data.verified_on === T0 && kp.data.verified_by === null && kjs.status === 400);
  const lm = (await get('/api/calls?limit=-1')).data; const la = (await get('/api/audit?limit=-5')).data;
  check('limit=-1 / negative -> the default cap, never unlimited', Array.isArray(lm) && lm.length <= 200 && la.length <= 100);
  check('bad %-encoding in an API path -> 400 (not 500)', (await get('/api/colleges/%E0%A4%A')).status === 400);
  const big = await apiH('POST', '/api/courses', JSON.stringify({ name: 'x', notes: 'y'.repeat(1100000) }), W);
  check('body over 1 MB -> 413 response (not a dropped connection)', big.status === 413);
  const h1 = await apiH('GET', '/api/health');
  const h2 = await fetch(`${base}/`);
  const csp = h2.headers.get('content-security-policy') || '';
  check('security headers: nosniff + X-Frame-Options DENY on API; CSP (self, frame-ancestors none, no unsafe-inline script) on HTML', h1.headers.get('x-frame-options') === 'DENY' && h1.headers.get('x-content-type-options') === 'nosniff'
    && /default-src 'self'/.test(csp) && /frame-ancestors 'none'/.test(csp) && /script-src 'self'/.test(csp) && !/script-src[^;]*unsafe-inline/.test(csp) && h1.data.version === 'v4', JSON.stringify([h1.headers.get('x-frame-options'), h1.data, csp, h2.status]));
  const s = (await get('/api/search?q=amb')).data;
  check('search: towns only match at a word start (no "Namburu" for "amb")', !s.some((r) => r.type === 'city' && !/(^|\s)amb/i.test(r.label)));
  const sp = (await get('/api/search?q=V4 Amb A2')).data.find((r) => r.type === 'person');
  check('search person sub shows the lead', !!sp && /reports to/.test(sp.sub));
  const actors = (await get('/api/audit/actors')).data;
  check('GET /api/audit/actors lists actors with counts', Array.isArray(actors) && actors.some((a) => a.actor === USER && a.n > 0));
  const dup = await api('POST', '/api/branches', { college_id: V4.A, code: 'CSE' }, W);
  check('constraint/duplicate errors never leak table names', dup.status === 409 && !/branches\.|UNIQUE|constraint/i.test(dup.data.error));
});

await step('v4 auth: session, passcode, viewer role, lockout (R14)', async () => {
  const s0 = (await get('/api/session')).data;
  check('no passcode configured: GET /api/session -> auth_required false, role editor (no lock-out)', s0.required === false && s0.authenticated === false && s0.auth_required === false && s0.role === 'editor');
  const login0 = await apiH('POST', '/api/session', { name: 'Open User' });
  check('without a passcode POST /api/session just remembers the name (cookie, editor)', login0.status === 200 && login0.data.role === 'editor' && /__session=/.test(login0.headers.get('set-cookie') || ''));
  process.env.PORTAL_PASSCODE = 'team-s3cret'; process.env.PORTAL_VIEWER_PASSCODE = 'just-look';
  try {
    const anon = await get('/api/colleges');
    const health = await get('/api/health');
    check('passcode set: reads need a sign-in (401 auth_required); /api/health stays open', anon.status === 401 && anon.data.code === 'auth_required' && health.status === 200 && health.data.auth_required === true);
    const resv = await apiH('POST', '/api/session', { name: 'system', passcode: 'team-s3cret' });
    check('reserved name at sign-in -> 400', resv.status === 400);
    const ok = await apiH('POST', '/api/session', { name: 'Sign In Tester', passcode: 'team-s3cret' });
    const ck = (ok.headers.get('set-cookie') || '').split(';')[0];
    check('correct passcode -> 200, HttpOnly + SameSite=Strict cookie, role editor', ok.status === 200 && ok.data.role === 'editor' && /HttpOnly/i.test(ok.headers.get('set-cookie')) && /SameSite=Strict/i.test(ok.headers.get('set-cookie')));
    const r1 = await apiH('GET', '/api/colleges?limit=1', undefined, { Cookie: ck });
    const a0 = auditCount();
    const w1 = await apiH('POST', '/api/courses', { name: 'V4 session course' }, { Cookie: ck });
    const actor = db.prepare('SELECT actor FROM audit_log ORDER BY id DESC LIMIT 1').get().actor;
    check('signed-in reads work; writes need no X-User and are audited as the session user', r1.status === 200 && w1.status === 201 && auditCount() > a0 && actor === 'Sign In Tester');
    const legacy = await apiH('GET', '/api/meta', undefined, { 'X-Passcode': 'team-s3cret' });
    check('legacy X-Passcode header still works for reads', legacy.status === 200 && legacy.data.auth?.auth_required === true);
    const vw = await apiH('POST', '/api/session', { name: 'Viewer', passcode: 'just-look' });
    const vck = (vw.headers.get('set-cookie') || '').split(';')[0];
    const vr = await apiH('GET', '/api/people', undefined, { Cookie: vck });
    const vwr = await apiH('POST', '/api/courses', { name: 'nope' }, { Cookie: vck, 'X-User': 'Viewer' });
    check('viewer passcode: role viewer, GET ok, writes -> 403 read_only', vw.data.role === 'viewer' && vr.status === 200 && vwr.status === 403 && vwr.data.code === 'read_only');
    const out = await apiH('DELETE', '/api/session', undefined, { Cookie: ck });
    const after = await apiH('GET', '/api/colleges?limit=1', undefined, { Cookie: ck });
    check('DELETE /api/session signs out (cookie cleared, session invalid)', out.status === 200 && /Max-Age=0/.test(out.headers.get('set-cookie') || '') && after.status === 401);
    const fails = [];
    for (let i = 0; i < 5; i++) fails.push((await apiH('POST', '/api/session', { name: 'Guesser', passcode: `wrong${i}` })).status);
    const locked = await apiH('POST', '/api/session', { name: 'Guesser', passcode: 'team-s3cret' });
    check('5 wrong passcodes -> 401 each, then 429 locked (even with the right passcode) + Retry-After', fails.every((s) => s === 401) && locked.status === 429 && locked.data.code === 'locked' && Number(locked.headers.get('retry-after')) > 0);
  } finally { delete process.env.PORTAL_PASSCODE; delete process.env.PORTAL_VIEWER_PASSCODE; }
  check('after removing the passcode the portal is open again (no lock-out of local use)', (await get('/api/colleges?limit=1')).status === 200);
});

await step('v4 HOST binding guard (R14)', async () => {
  const saved = process.env.HOST; delete process.env.HOST;
  let err = null;
  try { await startServer({ port: 0, host: '0.0.0.0', db }); } catch (e) { err = e; }
  check('HOST=0.0.0.0 without PORTAL_PASSCODE refuses to start (INSECURE_HOST)', err?.code === 'INSECURE_HOST');
  process.env.PORTAL_PASSCODE = 'lan-pass';
  check('HOST=0.0.0.0 with PORTAL_PASSCODE passes the guard (not bound here, to avoid a firewall prompt)', hostGuard('0.0.0.0') === null && hostGuard('192.168.1.5') === null);
  delete process.env.PORTAL_PASSCODE;
  check('loopback hosts never need a passcode', hostGuard('127.0.0.1') === null && hostGuard('localhost') === null && hostGuard('::1') === null && hostGuard('0.0.0.0') !== null);
  const d = await startServer({ port: 0, db });
  const hit = async (h) => { try { return (await fetch(`http://${h}:${d.port}/api/health`)).status; } catch { return 0; } };
  const s4 = await hit('127.0.0.1');
  check('default bind is loopback only: 127.0.0.1 always, plus ::1 when IPv6 exists (no other address)', d.host === '127.0.0.1' && s4 === 200
    && d.hosts[0] === '127.0.0.1' && d.hosts.every((h) => isLoopback(h)), JSON.stringify(d.hosts));
  if (d.hosts.includes('::1')) check('default bind also answers on [::1] (Windows resolves localhost to ::1 first), same port', (await hit('[::1]')) === 200);
  const ex = await startServer({ port: 0, host: '127.0.0.1', db });
  check('an explicit HOST binds only that address (single listener)', ex.hosts.length === 1 && ex.hosts[0] === '127.0.0.1');
  ex.server.close();
  d.server.close();
  const closed = await new Promise((r) => setTimeout(r, 100)).then(() => hit('127.0.0.1'));
  check('server.close() also closes the ::1 listener', closed === 0 && (!d.server.v6 || !d.server.v6.listening));
  if (saved !== undefined) process.env.HOST = saved;
});

await step('v4 importer idempotency after an admin rename (BE-01) and seed keeping admin edits (R12)', async () => {
  const anr = db.prepare("SELECT c.id FROM colleges c JOIN college_plan p ON p.college_id = c.id WHERE p.research_id = 'new-ANRG' LIMIT 1").get();
  if (!anr || !fs.existsSync(DEFAULT_CSV_DIR)) { check('importer: ANR research college present for the rename test', false, 'no new-ANRG plan row / CSVs'); return; }
  const r = await api('PATCH', `/api/colleges/${anr.id}`, { name: 'ANR renamed by admin', website: 'https://anr.example', aliases: [] }, W);
  const n0 = db.prepare('SELECT COUNT(*) n FROM colleges').get().n;
  const again = importResearch(db, { log: quiet });
  const n1 = db.prepare('SELECT COUNT(*) n FROM colleges').get().n;
  const plan = db.prepare("SELECT college_id FROM college_plan WHERE research_id = 'new-ANRG'").all();
  check('re-import after an admin renames the research college: no duplicate college, plan row still on it, admin edit kept', r.status === 200 && n1 === n0 && again.new_colleges.length === 0 && plan.length === 1 && plan[0].college_id === anr.id
    && db.prepare('SELECT name FROM colleges WHERE id = ?').get(anr.id).name === 'ANR renamed by admin', JSON.stringify({ n0, n1, nc: again.new_colleges.length, plan }));
  const c = db.prepare("SELECT id, name FROM colleges WHERE sno BETWEEN 1 AND 170 AND id NOT IN (SELECT college_id FROM college_plan WHERE research_id = 'new-ANRG') ORDER BY sno LIMIT 1 OFFSET 29").get();
  const edited = `${c.name} (admin edit v4)`;
  await api('PATCH', `/api/colleges/${c.id}`, { name: edited }, W);
  const seedRes = seedReference(db, { log: quiet });
  check('seed re-run keeps the admin-edited college name', db.prepare('SELECT name FROM colleges WHERE id = ?').get(c.id).name === edited, JSON.stringify(seedRes.colleges));
  const asSeed = await api('PATCH', `/api/colleges/${c.id}`, { name: 'by seed' }, { 'X-User': 'seed' });
  check('nobody can write as "seed" (which seed would treat as its own row)', asSeed.status === 400);
  await api('PATCH', `/api/colleges/${c.id}`, { name: c.name }, W);
});

// last: writes the program target (an explicit state target row), which would change the state rollup for earlier steps
await step('program: GET/PATCH /api/program', async () => {
  const g = (await get('/api/program')).data;
  check('GET /api/program shape (target, deadline, 3 groups -> 7 district ids, every district with group/is_target/counts)',
    Number.isInteger(g.target) && /^\d{4}-\d{2}-\d{2}$/.test(g.deadline) && Object.keys(g.target_district_groups).length === 3 && g.target_district_ids.length === 7
    && DEF7.every((id) => g.target_district_ids.includes(id)) && g.districts.length >= 26
    && g.districts.every((d) => 'group' in d && 'is_target' in d && Number.isInteger(d.colleges_total) && Number.isInteger(d.colleges_operational))
    && g.districts.find((d) => d.id === 'ntr').group === 'Krishna' && g.districts.find((d) => d.id === 'prakasam').is_target === false, JSON.stringify(g).slice(0, 300));
  const v = async (body) => (await api('PATCH', '/api/program', body, W));
  const r1 = await v({ target: 0 }); const r2 = await v({ deadline: '31/12/2026' }); const r3 = await v({ target_district_groups: { X: ['nowhere'] } });
  const r4 = await v({ target_district_groups: { A: ['guntur'], B: ['guntur'] } }); const r5 = await v({ foo: 1 }); const r6 = await v({ target_district_groups: [] });
  const r7 = await api('PATCH', '/api/program', { target: 401 });
  check('PATCH /api/program validation (target, deadline, unknown / duplicate district, unknown field, list instead of object, X-User)',
    r1.status === 400 && r1.data.fields.target && r2.status === 400 && r2.data.fields.deadline && r3.status === 400 && /nowhere/.test(r3.data.fields.target_district_groups)
    && r4.status === 400 && /both/.test(r4.data.fields.target_district_groups) && r5.status === 400 && r5.data.fields.foo && r6.status === 400 && r7.status === 401);
  const a0 = auditCount();
  const ok = await v({ target: 401, deadline: '2026-12-30' });
  const st = db.prepare("SELECT * FROM targets WHERE scope_type = 'state' AND course_id IS NULL").get();
  const set = (await get('/api/settings')).data;
  check('PATCH /api/program writes the state target row and the program settings (audited)', ok.status === 200 && ok.data.target === 401 && ok.data.deadline === '2026-12-30' && ok.data.target_source === 'state_target'
    && st?.target === 401 && st.deadline === '2026-12-30' && set.program_target === 401 && set.program_deadline === '2026-12-30' && auditCount() > a0);
  const a1 = auditCount();
  const same = await v({ target: 401, deadline: '2026-12-30' });
  check('PATCH /api/program with the same values is a no-op (no audit row)', same.status === 200 && auditCount() === a1);
  await api('POST', '/api/targets', { scope_type: 'state', target: 402, confirm_programme: true }, W);
  check('a state target written via /api/targets keeps program_target in sync', (await get('/api/program')).data.target === 402 && (await get('/api/settings')).data.program_target === 402);
  const g2 = await v({ target_district_groups: { Guntur: ['guntur', 'palnadu', 'bapatla'], Krishna: ['krishna', 'ntr'], 'West Godavari': ['west-godavari', 'eluru', 'polavaram'] } });
  const td = (await get(`/api/target-dashboard?scope=state&districts=${DEF7.join(',')}`)).data;
  // v4.1 (D2): the 7 old districts no longer include every programme district (polavaram added) -> the programme target does not apply
  check('target_district_groups saved; the default selection follows it', g2.status === 200 && g2.data.target_district_ids.length === 8 && td.program.is_default_selection === false && td.program.target === null && td.program.programme_target === 402 && /covers the 8 target districts/.test(td.program.target_reason || ''), JSON.stringify(td.program));
});

// ---------------------------------------------------------------- v4.1 fixes (FIXLIST "Server (BEF)"); runs after the program step
function rawReq(method, p, { body, headers = {} } = {}) {
  return new Promise((resolve) => {
    const data = body == null ? null : (typeof body === 'string' ? body : JSON.stringify(body));
    const h = { ...headers }; if (data != null) h['Content-Length'] = Buffer.byteLength(data);
    const r = http.request({ host: '127.0.0.1', port, method, path: p, headers: h }, (res) => {
      let t = ''; res.on('data', (c) => { t += c; }); res.on('end', () => { let j = null; try { j = JSON.parse(t); } catch { /* not json */ } resolve({ status: res.statusCode, headers: res.headers, data: j }); });
    });
    r.on('error', (e) => resolve({ status: 'ERR', data: String(e) }));
    if (data != null) r.write(data);
    r.end();
  });
}
let phoneN = 0;
const mob = () => `96${String(31000000 + (phoneN++)).padStart(8, '0')}`;
await step('v4.1 F1 / SEC-07 idempotency: only 2xx cached, body in the fingerprint, reuse -> 422', async () => {
  const k = `v41-${Date.now()}`;
  const dupName = (await get(`/api/colleges/${V4.A}`)).data.college.name;
  const r1 = await apiH('POST', '/api/colleges', { name: dupName, district_id: V4.district, city_name: 'V4 Selftest Town' }, { ...W, 'Idempotency-Key': k });
  const r2 = await apiH('POST', '/api/colleges', { name: 'V41 Idem Fixed College', district_id: V4.district, city_name: 'V4 Selftest Town' }, { ...W, 'Idempotency-Key': k });
  check('F1: a 409 is not cached: fixing the body and saving again with the same key creates the college', r1.status === 409 && r2.status === 201 && r2.headers.get('idempotent-replay') == null, JSON.stringify([r1.status, r2.status]));
  const r3 = await apiH('POST', '/api/colleges', { name: 'V41 Idem Fixed College', district_id: V4.district, city_name: 'V4 Selftest Town' }, { ...W, 'Idempotency-Key': k });
  const r4 = await apiH('POST', '/api/colleges', { name: 'V41 Idem Other Body', district_id: V4.district, city_name: 'V4 Selftest Town' }, { ...W, 'Idempotency-Key': k });
  check('F1: same key + same body replays the 201; same key + different body -> 422 idempotency_key_reused, nothing written', r3.status === 201 && r3.data.id === r2.data.id && r3.headers.get('idempotent-replay') === 'true'
    && r4.status === 422 && r4.data.code === 'idempotency_key_reused' && /different request/.test(r4.data.error) && !db.prepare("SELECT 1 FROM colleges WHERE name = 'V41 Idem Other Body'").get());
  const k2 = `v41b-${Date.now()}`;
  const o = await apiH('POST', '/api/followups', { scope_type: 'college', scope_id: V4.A, title: 'v41 idem actor' }, { ...W, 'Idempotency-Key': k2 });
  const o2 = await apiH('POST', '/api/followups', { scope_type: 'college', scope_id: V4.A, title: 'v41 idem actor' }, { 'X-User': 'Someone Else', 'Idempotency-Key': k2 });
  check('F1: the same key from another actor -> 422 (actor is in the fingerprint)', o.status === 201 && o2.status === 422);
  if (o.data?.id) await api('DELETE', `/api/followups/${o.data.id}`, undefined, W);
});
await step('v4.1 F2 / F5 / D5 team and combined blocks judged only with full target coverage', async () => {
  const c = await api('POST', '/api/colleges', { name: 'V41 Team College', district_id: V4.district, city_name: 'V4 Selftest Town', op_status: 'operational' }, W);
  const C = c.data.id; V4.T41 = C;
  const lead = (await person({ college_id: C, role: 'college_lead', full_name: 'V41 Lead', phone: mob() })).data;
  const a1 = (await person({ college_id: C, role: 'ambassador', full_name: 'V41 Amb One', phone: mob(), reports_to: lead.id })).data;
  const a2 = (await person({ college_id: C, role: 'ambassador', full_name: 'V41 Amb Two', phone: mob(), reports_to: lead.id })).data;
  await api('PUT', '/api/targets', { scope_type: 'person', scope_id: String(lead.id), target: 10 }, W);
  await api('PUT', '/api/targets', { scope_type: 'person', scope_id: String(a1.id), target: 1 }, W);
  for (const [pid, nm] of [[a1.id, 'S1'], [a1.id, 'S2'], [a2.id, 'S3']]) await api('POST', '/api/enrollments', { college_id: C, person_id: pid, student_name: `V41 ${nm}`, enrolled_on: '2026-11-01', stage: 'confirmed' }, W);
  const pr = (await get(`/api/performance?level=person&college_id=${C}`)).data.rows.find((r) => r.id === lead.id);
  check('F2: team target 1 (only Amb One has one), team actual 3 over both members -> partial_target, covers 1/2, no pct / exceeded (was 300 %)',
    pr.team.target === 1 && pr.team.actual === 3 && pr.team.actual_with_target === 2 && pr.team.status === 'partial_target' && pr.team.pct === null && pr.team.exceeded_by === null
    && pr.team.covers.with_target === 1 && pr.team.covers.total === 2, JSON.stringify(pr.team));
  check('F5/D5: own judged on own (0 of 10); combined = own+team target 11 vs 3, partial (covers 2/3) -> not 27 %', pr.target === 10 && pr.actual_own === 0 && pr.pct === 0
    && pr.combined.target === 11 && pr.combined.actual === 3 && pr.combined.status === 'partial_target' && pr.combined.pct === null && pr.combined.covers.with_target === 2 && pr.combined.covers.total === 3, JSON.stringify(pr.combined));
  const ro = (await get(`/api/people/${lead.id}`)).data.rollup;
  check('F2: person rollup team / combined blocks use the same rule', ro.team.status === 'partial_target' && ro.team.covers.total === 2 && ro.combined.status === 'partial_target' && ro.own.target === 10);
  await api('PUT', '/api/targets', { scope_type: 'person', scope_id: String(a2.id), target: 2 }, W);
  const pr2 = (await get(`/api/performance?level=person&college_id=${C}`)).data.rows.find((r) => r.id === lead.id);
  check('F2: once every member has a target the team block is judged (3 / 3 = met) and combined 3 / 13', pr2.team.target === 3 && pr2.team.status === 'met' && pr2.team.pct === 100
    && pr2.combined.target === 13 && pr2.combined.pct === Math.round((3 / 13) * 1000) / 10 && pr2.combined.covers.with_target === 3, JSON.stringify([pr2.team, pr2.combined]));
  V4.T41lead = lead.id;
});
await step('v4.1 F3 zero child target does not make an untargeted district "target 0"', async () => {
  // a town of its own (no other targets inside): two colleges, one with an explicit target 0 and 1 confirmed enrollment
  const z1 = (await api('POST', '/api/colleges', { name: 'V41 Zero College', district_id: V4.district, city_name: 'V41 Zero Town', op_status: 'operational' }, W)).data.id;
  await api('POST', '/api/colleges', { name: 'V41 Untargeted College', district_id: V4.district, city_name: 'V41 Zero Town', op_status: 'operational' }, W);
  const col = z1; const city = `${V4.district}--v41-zero-town`;
  await api('PUT', '/api/targets', { scope_type: 'college', scope_id: col, target: 0 }, W);
  await api('POST', '/api/enrollments', { college_id: col, student_name: 'V41 Zero S1', enrolled_on: '2026-11-01', stage: 'confirmed' }, W);
  const sm = (await get(`/api/summary?scope=city:${city}`)).data;
  const td = (await get(`/api/target-dashboard?scope=city:${city}`)).data;
  const cr = (await get(`/api/performance?level=college&college_id=${col}`)).data.rows[0];
  check('F3: a town with one college at target 0 (of 2) -> partial_target, not "target 0, exceeded by 1"; covers 1/2', sm.target === 0 && sm.target_source === 'sum_of_children' && sm.pace_status === 'partial_target'
    && sm.pct === null && sm.exceeded_by === null && sm.remaining === null && sm.covers.with_target === 1 && sm.covers.total === 2 && sm.target_complete === false, JSON.stringify(sm).slice(0, 300));
  check('F3: target-dashboard of that town: target_status partial_target, projection partial_target, no remaining / pct', td.target_status === 'partial_target' && td.projection.status === 'partial_target' && td.remaining === null && td.pct === null && td.covers.total === 2);
  check('F3: the college itself keeps its explicit zero_target', cr.status === 'zero_target' && cr.pct === null && cr.target === 0);
  const dtot = (await get(`/api/performance?level=district&districts=${V4.district}`)).data.totals;
  check('F3: performance totals leave partial rows out of target/pct and count them', dtot.with_target === 0 && dtot.partial_target === 1 && dtot.by_status.partial_target === 1, JSON.stringify(dtot));
});
await step('v4.1 F4 / D9 people counts exclude inactive people (like the lists)', async () => {
  const C = V4.T41;
  const x = (await person({ college_id: C, role: 'ambassador', full_name: 'V41 Inactive Unassigned', phone: mob() })).data;
  await api('PATCH', `/api/people/${x.id}`, { status: 'inactive' }, W);
  const all = (await get(`/api/people?college_id=${C}&page=1`)).data;
  const un = (await get(`/api/people?college_id=${C}&assignment=unassigned&page=1`)).data;
  check('F4: counts.unassigned = the unassigned list total; inactive reported separately', all.counts.unassigned === un.total && all.counts.inactive === 1 && all.counts.ambassador === 2, JSON.stringify([all.counts, un.total]));
  const withSt = (await get(`/api/people?college_id=${C}&status=inactive&page=1`)).data;
  check('F4: with status= the counts follow that filter', withSt.counts.ambassador === 1 && withSt.counts.inactive === 0);
});
await step('v4.1 F6 phone rules: people mobile only, contacts mobile or landline', async () => {
  const p = await person({ college_id: V4.T41, role: 'ambassador', full_name: 'V41 Landline', phone: '0863 2344700' });
  const p2 = await person({ college_id: V4.T41, role: 'ambassador', full_name: 'V41 Landline B', phone: '040 2344 7001' });
  const k = await api('POST', '/api/contacts', { college_id: V4.T41, name: 'Office', role: 'office', phone: '040 2344 7002' }, W);
  check('F6: a person with an STD landline (040 …) -> 400 "mobile"; a contact with a landline -> 201', p2.status === 400 && /mobile/i.test(p2.data.fields?.phone || '') && k.status === 201 && k.data.phone === '+914023447002', JSON.stringify([p.status, p2.data, k.status]));
  if (k.data?.id) await api('DELETE', `/api/contacts/${k.data.id}`, undefined, W);
});
await step('v4.1 F8 unknown district ids are refused on every GET', async () => {
  const urls = ['/api/search?q=vignan&districts=nowhere', '/api/meta?districts=nowhere', '/api/cities?district=nowhere', '/api/colleges?district=nowhere', '/api/audit?districts=nowhere'];
  const st = []; for (const u of urls) st.push((await get(u)).status);
  check('F8: districts=/district= with an unknown id -> 400 everywhere (also endpoints that do not filter by it)', st.every((x) => x === 400), JSON.stringify(st));
  check('BE-15: colleges?op_status=wizard -> 400', (await get('/api/colleges?op_status=wizard')).status === 400 && (await get('/api/colleges?op_status=operational')).status === 200);
});
await step('v4.1 F9 / SEC-04 Host allow-list by default', async () => {
  const evil = await rawReq('GET', '/api/people', { headers: { Host: 'evil.example' } });
  const evil2 = await rawReq('GET', '/', { headers: { Host: `127.evil.example:${port}` } });
  const ok = await Promise.all([`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`, '192.168.1.5:4173'].map((h) => rawReq('GET', '/api/health', { headers: { Host: h } })));
  check('F9: Host evil.example / 127.evil.example -> 403 bad_host; localhost, 127.0.0.1, [::1], IP literals -> 200', evil.status === 403 && evil.data?.code === 'bad_host' && evil2.status === 403 && ok.every((r) => r.status === 200), JSON.stringify(ok.map((r) => r.status)));
  process.env.PORTAL_ALLOWED_HOSTS = 'portal.local';
  const pl = await rawReq('GET', '/api/health', { headers: { Host: 'portal.local:8080' } });
  delete process.env.PORTAL_ALLOWED_HOSTS;
  check('F9: PORTAL_ALLOWED_HOSTS adds names', pl.status === 200);
  check('SEC-13: isLoopback only for IP literals (127.evil.example is not loopback)', isLoopback('127.0.0.5') && !isLoopback('127.evil.example'));
});
await step('v4.1 SEC-01 CSRF: JSON only, same origin only (session POST too)', async () => {
  const J = { 'Content-Type': 'application/json', ...W };
  const b = { scope_type: 'college', scope_id: V4.A, title: 'v41 csrf' };
  const tp = await rawReq('POST', '/api/followups', { body: b, headers: { ...W, 'Content-Type': 'text/plain' } });
  const fo = await rawReq('POST', '/api/followups', { body: 'title=x', headers: { ...W, 'Content-Type': 'application/x-www-form-urlencoded' } });
  const or = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, Origin: 'http://localhost:9999' } });
  const ss = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, Origin: `http://127.0.0.1:${port}`, 'Sec-Fetch-Site': 'same-site' } });
  const nu = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, Origin: 'null' } });
  const se = await rawReq('POST', '/api/session', { body: { name: 'CSRF Attacker' }, headers: { 'Content-Type': 'text/plain' } });
  const se2 = await rawReq('POST', '/api/session', { body: { name: 'CSRF Attacker' }, headers: { 'Content-Type': 'application/json', Origin: 'http://localhost:9999' } });
  const de = await rawReq('DELETE', '/api/followups/999999', { headers: { ...W, Origin: 'http://evil.example' } });
  check('SEC-01: text/plain and form bodies -> 415 json_required (also POST /api/session)', tp.status === 415 && tp.data.code === 'json_required' && fo.status === 415 && se.status === 415);
  check('SEC-01: foreign Origin, Origin null, Sec-Fetch-Site same-site -> 403 cross_origin (writes, session, delete)', or.status === 403 && or.data.code === 'cross_origin' && ss.status === 403 && nu.status === 403 && se2.status === 403 && de.status === 403);
  const good = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, Origin: `http://127.0.0.1:${port}`, 'Sec-Fetch-Site': 'same-origin' } });
  const noBody = await rawReq('POST', `/api/people/${V4.T41lead}/move`, { headers: { ...W } });
  check('SEC-01: same-origin JSON write -> 201; an empty body without Content-Type is still fine (400 validation, not 415)', good.status === 201 && noBody.status === 400, JSON.stringify([good.status, noBody.status]));
  check('SEC-01: no follow-up written by the refused requests', db.prepare("SELECT COUNT(*) n FROM followups WHERE title = 'v41 csrf'").get().n === 1);
  if (good.data?.id) await api('DELETE', `/api/followups/${good.data.id}`, undefined, W);
});
await step('Cloud Run behind Firebase Hosting: TRUST_PROXY, X-Forwarded-Host, allowed hosts', async () => {
  const J = { 'Content-Type': 'application/json', ...W };
  const b = { scope_type: 'college', scope_id: V4.A, title: 'proxy csrf' };
  const site = 'https://techdrona-colleges-data.web.app';
  const fwd = { Host: 'techdrona-portal-xyz.a.run.app', 'X-Forwarded-Host': 'techdrona-colleges-data.web.app', 'X-Forwarded-Proto': 'https', Origin: site };
  process.env.PORTAL_ALLOWED_HOSTS = 'techdrona-colleges-data.web.app,techdrona-portal-xyz.a.run.app';
  const noTrust = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, ...fwd } });
  process.env.TRUST_PROXY = '1';
  const viaProxy = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, ...fwd } });
  const evilOrigin = await rawReq('POST', '/api/followups', { body: b, headers: { ...J, ...fwd, Origin: 'https://evil.example' } });
  const evilFwd = await rawReq('GET', '/api/health', { headers: { Host: 'evil.example', 'X-Forwarded-Host': 'evil.example' } });
  const ses = await rawReq('POST', '/api/session', { body: { name: 'Proxy User' }, headers: { 'Content-Type': 'application/json', ...fwd } });
  delete process.env.TRUST_PROXY; delete process.env.PORTAL_ALLOWED_HOSTS;
  check('proxy: without TRUST_PROXY a web.app Origin on the run.app Host is refused (403)', noTrust.status === 403);
  check('proxy: with TRUST_PROXY=1 a write from the allowed web.app origin passes; a foreign origin / host is still refused', viaProxy.status === 201 && evilOrigin.status === 403 && evilFwd.status === 403, JSON.stringify([viaProxy.status, evilOrigin.status, evilFwd.status]));
  check('proxy: session cookie is __session and Secure behind https', /^__session=[^;]+;.*Secure/.test(String(ses.headers['set-cookie'])));
  const api1 = await rawReq('GET', '/api/health');
  check('API responses are Cache-Control: no-store (the Hosting CDN never caches data)', /no-store/.test(String(api1.headers['cache-control'])));
  if (viaProxy.data?.id) await api('DELETE', `/api/followups/${viaProxy.data.id}`, undefined, W);
  check('proxy: no test follow-up left behind', db.prepare("SELECT COUNT(*) n FROM followups WHERE title = 'proxy csrf'").get().n === 0);
});
await step('v4.1 SEC-03 canonical scope ids on write; delete guard sees them', async () => {
  const p = (await person({ college_id: V4.T41, role: 'ambassador', full_name: 'V41 Canon', phone: mob() })).data;
  const f = await api('POST', '/api/followups', { scope_type: 'person', scope_id: `00${p.id}`, title: 'v41 canon' }, W);
  const fc = await api('POST', '/api/followups', { scope_type: 'college', scope_id: ` ${V4.T41.toUpperCase()} `, title: 'v41 canon college' }, W);
  const d = await api('DELETE', `/api/people/${p.id}`, undefined, W);
  check('SEC-03: "00<id>" stored as "<id>", " C<n> " as "c<n>"; deleting the person -> 409 linked_records', f.data.scope_id === String(p.id) && fc.data.scope_id === V4.T41 && d.status === 409 && d.data.code === 'linked_records', JSON.stringify([f.data.scope_id, fc.data.scope_id, d.status]));
  const t = await api('PUT', '/api/targets', { scope_type: 'college', scope_id: V4.T41.toUpperCase(), target: 5 }, W);
  check('SEC-03: target college ids canonicalised too', t.status === 200 && t.data.scope_id === V4.T41, JSON.stringify(t.data).slice(0, 200));
  check('SEC-03: integrity followups_noncanonical_scope = 0', (await get('/api/quality')).data.integrity.followups_noncanonical_scope === 0);
  for (const x of [f.data.id, fc.data.id]) await api('DELETE', `/api/followups/${x}`, undefined, W);
  if (t.data?.id) await api('DELETE', `/api/targets/${t.data.id}`, undefined, W);
  // migration: a legacy non-canonical row is fixed when the DB is opened again
  db.prepare("INSERT INTO followups(scope_type, scope_id, title, status) VALUES ('person', ?, 'v41 legacy', 'open')").run(`000${V4.T41lead}`);
  const db2 = openDb(dbPath);
  const fixed = db2.prepare("SELECT scope_id FROM followups WHERE title = 'v41 legacy'").get().scope_id; db2.close();
  check('SEC-03: migration canonicalises existing rows (audited)', fixed === String(V4.T41lead));
  db.prepare("DELETE FROM followups WHERE title = 'v41 legacy'").run();
});
await step('v4.1 SEC-05 / SEC-06 prototype names', async () => {
  const st = []; for (const p of ['/api/constructor', '/api/__proto__', '/api/toString', '/api/hasOwnProperty']) st.push((await api('POST', p, {}, W)).status);
  const s1 = await rawReq('PATCH', '/api/settings', { body: '{"__proto__":1}', headers: { 'Content-Type': 'application/json', ...W } });
  const s2 = await api('PATCH', '/api/settings', { hasOwnProperty: 1 }, W);
  const s3 = await api('PATCH', '/api/settings/isPrototypeOf', { value: 1 }, W);
  check('SEC-05: POST /api/constructor, __proto__, toString, hasOwnProperty -> 404 (not 500)', st.every((x) => x === 404), JSON.stringify(st));
  check('SEC-06: settings keys __proto__ / hasOwnProperty / isPrototypeOf -> 400 Unknown setting, nothing stored', s1.status === 400 && s2.status === 400 && s3.status === 400
    && !db.prepare("SELECT 1 FROM settings WHERE key IN ('__proto__','hasOwnProperty','isPrototypeOf')").get());
  db.prepare("INSERT INTO settings(key, value) VALUES ('hasOwnProperty', '1') ON CONFLICT(key) DO NOTHING").run();
  const g = (await get('/api/settings')).data;
  const db2 = openDb(dbPath); const left = db2.prepare("SELECT 1 FROM settings WHERE key = 'hasOwnProperty'").get(); db2.close();
  check('SEC-06: a junk settings row never shadows a method, and the migration deletes it', typeof g.hasOwnProperty === 'function' && !left);
});
await step('v4.1 SEC-08..SEC-13 input limits, reserved names, sessions', async () => {
  const e1 = await api('POST', '/api/enrollments', { college_id: V4.T41, student_name: 'V41 Huge', amount_inr: 1e300, enrolled_on: '2026-11-01' }, W);
  const e2 = await api('POST', '/api/courses', { name: 'V41 Course', price_inr: 10000001 }, W);
  check('SEC-08: amount_inr / price_inr above 1,00,00,000 -> 400', e1.status === 400 && e1.data.fields?.amount_inr && e2.status === 400);
  const pg = (await get('/api/program')).data;
  const p1 = await api('PATCH', '/api/program', { start: '2027-12-01' }, W);
  const p2 = await api('PATCH', '/api/program', { deadline: '2026-01-01' }, W);
  check('SEC-09: programme start after the deadline (either side) -> 400; nothing changed', p1.status === 400 && p1.data.fields?.start && p2.status === 400 && p2.data.fields?.deadline && (await get('/api/program')).data.start === pg.start);
  const rs = []; for (const u of ['seed​', 'ｓｅｅｄ', ' S E E D ', 'seed.', 'Import-Research', '...']) rs.push((await api('POST', '/api/followups', { scope_type: 'college', scope_id: V4.A, title: 'v41 reserved' }, { 'X-User': encodeURIComponent(u) })).status);
  check('SEC-10: reserved-name look-alikes (zero-width, full-width, spaced, dotted) and names without letters -> 400', rs.every((x) => x === 400), JSON.stringify(rs));
  const n1 = await person({ college_id: V4.T41, role: 'ambassador', full_name: '​' });
  const n2 = await person({ college_id: V4.T41, role: 'ambassador', full_name: '...' });
  const n3 = await person({ college_id: V4.T41, role: 'ambassador', full_name: true });
  check('SEC-11 / BE-18: full_name zero-width only / no letter / boolean -> 400', n1.status === 400 && n2.status === 400 && n3.status === 400, JSON.stringify([n1.status, n2.status, n3.status]));
  const t1 = await api('POST', '/api/session', { name: { a: 1 } });
  const t2 = await api('POST', '/api/session', { name: 'x'.repeat(81) });
  check('SEC-12: session name must be a string of at most 80 characters', t1.status === 400 && t2.status === 400);
  const untrusted = await rawReq('POST', '/api/session', { body: { name: 'V41 Https' }, headers: { 'Content-Type': 'application/json', 'X-Forwarded-Proto': 'https' } });
  process.env.TRUST_PROXY = '1';
  const sec = await rawReq('POST', '/api/session', { body: { name: 'V41 Https' }, headers: { 'Content-Type': 'application/json', 'X-Forwarded-Proto': 'https' } });
  delete process.env.TRUST_PROXY;
  const pla = await rawReq('POST', '/api/session', { body: { name: 'V41 Http' }, headers: { 'Content-Type': 'application/json' } });
  check('SEC-13: cookie Secure only over https (X-Forwarded-Proto trusted only with TRUST_PROXY=1)', /;\s*Secure/.test(String(sec.headers['set-cookie'])) && !/Secure/.test(String(pla.headers['set-cookie'])) && !/Secure/.test(String(untrusted.headers['set-cookie'])));
  check('session cookie is named __session (the only cookie Firebase Hosting forwards to Cloud Run)', /^__session=/.test(String(pla.headers['set-cookie'])));
  const first = /__session=([^;]+)/.exec(String(pla.headers['set-cookie']))[1];
  for (let i = 0; i < 500; i++) await rawReq('POST', '/api/session', { body: { name: `V41 Cap ${i}` }, headers: { 'Content-Type': 'application/json' } });
  const chk = await rawReq('GET', '/api/session', { headers: { Cookie: `__session=${first}` } });
  check('SEC-13: sessions are capped at 500 (oldest evicted)', chk.data.authenticated === false);
});
await step('v4.1 D1 plan totals count every college in scope', async () => {
  const pl = (await get(`/api/plan?districts=${V4.district}`)).data;
  const sqlLeads = db.prepare("SELECT COUNT(*) n FROM people p JOIN colleges c ON c.id = p.college_id WHERE c.district_id = ? AND p.role = 'college_lead' AND p.status <> 'inactive'").get(V4.district).n;
  const ta = pl.totals_actual;
  check('D1: totals_actual.college_leads = every active lead in scope (incl. colleges outside the plan) = in_plan + outside_plan', ta.college_leads === sqlLeads && sqlLeads >= 1
    && ta.in_plan.college_leads + ta.outside_plan.college_leads === ta.college_leads && ta.outside_plan.college_leads >= 1, JSON.stringify({ ta: { cl: ta.college_leads, ip: ta.in_plan.college_leads, op: ta.outside_plan.college_leads }, sqlLeads }));
});
await step('v4.1 D2 programme target applies only to selections covering the programme districts', async () => {
  const prog = (await get('/api/program')).data;
  const all = prog.target_district_ids.join(',');
  // a non-programme district without any target inside (the V4 scenario district has college targets: tested separately below)
  const other = (await get('/api/meta')).data.districts.find((d) => !prog.target_district_ids.includes(d.id) && d.id !== V4.district
    && !db.prepare("SELECT 1 FROM targets t LEFT JOIN colleges c ON c.id = t.scope_id LEFT JOIN cities ci ON ci.id = t.scope_id WHERE t.scope_id = ? OR c.district_id = ? OR ci.district_id = ?").get(d.id, d.id, d.id)).id;
  const td = (await get(`/api/target-dashboard?scope=state&districts=${other}`)).data;
  check('D2: target-dashboard for a non-programme district -> target null, reason, programme_target kept', td.target === null && td.program.target === null && td.program.programme_target === prog.target && /covers the/.test(td.target_reason || '') && td.remaining === null && td.pct === null, JSON.stringify({ t: td.target, p: td.program, r: td.target_reason }));
  const pf = (await get(`/api/performance?level=state&districts=${other}`)).data;
  check('D2: performance state row + programme block for that district -> target null + reason', pf.rows[0].target === null && pf.programme.target === null && /covers the/.test(pf.programme.target_reason || '') && pf.programme.programme_target === prog.target, JSON.stringify(pf.programme));
  const sm = (await get(`/api/summary?scope=state&districts=${other}`)).data;
  check('D2: summary of that selection does not inherit the programme target', sm.target_source !== 'explicit' && /covers the/.test(sm.target_reason || ''));
  const own = (await get(`/api/target-dashboard?scope=state&districts=${V4.district}`)).data;
  const ownS = (await get(`/api/summary?scope=state&districts=${V4.district}`)).data;
  check('D2: a non-programme district WITH its own college targets shows those (rolled up, with covers), never the programme 400', own.program.target === null && own.target === ownS.target && own.target !== prog.target && ownS.target_source === 'sum_of_children' && !!own.covers, JSON.stringify({ t: own.target, s: ownS.target }));
  const full = (await get(`/api/target-dashboard?scope=state&districts=${all}`)).data;
  const sup = (await get(`/api/performance?level=state&districts=${all},${other}`)).data;
  const none = (await get('/api/performance?level=state')).data;
  check('D2: the full programme selection (or a superset, or no filter) -> the programme target', full.target === prog.target && full.program.target === prog.target && sup.programme.target === prog.target && sup.rows[0].target === prog.target && none.programme.target === prog.target);
});
await step('v4.1 D3 field messages keep proper names', async () => {
  const other = db.prepare("SELECT id FROM people WHERE college_id <> ? AND status <> 'inactive' AND full_name GLOB '[A-Z]*' LIMIT 1").get(V4.T41);
  const r = await api('POST', '/api/enrollments', { college_id: V4.T41, person_id: other.id, student_name: 'V41 Cross', enrolled_on: '2026-11-01' }, W);
  const nm = db.prepare('SELECT full_name FROM people WHERE id = ?').get(other.id).full_name;
  const r2 = await api('POST', '/api/followups', { scope_type: 'person', scope_id: '999999', title: 'x' }, W);
  check('D3: "Person: <Name as typed> belongs to …" (not lower-cased); label words still lower-cased ("Scope: unknown person")', r.status === 400 && r.data.error.includes(`Person: ${nm} belongs`) && /Scope: unknown person/.test(r2.data.error), r.data.error);
});

server.close();
db.close();
try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch { /* Windows may hold the WAL briefly */ }

const pass = results.filter((r) => r.ok).length;
for (const r of results) console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${!r.ok && r.detail ? `\n      ${String(r.detail).split('\n').slice(0, 6).join('\n      ')}` : ''}`);
console.log(`\n${pass}/${results.length} passed`);
process.exit(pass === results.length ? 0 : 1);
