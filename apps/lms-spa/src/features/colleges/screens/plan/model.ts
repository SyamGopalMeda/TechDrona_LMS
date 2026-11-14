/* eslint-disable @typescript-eslint/no-explicit-any -- verbatim port of js/plan/model.js; rows are the loosely typed /api/plan colleges */
// Tech Drona portal — 400-target planner model, ported verbatim from apps/college-data/portal/public/js/plan/model.js
// (types added only). Pure module: no DOM.
//
// It re-implements the research formula of compute_v2.py (research v2, 7 Nov 2026) so that the research
// defaults reproduce the published totals exactly (377 / 655 / 1,143 paid enrollments, 299 ambassadors,
// 64 College Leads for the 84 targeted colleges). Every input is an ASSUMPTION the user can change; nothing
// here is measured. Inputs are PlanCollege rows from GET /api/plan (see build SPEC).
//
//   per college  V[i] = round( k[type][i] × x × ( RF[i]·F + w·RT[i]·T + w·RS[i]·S ) )   i = min, avg, max
//                F/T/S = IT final-year / 3rd-year / 2nd-year students (a year group switched off counts 0)
//                x = contact factor (access_x: 1.0 verified TPO line, 0.8 office line, 0.6 none), w = 0.5
//                floor: F > 0 and x ≥ 0.8 → min ≥ 2; then avg ≥ min, max ≥ avg; targeted = min > 0
//   staffing     buffered = ceil(buffer × min); ambassadors = max(minAmb, ceil(buffered ÷ (paid × active share)))
//                standby = ceil(ambassadors ÷ 4); College Lead: own when ambassadors ≥ 4, otherwise two small
//                colleges in the same town share one (0.5 each, paired by rank); ambassador leads when ambassadors > span
//   RAG (400 per college)  GREEN avg ≥ 400; AMBER max + 0.5·(F+T+S) ≥ 400 and type a/b; else RED

export const RESEARCH_VERSION = 'v2 2026-11-07';

export const DEFAULTS = Object.freeze({
  program_target: 400,
  deadline: '2026-12-31',
  years: { final: true, third: true, second: true },
  // conversion of IT students to paid enrollments, as fractions [min, avg, max]
  rates: { final: [0.0075, 0.0125, 0.02], third: [0.00375, 0.00625, 0.01], second: [0.0015, 0.0025, 0.005] },
  junior_weight: 0.5, // 3rd- and 2nd-year students count at half weight
  type_k: { a: [0.8, 1.0, 1.2], b: [1.0, 1.0, 1.0], c: [0.8, 0.9, 1.0], d: [0.9, 1.0, 1.1] },
  floor_min: 2, // any college with final-years and a usable contact gets at least this minimum
  paid_per_active: 5, // paid enrollments per ACTIVE ambassador
  active_share: 0.5, // share of recruited ambassadors who stay active
  buffer: 1.2, // recruit against buffer × minimum
  min_ambassadors: 3,
  standby_per: 4, // one standby per N ambassadors
  own_lead_from: 4, // a college with at least this many ambassadors gets its own College Lead; smaller ones share in pairs
  lead_span: 7, // ambassadors a College Lead manages directly; above it, ambassador leads are added
  amb_targets: { min: 3, standard: 5, stretch: 15 }, // personal targets per ambassador
  district_lead_span: 6, // College Leads per District/City Lead
  mou_share: 0.5, // AMBER test: share of IT students an institutional MoU could cover from Jan 2027
});

export const TARGET_GROUPS = Object.freeze({
  Guntur: ['guntur', 'palnadu', 'bapatla'],
  Krishna: ['krishna', 'ntr'],
  'West Godavari': ['west-godavari', 'eluru'],
});

const SC = ['min', 'avg', 'max'];
const rnd = (x: number): number => Math.floor(x + 0.5); // Python's int(floor(x + 0.5)) in compute_v2.py
const num = (v: any): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : (v && typeof v === 'object' ? num(v.value) : null));
const clone = <T,>(o: T): T => JSON.parse(JSON.stringify(o));

/** Deep-merge saved/partial assumptions over the research defaults; invalid values fall back to the default. */
export type Assumptions = any;
export type Plan = any;
export type PlanRow = any;

