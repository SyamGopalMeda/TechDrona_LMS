// Tests for server/live.js (official-source fetchers). Run: node --test server/live.test.js
// No network: every source is served by a fake fetch built from markup copied from the real pages (9 Nov 2026).
import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { openDb } from './db.js';
import { createLive, parseCap, parseJntukAffiliated, parseJntukNotifications, categorize, nameTokens } from './live.js';
import { createApp } from './server.js';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const branch = (code, b, name, seats, left) => ({ inst_code: code, inst_name: name, branch_code: b, branch_name: b, course_type: 'ENG', total_seats: seats, left_over_seats: left, fee_with_no_exemption: 47000 });
const capRec = (code, name, place, district, branches, extra = {}) => ({ inst_code: code, inst_name: name, place, district_id: district, affiliated_to: 'JNTUK', ph_no: '0863-2286666',
  e_mail: 'principal@example.in', website: 'www.example-feed.in', entry_date: '2026-07-24 10:00:00', college_type: 'PVT', courses_offered_arr: JSON.stringify(branches), ...extra });
const CAP = (recs) => JSON.stringify({ status: true, scode: '01', sdesc: 'data found', data: recs, data_count: recs.length });

const JNTUK_EXAMS = `<div id="subtab-110" class="gov-tab-content "><h3>Guntur</h3>
<div class="content-text"><table><thead><tr><th scope="col">S.No</th><th scope="col">CC</th><th scope="col">College Name</th><th scope="col">Course offered</th></tr></thead>
<tbody><tr><td scope="row">1</td><td scope="row">JR</td><td>TESTA INST. OF TECH. &amp; SCI, VINJANAMPADU, GUNTUR</td><td>B.Tech, M.Tech</td></tr>
<tr><td scope="row">2</td><td scope="row">CD</td><td>TESTA INST. OF PHARM.SCI., GUNTUR</td><td>B.Pharmacy</td></tr></tbody></table></div></div>
<div class="gov-tab-content"><h3>Autonomous Colleges</h3>
<div class="content-text"><table><tbody><tr><td>1</td><td>47</td><td>St. Ann&rsquo;s College of Engineering &amp; Technology,vetapalem</td><td>PKS</td></tr></tbody></table></div></div>`;

const notifRow = (att, ts, mon, day, yr, title, dept) => `<tr class="notif-row has-att" data-att-id="${att}" data-icon-id="i"><td>1</td><td data-order="${ts}"><div class="notif-item">
<div class="notif-date"><span class="nd-mon">${mon}</span><span class="nd-day">${day}</span><span class="nd-yr">${yr}</span></div>
<div class="notif-body"><div class="notif-title"> ${title} </div><span class="notif-dept"><i class="fa fa-building-o"></i>${dept}</span></div></div></td><td></td></tr>`;
const attBlock = (att, name, href) => `<div id="${att}" class="att-store-item"><div class="att-sub-table-wrap"><div class="att-item"><div class="att-name"> ${name} </div>
<div class="att-act"><a href="${href}" target="_blank" title="View"></a></div></div></div></div>`;
const NOTICES = (extra = '') => `<h2 class="event-title"> Notifications and Circulars </h2><table class="table datatable" id="table_9"><tbody>
${notifRow('att_row_9_1', 1, 'Nov', '07', '2026', 'III B.Tech I Sem (R23) Regular Examinations Time Table – Nov 2026', 'Controller of Examinations')}
${notifRow('att_row_9_2', 1, 'Nov', '06', '2026', 'Circular for Certificates verification for LE students-2026-27', 'Director - Admissions')}
${extra}</tbody></table>
<h2 class="event-title"> Live Scrollings </h2><table id="table_5"><tbody>
${notifRow('att_row_5_1', 1, 'Nov', '07', '2026', 'III B.Tech I Sem (R23) Regular Examinations Time Table – Nov 2026', 'Controller of Examinations')}</tbody></table>
<h2 class="event-title"> Tenders </h2><table id="table_10"><tbody>${notifRow('att_row_10_1', 1, 'Nov', '01', '2026', 'Tender for furniture', 'Purchase')}</tbody></table>
${attBlock('att_row_9_1', 'Time table', 'universityadmin/uploads/notifications/tt.pdf')}${attBlock('att_row_9_2', 'Circular', 'universityadmin/uploads/notifications/cv.jpg')}`;

