// Calling system: contact status, derived college call status, the internal priority score, the calling queue and the
// target dashboard (CONTRACT.md "Calling system"). Pure functions over a rollup context plus a few grouped queries.
import { addDays, daysBetween, summary, scopeColleges, scopePeople, personRollup, scopeFunnel, hrefFor, scopeLabel, STAGES } from './rollup.js';

export const CONTACT_ROLES = ['tpo', 'principal', 'hod', 'office', 'admissions', 'dean', 'other'];
export const CONTACT_STATUSES = ['untested', 'working', 'non_working', 'invalid'];
export const CALL_OUTCOMES = ['connected_interested', 'connected_callback', 'connected_not_interested', 'connected_info_only',
  'no_answer', 'busy', 'switched_off', 'not_reachable', 'wrong_number', 'invalid_number', 'disconnected'];
export const CONNECTED = new Set(['connected_interested', 'connected_callback', 'connected_not_interested', 'connected_info_only']);
/** attempts that reached nobody but say nothing about the number itself */
export const UNANSWERED = new Set(['no_answer', 'busy', 'switched_off', 'not_reachable']);
export const CALL_STATUSES = ['not_called', 'attempted_no_answer', 'follow_up_due', 'contacted', 'interested', 'participation_confirmed', 'enrolled'];
export const PRIORITY_TIERS = ['high', 'medium', 'low'];
export const CONTACT_FILTERS = ['working', 'non_working', 'untested', 'none'];
export const QUEUE_FILTERS = ['all', 'working', 'high', 'pending', 'invalid', 'interested', 'confirmed'];
export { STAGES };

/**
 * Contact status from its call history (calls ordered oldest first). Returns null when the calls say nothing (keep stored).
 * - the latest *decisive* call wins: connected_* -> working; wrong_number / invalid_number -> invalid; disconnected -> non_working;
 * - unless, after the last connected call, there are >= `unreachableAfter` unanswered attempts in a row
 *   (no_answer / busy / switched_off / not_reachable) -> non_working ("unreachable").
 */
export function statusFromCalls(calls, unreachableAfter = 6) {
  let status = null; let streak = 0;
  for (const c of calls) {
    if (CONNECTED.has(c.outcome)) { status = 'working'; streak = 0; } else if (c.outcome === 'wrong_number' || c.outcome === 'invalid_number') { status = 'invalid'; streak = 0; } else if (c.outcome === 'disconnected') { status = 'non_working'; streak = 0; } else if (UNANSWERED.has(c.outcome)) streak++;
  }
  const n = Number(unreachableAfter);
  if (n > 0 && streak >= n && status !== 'invalid') return { status: 'non_working', unreachable: true, streak };
  return status ? { status, unreachable: false, streak } : (streak ? { status: null, unreachable: false, streak } : null);
}

// ------------------------------------------------------------------------------------------------ lazy per-context index
export function callsCtx(ctx) {
  if (ctx._calls) return ctx._calls;
  const db = ctx.db;
  const contacts = db.prepare('SELECT * FROM contacts ORDER BY id').all();
  const calls = db.prepare('SELECT * FROM calls ORDER BY called_at, id').all();
  const group = (rows, key) => { const m = new Map(); for (const r of rows) { const k = r[key]; if (k == null) continue; let a = m.get(k); if (!a) m.set(k, (a = [])); a.push(r); } return m; };
  ctx._calls = {
    contacts, calls,
    contactById: new Map(contacts.map((c) => [c.id, c])),
    contactsByCollege: group(contacts, 'college_id'),
    callsByCollege: group(calls, 'college_id'),
    callsByContact: group(calls, 'contact_id'),
    openFu: new Map(ctx.openFollowups.map((f) => [f.id, f])),
    info: new Map(),
  };
  return ctx._calls;
}