export function normalizeAssumptions(a: any = {}): Assumptions {
  const d: any = clone(DEFAULTS);
  const pos = (v: any, dv: number, { int = false, min = 0, max = Infinity }: { int?: boolean; min?: number; max?: number } = {}): number => {
    const n = Number(v);
    if (v === null || v === undefined || v === '' || !Number.isFinite(n) || n < min || n > max) return dv;
    return int ? Math.round(n) : n;
  };
  const out: any = { ...d };
  out.program_target = pos(a.program_target, d.program_target, { int: true, min: 1 });
  out.deadline = typeof a.deadline === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(a.deadline) ? a.deadline : d.deadline;
  out.years = { ...d.years };
  for (const k of Object.keys(d.years)) if (a.years && typeof a.years[k] === 'boolean') out.years[k] = a.years[k];
  out.rates = {};
  for (const k of Object.keys(d.rates)) {
    out.rates[k] = d.rates[k].map((dv: number, i: number) => pos(a.rates?.[k]?.[i], dv, { max: 1 }));
    out.rates[k][1] = Math.max(out.rates[k][1], out.rates[k][0]);
    out.rates[k][2] = Math.max(out.rates[k][2], out.rates[k][1]);
  }
  out.type_k = {};
  for (const k of Object.keys(d.type_k)) out.type_k[k] = d.type_k[k].map((dv: number, i: number) => pos(a.type_k?.[k]?.[i], dv, { max: 10 }));
  out.junior_weight = pos(a.junior_weight, d.junior_weight, { max: 1 });
  out.floor_min = pos(a.floor_min, d.floor_min, { int: true });
  out.paid_per_active = pos(a.paid_per_active, d.paid_per_active, { min: 0.1, max: 100 });
  out.active_share = pos(a.active_share, d.active_share, { min: 0.05, max: 1 });
  out.buffer = pos(a.buffer, d.buffer, { min: 1, max: 3 });
  out.min_ambassadors = pos(a.min_ambassadors, d.min_ambassadors, { int: true, min: 1, max: 50 });
  out.standby_per = pos(a.standby_per, d.standby_per, { int: true, min: 1, max: 50 });
  out.own_lead_from = pos(a.own_lead_from, d.own_lead_from, { int: true, min: 1, max: 50 });
  out.lead_span = pos(a.lead_span, d.lead_span, { int: true, min: 2, max: 50 });
  out.district_lead_span = pos(a.district_lead_span, d.district_lead_span, { int: true, min: 1, max: 50 });
  out.mou_share = pos(a.mou_share, d.mou_share, { max: 1 });
  out.amb_targets = {};
  for (const k of Object.keys(d.amb_targets)) out.amb_targets[k] = pos(a.amb_targets?.[k], d.amb_targets[k], { int: true, min: 0, max: 1000 });
  return out;
}

/** Paid enrollments expected per RECRUITED ambassador (paid per active × active share; research 2.5). */
export const perRecruited = (A: Assumptions): number => A.paid_per_active * A.active_share;

/** True when the assumptions equal the research defaults (used for the "changed" badge). */
export function isDefault(a: any): boolean { return JSON.stringify(normalizeAssumptions(a)) === JSON.stringify(normalizeAssumptions({})); }

/** Cluster key for College Lead sharing: explicit cluster, else the town in the research lead note, else the city. */
export function clusterOf(c: any): string {
  if (c.cluster) return c.cluster;
  const m = /^shared College Lead with \S+ \((.+)\)$/.exec(c.lead_assignment || '');
  return m ? m[1]! : (c.city || c.college_id);
}

/** One college → targets (no staffing). */
export function collegeTargets(c: any, A: Assumptions): any {
  const F = A.years.final ? num(c.it_fy) : 0;
  const T = A.years.third ? (num(c.it_3rd) || 0) : 0;
  const S = A.years.second ? (num(c.it_2nd) || 0) : 0;
  const Fraw = num(c.it_fy);
  const x = num(c.access_x) ?? 0;
  const k = A.type_k[c.type] || null;
  const eligible = c.status_final === 'active' && !!k && Fraw !== null;
  let V: any[] = [0, 0, 0];
  if (eligible) {
    const w = A.junior_weight;
    V = [0, 1, 2].map((i) => rnd(k[i] * x * (A.rates.final[i] * (F || 0) + A.rates.third[i] * T * w + A.rates.second[i] * S * w)));
    if (A.years.final && (F || 0) > 0 && x >= 0.8 && V[0] < A.floor_min) V[0] = A.floor_min;
    V[1] = Math.max(V[1], V[0]); V[2] = Math.max(V[2], V[1]);
  }
  const targeted = eligible && V[0] > 0;
  if (!targeted) V = [0, 0, 0];
  const pool = (F || 0) + T + S;
  const fullPool = (Fraw || 0) + (num(c.it_3rd) || 0) + (num(c.it_2nd) || 0);
  let rag = 'RED';
  if (V[1] >= A.program_target) rag = 'GREEN';
  else if (eligible && V[2] + A.mou_share * fullPool >= A.program_target && (c.type === 'a' || c.type === 'b')) rag = 'AMBER';
  return {
    id: c.college_id, eligible, targeted, min: V[0], avg: V[1], max: V[2],
    pool, reachable: eligible ? rnd(x * pool) : null, rag,
  };
}

