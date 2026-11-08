// Shared helpers for the page-by-page audit (READ-ONLY on product code; synthetic data only).
// Requires the live dev stack (web :13000, api :18000, Mailpit :8025) and apps/web/.env.e2e.local.
import { createRequire } from "node:module";
import { createHmac, createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(HERE, "../../..");
const req = createRequire(path.join(REPO, "apps/web/package.json"));
export const { chromium } = req("playwright");

export const BASE = process.env.AUDIT_BASE ?? "http://localhost:13000";
export const MAILPIT = "http://localhost:8025";
export const SHOTS = path.join(REPO, "docs/redesign/shots/audit");
// Session/device state + raw logs live OUTSIDE the repo (they hold session cookies).
export const STATE = process.env.AUDIT_STATE ?? path.join(process.env.TEMP ?? "/tmp", "td-page-audit");
mkdirSync(SHOTS, { recursive: true });
mkdirSync(STATE, { recursive: true });

export function loadEnv() {
  const f = path.join(REPO, "apps/web/.env.e2e.local");
  const env = {};
  for (const raw of readFileSync(f, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    env[line.slice(0, i)] = line.slice(i + 1).replace(/^(["'])(.*)\1$/, "$2");
  }
  return env;
}
const ENV = loadEnv();
export const ROLES = {
  student: { id: ENV.E2E_STUDENT_IDENTIFIER, pw: ENV.E2E_STUDENT_PASSWORD },
  admin: { id: ENV.E2E_ADMIN_IDENTIFIER, pw: ENV.E2E_ADMIN_PASSWORD, totp: ENV.E2E_ADMIN_TOTP_SECRET },
  trainer: { id: ENV.E2E_TRAINER_IDENTIFIER, pw: ENV.E2E_TRAINER_PASSWORD, totp: ENV.E2E_TRAINER_TOTP_SECRET },
  evaluator: { id: ENV.E2E_EVALUATOR_IDENTIFIER, pw: ENV.E2E_EVALUATOR_PASSWORD, totp: ENV.E2E_EVALUATOR_TOTP_SECRET },
  content: { id: ENV.E2E_CONTENT_IDENTIFIER, pw: ENV.E2E_CONTENT_PASSWORD, totp: ENV.E2E_CONTENT_TOTP_SECRET },
};

export function log(file, obj) {
  appendFileSync(path.join(STATE, file), `${JSON.stringify(obj)}\n`);
}

function b32(input) {
  const a = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0, value = 0;
  const out = [];
  for (const ch of input.replace(/=+$/, "").replace(/\s/g, "").toUpperCase()) {
    const i = a.indexOf(ch);
    if (i < 0) continue;
    value = (value << 5) | i;
    bits += 5;
    if (bits >= 8) { out.push((value >>> (bits - 8)) & 0xff); bits -= 8; }
  }
  return Buffer.from(out);
}
function totpAt(secret, step) {
  const c = Buffer.alloc(8);
  c.writeBigUInt64BE(BigInt(step));
  const h = createHmac("sha1", b32(secret)).update(c).digest();
  const o = h[h.length - 1] & 0xf;
  return ((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}
/** TOTP from a 30 s step not used before by this tool (api has a replay guard). */
export async function freshTotp(secret) {
  const f = path.join(STATE, `totp-${createHash("sha256").update(secret).digest("hex").slice(0, 12)}.step`);
  const last = existsSync(f) ? Number(readFileSync(f, "utf8")) : -1;
  let step = Math.floor(Date.now() / 30_000);
  if (step <= last) {
    await sleep((last + 1) * 30_000 - Date.now() + 300);
    step = Math.floor(Date.now() / 30_000);
  }
  writeFileSync(f, String(step));
  return totpAt(secret, step);
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const seenMail = new Set();
export async function mailFor(to, after, re, tries = 40) {
  for (let i = 0; i < tries; i += 1) {
    const r = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    if (r.ok) {
      const msgs = (await r.json()).messages ?? [];
      for (const m of msgs) {
        if (seenMail.has(m.ID) || Date.parse(m.Created) < after - 1500) continue;
        const b = await (await fetch(`${MAILPIT}/api/v1/message/${m.ID}`)).json();
        const t = `${b.Subject ?? ""}\n${b.Text ?? ""}\n${b.HTML ?? ""}`;
        if (re.test(t)) { seenMail.add(m.ID); return t; }
      }
    }
    await sleep(1000);
  }
  throw new Error(`no mail ${re} for ${to}`);
}

/** Attach diagnostics collectors to a context; returns a mutable bucket that callers reset per page. */
export function watch(context) {
  const bucket = { console: [], http: [], failed: [] };
  const hook = (page) => {
    page.on("console", (m) => { if (m.type() === "error") bucket.console.push(m.text().slice(0, 300)); });
    page.on("pageerror", (e) => bucket.console.push(`pageerror: ${String(e).slice(0, 300)}`));
    page.on("requestfailed", (r) => {
      const f = r.failure()?.errorText ?? "";
      if (/ERR_ABORTED/.test(f)) return;
      bucket.failed.push(`${r.method()} ${r.url().replace(BASE, "")} ${f}`);
    });
    page.on("response", (r) => {
      if (r.status() >= 400) bucket.http.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, "")}`);
    });
  };
  context.pages().forEach(hook);
  context.on("page", hook);
  bucket.reset = () => { bucket.console.length = 0; bucket.http.length = 0; bucket.failed.length = 0; };
  return bucket;
}

/** UI sign-in, completing TOTP / new-device OTP / device & session caps. */
export async function uiLogin(page, who, next = "/") {
  await page.goto(`${BASE}/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email or mobile").fill(who.id);
  await page.getByLabel(/^Password/).fill(who.pw);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !/^\/login\/?$/.test(u.pathname), { timeout: 30_000 });
  if (/\/login\/mfa/.test(page.url())) {
    await page.getByLabel("Authenticator code").fill(await freshTotp(who.totp));
    await page.getByRole("button", { name: "Verify" }).click();
    await page.waitForURL((u) => !/\/login\/mfa/.test(u.pathname), { timeout: 30_000 });
  }
  if (/\/login\/verify-device/.test(page.url())) {
    const t = Date.now();
    await page.getByRole("button", { name: /Send code by email/ }).click();
    const mail = await mailFor(who.id, t, /\b\d{6}\b/);
    await page.getByLabel("6-digit code").fill(/\b(\d{6})\b/.exec(mail.split("\n").slice(1).join("\n"))[1]);
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 10_000 }).catch(() => undefined);
    const replace = page.getByRole("button", { name: "Remove and continue" });
    if (await replace.isVisible().catch(() => false)) {
      await page.getByRole("radio", { name: /last used (?!now)/ }).first().check();
      await replace.click();
    }
    await page.waitForURL((u) => !u.pathname.startsWith("/login") || /session-choice/.test(u.pathname), { timeout: 30_000 });
  }
  if (/\/login\/session-choice/.test(page.url())) {
    await page.getByRole("radio", { name: /active (?!now)/ }).first().check();
    await page.getByRole("button", { name: "Sign out selected and continue" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
  }
  return page.url();
}

/** A browser context signed in as `role`, reusing the saved state (same device cookie) when still valid. */
export async function roleContext(browser, role, who = ROLES[role], opts = {}) {
  const sf = path.join(STATE, `state-${role}.json`);
  const ctxOpts = { viewport: { width: 1280, height: 800 }, ...opts };
  let ctx = await browser.newContext(existsSync(sf) ? { ...ctxOpts, storageState: sf } : ctxOpts);
  const page = await ctx.newPage();
  const probe = await page.request.get(`${BASE}/api/v1/me`).catch(() => null);
  if (!probe || probe.status() !== 200) {
    // keep only the device cookie so the api sees the same device
    const dev = (await ctx.cookies()).filter((c) => /td_device/.test(c.name));
    await ctx.close();
    ctx = await browser.newContext(ctxOpts);
    if (dev.length) await ctx.addCookies(dev);
    const p = await ctx.newPage();
    await uiLogin(p, who);
    await ctx.storageState({ path: sf });
    await p.close();
  } else {
    await page.close();
  }
  return ctx;
}

/** Same-origin BFF call from a page of the context (CSRF + idempotency handled). */
export async function bff(page, method, apiPath, body) {
  return page.evaluate(
    async ({ method, apiPath, body }) => {
      if (method !== "GET") await fetch("/api/v1/_bff/csrf", { credentials: "same-origin" });
      const csrf = document.cookie.split("; ").find((c) => /td_csrf=/.test(c))?.split("=")[1] ?? "";
      const headers = { accept: "application/json" };
      if (method !== "GET") { headers["x-csrf-token"] = decodeURIComponent(csrf); headers["idempotency-key"] = crypto.randomUUID(); }
      if (body !== undefined) headers["content-type"] = "application/json";
      const res = await fetch(`/api/v1/${apiPath}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
      const text = await res.text();
      let json = text;
      try { json = JSON.parse(text); } catch { /* text */ }
      return { status: res.status, json };
    },
    { method, apiPath, body },
  );
}

export function slug(s) {
  return s.replace(/^\//, "").replace(/[^a-z0-9]+/gi, "_").slice(0, 80) || "root";
}
