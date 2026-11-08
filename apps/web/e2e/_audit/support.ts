import { appendFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { expect, type APIRequestContext, type BrowserContext, type Page, type TestInfo } from "@playwright/test";
import { MAILPIT, freshTotp } from "../support/auth";

/**
 * AUDIT (Phase A) helpers — exploratory specs, not part of the product suite.
 * Diagnostics (console errors, page errors, failed / >=400 requests) are appended to
 * AUDIT_OUT (default: <os tmp>/td-audit) as JSON lines so the audit can quote them.
 */
export const OUT = process.env.AUDIT_OUT ?? path.join(process.env.TEMP ?? "/tmp", "td-audit");
mkdirSync(OUT, { recursive: true });
export const DEV_PASSWORD = "dev-only-lantern-harbour-2026";
export const NOTICE = "2026-11-01";

export function log(file: string, obj: unknown) {
  appendFileSync(path.join(OUT, file), `${JSON.stringify(obj)}\n`);
}

/** Records console errors, page errors, failed requests and HTTP >= 400 on every page of a context. */
export function watch(context: BrowserContext, info: TestInfo, label = "") {
  const tag = `${info.title}${label ? ` [${label}]` : ""}`;
  const hook = (page: Page) => {
    page.on("console", (m) => {
      if (m.type() === "error" || m.type() === "warning")
        log("console.jsonl", { test: tag, type: m.type(), url: page.url(), text: m.text().slice(0, 400) });
    });
    page.on("pageerror", (e) => log("console.jsonl", { test: tag, type: "pageerror", url: page.url(), text: String(e).slice(0, 400) }));
    page.on("requestfailed", (r) => {
      const f = r.failure()?.errorText ?? "";
      if (/ERR_ABORTED/.test(f)) return; // navigation-cancelled prefetches
      log("network.jsonl", { test: tag, kind: "failed", method: r.method(), url: r.url(), error: f, page: page.url() });
    });
    page.on("response", (r) => {
      if (r.status() >= 400)
        log("network.jsonl", { test: tag, kind: "http", status: r.status(), method: r.request().method(), url: r.url(), page: page.url() });
    });
  };
  context.pages().forEach(hook);
  context.on("page", hook);
}

/** Same-origin BFF call from inside the page (session + CSRF cookies of that browser context). */
export async function api<T = unknown>(page: Page, method: string, apiPath: string, body?: unknown): Promise<{ status: number; json: T }> {
  return page.evaluate(
    async ({ method, apiPath, body }) => {
      if (method !== "GET") await fetch("/api/v1/_bff/csrf", { credentials: "same-origin" });
      const csrf = document.cookie.split("; ").find((c) => /td_csrf=/.test(c))?.split("=")[1] ?? "";
      const headers: Record<string, string> = { accept: "application/json" };
      if (method !== "GET") {
        headers["x-csrf-token"] = decodeURIComponent(csrf);
        headers["idempotency-key"] = crypto.randomUUID();
      }
      if (body !== undefined) headers["content-type"] = "application/json";
      const res = await fetch(`/api/v1/${apiPath}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
      const text = await res.text();
      let json: unknown = text;
      try {
        json = JSON.parse(text);
      } catch {
        /* not json */
      }
      return { status: res.status, json };
    },
    { method, apiPath, body },
  ) as Promise<{ status: number; json: T }>;
}

export async function mailText(request: APIRequestContext, to: string, after: number, re: RegExp): Promise<string> {
  for (let i = 0; i < 30; i += 1) {
    const res = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    if (res.ok()) {
      const msgs = ((await res.json()) as { messages?: { ID: string; Created: string }[] }).messages ?? [];
      for (const m of msgs) {
        if (Date.parse(m.Created) < after - 5_000) continue;
        const b = (await (await request.get(`${MAILPIT}/api/v1/message/${m.ID}`)).json()) as { Subject?: string; Text?: string; HTML?: string };
        const t = `${b.Subject ?? ""}\n${b.Text ?? ""}\n${b.HTML ?? ""}`;
        if (re.test(t)) return t;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`No mail matching ${re} for ${to}`);
}

const seenOtp = new Set<string>();
/** Device OTP from Mailpit: strictly newer than `after`, never the same message twice (the shared helper's 5 s slack can return an older code). */
export async function latestOtp(request: APIRequestContext, to: string, after: number): Promise<string> {
  for (let i = 0; i < 30; i += 1) {
    const res = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    if (res.ok()) {
      const msgs = ((await res.json()) as { messages?: { ID: string; Created: string; Snippet?: string }[] }).messages ?? [];
      const fresh = msgs.find((m) => !seenOtp.has(m.ID) && Date.parse(m.Created) >= after - 1_000 && /code/i.test(m.Snippet ?? ""));
      if (fresh) {
        const body = (await (await request.get(`${MAILPIT}/api/v1/message/${fresh.ID}`)).json()) as { Text?: string };
        const code = /\b(\d{6})\b/.exec(body.Text ?? "")?.[1];
        if (code) {
          seenOtp.add(fresh.ID);
          return code;
        }
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`No OTP email for ${to}`);
}

export interface Fresh {
  email: string;
  password: string;
}

export function freshIdentity(tag: string): Fresh {
  const n = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
  return { email: `audit.${tag}.${n}@example.com`, password: `audit-${n}-correct-horse-battery` };
}

/** Signup through the real UI, then click the email verification link from Mailpit. */
export async function signupAndVerify(page: Page, request: APIRequestContext, who: Fresh, name = "Audit Learner") {
  const t0 = Date.now();
  await page.goto("/signup");
  await page.getByLabel(/Full name/).fill(name);
  await page.getByLabel(/^Email/).fill(who.email);
  await page.getByLabel("Day").selectOption("12");
  await page.getByLabel("Month").selectOption("April");
  await page.getByLabel("Year").selectOption("2000");
  await page.getByLabel(/^Password/).fill(who.password);
  await page.getByRole("checkbox", { name: /I agree to the/ }).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible({ timeout: 20_000 });
  const mail = await mailText(request, who.email, t0, /verify\/email\//);
  const token = /\/verify\/email\/([A-Za-z0-9_\-.~%]+)/.exec(mail)![1];
  await page.goto(`/verify/email/${token}`);
  await page.getByRole("button", { name: "Verify my email" }).click();
  await expect(page.getByText("Your email is verified")).toBeVisible({ timeout: 20_000 });
}

/** UI login on this page's context; handles new-device OTP / MFA / caps. Returns final pathname-ish url. */
export async function uiLogin(
  page: Page,
  request: APIRequestContext,
  identifier: string,
  password: string,
  opts: { totpSecret?: string; next?: string; resolveCaps?: boolean } = {},
): Promise<string> {
  await page.goto(`/login${opts.next ? `?next=${encodeURIComponent(opts.next)}` : ""}`);
  await page.getByLabel("Email or mobile").fill(identifier);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !/^\/login\/?$/.test(u.pathname), { timeout: 20_000 }).catch(() => undefined);
  if (/\/login\/mfa/.test(page.url())) {
    await page.getByLabel("Authenticator code").fill(await freshTotp(opts.totpSecret!));
    await page.getByRole("button", { name: "Verify" }).click();
    await page.waitForURL((u) => !/\/login\/mfa/.test(u.pathname), { timeout: 20_000 });
  }
  if (/\/login\/verify-device/.test(page.url())) {
    const sentAt = Date.now();
    await page.getByRole("button", { name: /Send code by email/ }).click();
    await page.getByLabel("6-digit code").fill(await latestOtp(request, identifier, sentAt));
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.waitForTimeout(2_500);
  }
  return page.url();
}

export async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT, "shots", `${name}.png`), fullPage: true });
}

/** True when the document is wider than the viewport (horizontal scroll at this width). */
export async function overflowX(page: Page): Promise<{ scroll: number; client: number; offenders: string[] }> {
  return page.evaluate(() => {
    const client = document.documentElement.clientWidth;
    const offenders: string[] = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const r = (el as HTMLElement).getBoundingClientRect();
      if (r.right > client + 1 && r.width > 0 && offenders.length < 8) {
        const h = el as HTMLElement;
        offenders.push(`${h.tagName.toLowerCase()}${h.id ? `#${h.id}` : ""}${h.className && typeof h.className === "string" ? `.${h.className.split(" ").slice(0, 2).join(".")}` : ""} right=${Math.round(r.right)}`);
      }
    }
    return { scroll: document.documentElement.scrollWidth, client, offenders };
  });
}
