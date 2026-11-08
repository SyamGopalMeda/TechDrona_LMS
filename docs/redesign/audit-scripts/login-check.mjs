// Signs in each role once (saving state outside the repo) and prints /me status + portals.
import { chromium, roleContext, bff, BASE } from "./lib.mjs";
const browser = await chromium.launch();
for (const role of (process.argv[2] ?? "admin,trainer,evaluator,content,student").split(",")) {
  try {
    const ctx = await roleContext(browser, role);
    const p = await ctx.newPage();
    await p.goto(`${BASE}/`);
    const g = await bff(p, "GET", "me/grants");
    console.log(role, g.status, JSON.stringify(g.json.portals), (g.json.data ?? []).map((x) => `${x.role_key}@${x.scope_type ?? ""}`).join(","));
    await ctx.close();
  } catch (e) { console.log(role, "LOGIN FAILED", String(e).slice(0, 300)); }
}
await browser.close();
