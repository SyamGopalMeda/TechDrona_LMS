// Tech Drona portal: district (#/d/:district) and city (#/d/:district/:city) pages — owned by CL.
// Each page = a compact summary of the place + the shared colleges list filtered to it (same filters, sort, paging
// as #/colleges). The routes stay as they were; old links keep working.
import { h, fmt } from '../ui/h.js';
import {
  mount, fetchAll, errorNote, setCrumbs, kpi, kpiB, progressNode, statusNode, cityShort, cityIdFrom, citySlug,
  attentionList, rowId, isNum, daysLeftText, pctText, collegeList, openCollegeForm, remainingText,
} from './dashboard.js';
import { getScope, inScope, setDistrictScope, targetGroupOf } from '../state.js';

export { destroy } from './dashboard.js';

/** Note shown on a district/city page outside the global district selection. */
function outOfScopeNote(ctx, id, name) {
  if (inScope(id)) return null;
  const sc = getScope();
  return h('div', { class: 'vg-scope-note', role: 'note' },
    ctx.ui.icon('info', { size: 18 }),
    h('div', null, h('strong', null, `${name} is outside the selected districts`),
      h('p', { class: 'vd-muted vd-small' }, 'Home, Reports and the map leave it out. Add it to the selection to include it everywhere.')),
    h('div', { class: 'vg-scope-act' },
      ctx.ui.button({ label: `Add ${name}`, size: 'sm', tone: 'primary', onClick: () => setDistrictScope([...(sc.ids || []), id]) }),
      ctx.ui.button({ label: 'All districts', size: 'sm', onClick: () => setDistrictScope('all') })));
}

const districtParam = (params) => decodeURIComponent(String((params && (params.district ?? params.id ?? params[0])) || ''));

function pageHead(ctx, { eyebrow, title, sub, actions }) {
  if (typeof ctx.ui.pageHeader === 'function') return ctx.ui.pageHeader({ eyebrow, title, sub, actions });
  return h('header', { class: 'vg-head' },
    h('div', null, h('p', { class: 'vd-eyebrow' }, eyebrow), h('h1', null, title), sub ? h('p', { class: 'vd-muted' }, sub) : null), actions || null);
}

/** Target progress of the place (server summary). Rolled-up targets say how much they cover (TG-01). */
function targetBlock(ctx, S, what, children) {
  if (!(S.target > 0)) {
    return h('div', { class: 'vg-target td-card is-empty' },
      h('div', null, h('strong', null, S.target === 0 ? `Target 0 for this ${what}` : `No target for this ${what}`),
        h('p', { class: 'vd-muted vd-small' }, `${fmt.num(S.enrolled ?? 0)} confirmed so far.`)),
      h('a', { class: 'td-btn td-btn--secondary td-btn--sm', href: '#/targets' }, 'Set targets'));
  }
  const withT = Array.isArray(children) ? children.filter((r) => r.target > 0).length : null;
  // only the parts that have a value (no "· — achieved" when pct / remaining are unknown, e.g. a partial roll-up)
  const progressLine = [remainingText(S), isNum(S.pct) ? `${pctText(S.pct)} achieved` : null].filter(Boolean).join(' · ');
  return h('div', { class: 'vg-target td-card' },
    h('div', { class: 'vg-target-row' }, h('strong', null, 'Target vs confirmed'), statusNode(ctx, S)),
    ctx.ui.progress({ target: S.target, done: S.enrolled ?? 0, size: 'lg' }),
    h('div', { class: 'vg-target-meta vd-muted vd-small' },
      progressLine ? h('span', null, progressLine) : null,
      h('span', null, daysLeftText(null, S.deadline)),
      S.target_source === 'sum_of_children' ? h('span', null, withT !== null ? `Sum of lower-level targets · covers ${fmt.num(withT)} of ${fmt.num(children.length)}` : 'Sum of lower-level targets') : null));
}