function fakeFetch(routes) {
  const calls = [];
  const fn = async (url) => {
    calls.push(url);
    const r = routes[url] ?? routes['*'];
    if (typeof r === 'function') return r(url);
    if (r instanceof Error) throw r;
    if (r == null) throw Object.assign(new Error('fetch failed'), { cause: { code: 'ENOTFOUND' } });
    const [status, body] = Array.isArray(r) ? r : [200, r];
    return new Response(body, { status });
  };
  fn.calls = calls;
  return fn;
}
function tmpDb() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'live-'));
  const db = openDb(path.join(dir, 't.db'));
  db.exec("INSERT OR IGNORE INTO districts(id, name) VALUES ('guntur','Guntur'),('bapatla','Bapatla'),('east-godavari','East Godavari')");
  const add = (id, name, district, extra = {}) => db.prepare('INSERT INTO colleges(id, sno, name, district_id, website, short_name, aliases, notes) VALUES (?,?,?,?,?,?,?,?)')
    .run(id, Number(id.slice(1)), name, district, extra.website ?? null, extra.short_name ?? null, extra.aliases ?? null, extra.notes ?? null);
  add('c12', 'Testa Institute of Technology & Sciences', 'guntur', { website: 'https://testa.ac.in', notes: 'EAPCET: TSTA' });
  add('c53', "St. Ann's College of Engineering & Technology", 'bapatla');
  add('c138', 'Chaitanya Institute of Engineering & Technology', 'east-godavari');
  return db;
}
const ROUTES = (over = {}) => ({
  'https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details': CAP([
    capRec('TSTA', 'TESTA INST OF TECH AND SCI', 'GUNTUR', 'GUNTUR', [branch('TSTA', 'CSE', 'X', 180, 20), branch('TSTA', 'ECE', 'X', 60, 30)]),
    capRec('CEVP', 'CHAITANYA ENGINEERING COLLEGE', 'VISAKHAPATNAM', '', [branch('CEVP', 'CSE', 'X', 60, 10)]),
  ]),
  'https://api.cap.apcfss.in/oamreadapi/oam-public/ecet-clg-home-page-details': CAP([capRec('TSTA', 'TESTA INST OF TECH AND SCI', 'GUNTUR', undefined, [branch('TSTA', 'CSE', 'X', 20, 5)])]),
  'https://www.jntuk.edu.in/examinations': JNTUK_EXAMS,
  'https://www.jntuk.edu.in/notifications': NOTICES(),
  'https://testa.ac.in': [403, 'forbidden'],
  ...over,
});

test('parsers read the real page/feed structure', () => {
  const cap = parseCap(CAP([capRec('TSTA', 'T', 'P', 'GUNTUR', [branch('TSTA', 'CSE', 'X', 180, 20), branch('TSTA', 'ECE', 'X', 60, 30)])]));
  assert.equal(cap.length, 1);
  assert.deepEqual(cap[0].totals, { seats: 240, left_over: 50, filled: 190 });
  assert.equal(cap[0].branches[0].filled, 160);
  assert.throws(() => parseCap('{"status":false}'), /no data array/);

  const aff = parseJntukAffiliated(JNTUK_EXAMS);
  assert.equal(aff.length, 3);
  assert.deepEqual(aff[0], { district: 'Guntur', cc: 'JR', name: 'TESTA INST. OF TECH. & SCI, VINJANAMPADU, GUNTUR', courses: 'B.Tech, M.Tech' });
  assert.equal(aff[2].name, "St. Ann's College of Engineering & Technology,vetapalem");
  assert.throws(() => parseJntukAffiliated('<html>redesigned</html>'), /layout/);

  const n = parseJntukNotifications(NOTICES());
  assert.equal(n.length, 2, 'duplicate in Live Scrollings collapses; Tenders section ignored');
  assert.equal(n[0].date, '2026-11-07');
  assert.equal(n[0].category, 'exam');
  assert.equal(n[1].category, 'admission');
  assert.equal(n[0].attachments[0].url, 'https://www.jntuk.edu.in/universityadmin/uploads/notifications/tt.pdf');
  assert.throws(() => parseJntukNotifications('<html></html>'), /layout/);
});

