import { createHash, createHmac } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/** Shared sign-in helpers for the integration specs (seeded accounts, Mailpit OTP, TOTP). */
export const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";

export interface Account {
  identifier: string;
  password: string;
  totpSecret?: string;
}

export function account(prefix: string): Account | null {
  const identifier = process.env[`E2E_${prefix}_IDENTIFIER`];
  const password = process.env[`E2E_${prefix}_PASSWORD`];
  if (!identifier || !password) return null;
  return { identifier, password, totpSecret: process.env[`E2E_${prefix}_TOTP_SECRET`] };
}

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const ch of input.replace(/=+$/, "").replace(/\s/g, "").toUpperCase()) {
    const idx = alphabet.indexOf(ch);
    if (idx < 0) continue;
    value = (value << 5) | idx;
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

/** RFC 6238 TOTP (SHA-1, 30 s, 6 digits). */
export function totp(secret: string, now = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30_000)));
  const h = createHmac("sha1", base32Decode(secret)).update(counter).digest();
  const off = h[h.length - 1]! & 0xf;
  return ((h.readUInt32BE(off) & 0x7fffffff) % 1_000_000).toString().padStart(6, "0");
}

/** Mail IDs already used, so a later call never returns an earlier device's code (E2E-10). */
const consumedOtpMails = new Set<string>();

export async function latestOtp(request: APIRequestContext, to: string, after: number): Promise<string> {
  for (let i = 0; i < 30; i += 1) {
    const res = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    if (res.ok()) {
      const msgs = ((await res.json()) as { messages?: { ID: string; Created: string }[] }).messages ?? [];
      // Newest unused mail; 1 s tolerance only for clock skew between Mailpit and the runner.
      const fresh = msgs
        .filter((m) => !consumedOtpMails.has(m.ID) && Date.parse(m.Created) >= after - 1_000)
        .sort((a, b) => Date.parse(b.Created) - Date.parse(a.Created))[0];
      if (fresh) {
        const body = (await (await request.get(`${MAILPIT}/api/v1/message/${fresh.ID}`)).json()) as { Text?: string };
        const code = /\b(\d{6})\b/.exec(body.Text ?? "")?.[1];
        if (code) {
          consumedOtpMails.add(fresh.ID);
          return code;
        }
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`No OTP email for ${to}`);
}

/*
 * Every new browser context is a new *device* to the api (td_device cookie), and accounts are
 * capped at 3 devices (sessions policy). Reuse one device per account across specs: the
 * device cookie is kept in apps/web/.e2e-devices/<project>/<account>.json (gitignored; Playwright wipes test-results) and re-added before sign-in.
 * Sign-ins for the same account on the same device end each other's sessions, so run specs
 * that share an account with --workers=1.
 */
const DEVICES = path.join(__dirname, "..", "..", ".e2e-devices");

/**
 * E2E-02: keyed per Playwright project. A desktop device cookie replayed with the mobile UA is a
 * device mismatch (TO-08) to the api, which escalated to a protect-lock of the shared fixture.
 */
function deviceFile(identifier: string) {
  let project = "default";
  try {
    project = test.info().project.name || project;
  } catch {
    /* called outside a test (global setup) */
  }
  const safe = (v: string) => v.replace(/[^a-z0-9.@_-]/gi, "_");
  return path.join(DEVICES, safe(project), `${safe(identifier)}.json`);
}

async function restoreDevice(page: Page, identifier: string) {
  const f = deviceFile(identifier);
  if (!existsSync(f)) return;
  try {
    await page.context().addCookies(JSON.parse(readFileSync(f, "utf8")));
  } catch {
    /* stale file: sign in as a new device */
  }
}

async function saveDevice(page: Page, identifier: string) {
  const cookies = (await page.context().cookies()).filter((c) => /td_device$/.test(c.name));
  if (!cookies.length) return;
  const f = deviceFile(identifier);
  mkdirSync(path.dirname(f), { recursive: true });
  writeFileSync(f, JSON.stringify(cookies));
}

/*
 * The api rejects a TOTP code whose 30 s step was already used for the account (replay guard).
 * Specs that sign the same account in back to back (security-console, then security-staff) hit
 * that inside one step. Remember the last step used per account (file, so it holds across spec
 * files and projects) and, when the current step is spent, wait for the next step boundary.
 */
function totpStepFile(secret: string) {
  // Keyed by a hash of the secret (one secret per account); the secret itself is never written.
  return path.join(DEVICES, "_totp", `${createHash("sha256").update(secret).digest("hex").slice(0, 16)}.step`);
}

/** A TOTP code from a 30 s step not yet used for this secret (waits for the next step if needed). */
export async function freshTotp(secret: string): Promise<string> {
  const f = totpStepFile(secret);
  const last = existsSync(f) ? Number(readFileSync(f, "utf8")) : -1;
  let step = Math.floor(Date.now() / 30_000);
  if (Number.isFinite(last) && step <= last) {
    const waitMs = (last + 1) * 30_000 - Date.now() + 250;
    // The wait is known up front: grant it to the test instead of eating its timeout budget.
    try {
      test.info().setTimeout(test.info().timeout + waitMs);
    } catch {
      /* outside a test (global setup): no per-test timeout to extend */
    }
    await new Promise((r) => setTimeout(r, waitMs));
    step = Math.floor(Date.now() / 30_000);
  }
  mkdirSync(path.dirname(f), { recursive: true });
  writeFileSync(f, String(step));
  return totp(secret, step * 30_000);
}

/** Signs in and completes MFA / new-device verification when asked. Ends off /login. */
export async function signIn(page: Page, request: APIRequestContext, who: Account, next = "/") {
  await restoreDevice(page, who.identifier);
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email or mobile").fill(who.identifier);
  await page.getByLabel(/^Password/).fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !/^\/login\/?$/.test(u.pathname), { timeout: 20_000 });
  if (/\/login\/mfa/.test(page.url())) {
    expect(who.totpSecret, `TOTP secret for ${who.identifier}`).toBeTruthy();
    await page.getByLabel("Authenticator code").fill(await freshTotp(who.totpSecret!));
    await page.getByRole("button", { name: "Verify" }).click();
    await page.waitForURL((u) => !/\/login\/mfa/.test(u.pathname), { timeout: 20_000 });
  }
  if (/\/login\/verify-device/.test(page.url())) {
    const sentAt = Date.now();
    await page.getByRole("button", { name: /Send code by email/ }).click();
    await page.getByLabel("6-digit code").fill(await latestOtp(request, who.identifier, sentAt));
    await page.getByRole("button", { name: "Confirm" }).click();
    // Device cap: replace the least recently used device (counts as 1 of 2 replacements / 30 days).
    const replace = page.getByRole("button", { name: "Remove and continue" });
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 10_000 }).catch(() => undefined);
    if (await replace.isVisible().catch(() => false)) {
      await page.getByRole("radio", { name: /last used (?!now)/ }).first().check();
      await replace.click();
    }
    await page.waitForURL((u) => !u.pathname.startsWith("/login") || /\/login\/session-choice/.test(u.pathname), { timeout: 20_000 });
  }
  if (/\/login\/session-choice/.test(page.url())) {
    // Session cap (2): sign out the least recently active other session.
    await page.getByRole("radio", { name: /active (?!now)/ }).first().check();
    await page.getByRole("button", { name: "Sign out selected and continue" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20_000 });
  }
  await saveDevice(page, who.identifier);
}