const ROLE_RANK = { tpo: 0, admissions: 1, principal: 2, dean: 3, hod: 4, office: 5, other: 6 };
const STATUS_RANK = { working: 0, untested: 1, non_working: 2, invalid: 3 };
/** Best contact to call: working before untested, verified before pending, then role (TPO first), never invalid/non-working. */
export function bestContact(contacts) {
  const ok = contacts.filter((c) => (c.status === 'working' || c.status === 'untested') && c.phone);
  ok.sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || (a.basis === 'verified' ? 0 : 1) - (b.basis === 'verified' ? 0 : 1)
    || (ROLE_RANK[a.role] ?? 9) - (ROLE_RANK[b.role] ?? 9) || a.id - b.id);
  return ok[0] || null;
}
export const contactLite = (c) => c && ({ id: c.id, name: c.name, role: c.role, phone: c.phone, email: c.email, status: c.status, basis: c.basis, branch_id: c.branch_id, source_url: c.source_url });

/** Everything the calling system knows about one college. Memoised per context. */
export function collegeCallInfo(ctx, c) {
  const K = callsCtx(ctx);
  if (K.info.has(c.id)) return K.info.get(c.id);
  const contacts = K.contactsByCollege.get(c.id) || [];
  const calls = K.callsByCollege.get(c.id) || [];
  const counts = { total: contacts.length, working: 0, non_working: 0, invalid: 0, untested: 0, verified: 0 };
  for (const x of contacts) { counts[x.status] = (counts[x.status] || 0) + 1; if (x.basis === 'verified') counts.verified++; }
  const last = calls.length ? calls[calls.length - 1] : null;
  let lastConnected = null; for (let i = calls.length - 1; i >= 0; i--) if (CONNECTED.has(calls[i].outcome)) { lastConnected = calls[i]; break; }
  const callFus = calls.map((x) => x.followup_id && K.openFu.get(x.followup_id)).filter(Boolean);
  const dueFus = callFus.filter((f) => f.due_date).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const nextFu = dueFus[0] || callFus[0] || null;
  const enrolled = summary(ctx, { type: 'college', id: c.id }).enrolled;
  let status;
  if (enrolled > 0) status = 'enrolled';
  else if (c.participation_confirmed_on) status = 'participation_confirmed';
  else if (lastConnected?.outcome === 'connected_interested') status = 'interested';
  else if (dueFus.some((f) => f.due_date <= ctx.today)) status = 'follow_up_due';
  else if (lastConnected) status = 'contacted';
  else if (calls.length) status = 'attempted_no_answer';
  else status = 'not_called';
  const today = ctx.today; const weekAgo = addDays(today, -6);
  const out = {
    call_status: status, contact_counts: counts, best_contact: contactLite(bestContact(contacts)),
    last_call: last ? { id: last.id, called_at: last.called_at, outcome: last.outcome, caller: last.caller, contact_id: last.contact_id, notes: last.notes } : null,
    last_connected_outcome: lastConnected ? lastConnected.outcome : null,
    calls_total: calls.length,
    calls_today: calls.filter((x) => String(x.called_at).slice(0, 10) === today).length,
    calls_7d: calls.filter((x) => String(x.called_at).slice(0, 10) >= weekAgo && String(x.called_at).slice(0, 10) <= today).length,
    next_action: nextFu ? { followup_id: nextFu.id, title: nextFu.title, due_date: nextFu.due_date, overdue: !!nextFu.due_date && nextFu.due_date < today, due: !!nextFu.due_date && nextFu.due_date <= today } : null,
    enrolled_confirmed: enrolled,
    participation_confirmed_on: c.participation_confirmed_on || null,
  };
  out.priority = priority(ctx, c, out);
  K.info.set(c.id, out);
  return out;
}

