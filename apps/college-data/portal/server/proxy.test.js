// Proxy mode (Tech Drona LMS integration): the LMS serves the portal under /college-portal/ through an authenticated proxy
// that sends x-td-proxy-secret / x-td-proxy-user / x-td-proxy-role. Run: node --test server/proxy.test.js
// Runs against a temporary COPY of data/techdrona.db (the real database is never opened for writing).
import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { DEFAULT_DB_PATH, openDb } from './db.js';
import { startServer, hostGuard } from './server.js';

const SECRET = 'test-proxy-secret-0123456789-abcdefghij'; // >= 32 characters
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'techdrona-proxytest-'));
const dbPath = path.join(tmpDir, 'test.db');
if (fs.existsSync(DEFAULT_DB_PATH)) {
  fs.copyFileSync(DEFAULT_DB_PATH, dbPath);
  if (fs.existsSync(`${DEFAULT_DB_PATH}-wal`)) fs.copyFileSync(`${DEFAULT_DB_PATH}-wal`, `${dbPath}-wal`);
}
const ENV_KEYS = ['PORTAL_PROXY_SECRET', 'PORTAL_PASSCODE', 'PORTAL_VIEWER_PASSCODE', 'DB_PATH', 'TODAY', 'LIVE_DISABLED', 'TRUST_PROXY', 'PORTAL_CSP'];
const savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
Object.assign(process.env, { DB_PATH: dbPath, TODAY: '2026-11-03', LIVE_DISABLED: '1' });
delete process.env.PORTAL_PASSCODE; delete process.env.PORTAL_VIEWER_PASSCODE; delete process.env.TRUST_PROXY; delete process.env.PORTAL_CSP;

let srv = null; let db = null; let collegeId = null;

/** raw HTTP request (fetch cannot set Host) -> {status, headers, data} */
function req(method, p, { headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? null : Buffer.from(JSON.stringify(body));
    const r = http.request({ host: '127.0.0.1', port: srv.port, method, path: p,
      headers: { ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': payload.length } : {}), ...headers } }, (res) => {
      const chunks = []; res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        let data = text; try { data = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
        resolve({ status: res.statusCode, headers: res.headers, data, text });
      });
    });
    r.on('error', reject);
    if (payload) r.write(payload);
    r.end();
  });
}
const lms = (role = 'editor', user = 'Priya Admin') => ({ 'x-td-proxy-secret': SECRET, 'x-td-proxy-user': encodeURIComponent(user), 'x-td-proxy-role': role });