function summaryKpis(ctx, S, base) {
  const ex = S.exams || {};
  return h('div', { class: 'vg-kpiwrap' }, h('div', { class: 'vd-kpis vd-kpis-tight vg-kpis' },
    kpi(ctx, { label: 'Targeted colleges', value: S.targeted_colleges, sub: isNum(S.operational_colleges) ? `${fmt.num(S.operational_colleges)} operational` : null, icon: 'college', href: `${base}?targeted=1` }),
    kpi(ctx, { label: 'Colleges with a lead', value: S.colleges_with_lead, sub: isNum(S.targeted_colleges) ? `of ${fmt.num(S.targeted_colleges)} targeted` : null, icon: 'lead', href: `${base}?team=no_lead&targeted=1` }),
    kpi(ctx, { label: 'Ambassadors', value: S.ambassadors, sub: isNum(S.ambassador_leads) ? fmt.plural(S.ambassador_leads, 'ambassador lead') : null, icon: 'ambassador' }),
    kpi(ctx, { label: 'Target branches without ambassador', value: S.branches_needing_ambassadors, tone: S.branches_needing_ambassadors > 0 ? 'warn' : undefined, icon: 'warn', href: `${base}?amb=gap` }),
    kpiB(ctx, 'Likely prospects (est.)', S.eligible, { icon: 'people' }),
    kpi(ctx, { label: 'Follow-ups open', value: S.followups_open, sub: S.followups_overdue > 0 ? `${fmt.num(S.followups_overdue)} overdue` : null, tone: S.followups_overdue > 0 ? 'bad' : undefined, icon: 'followup', href: `${base}?followup=open` }),
    kpi(ctx, { label: 'Exams now or in 14 days', value:isNum(ex.in_exams) || isNum(ex.exams_soon) ? (ex.in_exams || 0) + (ex.exams_soon || 0) : null, sub: isNum(ex.unknown) ? `${fmt.num(ex.unknown)} with unknown dates` : null, icon: 'exam', href: `${base}?exam=in_exams` })));
}

function districtPicker(ctx, meta, current) {
  const ds = [...(meta.districts || [])].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  return h('label', { class: 'vd-field vg-picker' }, h('span', null, 'Switch district'),
    h('select', { class: 'td-input td-select td-input--sm', onChange: (e) => e.target.value && ctx.navigate(`#/d/${e.target.value}`) },
      ds.some((d) => d.id === current) ? null : h('option', { value: '', selected: true }, 'Choose a district…'),
      ds.map((d) => h('option', { value: d.id, selected: d.id === current ? true : null }, d.name + (targetGroupOf(d.id) ? ' (target)' : inScope(d.id) ? '' : ' (not selected)')))));
}

/** Cities & towns of a district, as compact chips linking to the city page. */
function cityChips(ctx, did, meta, lb) {
  const lbMap = new Map((lb || []).map((r) => [rowId(r), r]));
  const cities = (meta.cities || []).filter((c) => c.district_id === did).map((c) => ({ ...c, lb: lbMap.get(c.id) || null }))
    .filter((c) => c.lb ? (c.lb.colleges ?? 1) > 0 : true)
    .sort((a, b) => (b.lb?.enrolled ?? 0) - (a.lb?.enrolled ?? 0) || String(a.name).localeCompare(String(b.name)));
  if (!cities.length) return null;
  return h('details', { class: 'vg-cities' },
    h('summary', null, `Cities & towns (${fmt.num(cities.length)})`),
    h('ul', { class: 'vg-citylist' }, cities.map((c) => h('li', null,
      h('a', { href: `#/d/${did}/${encodeURIComponent(citySlug(did, c.id))}`, class: 'vg-city' },
        h('strong', null, c.name),
        c.lb && c.lb.target > 0 ? h('span', { class: 'vd-small' }, progressNode(ctx, c.lb)) : c.lb && c.lb.enrolled ? h('span', { class: 'vd-muted vd-small' }, `${fmt.num(c.lb.enrolled)} confirmed`) : null)))));
}

const phoneForm = () => document.documentElement.dataset.form === 'phone' || !!window.matchMedia?.('(max-width: 699px)').matches;

/**
 * Map card scoped to the place: the shell's shared map (ctx.mountMap) focused on the district / town.
 * Open by default on tablets and desktops, collapsed on phones; the choice is remembered ('td.geo.map').
 * Districts outside the global selection get their own colleges loaded so the map is never empty.
 */