// ------------------------------------------------------------------------------------------------ priority
// Internal calling priority (0-100). Only shown in the calling queue. Real fields only; see CONTRACT.md.
const ELIGIBLE_CAP = 1000; // eligible students at which "potential" maxes out (~75th percentile of colleges with data)
const EXAM_POINTS = { clear: 15, unknown: 8, exams_soon: 5, in_exams: 0 };
const EXAM_TEXT = { clear: 'no exams in the next 14 days — outreach window open', unknown: 'exam dates unknown', exams_soon: 'exams start within 14 days', in_exams: 'students are writing exams now' };
const TIER_POINTS = { 'tier 1': 10, 'tier 2': 7, 'tier 3': 4 };
const NAAC_POINTS = { 'A++': 10, 'A+': 9, A: 8, 'B++': 6, 'B+': 5, B: 4, C: 2 };
export function tierFor(score) { return score >= 60 ? 'high' : score >= 40 ? 'medium' : 'low'; }
function naacGrade(text) { const m = /(?:^|[^A-Za-z+])(A\+\+|A\+|A|B\+\+|B\+|B|C)(?![A-Za-z])/.exec(String(text || '')); return m ? m[1] : null; }

export function priority(ctx, c, info) {
  const s = summary(ctx, { type: 'college', id: c.id });
  const parts = [];
  // 1. potential: eligible final-year students (relevance-weighted), 0-40
  const ev = s.eligible?.value;
  parts.push({ key: 'potential', label: 'Student potential', max: 40, points: ev == null ? 0 : Math.round(40 * Math.min(1, ev / ELIGIBLE_CAP)),
    basis: ev == null ? 'pending' : s.eligible.basis, estimated: s.eligible?.basis === 'estimated',
    detail: ev == null ? 'eligible students not known yet (branch intake pending)' : `≈ ${ev.toLocaleString('en-IN')} eligible final-year students${s.eligible.basis === 'estimated' ? ' (estimated from intake)' : ''}` });
  // 2. contact reliability, 0-20
  const k = callsCtx(ctx).contactsByCollege.get(c.id) || [];
  const has = (st, b) => k.some((x) => x.status === st && x.phone && (!b || x.basis === b));
  let cp = 0; let cd = 'no callable contact on record';
  if (has('working', 'verified')) { cp = 20; cd = 'a verified number answered'; } else if (has('working')) { cp = 15; cd = 'a number answered (source not verified)'; } else if (has('untested', 'verified')) { cp = 10; cd = 'verified number, not called yet'; } else if (has('untested')) { cp = 6; cd = 'number not called yet (source pending)'; } else if (k.length) cd = 'only non-working / invalid numbers';
  parts.push({ key: 'contact', label: 'Contact reliability', max: 20, points: cp, detail: cd });
  // 3. exam window, 0-15
  const ex = ctx.exam.get(c.id)?.exam_state || 'unknown';
  parts.push({ key: 'exams', label: 'Outreach window', max: 15, points: EXAM_POINTS[ex] ?? 8, detail: EXAM_TEXT[ex] || ex });
  // 4. college standing (tier from the master list, NAAC grade text), 0-10
  const tp = TIER_POINTS[String(c.tier || '').trim().toLowerCase()] ?? null;
  const g = naacGrade(c.naac); const np = g ? NAAC_POINTS[g] : null;
  const qp = Math.max(tp ?? 0, np ?? 0);
  parts.push({ key: 'standing', label: 'College standing', max: 10, points: qp, estimated: !!(c.naac && /aggregator|unverified|claimed|conflict/i.test(c.naac)),
    detail: [c.tier ? `${c.tier}` : null, g ? `NAAC ${g}${/aggregator|unverified|claimed|conflict/i.test(c.naac) ? ' (from listings, unverified)' : ''}` : null].filter(Boolean).join(' · ') || 'tier / NAAC not recorded' });
  // 5. engagement so far, 0-15
  const ENG = { enrolled: [15, 'students already confirmed'], participation_confirmed: [15, 'college confirmed participation'], interested: [15, 'last conversation: interested'],
    follow_up_due: [12, 'a call-back is due'], attempted_no_answer: [3, 'called, no answer yet'], not_called: [5, 'not called yet'] };
  let ep; let ed;
  if (info.call_status === 'contacted') {
    const o = info.last_connected_outcome;
    [ep, ed] = o === 'connected_callback' ? [10, 'asked us to call back'] : o === 'connected_info_only' ? [6, 'took information only'] : o === 'connected_not_interested' ? [0, 'said not interested'] : [6, 'spoken to'];
  } else [ep, ed] = ENG[info.call_status] || [0, ''];
  parts.push({ key: 'engagement', label: 'Engagement so far', max: 15, points: ep, detail: ed });
  const score = parts.reduce((a, p) => a + p.points, 0);
  return { score, tier: tierFor(score), parts, has_estimates: parts.some((p) => p.estimated) };
}