/**
 * Full plan for a set of PlanCollege rows.
 * opts.groups: {groupName: [district ids]} (default the 3 target groups); opts.today: 'YYYY-MM-DD'.
 * Returns {A, colleges:[row], byId, totals, districts, groups, reach:{min,avg}, perAmbassador, perLead, progress}.
 */
export function computePlan(colleges: any[] = [], assumptions: any = {}, opts: { groups?: Record<string, readonly string[]>; today?: string | null } = {}): Plan {
  const A = normalizeAssumptions(assumptions);
  const groups = opts.groups || TARGET_GROUPS;
  const groupOf: Record<string, string> = {};
  for (const [g, ids] of Object.entries(groups)) for (const id of ids) groupOf[id] = g;
  const per = perRecruited(A);

  const rows = colleges.map((c) => {
    const t = collegeTargets(c, A);
    const r: any = { ...t, college: c, rank: num(c.rank), group: groupOf[c.district_id] || null, district_id: c.district_id };
    if (t.targeted) {
      r.buffered = Math.ceil(A.buffer * t.min);
      r.ambassadors = Math.max(A.min_ambassadors, Math.ceil(r.buffered / per));
      r.standby = Math.ceil(r.ambassadors / A.standby_per);
      r.ambassador_leads = r.ambassadors > A.lead_span ? Math.ceil(r.ambassadors / A.lead_span) : 0;
    } else {
      r.buffered = r.ambassadors = r.standby = r.ambassador_leads = 0;
    }
    r.college_leads = 0; r.lead_note = t.targeted ? '' : 'not targeted'; r.lead_partner = null;
    return r;
  });

  // College Leads: own lead from `own_lead_from` ambassadors; smaller colleges pair up within a town by rank.
  const small = new Map<string, any[]>();
  for (const r of rows) {
    if (!r.targeted) continue;
    if (r.ambassadors >= A.own_lead_from) {
      r.college_leads = 1;
      r.lead_note = r.ambassador_leads ? `own College Lead + ${r.ambassador_leads} ambassador leads` : 'own College Lead';
    } else {
      const k = clusterOf(r.college);
      if (!small.has(k)) small.set(k, []);
      small.get(k)!.push(r);
    }
  }
  for (const [cl, lst] of small) {
    lst.sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9));
    for (let i = 0; i < lst.length; i += 2) {
      const [a, b] = lst.slice(i, i + 2);
      if (!b) { a.college_leads = 1; a.lead_note = 'own College Lead (no small partner in town)'; continue; }
      a.college_leads = b.college_leads = 0.5;
      a.lead_partner = b.id; b.lead_partner = a.id;
      a.lead_note = `shares a College Lead with ${b.college.short_name || b.college.name} (${cl})`;
      b.lead_note = `shares a College Lead with ${a.college.short_name || a.college.name} (${cl})`;
    }
  }

  for (const r of rows) {
    const act = r.college.actual || {};
    r.confirmed = num(act.confirmed) || 0;
    r.recruited = num(act.ambassadors) || 0;
    r.amb_gap = Math.max(0, r.ambassadors - r.recruited);
    r.perAmb = SC.reduce((o: any, s) => ((o[s] = r.ambassadors ? r[s] / r.ambassadors : null), o), {});
  }

  const byId = new Map(rows.map((r) => [r.id, r]));
  const totals = sumRows(rows, A);
  const districts = groupBy(rows, (r) => r.district_id, A);
  const groupTotals = groupBy(rows, (r) => r.group || 'Other districts', A);
  for (const g of groupTotals) g.district_leads = Math.ceil(g.college_leads / A.district_lead_span);
  totals.district_leads = groupTotals.reduce((s, g) => s + g.district_leads, 0);

  const reach = { min: reachTarget(rows, 'min', A), avg: reachTarget(rows, 'avg', A) };
  return {
    A, colleges: rows, byId, totals, districts, groups: groupTotals, reach,
    perAmbassador: perRole(totals, totals.ambassadors), perLead: perRole(totals, totals.college_leads),
    progress: progress(totals, A, opts.today),
  };
}

