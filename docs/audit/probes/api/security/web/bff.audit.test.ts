import { describe, expect, it } from "vitest";
import { safeNextPath } from "@/features/auth/lib/validation";
import { resolveClientIp } from "@/lib/bff/headers";
import { handleBffRequest } from "@/lib/bff/proxy";
import { mintCsrfToken } from "@/lib/bff/csrf";

describe("AUDIT web security probes", () => {
  it("safeNextPath rejects tab-smuggled protocol-relative paths", () => {
    const sp = new URLSearchParams("next=/%09/evil.example");
    const out = safeNextPath(sp.get("next"));
    const resolved = new URL(out, "http://localhost:13000").href;
    console.log(`AUDIT safeNextPath(${JSON.stringify(sp.get("next"))}) -> ${JSON.stringify(out)} -> ${resolved}`);
    expect(new URL(out, "http://localhost:13000").origin).toBe("http://localhost:13000");
  });

  it("client IP with TD_TRUSTED_PROXY_HOPS=0 is taken from client-supplied X-Forwarded-For", () => {
    const h = new Headers({ "x-forwarded-for": "6.6.6.6" });
    const ip = resolveClientIp(h, 0);
    console.log(`AUDIT resolveClientIp(XFF=6.6.6.6, hops=0) -> ${ip}`);
    expect(ip).toBeNull();
  });

  it("cross-site POST without CSRF is refused; same-origin with valid token is proxied", async () => {
    const config = { apiInternalUrl: "http://api", serviceToken: "s".repeat(40), csrfKeys: ["k".repeat(40)], publicOrigin: "http://localhost:3000", proxyTimeoutMs: 1000, originVerifyValue: "", trustedProxyHops: 0, cookieMode: "dev-insecure" as const };
    let calls = 0;
    const fetchImpl = (async () => { calls++; return new Response("{}", { status: 200, headers: { "content-type": "application/json" } }); }) as unknown as typeof fetch;
    const cross = await handleBffRequest(new Request("http://localhost:3000/api/v1/me/profile", { method: "PATCH", headers: { "sec-fetch-site": "cross-site", "content-type": "application/json" }, body: "{}" }), { config, fetchImpl, env: {} as NodeJS.ProcessEnv });
    const tok = mintCsrfToken(config.csrfKeys[0]!, "sess");
    const noHeader = await handleBffRequest(new Request("http://localhost:3000/api/v1/me/profile", { method: "PATCH", headers: { "sec-fetch-site": "same-origin", "content-type": "application/json", cookie: `td_session=sess; td_csrf=${tok}` }, body: "{}" }), { config, fetchImpl, env: {} as NodeJS.ProcessEnv });
    const ok = await handleBffRequest(new Request("http://localhost:3000/api/v1/me/profile", { method: "PATCH", headers: { "sec-fetch-site": "same-origin", "content-type": "application/json", "x-csrf-token": tok, cookie: `td_session=sess; td_csrf=${tok}` }, body: "{}" }), { config, fetchImpl, env: {} as NodeJS.ProcessEnv });
    const otherSess = await handleBffRequest(new Request("http://localhost:3000/api/v1/me/profile", { method: "PATCH", headers: { "sec-fetch-site": "same-origin", "content-type": "application/json", "x-csrf-token": tok, cookie: `td_session=other; td_csrf=${tok}` }, body: "{}" }), { config, fetchImpl, env: {} as NodeJS.ProcessEnv });
    const formPost = await handleBffRequest(new Request("http://localhost:3000/api/v1/auth/login", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "a=b" }), { config, fetchImpl, env: {} as NodeJS.ProcessEnv });
    console.log(`AUDIT BFF cross-site=${cross.status} no-header=${noHeader.status} valid=${ok.status} token-bound-to-other-session=${otherSess.status} form-post=${formPost.status} upstream-calls=${calls}`);
    expect([cross.status, noHeader.status, otherSess.status]).toEqual([403, 403, 403]);
    expect(ok.status).toBe(200);
  });
});