test('categorize', () => {
  assert.equal(categorize('Revised Academic Calendar for II B.Tech 2026-27'), 'calendar');
  assert.equal(categorize('Declaration of holidays for Sankranthi'), 'holiday');
  assert.equal(categorize('IV B.Tech I Sem results released'), 'result');
  assert.equal(categorize('Tender for furniture'), 'other');
});

test('name tokens: initials and abbreviations', () => {
  assert.deepEqual([...nameTokens('B.V.C. College of Engg')], ['bvc']);
  assert.ok(nameTokens('NARSARAOPET INSTT. OF PHARM.SCI.').has('pharmacy'));
});

test('refresh: links, presence, diffs, no false matches', async () => {
  const db = tmpDb();
  const live = createLive(db, { fetchImpl: fakeFetch(ROUTES()), log: () => {} });
  await live.refreshAndWait({ force: true });
  const st = live.status();
  for (const s of st.sources) assert.equal(s.last_status, 'ok', `${s.id}: ${s.last_error}`);
  const c12 = live.college('c12');
  assert.equal(c12.eapcet.link.basis, 'research_code');
  assert.equal(c12.eapcet.record.totals.seats, 240);
  assert.equal(c12.presence.jntuk_affiliated, true, 'district list B.Tech row matched by name');
  assert.equal(c12.jntuk.record.cc, 'JR');
  assert.equal(c12.presence.website, true, '403 = site up, blocks robots');
  assert.ok(c12.diffs.some((d) => d.field === 'website' && d.note && d.note_checked_at), 'feed website differs, ours is up -> note');
  assert.ok(c12.diffs.some((d) => d.field === 'affiliation' && d.live === 'JNTUK'));
  const c53 = live.college('c53');
  assert.equal(c53.presence.jntuk_affiliated, true, 'autonomous table, Prakasam tag covers Bapatla');
  const c138 = live.college('c138');
  assert.equal(c138.presence.eapcet, false, 'single shared word in another district must not link');
  assert.equal(c138.signal, 'not_found_anywhere');
  const ann = live.announcements({ category: 'exam' });
  assert.equal(ann.items.length, 1);
  assert.equal(ann.items[0].is_new, false, 'first-ever batch is the baseline, not new');
});

test('a failing source keeps the last good copy and says so', async () => {
  const db = tmpDb();
  let t = new Date('2026-11-09T10:00:00Z');
  const routes = ROUTES();
  const live = createLive(db, { fetchImpl: fakeFetch(routes), now: () => t, log: () => {} });
  await live.refreshAndWait({ force: true });
  // 2 hours later JNTUK is down and the page layout of the notices changed
  t = new Date('2026-11-09T12:00:00Z');
  routes['https://www.jntuk.edu.in/notifications'] = [503, 'down'];
  routes['https://www.jntuk.edu.in/examinations'] = '<html>new layout</html>';
  await live.refreshAndWait({ force: true });
  const st = live.status();
  const n = st.sources.find((s) => s.id === 'jntuk_notifications');
  assert.equal(n.last_status, 'error');
  assert.equal(n.last_error, 'HTTP 503');
  assert.equal(n.using_fallback, true);
  assert.equal(n.last_success_at, '2026-11-09T10:00:00.000Z');
  assert.equal(st.sources.find((s) => s.id === 'jntuk_affiliated').using_fallback, true);
  assert.equal(live.announcements({}).items.length, 2, 'old notices still served');
  assert.equal(live.college('c12').presence.jntuk_affiliated, true, 'last good affiliated list still used');
});

test('TTL: only stale sources refresh; failures retry after 15 min', async () => {
  const db = tmpDb();
  let t = new Date('2026-11-09T10:00:00Z');
  const ff = fakeFetch(ROUTES());
  const live = createLive(db, { fetchImpl: ff, now: () => t, log: () => {} });
  await live.refreshAndWait({});
  const first = ff.calls.length;
  t = new Date('2026-11-09T10:10:00Z');
  assert.deepEqual(live.refresh({}), [], 'nothing stale after 10 min');
  t = new Date('2026-11-09T10:31:00Z');
  assert.deepEqual(live.refresh({}), ['jntuk_notifications'], 'notices TTL is 30 min');
  await live.refreshAndWait({});
  assert.equal(ff.calls.length, first + 1);
});