function sumRows(rows: any[], A: Assumptions): any {
  const t: any = { colleges: 0, eligible: 0, targeted: 0, hold: 0, min: 0, avg: 0, max: 0, pool: 0, reachable: 0, buffered: 0, ambassadors: 0,
    standby: 0, ambassador_leads: 0, college_leads: 0, confirmed: 0, recruited: 0, rag: { GREEN: 0, AMBER: 0, RED: 0 } };
  for (const r of rows) {
    if (r.college.status_final === 'active') t.colleges++; // active colleges (closed / merged rows are listed but not counted)
    if (r.eligible) t.eligible++;
    if (r.targeted) t.targeted++; else if (r.college.status_final === 'active') t.hold++;
    for (const k of ['min', 'avg', 'max', 'pool', 'buffered', 'ambassadors', 'standby', 'ambassador_leads', 'college_leads', 'confirmed', 'recruited']) t[k] += r[k] || 0;
    t.reachable += r.reachable || 0;
    if (r.college.status_final === 'active') t.rag[r.rag]++;
  }
  t.target = A.program_target;
  t.gap = SC.reduce((o: any, s) => ((o[s] = t[s] - A.program_target), o), {});
  t.pctOfTarget = SC.reduce((o: any, s) => ((o[s] = A.program_target ? t[s] / A.program_target : null), o), {});
  return t;
}

function groupBy(rows: any[], keyFn: (r: any) => string, A: Assumptions): any[] {
  const m = new Map<string, any[]>();
  for (const r of rows) { const k = keyFn(r); if (!m.has(k)) m.set(k, []); m.get(k)!.push(r); }
  return [...m].map(([key, list]) => ({ key, ...sumRows(list, A) }))
    .map((g: any) => ({ ...g, shareOfTarget: SC.reduce((o: any, s) => ((o[s] = A.program_target ? g[s] / A.program_target : null), o), {}) }))
    .sort((a: any, b: any) => b.avg - a.avg || String(a.key).localeCompare(String(b.key)));
}

const perRole = (t: any, n: number): any => SC.reduce((o: any, s) => ((o[s] = n ? t[s] / n : null), o), {});

/** Greedy by priority rank: add targeted colleges until the cumulative `scenario` total reaches the target. */
export function reachTarget(rows: any[], scenario: 'min' | 'avg', A: Assumptions): any {
  const list = rows.filter((r) => r.targeted).sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || b.avg - a.avg);
  const out: any = { scenario, target: A.program_target, reached: false, colleges: 0, ids: [], total: 0, min: 0, avg: 0, max: 0,
    college_leads: 0, ambassador_leads: 0, ambassadors: 0, standby: 0, shortfall: 0 };
  for (const r of list) {
    if (out.total >= A.program_target) break;
    out.colleges++; out.ids.push(r.id); out.total += r[scenario];
    for (const k of ['min', 'avg', 'max', 'ambassador_leads', 'ambassadors', 'standby']) out[k] += r[k];
  }
  // a shared lead whose partner is outside the chosen set still needs a whole person
  const chosen = new Set(out.ids);

  const seen = new Set<string>();
  for (const id of out.ids) {
    const r = rows.find((x) => x.id === id);
    if (r.college_leads === 1) out.college_leads++;
    else if (!seen.has(id)) { out.college_leads++; seen.add(id); if (r.lead_partner && chosen.has(r.lead_partner)) seen.add(r.lead_partner); }
  }
  out.reached = out.total >= A.program_target;
  out.shortfall = Math.max(0, A.program_target - out.total);
  out.perAmbassador = perRole(out, out.ambassadors);
  out.perLead = perRole(out, out.college_leads);
  return out;
}

function daysBetween(a: string, b: string): number | null {
  const x = Date.parse(String(a).slice(0, 10) + 'T00:00:00Z'), y = Date.parse(String(b).slice(0, 10) + 'T00:00:00Z');
  return Number.isNaN(x) || Number.isNaN(y) ? null : Math.round((y - x) / 86400000);
}

/** Progress of actual confirmed enrollments against the programme target and the planned minimum. */
export function progress(totals: any, A: Assumptions, today?: string | null): any {
  const t = today || new Date().toISOString().slice(0, 10);
  const d = daysBetween(t, A.deadline);
  const days_left = d === null ? null : Math.max(0, d + 1); // including today (same rule as /api/target-dashboard)
  const remaining = Math.max(0, A.program_target - totals.confirmed);
  return {
    today: t, deadline: A.deadline, days_left, confirmed: totals.confirmed, target: A.program_target, remaining,
    pct: A.program_target ? totals.confirmed / A.program_target : null,
    required_weekly: days_left ? remaining / (days_left / 7) : null,
    required_daily: days_left ? remaining / days_left : null,
  };
}
