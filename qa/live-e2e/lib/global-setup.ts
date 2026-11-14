import fs from "node:fs";
import path from "node:path";
import { request, type FullConfig } from "@playwright/test";
import { creds, roles, stateFile } from "./roles";

/** Sign every QA role in through the live API once per run and save its cookies (storageState). */
export default async function globalSetup(config: FullConfig) {
  const base = config.projects[0]?.use.baseURL ?? "https://techdrona-lms-app.web.app";
  fs.mkdirSync(path.dirname(stateFile("admin")), { recursive: true });
  const c = creds();
  for (const r of roles()) {
    const ctx = await request.newContext({ baseURL: base });
    await ctx.get("/api/v1/_bff/csrf");
    const tok = (await ctx.storageState()).cookies.find((k) => k.name.endsWith("td_csrf"))?.value ?? "";
    const res = await ctx.post("/api/v1/auth/login", {
      data: { identifier: c.accounts[r], password: c.password },
      headers: { "x-csrf-token": tok, origin: base },
    });
    if (res.status() !== 200) throw new Error(`login ${r}: HTTP ${res.status()} ${(await res.text()).slice(0, 200)}`);
    await ctx.storageState({ path: stateFile(r) });
    await ctx.dispose();
  }
}