// ------------------------------------------------------------------------------------------------ queue
export function matchesQueueFilter(info, f) {
  const cc = info.contact_counts;
  switch (f) {
    case 'working': return cc.working > 0;
    case 'high': return info.priority.tier === 'high';
    case 'pending': return ['not_called', 'attempted_no_answer', 'follow_up_due'].includes(info.call_status) || !!info.next_action?.due;
    case 'invalid': return cc.non_working + cc.invalid > 0;
    case 'interested': return info.call_status === 'contacted' || info.call_status === 'interested';
    case 'confirmed': return info.call_status === 'participation_confirmed' || info.call_status === 'enrolled';
    default: return true;
  }
}
export function contactFilter(info, f) {
  const cc = info.contact_counts;
  if (f === 'working') return cc.working > 0;
  if (f === 'non_working') return cc.non_working + cc.invalid > 0;
  if (f === 'untested') return cc.untested > 0;
  if (f === 'none') return cc.total === 0;
  return true;
}

export function queueRow(ctx, c) {
  const info = collegeCallInfo(ctx, c);
  return {
    college_id: c.id, sno: c.sno, name: c.name, short_name: c.short_name, district_id: c.district_id, city_id: c.city_id,
    district_name: ctx.districts.get(c.district_id)?.name ?? null, city_name: ctx.cities.get(c.city_id)?.name ?? null,
    op_status: c.op_status, targeted: c.targeted, exam_state: ctx.exam.get(c.id)?.exam_state || 'unknown', href: hrefFor(ctx, 'college', c.id),
    ...info,
  };
}

// ------------------------------------------------------------------------------------------------ target dashboard
/** SQL fragment restricting a table with college_id / branch_id / person_id columns to a scope. */
export function scopeWhere(ctx, sc, alias = '') {
  const a = alias ? `${alias}.` : '';
  if (sc.type === 'state' && !sc.districts) return { where: '', params: [] };
  if (sc.type === 'branch' && !sc.districts) return { where: `AND ${a}branch_id = ?`, params: [Number(sc.id)] };
  if (sc.type === 'person' && !sc.districts) return { where: `AND ${a}person_id = ?`, params: [Number(sc.id)] };
  if (sc.type === 'branch' || sc.type === 'person') {
    const ok = scopeColleges(ctx, sc).length > 0; // the branch's / person's college is inside the district filter
    return ok ? { where: `AND ${a}${sc.type}_id = ?`, params: [Number(sc.id)] } : { where: 'AND 0', params: [] };
  }
  const ids = scopeColleges(ctx, sc).map((c) => c.id);
  return ids.length ? { where: `AND ${a}college_id IN (${ids.map(() => '?').join(',')})`, params: ids } : { where: 'AND 0', params: [] };
}

export const STAGE_LABEL = { lead: 'Lead', interested: 'Interested', registered: 'Registered', applied: 'Applied', confirmed: 'Confirmed enrollment', dropped: 'Dropped / refunded' };

export function funnelOut(ctx, sc) {
  const f = scopeFunnel(ctx, sc);
  return {
    scope: sc.type === 'state' ? 'state' : `${sc.type}:${sc.id}`, label: scopeLabel(ctx, sc),
    stages: STAGES.map((k) => ({ stage: k, label: STAGE_LABEL[k], count: f[k], counts_toward_target: k === 'confirmed' })),
    total: f.total, active: f.active, confirmed: f.confirmed, dropped: f.dropped,
    note: 'Each student record is counted once, at its current stage. Only confirmed enrollments count toward targets.',
  };
}

