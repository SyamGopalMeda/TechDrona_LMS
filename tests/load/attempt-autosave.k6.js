// k6 smoke: login → start a timed attempt → autosave loop, through the Next.js BFF.
//
// LOCAL LAPTOP SMOKE ONLY: numbers describe this docker-compose stack on one machine, not
// production capacity (testing-and-acceptance-criteria §8 load profiles run on staging).
//
// Prereqs: compose `app` profile up, scripts/seed-dev.* run, and the synthetic load users:
//   cd apps/api && .venv/Scripts/python ../../tests/load/seed_load_users.py 200
// Run (Docker, no local k6 needed):
//   docker run --rm -i -v "$PWD/tests/load:/scripts" -e BASE_URL=http://host.docker.internal:13000 \
//     -e ORIGIN=http://localhost:13000 -e TEST_ID=<published free test id> -e PASSWORD=<dev seed password> \
//     grafana/k6:0.54.0 run /scripts/attempt-autosave.k6.js
// Env: VUS (200), DURATION (2m), AUTOSAVE_EVERY_S (3; server limit 30/min per attempt),
//      USER_PREFIX (load), USER_DOMAIN (load.techdrona.local).
//
// The web container issues `__Host-`/Secure cookies (production names). k6's cookie jar never
// sends Secure cookies over plain http, so this script carries the cookies itself.

import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://host.docker.internal:13000";
const ORIGIN = __ENV.ORIGIN || "http://localhost:13000";
const TEST_ID = __ENV.TEST_ID;
const PASSWORD = __ENV.PASSWORD;
const PREFIX = __ENV.USER_PREFIX || "load";
const DOMAIN = __ENV.USER_DOMAIN || "load.techdrona.local";
const EVERY = Number(__ENV.AUTOSAVE_EVERY_S || 3);
// Accounts are load{OFFSET+VU}: a user whose first sign-in trusted a k6 device that is gone
// would need a device OTP, so use fresh accounts (a new offset) for every run.
const OFFSET = Number(__ENV.USER_OFFSET || 0);

export const options = {
  scenarios: {
    autosave: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 200),
      duration: __ENV.DURATION || "2m",
      gracefulStop: "10s",
    },
  },
  thresholds: {
    // Targets from NFR-PERF (autosave p95 < 300 ms server-side); reported, not gating locally.
    "http_req_duration{name:autosave}": ["p(95)<300"],
    "http_req_failed{name:autosave}": ["rate<0.01"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

const loginOk = new Rate("login_ok");
const startOk = new Rate("attempt_start_ok");
const autosaveOk = new Rate("autosave_ok");
const autosaveStatus = new Counter("autosave_non_2xx");
const loginDuration = new Trend("login_duration", true);

// Per-VU state (module scope is per VU in k6).
const jar = {};
let attempt = null;
let seq = 0;

function remember(res) {
  for (const [name, list] of Object.entries(res.cookies || {})) {
    const c = list[0];
    if (!c) continue;
    if (c.value === "" || c.max_age < 0) delete jar[name];
    else jar[name] = c.value;
  }
}

function headers(extra) {
  const csrf = jar["__Host-td_csrf"] || jar.td_csrf;
  return Object.assign(
    {
      accept: "application/json",
      "content-type": "application/json",
      origin: ORIGIN,
      "sec-fetch-site": "same-origin",
      cookie: Object.entries(jar)
        .map(([k, v]) => `${k}=${v}`)
        .join("; "),
    },
    csrf ? { "x-csrf-token": csrf } : {},
    extra || {},
  );
}

function uuid4() {
  const h = "0123456789abcdef";
  let s = "";
  for (let i = 0; i < 36; i += 1) {
    if (i === 8 || i === 13 || i === 18 || i === 23) s += "-";
    else if (i === 14) s += "4";
    else s += h[Math.floor(Math.random() * 16)];
  }
  return s;
}

function post(path, body, name, extra) {
  const res = http.post(`${BASE}/api/v1/${path}`, JSON.stringify(body), { headers: headers(extra), tags: { name }, redirects: 0 });
  remember(res);
  return res;
}

function login() {
  // Start clean (keep only this VU's device cookie, so a retry is the same device).
  for (const k of Object.keys(jar)) if (!/td_device$/.test(k)) delete jar[k];
  const res0 = http.get(`${BASE}/login`, { tags: { name: "login_page" }, redirects: 0 });
  remember(res0);
  remember(http.get(`${BASE}/api/v1/_bff/csrf`, { headers: headers(), tags: { name: "csrf" }, redirects: 0 }));
  const n = String(OFFSET + __VU).padStart(3, "0");
  const res = post("auth/login", { identifier: `${PREFIX}${n}@${DOMAIN}`, password: PASSWORD }, "login");
  loginDuration.add(res.timings.duration);
  const ok = res.status === 200 && !!(jar["__Host-td_session"] || jar.td_session);
  loginOk.add(ok);
  if (!ok) {
    console.warn(`VU ${__VU} login ${res.status} ${String(res.body).slice(0, 200)}`);
    return false;
  }
  return true;
}

function start() {
  const res = post("attempts", { test_id: TEST_ID, integrity_consent: true }, "attempt_start", { "idempotency-key": uuid4() });
  let body = null;
  try {
    body = res.json();
  } catch (_) {
    body = null;
  }
  // 409 attempt in progress → resume it (re-runs with the same user).
  let attemptId = body && body.attempt_id;
  if (!attemptId && body && body.code && body.attempt_id === undefined && body.in_progress_attempt_id) attemptId = body.in_progress_attempt_id;
  const ok = (res.status === 200 || res.status === 201) && !!attemptId;
  startOk.add(ok);
  if (!ok) {
    console.warn(`VU ${__VU} start ${res.status} ${String(res.body).slice(0, 200)}`);
    return null;
  }
  const qs = [];
  for (const s of body.sections || []) for (const q of s.questions || []) qs.push(q);
  return { id: attemptId, questions: qs };
}

export default function () {
  if (!TEST_ID || !PASSWORD) fail("set TEST_ID and PASSWORD");
  if (!attempt) {
    // Stagger logins over ~20 s so 200 VUs do not all hash passwords in the same instant.
    sleep(Math.random() * 20);
    if (!login()) {
      sleep(10);
      return;
    }
    attempt = start();
    if (!attempt) {
      sleep(10);
      return;
    }
  }
  const q = attempt.questions.length ? attempt.questions[seq % attempt.questions.length] : null;
  seq += 1;
  const items = q
    ? [
        {
          question_version_id: q.question_version_id,
          response: q.options && q.options.length ? { option_ids: [q.options[seq % q.options.length].option_id] } : { value: String(seq) },
          client_seq: seq,
          time_spent_ms: EVERY * 1000,
        },
      ]
    : [];
  const res = post(`attempts/${attempt.id}/autosave`, { items, events: [] }, "autosave");
  const ok = res.status >= 200 && res.status < 300;
  autosaveOk.add(ok);
  if (!ok) autosaveStatus.add(1, { status: String(res.status) });
  check(res, { "autosave 2xx": () => ok });
  sleep(EVERY);
}
