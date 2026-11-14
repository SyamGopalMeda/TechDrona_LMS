// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import type { BffConfig } from "./config";
import { allowedOrigins, handlePublicAdmissions, resolveRoute, sniff } from "./public-admissions";

const SITE = "https://35-244-50-26.sslip.io";
const config: BffConfig = {
  apiInternalUrl: "http://api:8000",
  serviceToken: "svc-token",
  csrfKeys: ["k".repeat(40)],
  publicOrigin: "https://lms.35-244-50-26.sslip.io",
  proxyTimeoutMs: 5000,
  originVerifyValue: "",
  trustedProxyHops: 1,
  cookieMode: "secure",
};
const env = { TD_WEBSITE_URL: SITE } as unknown as NodeJS.ProcessEnv;
const base = "https://lms.35-244-50-26.sslip.io/api/public/admissions/";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...new Array(300).fill(1)]);

function upstreamOk(status = 201, body: unknown = { reg_no: "TDR-AB12CD34" }) {
  return vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

function form(data: Record<string, unknown>, files: Record<string, Uint8Array | string> = { proof: PNG }): FormData {
  const f = new FormData();
  f.set("data", JSON.stringify(data));
  for (const [k, v] of Object.entries(files)) {
    if (typeof v === "string") f.set(k, v);
    else f.set(k, new Blob([v as BlobPart]), `${k}.bin`);
  }
  return f;
}

describe("public admissions bridge", () => {
  it("serves only the four public routes", () => {
    expect(resolveRoute("GET", "plans/full-stack-java")?.upstream).toBe("public/admissions/plans/full-stack-java");
    expect(resolveRoute("POST", "registrations")?.kind).toBe("multipart");
    expect(resolveRoute("POST", "status")?.kind).toBe("json");
    expect(resolveRoute("GET", "plans/../x")).toBeNull();
    expect(resolveRoute("POST", "plans/x")).toBeNull();
    expect(resolveRoute("DELETE", "claims")).toBeNull();
  });

  it("builds the allow-list from env without wildcards", () => {
    expect([...allowedOrigins({ TD_ADMISSIONS_ALLOWED_ORIGINS: `${SITE}/, http://evil.example, *` } as unknown as NodeJS.ProcessEnv)]).toEqual([SITE]);
    expect([...allowedOrigins({} as NodeJS.ProcessEnv)]).toEqual([]);
  });

  it("answers the preflight only for the website origin", async () => {
    const ok = await handlePublicAdmissions(new Request(`${base}registrations`, { method: "OPTIONS", headers: { origin: SITE } }), { config, env });
    expect(ok.status).toBe(204);
    expect(ok.headers.get("access-control-allow-origin")).toBe(SITE);
    expect(ok.headers.get("access-control-allow-credentials")).toBeNull();
    const bad = await handlePublicAdmissions(new Request(`${base}registrations`, { method: "OPTIONS", headers: { origin: "https://evil.example" } }), { config, env });
    expect(bad.status).toBe(403);
    expect(bad.headers.get("access-control-allow-origin")).toBeNull();
  });

  it("forwards a multipart registration as JSON with base64 files, service token and client ip", async () => {
    const fetchImpl = upstreamOk();
    const req = new Request(`${base}registrations`, {
      method: "POST",
      headers: { origin: SITE, "x-forwarded-for": "203.0.113.9, 10.0.0.2", cookie: "__Host-td_session=steal" },
      body: form({ course_slug: "java", resume: "ignored" }, { proof: PNG, proof_sha256: "a".repeat(64) }),
    });
    const res = await handlePublicAdmissions(req, { config, env, fetchImpl: fetchImpl as unknown as typeof fetch });
    expect(res.status).toBe(201);
    expect(res.headers.get("access-control-allow-origin")).toBe(SITE);
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(String(url)).toBe("http://api:8000/api/v1/public/admissions/registrations");
    const h = new Headers(init!.headers);
    expect(h.get("authorization")).toBe("Service svc-token");
    expect(h.get("cookie")).toBeNull();
    expect(h.get("x-td-client-ip")).toBe("203.0.113.9");
    const body = JSON.parse(String(init!.body));
    expect(body.course_slug).toBe("java");
    expect(body.resume).toBeUndefined();
    expect(body.proof.original_sha256).toBe("a".repeat(64));
    expect(Buffer.from(body.proof.data_b64, "base64")[0]).toBe(0x89);
  });

  it("refuses wrong origins, missing origin on writes, bad types and big files", async () => {
    const fetchImpl = upstreamOk();
    const deps = { config, env, fetchImpl: fetchImpl as unknown as typeof fetch };
    const evil = await handlePublicAdmissions(new Request(`${base}claims`, { method: "POST", headers: { origin: "https://evil.example" }, body: form({}) }), deps);
    expect(evil.status).toBe(403);
    const none = await handlePublicAdmissions(new Request(`${base}claims`, { method: "POST", body: form({}) }), deps);
    expect(none.status).toBe(403);
    const txt = await handlePublicAdmissions(new Request(`${base}claims`, { method: "POST", headers: { origin: SITE }, body: form({}, { proof: new TextEncoder().encode("hello ".repeat(50)) }) }), deps);
    expect(txt.status).toBe(422);
    const big = new Uint8Array(2 * 1024 * 1024 + 10);
    big.set(PNG.slice(0, 8));
    const large = await handlePublicAdmissions(new Request(`${base}claims`, { method: "POST", headers: { origin: SITE }, body: form({}, { proof: big }) }), deps);
    expect(large.status).toBe(422);
    const json = await handlePublicAdmissions(new Request(`${base}claims`, { method: "POST", headers: { origin: SITE, "content-type": "application/json" }, body: "{}" }), deps);
    expect(json.status).toBe(415);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("proxies the plan GET and the JSON status lookup", async () => {
    const fetchImpl = upstreamOk(200, { slug: "java" });
    const deps = { config, env, fetchImpl: fetchImpl as unknown as typeof fetch };
    expect((await handlePublicAdmissions(new Request(`${base}plans/java`, { headers: { origin: SITE } }), deps)).status).toBe(200);
    const st = await handlePublicAdmissions(
      new Request(`${base}status`, { method: "POST", headers: { origin: SITE, "content-type": "application/json" }, body: JSON.stringify({ reg_no: "TDR-AB12CD34", email: "a@b.co" }) }),
      deps,
    );
    expect(st.status).toBe(200);
    expect(String(fetchImpl.mock.calls[1]![0])).toContain("/public/admissions/status");
  });

  it("serves the course registration status to the website (GET only, same CORS allow-list)", async () => {
    const fetchImpl = upstreamOk(200, { data: { java: "open" }, updated_at: null });
    const deps = { config, env, fetchImpl: fetchImpl as unknown as typeof fetch };
    const url = "https://lms.35-244-50-26.sslip.io/api/public/courses/status";
    const ok = await handlePublicAdmissions(new Request(url, { headers: { origin: SITE } }), deps);
    expect(ok.status).toBe(200);
    expect(ok.headers.get("access-control-allow-origin")).toBe(SITE);
    expect(await ok.json()).toEqual({ data: { java: "open" }, updated_at: null });
    expect(String(fetchImpl.mock.calls[0]![0])).toBe("http://api:8000/api/v1/public/courses/status");
    expect((await handlePublicAdmissions(new Request(url, { method: "POST", headers: { origin: SITE } }), deps)).status).toBe(404);
    expect((await handlePublicAdmissions(new Request(url, { headers: { origin: "https://evil.example" } }), deps)).status).toBe(403);
    expect((await handlePublicAdmissions(new Request(`${url}/x`, { headers: { origin: SITE } }), deps)).status).toBe(404);
  });

  it("sniffs magic bytes", () => {
    expect(sniff(PNG)).toBe("image/png");
    expect(sniff(new TextEncoder().encode("%PDF-1.4"))).toBe("application/pdf");
    expect(sniff(new Uint8Array([1, 2, 3]))).toBe("");
  });
});