test('change log records seat changes and new notices', async () => {
  const db = tmpDb();
  const routes = ROUTES();
  const live = createLive(db, { fetchImpl: fakeFetch(routes), log: () => {} });
  await live.refreshAndWait({ force: true });
  routes['https://api.cap.apcfss.in/oamreadapi/oam-public/eapcet-clg-home-page-details'] = CAP([
    capRec('TSTA', 'TESTA INST OF TECH AND SCI', 'GUNTUR', 'GUNTUR', [branch('TSTA', 'CSE', 'X', 180, 10), branch('TSTA', 'ECE', 'X', 60, 30)])]);
  routes['https://www.jntuk.edu.in/notifications'] = NOTICES(notifRow('att_row_9_3', 1, 'Nov', '09', '2026', 'Declaration of holiday on 10-11-2026', 'Registrar'));
  await live.refreshAndWait({ force: true });
  const ch = live.status().recent_changes.map((c) => c.summary);
  assert.ok(ch.some((s) => /EAPCET seats for TESTA.*left over 50 → 40/.test(s)), ch.join('\n'));
  assert.ok(ch.some((s) => /CHAITANYA.*no longer in the EAPCET/.test(s)));
  assert.ok(ch.some((s) => /1 new JNTUK notice/.test(s)));
  const hol = live.announcements({ category: 'holiday' }).items;
  assert.equal(hol.length, 1);
  assert.equal(hol[0].is_new, true, 'appeared after the baseline');
});

test('HTTP API: auth, viewer read-only, validation', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'live-api-'));
  const db = openDb(path.join(dir, 'a.db'));
  const saved = { ...process.env };
  let after = () => {};
  process.env.PORTAL_PASSCODE = 'editor-pass-1'; process.env.PORTAL_VIEWER_PASSCODE = 'viewer-pass-1';
  try {
    const app = createApp({ db, liveFetch: fakeFetch(ROUTES()) });
    const http = await import('node:http');
    const srv = http.createServer((q, r) => app.handler(q, r));
    await new Promise((r) => srv.listen(0, '127.0.0.1', r));
    const base = `http://127.0.0.1:${srv.address().port}`;
    after = () => srv.close();
    const call = async (method, url, headers = {}, body) => {
      const r = await fetch(base + url, { method, headers: { ...(body ? { 'content-type': 'application/json' } : {}), ...headers }, body: body ? JSON.stringify(body) : undefined });
      return { status: r.status, body: await r.json().catch(() => null) };
    };
    assert.equal((await call('GET', '/api/live')).status, 401);
    const v = await call('GET', '/api/live', { 'x-passcode': 'viewer-pass-1' });
    assert.equal(v.status, 200);
    assert.equal(v.body.sources.length, 5);
    assert.ok(v.body.automation.some((a) => a.status === 'manual' && /Placements/.test(a.topic)));
    const vr = await call('POST', '/api/live/refresh', { 'x-passcode': 'viewer-pass-1', 'x-user': 'Tester', origin: base }, {});
    assert.equal(vr.status, 403);
    const bad = await call('POST', '/api/live/refresh', { 'x-passcode': 'editor-pass-1', 'x-user': 'Tester', origin: base }, { source: 'nope' });
    assert.equal(bad.status, 400);
    const ok = await call('POST', '/api/live/refresh', { 'x-passcode': 'editor-pass-1', 'x-user': 'Tester', origin: base }, { source: 'eapcet' });
    assert.equal(ok.status, 200);
    assert.equal((await call('GET', '/api/live/announcements?category=zzz', { 'x-passcode': 'viewer-pass-1' })).status, 400);
    assert.equal((await call('GET', '/api/live/college/c999', { 'x-passcode': 'viewer-pass-1' })).status, 404);
  } finally { after(); for (const k of ['PORTAL_PASSCODE', 'PORTAL_VIEWER_PASSCODE']) { if (saved[k] == null) delete process.env[k]; else process.env[k] = saved[k]; } }
});
void DatabaseSync;
