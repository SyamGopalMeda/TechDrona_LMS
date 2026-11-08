import { describe, expect, it } from "vitest";
import { buildCsp, cspOptionsFromEnv, parseCsp, toOrigin, uploadOriginsFromEnv, VDOCIPHER, vdocipherUploadOriginsFromEnv } from "./csp";

const NONCE = "abc123==";

describe("buildCsp", () => {
  it("keeps a strict nonce-based script-src in production (no unsafe-inline / unsafe-eval)", () => {
    const d = parseCsp(buildCsp(NONCE, { dev: false }));
    expect(d["script-src"]).toEqual(expect.arrayContaining(["'self'", `'nonce-${NONCE}'`, "'strict-dynamic'"]));
    expect(d["script-src"]).not.toContain("'unsafe-inline'");
    expect(d["script-src"]).not.toContain("'unsafe-eval'");
    expect(d["connect-src"]).not.toContain("ws:");
    expect(d["object-src"]).toEqual(["'none'"]);
    expect(d["base-uri"]).toEqual(["'none'"]);
    expect(d["frame-ancestors"]).toEqual(["'none'"]);
  });

  it("allows Razorpay Checkout script, frames and API calls", () => {
    const d = parseCsp(buildCsp(NONCE, { dev: false }));
    expect(d["script-src"]).toContain("https://checkout.razorpay.com");
    expect(d["frame-src"]).toEqual(expect.arrayContaining(["https://api.razorpay.com", "https://checkout.razorpay.com"]));
    expect(d["connect-src"]).toContain("https://api.razorpay.com");
  });

  it("allows VdoCipher player frames and API script", () => {
    const d = parseCsp(buildCsp(NONCE, { dev: false }));
    expect(d["frame-src"]).toContain("https://player.vdocipher.com");
    expect(d["script-src"]).toContain("https://player.vdocipher.com");
  });

  it("D9: frames only VdoCipher, Razorpay and the learning-path embed hosts (no 'self', no wildcards)", () => {
    const d = parseCsp(buildCsp(NONCE, { dev: false }));
    expect(d["frame-src"]!.sort()).toEqual(
      [
        "https://player.vdocipher.com",
        "https://api.razorpay.com",
        "https://checkout.razorpay.com",
        "https://www.youtube-nocookie.com",
        "https://player.vimeo.com",
        "https://docs.google.com",
        "https://drive.google.com",
      ].sort(),
    );
  });

  it("allows Monaco from /vendor (self) with same-origin/blob workers and no eval", () => {
    const d = parseCsp(buildCsp(NONCE, { dev: false }));
    expect(d["worker-src"]).toEqual(["'self'", "blob:"]);
    expect(d["font-src"]).toContain("'self'");
  });

  it("adds upload origins to connect-src and form-action", () => {
    const d = parseCsp(buildCsp(NONCE, { dev: false, uploadOrigins: ["https://td-uploads-prod.s3.ap-south-1.amazonaws.com"] }));
    expect(d["connect-src"]).toContain("https://td-uploads-prod.s3.ap-south-1.amazonaws.com");
    expect(d["form-action"]).toEqual(["'self'", "https://td-uploads-prod.s3.ap-south-1.amazonaws.com"]);
  });

  it("refuses http upload origins in production but allows them in dev", () => {
    expect(parseCsp(buildCsp(NONCE, { dev: false, uploadOrigins: ["http://localhost:9000"] }))["connect-src"]).not.toContain("http://localhost:9000");
    const dev = parseCsp(buildCsp(NONCE, { dev: true, uploadOrigins: ["http://localhost:9000"] }));
    expect(dev["connect-src"]).toEqual(expect.arrayContaining(["http://localhost:9000", "ws:", "wss:"]));
    expect(dev["script-src"]).toContain("'unsafe-eval'");
  });

  it("still accepts the legacy boolean signature", () => {
    expect(buildCsp(NONCE, true)).toContain("'unsafe-eval'");
    expect(buildCsp(NONCE, false)).not.toContain("'unsafe-eval'");
  });

  it("cannot be injected through upload origins", () => {
    const csp = buildCsp(NONCE, { dev: false, uploadOrigins: ["https://ok.example.com/path; script-src *", "javascript:alert(1)", "https://u:p@x.example.com"] });
    const d = parseCsp(csp);
    expect(d["connect-src"]).toContain("https://ok.example.com");
    expect(csp).not.toContain("script-src *");
    expect(csp).not.toContain("javascript:");
    expect(csp).not.toContain("x.example.com");
  });
});

describe("upload origins from env", () => {
  it("dev with local SeaweedFS endpoint", () => {
    expect(uploadOriginsFromEnv({ S3_ENDPOINT_URL: "http://localhost:9000" }, true)).toEqual(["http://localhost:9000"]);
  });

  it("production derives the AWS virtual-hosted bucket origin and never adds localhost", () => {
    const env = { NODE_ENV: "production", S3_BUCKET_UPLOADS: "td-uploads-prod", AWS_REGION: "ap-south-1" };
    expect(cspOptionsFromEnv(env)).toEqual({ dev: false, uploadOrigins: ["https://td-uploads-prod.s3.ap-south-1.amazonaws.com", ...VDOCIPHER.upload] });
  });

  it("production allows the content bucket and the VdoCipher upload origin in connect-src and form-action (webstaff R7)", () => {
    const env = { NODE_ENV: "production", S3_BUCKET_UPLOADS: "td-uploads-prod", S3_BUCKET_CONTENT: "td-content-prod", AWS_REGION: "ap-south-1", TD_CSP_VDOCIPHER_UPLOAD_ORIGINS: "https://vdo-ap-southeast.s3-accelerate.amazonaws.com/" };
    const csp = parseCsp(buildCsp("n0nce", cspOptionsFromEnv(env)));
    for (const d of ["connect-src", "form-action"]) {
      expect(csp[d]).toContain("https://td-content-prod.s3.ap-south-1.amazonaws.com");
      expect(csp[d]).toContain("https://td-uploads-prod.s3.ap-south-1.amazonaws.com");
      expect(csp[d]).toContain("https://vdo-ap-southeast.s3-accelerate.amazonaws.com");
      expect(csp[d]!.some((v) => v.includes("*"))).toBe(false);
    }
    expect(csp["script-src"]).toContain("'nonce-n0nce'");
  });

  it("never accepts a wildcard or http VdoCipher upload origin in production", () => {
    expect(vdocipherUploadOriginsFromEnv({ TD_CSP_VDOCIPHER_UPLOAD_ORIGINS: "https://*.amazonaws.com, http://x.example.com, https://ok.example.com" }, false)).toEqual(["https://ok.example.com"]);
  });

  it("production ignores an http endpoint", () => {
    expect(uploadOriginsFromEnv({ S3_ENDPOINT_URL: "http://localhost:9000" }, false)).toEqual([]);
  });

  it("explicit TD_CSP_UPLOAD_ORIGINS wins", () => {
    expect(uploadOriginsFromEnv({ TD_CSP_UPLOAD_ORIGINS: "https://a.example.com, https://b.example.com/x", S3_ENDPOINT_URL: "https://ignored.example.com" }, false)).toEqual([
      "https://a.example.com",
      "https://b.example.com",
    ]);
  });

  it("toOrigin strips paths", () => {
    expect(toOrigin("http://localhost:9000/local-td-uploads", true)).toBe("http://localhost:9000");
    expect(toOrigin("not a url", true)).toBeNull();
  });
});