/**
 * Target dashboard. `program` (optional, from GET /api/target-dashboard?districts=…): {target, deadline, selected_districts,
 * is_default_selection, …}. For the state scope the program target and deadline then replace the rollup's (target_source
 * 'program'); confirmed counts only the selected districts (sc.districts).
 */
export function targetDashboard(ctx, sc, program = null) {
  const db = ctx.db;
  const s = sc.type === 'person' ? personRollup(ctx, sc.id) : summary(ctx, sc);
  const today = ctx.today;
  const useProgram = !!program && sc.type === 'state' && program.target != null;
  const target = useProgram ? program.target : (s.target ?? null);
  // v4 (R10): a rolled-up target is compared with the actual of the children that have a target (s.actual_against_target)
  const confirmed = sc.type === 'person' && sc.districts && !scopeColleges(ctx, sc).length ? 0 : (!useProgram && s.actual_against_target != null ? s.actual_against_target : s.enrolled);
  // v4.1 (F3/D2): a rolled-up target that does not cover the whole scope is shown, never judged
  const partial = !useProgram && target != null && s.pace_status === 'partial_target';
  const remaining = target == null || partial ? null : Math.max(target - confirmed, 0);
  const deadline = (useProgram ? program.deadline : null) || s.deadline || null;
  const daysLeft = deadline ? (daysBetween(today, deadline) ?? -1) + 1 : null; // including today
  const weeksLeft = daysLeft != null && daysLeft > 0 ? daysLeft / 7 : null;
  const { where, params } = scopeWhere(ctx, sc);
  const from14 = addDays(today, -13);
  const recent = Number(db.prepare(`SELECT COUNT(*) n FROM enrollments WHERE stage = 'confirmed' AND COALESCE(confirmed_on, enrolled_on) BETWEEN ? AND ? ${where}`).get(from14, today, ...params).n);
  const pace14 = recent / 14;
  let projection;
  if (target == null) projection = { date: null, status: 'no_target', explanation: s.target_reason || program?.target_reason || 'No target is set for this scope yet, so there is nothing to project.' };
  else if (partial) projection = { date: null, status: 'partial_target', explanation: `Only ${s.covers?.with_target ?? 0} of ${s.covers?.total ?? 0} parts of this scope have a target, so there is nothing to project.` };
  else if (target === 0) projection = { date: null, status: 'zero_target', explanation: 'The target is set to 0, so there is nothing to project.' };
  else if (remaining === 0) projection = { date: null, status: 'achieved', explanation: 'The target is already reached.' };
  else if (pace14 > 0) {
    const days = Math.ceil(remaining / pace14);
    const date = addDays(today, days);
    projection = { date, days, status: deadline && date > deadline ? 'after_deadline' : 'on_or_before_deadline',
      explanation: `At the last 14 days' pace (${recent} confirmed, ${(pace14 * 7).toFixed(1)} a week) the remaining ${remaining} take about ${days} days.` };
  } else projection = { date: null, status: 'no_recent_pace', explanation: 'No confirmed enrollments in the last 14 days, so there is no pace to project from yet.' };

  // contacts and calls in scope
  const cols = sc.type === 'person' ? scopeColleges(ctx, sc) : scopeColleges(ctx, sc);
  const contacts = { total: 0, working: 0, non_working: 0, invalid: 0, untested: 0, colleges_with_working: 0, colleges_without_contact: 0 };
  const calls = { today: 0, last_7d: 0, total: 0, colleges_called: 0 };
  const pending = { callbacks_due: 0, callbacks_scheduled: 0, never_called: 0 };
  const byStatus = Object.fromEntries(CALL_STATUSES.map((k) => [k, 0]));
  for (const c of cols) {
    const i = collegeCallInfo(ctx, c);
    for (const k of ['total', 'working', 'non_working', 'invalid', 'untested']) contacts[k] += i.contact_counts[k];
    if (i.contact_counts.working) contacts.colleges_with_working++;
    if (!i.contact_counts.total) contacts.colleges_without_contact++;
    calls.today += i.calls_today; calls.last_7d += i.calls_7d; calls.total += i.calls_total; if (i.calls_total) calls.colleges_called++;
    if (c.op_status !== 'closed') byStatus[i.call_status]++;
    // same population as the default calling queue (GET /api/calls/queue: operational colleges only)
    if (!i.calls_total && c.op_status === 'operational') pending.never_called++;
  }
  // call-backs: open follow-ups created by a logged call, in scope
  const K = callsCtx(ctx); const colSet = new Set(cols.map((c) => c.id));
  const seen = new Set();
  for (const x of K.calls) {
    if (!x.followup_id || seen.has(x.followup_id) || !colSet.has(x.college_id)) continue;
    const f = K.openFu.get(x.followup_id); if (!f) continue; seen.add(f.id);
    if (f.due_date && f.due_date <= today) pending.callbacks_due++; else pending.callbacks_scheduled++;
  }
  const people = scopePeople(ctx, sc).filter((p) => p.status !== 'inactive').map((p) => {
    const r = personRollup(ctx, p.id); const c = ctx.colleges.get(p.college_id);
    return { id: p.id, full_name: p.full_name, role: p.role, college_id: p.college_id, college_label: c?.short_name || c?.name || null, href: r.href,
      confirmed: r.enrolled, target: r.target, in_pipeline: r.funnel.active, reached: r.reached };
  }).sort((a, b) => b.confirmed - a.confirmed || b.in_pipeline - a.in_pipeline || String(a.full_name).localeCompare(String(b.full_name)));
  return {
    scope: sc.type === 'state' ? 'state' : `${sc.type}:${sc.id}`, label: s.label, today,
    target, target_source: useProgram ? 'program' : s.target_source, deadline, confirmed, remaining,
    // v4.1: status of the comparison; covers when the target is a partial roll-up; reason when the programme target does not apply
    target_status: target == null ? 'no_target' : partial ? 'partial_target' : 'judged',
    covers: useProgram ? null : (s.covers ?? null), target_reason: target == null ? (program?.target_reason || s.target_reason || null) : null,
    ...(program ? { program: { ...program, confirmed, remaining: program.target == null ? null : Math.max(program.target - confirmed, 0), pct: program.target ? confirmed / program.target : null } } : {}),
    pct: target && !partial ? confirmed / target : null,
    days_left: daysLeft,
    required_daily: remaining != null && daysLeft > 0 ? remaining / daysLeft : null,
    required_weekly: remaining != null && weeksLeft ? remaining / weeksLeft : null,
    deadline_passed: daysLeft != null && daysLeft <= 0,
    recent_window_days: 14, confirmed_last_14d: recent,
    current_daily: pace14, current_weekly: pace14 * 7,
    projection,
    funnel: funnelOut(ctx, sc),
    contacts, calls, pending_calls: pending, colleges_by_call_status: byStatus,
    followups_due: (s.followups_overdue || 0) + countDueToday(ctx, sc),
    followups_overdue: s.followups_overdue || 0,
    people: people.slice(0, 10), people_total: people.length,
  };
}
function countDueToday(ctx, sc) {
  const cols = new Set(scopeColleges(ctx, sc).map((c) => c.id));
  let n = 0;
  for (const f of ctx.openFollowups) {
    if (f.due_date !== ctx.today) continue;
    const cid = f.scope_type === 'college' ? f.scope_id : f.scope_type === 'branch' ? ctx.branches.get(Number(f.scope_id))?.college_id : ctx.people.get(Number(f.scope_id))?.college_id;
    if ((sc.type === 'state' && !sc.districts) || cols.has(cid)) n++;
  }
  return n;
}