before(async () => {
  process.env.PORTAL_PROXY_SECRET = SECRET;
  db = openDb(dbPath);
  collegeId = db.prepare('SELECT id FROM colleges ORDER BY id LIMIT 1').get()?.id;
  srv = await startServer({ port: 0, host: '127.0.0.1', db });
});
after(async () => {
  if (srv) await new Promise((r) => srv.server.close(r));
  try { db?.close(); } catch { /* ignore */ }
  for (const [k, v] of Object.entries(savedEnv)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

test('startServer refuses a PORTAL_PROXY_SECRET shorter than 32 characters', async () => {
  const keep = process.env.PORTAL_PROXY_SECRET;
  process.env.PORTAL_PROXY_SECRET = 'short';
  try {
    await assert.rejects(startServer({ port: 0, host: '127.0.0.1', db }), (e) => e.code === 'WEAK_PROXY_SECRET' && /32 characters/.test(e.message));
    assert.notEqual(hostGuard('0.0.0.0'), null, 'a weak secret does not open non-loopback hosts');
  } finally { process.env.PORTAL_PROXY_SECRET = keep; }
  assert.equal(hostGuard('0.0.0.0'), null, 'a valid secret allows binding 0.0.0.0 (internal network)');
});

test('GET/HEAD /api/health is open without the secret (container health checks)', async () => {
  const g = await req('GET', '/api/health');
  assert.equal(g.status, 200);
  assert.equal(g.data.ok, true);
  const hd = await req('HEAD', '/api/health');
  assert.equal(hd.status, 200);
});

test('everything else without the secret -> 401 proxy_required', async () => {
  for (const [m, p] of [['GET', '/api/session'], ['GET', '/api/meta'], ['GET', '/api/colleges'], ['GET', '/'], ['GET', '/index.html'], ['GET', '/js/app.js'], ['POST', '/api/session']]) {
    const r = await req(m, p, m === 'POST' ? { body: { name: 'x', passcode: 'y' } } : {});
    assert.equal(r.status, 401, `${m} ${p}`);
    assert.equal(r.data.code, 'proxy_required', `${m} ${p}`);
    assert.equal(r.data.error, 'This portal is only reachable through the Tech Drona LMS');
  }
});

test('a wrong secret -> 401 proxy_required', async () => {
  for (const s of ['wrong', `${SECRET}x`, SECRET.slice(0, -1)]) {
    const r = await req('GET', '/api/colleges', { headers: { ...lms(), 'x-td-proxy-secret': s } });
    assert.equal(r.status, 401);
    assert.equal(r.data.code, 'proxy_required');
  }
});

test('valid secret: GET /api/session is the LMS identity (sso)', async () => {
  const r = await req('GET', '/api/session', { headers: lms('editor', 'Priya Admin') });
  assert.equal(r.status, 200);
  assert.deepEqual(r.data, { required: true, auth_required: true, authenticated: true, role: 'editor', user: 'Priya Admin', sso: true,
    sso_provider: 'Tech Drona LMS', login_url: '/login?next=%2Fadmin%2Fcollege-data', expires_at: null, viewer_enabled: false });
  const meta = await req('GET', '/api/meta', { headers: lms('viewer', 'Ravi K.') });
  assert.equal(meta.status, 200);
  assert.equal(meta.data.auth.sso, true);
  assert.equal(meta.data.auth.role, 'viewer');
  assert.equal(meta.data.auth.user, 'Ravi K.');
});

test('valid secret: odd role -> viewer; empty / reserved user -> "LMS admin"; passcode set does not matter', async () => {
  process.env.PORTAL_PASSCODE = 'some-team-passcode';
  try {
    const odd = await req('GET', '/api/session', { headers: lms('admin', 'Asha') });
    assert.equal(odd.data.role, 'viewer');
    assert.equal(odd.data.user, 'Asha');
    const empty = await req('GET', '/api/session', { headers: { 'x-td-proxy-secret': SECRET, 'x-td-proxy-role': 'editor' } });
    assert.equal(empty.data.user, 'LMS admin');
    assert.equal(empty.data.role, 'editor');
    const comma = await req('GET', '/api/session', { headers: lms('editor', 'Rao, K. (Admin)') });
    assert.equal(comma.data.user, 'Rao, K. (Admin)');
    const reserved = await req('GET', '/api/session', { headers: lms('editor', 'seed') });
    assert.equal(reserved.data.user, 'LMS admin');
    const reads = await req('GET', '/api/colleges', { headers: lms('viewer') });
    assert.equal(reads.status, 200, 'reads work with the LMS identity even when a passcode is configured');
  } finally { delete process.env.PORTAL_PASSCODE; }
});

test('POST /api/session -> 409 sso; DELETE -> 200 without a cookie', async () => {
  const p = await req('POST', '/api/session', { headers: lms(), body: { name: 'X', passcode: 'y' } });
  assert.equal(p.status, 409);
  assert.equal(p.data.code, 'sso');
  assert.equal(p.data.error, 'You are signed in through the Tech Drona LMS');
  const d = await req('DELETE', '/api/session', { headers: lms() });
  assert.equal(d.status, 200);
  assert.deepEqual(d.data, { ok: true });
  assert.equal(d.headers['set-cookie'], undefined);
});

test('editor write: actor is the LMS user and the audit log records it', async () => {
  assert.ok(collegeId, 'the test DB has at least one college');
  const user = 'Priya Admin (LMS)';
  // Host is the internal docker name and Origin the LMS site: both accepted with a valid secret
  const headers = { ...lms('editor', user), Host: 'college-portal:4173', Origin: 'https://lms.example.org', 'Sec-Fetch-Site': 'same-origin', 'X-User': 'Someone Else' };
  const c = await req('POST', '/api/followups', { headers, body: { scope_type: 'college', scope_id: collegeId, title: 'Proxy test follow-up', due_date: '2026-11-05' } });
  assert.equal(c.status, 201, JSON.stringify(c.data));
  assert.equal(c.data.created_by, user);
  const id = c.data.id;
  const au = await req('GET', `/api/audit?entity=followup&entity_id=${id}`, { headers: lms('viewer') });
  assert.equal(au.status, 200);
  // (ids of deleted rows can be reused, so older audit rows for the same id may exist: look for this create)
  const mine = au.data.filter((r) => r.action === 'create' && r.after?.title === 'Proxy test follow-up');
  assert.equal(mine.length, 1, JSON.stringify(au.data.map((r) => [r.action, r.actor])));
  assert.equal(mine[0].actor, user);
  const del = await req('DELETE', `/api/followups/${id}`, { headers });
  assert.ok(del.status === 200 || del.status === 204, JSON.stringify(del.data));
  const au2 = await req('GET', `/api/audit?entity=followup&entity_id=${id}`, { headers: lms('viewer') });
  assert.ok(au2.data.some((r) => r.action === 'delete' && r.actor === user), JSON.stringify(au2.data.map((r) => [r.action, r.actor])));
});

test('viewer write -> 403 read_only', async () => {
  const r = await req('POST', '/api/followups', { headers: lms('viewer'), body: { scope_type: 'college', scope_id: collegeId, title: 'nope', due_date: '2026-11-05' } });
  assert.equal(r.status, 403);
  assert.equal(r.data.code, 'read_only');
});

test('the JSON content-type check still applies', async () => {
  const r = await new Promise((resolve, reject) => {
    const x = http.request({ host: '127.0.0.1', port: srv.port, method: 'POST', path: '/api/followups', headers: { ...lms(), 'Content-Type': 'text/plain' } }, (res) => {
      const ch = []; res.on('data', (c) => ch.push(c)); res.on('end', () => resolve({ status: res.statusCode, data: JSON.parse(Buffer.concat(ch).toString()) }));
    });
    x.on('error', reject); x.end('{}');
  });
  assert.equal(r.status, 415);
  assert.equal(r.data.code, 'json_required');
});

test('framing: SAMEORIGIN + frame-ancestors self on index.html; Host college-portal:4173 accepted', async () => {
  const r = await req('GET', '/index.html', { headers: { ...lms('viewer'), Host: 'college-portal:4173' } });
  assert.equal(r.status, 200);
  assert.equal(r.headers['x-frame-options'], 'SAMEORIGIN');
  assert.match(r.headers['content-security-policy'], /frame-ancestors 'self'/);
  assert.doesNotMatch(r.headers['content-security-policy'], /frame-ancestors 'none'/);
  const api = await req('GET', '/api/meta', { headers: { ...lms('viewer'), Host: 'college-portal:4173' } });
  assert.equal(api.status, 200);
  assert.equal(api.headers['x-frame-options'], 'SAMEORIGIN');
  // standalone (no secret) keeps DENY / 'none' — checked on the same app by switching the env per request
  const keep = process.env.PORTAL_PROXY_SECRET;
  delete process.env.PORTAL_PROXY_SECRET;
  try {
    const s = await req('GET', '/index.html', { headers: { Host: 'college-portal:4173' } });
    assert.equal(s.status, 403, 'standalone: unknown Host refused');
    const s2 = await req('GET', '/index.html');
    assert.equal(s2.headers['x-frame-options'], 'DENY');
    assert.match(s2.headers['content-security-policy'], /frame-ancestors 'none'/);
  } finally { process.env.PORTAL_PROXY_SECRET = keep; }
});