function placeMap(ctx, { districtId, title, focus }) {
  if (typeof ctx.mountMap !== 'function') return null;
  const KEY = 'td.geo.map';
  let open = !phoneForm();
  try { const v = localStorage.getItem(KEY); if (v !== null) open = v === '1'; } catch { /* private mode */ }
  const host = h('div', { class: 'vg-mapbox td-mapcard', hidden: open ? null : true });
  let m = null, building = false;
  const build = async () => {
    if (m) { m.invalidateSize?.(); focus(m); return; }
    if (building) return;
    building = true;
    try {
      const mm = await ctx.mountMap(host);
      if (!mm || !host.isConnected) return;
      m = mm;
      if (!inScope(districtId)) {
        try {
          const rows = await ctx.api.get('/colleges', { districts: districtId });
          // filter client-side too: the static snapshot (/api_static) ignores query params
          const list = (Array.isArray(rows) ? rows : (rows && rows.items) || []).filter((r) => r && r.district_id === districtId);
          if (host.isConnected && list.length) m.setColleges?.(list);
        } catch { /* the polygon is still framed */ }
      }
      if (host.isConnected) focus(m);
    } finally { building = false; }
  };
  const btn = h('button', { type: 'button', class: 'td-btn td-btn--secondary td-btn--sm', 'aria-expanded': open ? 'true' : 'false' });
  const label = () => btn.replaceChildren(ctx.ui.icon('map', { size: 16 }), h('span', null, open ? 'Hide map' : 'Show map'));
  btn.addEventListener('click', () => {
    open = !open; host.hidden = !open; btn.setAttribute('aria-expanded', open ? 'true' : 'false'); label();
    try { localStorage.setItem(KEY, open ? '1' : '0'); } catch { /* private mode */ }
    if (open) build();
  });
  label();
  if (open) setTimeout(build, 0);
  return h('section', { class: 'vg-mapsec td-card', 'aria-label': `Map of ${title}` },
    h('div', { class: 'vg-mapsec-head' },
      h('div', null, h('h2', null, 'Map'), h('span', { class: 'vd-muted vd-small' }, `Colleges in ${title}`)),
      btn),
    host);
}

/* ===================================== #/d/:district ===================================== */
export async function renderDistrict(el, params, ctx) {
  const id = districtParam(params);
  ctx.map?.focusDistrict?.(id);
  mount(el, 'v-geo', ctx.ui.skeleton ? ctx.ui.skeleton(5) : 'Loading…');
  const scope = `district:${id}`;
  const { data, errors } = await fetchAll({
    meta: ctx.api.get('/meta'),
    summary: ctx.api.get('/summary', { scope }),
    attention: ctx.api.get('/attention', { scope }),
    cityLb: ctx.api.get('/leaderboard', { level: 'city', scope, limit: 200 }),
    collegeLb: ctx.api.get('/leaderboard', { level: 'college', scope, limit: 500 }),
  });
  const meta = data.meta || { districts: [], cities: [] };
  const S = data.summary;
  const dist = (meta.districts || []).find((d) => d.id === id);
  const dName = (S && S.label) || (dist && dist.name) || id;
  setCrumbs(ctx, [{ label: 'Colleges', href: '#/colleges' }, { label: dName, href: `#/d/${id}` }]);
  if (!S) {
    mount(el, 'v-geo', districtPicker(ctx, meta, id),
      errors.summary && (errors.summary.status === 404 || errors.summary.status === 400 || /unknown scope/i.test(errors.summary.message || ''))
        ? ctx.ui.emptyState({ title: 'District not found', text: 'Pick a district from the list above, or open the colleges list.', action: h('a', { class: 'td-btn td-btn--primary', href: '#/colleges' }, 'All colleges') })
        : errorNote(errors.summary, 'this district'));
    return;
  }
  const base = `#/d/${id}`;
  const list = collegeList(ctx, { meta, params: params || {}, base, fixed: { district: id } });
  const sub = [fmt.plural(S.colleges ?? 0, 'college'), `${fmt.num(S.targeted_colleges ?? 0)} targeted`, fmt.plural(S.cities ?? 0, 'city or town', 'cities and towns')];
  const attn = (data.attention || []).filter((r) => r.type !== 'group');
  mount(el, 'v-geo',
    pageHead(ctx, {
      eyebrow: targetGroupOf(id) ? `Target district · ${targetGroupOf(id)}` : 'District', title: dName,
      sub: sub.join(' · ') + (dist && dist.old_district && dist.old_district !== dist.name ? ` · formerly part of ${dist.old_district}` : ''),
      actions: [districtPicker(ctx, meta, id), ctx.ui.button({ label: 'Add college', icon: 'plus', tone: 'secondary', onClick: () => openCollegeForm(ctx, null, { district_id: id }) })],
    }),
    outOfScopeNote(ctx, id, dName),
    h('div', { class: 'vg-summary' }, h('div', { class: 'vg-sumgrid' }, targetBlock(ctx, S, 'district', data.collegeLb), summaryKpis(ctx, S, base))),
    placeMap(ctx, { districtId: id, title: dName, focus: (m) => m.focusDistrict?.(id) }),
    h('div', { class: 'vg-extras' },
      cityChips(ctx, id, meta, data.cityLb),
      attn.length ? h('details', { class: 'vg-attn' }, h('summary', null, `Alerts in ${dName} (${fmt.num(attn.length)})`), attentionList(ctx, attn, 6)) : null),
    ctx.ui.section({ title: `Colleges in ${dName}`, actions: list.exportBtn, body: list.el }));
  await list.load();
}

/* ===================================== #/d/:district/:city ===================================== */
export async function renderCity(el, params, ctx) {
  const did = districtParam(params);
  const cityId = cityIdFrom(did, params && (params.city ?? params[1]));
  ctx.map?.focusCity?.(did, cityId);
  mount(el, 'v-geo', ctx.ui.skeleton ? ctx.ui.skeleton(5) : 'Loading…');
  const { data, errors } = await fetchAll({
    meta: ctx.api.get('/meta'),
    summary: ctx.api.get('/summary', { scope: `city:${cityId}` }),
    collegeLb: ctx.api.get('/leaderboard', { level: 'college', scope: `city:${cityId}`, limit: 500 }),
  });
  const meta = data.meta || { districts: [], cities: [] };
  const S = data.summary;
  const dist = (meta.districts || []).find((d) => d.id === did);
  const city = (meta.cities || []).find((c) => c.id === cityId);
  const cityName = (S && S.label) || (city && city.name) || cityShort(did, cityId);
  const base = `#/d/${did}/${encodeURIComponent(citySlug(did, cityId))}`;
  setCrumbs(ctx, [{ label: 'Colleges', href: '#/colleges' }, { label: (dist && dist.name) || did, href: `#/d/${did}` }, { label: cityName, href: base }]);
  if (!S) {
    mount(el, 'v-geo', h('a', { class: 'vd-link', href: `#/d/${did}` }, `← Back to ${(dist && dist.name) || 'district'}`),
      errors.summary && (errors.summary.status === 404 || errors.summary.status === 400 || /unknown scope/i.test(errors.summary.message || ''))
        ? ctx.ui.emptyState({ title: 'City not found', text: 'This city is not in the master list. Go back to the district to pick another one.' })
        : errorNote(errors.summary, 'this city'));
    return;
  }
  const list = collegeList(ctx, { meta, params: { op: 'all', ...(params || {}) }, base, fixed: { city: cityId } });
  mount(el, 'v-geo',
    pageHead(ctx, {
      eyebrow: h('span', null, 'City / town · ', h('a', { href: `#/d/${did}` }, (dist && dist.name) || did)), title: cityName,
      sub: `${fmt.plural(S.colleges ?? 0, 'college')} · ${fmt.num(S.targeted_colleges ?? 0)} targeted`,
      actions: ctx.ui.button({ label: 'Add college', icon: 'plus', tone: 'secondary', onClick: () => openCollegeForm(ctx, null, { district_id: did, city_id: cityId }) }),
    }),
    outOfScopeNote(ctx, did, (dist && dist.name) || did),
    h('div', { class: 'vg-summary' }, h('div', { class: 'vg-sumgrid' }, targetBlock(ctx, S, 'city', data.collegeLb), summaryKpis(ctx, S, base))),
    placeMap(ctx, { districtId: did, title: cityName, focus: (m) => m.focusCity?.(did, cityId) }),
    ctx.ui.section({ title: `Colleges in ${cityName}`, actions: list.exportBtn, body: list.el }));
  await list.load();
}

export default { renderDistrict, renderCity };
