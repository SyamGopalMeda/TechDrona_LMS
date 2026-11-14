import { uuid7 } from "@/lib/ids/uuid7";
import { loadBffConfig, type BffConfig } from "./config";
import { resolveClientIp } from "./headers";

/**
 * Public admissions bridge for the company website (a different origin):
 *   website (https://<site>) → LMS web /api/public/admissions/* → api /api/v1/public/admissions/*
 *
 * Why a separate handler instead of the /api/v1 BFF: that proxy is same-origin only (Fetch
 * Metadata + signed double-submit CSRF) and must stay that way for every authenticated route.
 * This handler is cookie-less and only ever reaches four public endpoints, so it can safely
 * answer CORS for an explicit allow-list of website origins:
 *   - Allowed origins: TD_ADMISSIONS_ALLOWED_ORIGINS (comma list), else TD_WEBSITE_URL, else
 *     NEXT_PUBLIC_SITE_URL. No wildcard; `Access-Control-Allow-Credentials` is never sent and
 *     cookies from the browser are never forwarded.
 *   - Writes (POST) must carry an allowed `Origin` (blocks cross-site form posts from elsewhere).
 *   - Uploads are multipart/form-data: a `data` JSON field plus `proof` (JPEG/PNG/WebP/PDF) and
 *     optional `resume` (PDF/DOC/DOCX) files, each ≤ 2 MiB, type checked by magic bytes; the
 *     whole body ≤ 5 MiB. The api re-checks everything (type, size, sha256, re-encode).
 *   - Forwarded as JSON (files base64) with the service token and the attributed client IP, so
 *     the api's per-IP rate limits apply.
 */

export const PUBLIC_PREFIX = "/api/public/admissions/";
/** Course registration status (open / coming soon / closed) for the website's course pages. */
export const COURSE_STATUS_PATHNAME = "/api/public/courses/status";
export const MAX_FILE_BYTES = 2 * 1024 * 1024;
export const MAX_BODY_BYTES = 5 * 1024 * 1024;
const JSON_MAX = 16 * 1024;

type Route = { method: "GET" | "POST"; upstream: string; kind: "plain" | "json" | "multipart" };

/** The only paths this bridge serves (anything else is 404). */
export function resolveRoute(method: string, path: string): Route | null {
  const plan = /^plans\/([a-z0-9][a-z0-9-]{0,79})$/.exec(path);
  if (plan && method === "GET") return { method: "GET", upstream: `public/admissions/plans/${plan[1]}`, kind: "plain" };
  if (method !== "POST") return null;
  if (path === "registrations") return { method: "POST", upstream: "public/admissions/registrations", kind: "multipart" };
  if (path === "claims") return { method: "POST", upstream: "public/admissions/claims", kind: "multipart" };
  if (path === "status") return { method: "POST", upstream: "public/admissions/status", kind: "json" };
  return null;
}

const COURSE_STATUS_ROUTE: Route = { method: "GET", upstream: "public/courses/status", kind: "plain" };

export function allowedOrigins(env: NodeJS.ProcessEnv = process.env): Set<string> {
  const raw = env.TD_ADMISSIONS_ALLOWED_ORIGINS || env.TD_WEBSITE_URL || env.NEXT_PUBLIC_SITE_URL || "";
  const out = new Set<string>();
  for (const part of raw.split(",")) {
    const v = part.trim();
    if (!v) continue;
    try {
      const u = new URL(v);
      if (u.protocol === "https:" || u.hostname === "localhost" || u.hostname === "127.0.0.1") out.add(u.origin);
    } catch {
      /* ignore malformed entries */
    }
  }
  return out;
}

/** Real content type from the first bytes ("" when unknown). Mirrors the api / website sniffers. */
export function sniff(b: Uint8Array): string {
  const at = (i: number, ...xs: number[]) => xs.every((x, k) => b[i + k] === x);
  if (at(0, 0xff, 0xd8, 0xff)) return "image/jpeg";
  if (at(0, 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return "image/png";
  if (at(0, 0x52, 0x49, 0x46, 0x46) && at(8, 0x57, 0x45, 0x42, 0x50)) return "image/webp";
  if (at(0, 0x25, 0x50, 0x44, 0x46, 0x2d)) return "application/pdf";
  if (at(0, 0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1)) return "application/msword";
  if (at(0, 0x50, 0x4b, 0x03, 0x04)) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  return "";
}

const PROOF_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "application/pdf"]);
const RESUME_TYPES = new Set([
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);

export interface PublicDeps {
  config?: BffConfig;
  fetchImpl?: typeof fetch;
  env?: NodeJS.ProcessEnv;
}

function corsHeaders(origin: string | null, allowed: Set<string>): Headers {
  const h = new Headers({ vary: "Origin", "cache-control": "no-store", "x-content-type-options": "nosniff" });
  if (origin && allowed.has(origin)) {
    h.set("access-control-allow-origin", origin);
    h.set("access-control-allow-methods", "GET, POST, OPTIONS");
    h.set("access-control-allow-headers", "content-type");
    h.set("access-control-max-age", "600");
  }
  return h;
}

function problem(status: number, code: string, detail: string, headers: Headers, requestId: string, extra: Record<string, unknown> = {}): Response {
  headers.set("content-type", "application/problem+json");
  headers.set("x-request-id", requestId);
  return new Response(JSON.stringify({ type: `https://techdrona.in/problems/${code}`, title: detail, status, detail, code, request_id: requestId, ...extra }), {
    status,
    headers,
  });
}

function fieldProblem(field: string, message: string, headers: Headers, requestId: string): Response {
  return problem(422, "validation_failed", message, headers, requestId, { errors: [{ field, code: "invalid_file", message }] });
}

function b64(bytes: Uint8Array): string {
  return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength).toString("base64");
}

async function fileField(form: FormData, name: "proof" | "resume", required: boolean): Promise<{ ok: true; value: Record<string, string> | null } | { ok: false; message: string }> {
  const f = form.get(name);
  if (f === null || f === "") return required ? { ok: false, message: "Upload the payment screenshot or receipt." } : { ok: true, value: null };
  if (typeof f === "string") return { ok: false, message: "The file could not be read. Choose it again." };
  if (f.size > MAX_FILE_BYTES) return { ok: false, message: "That file is too large. The limit is 2 MB." };
  if (f.size < 100) return { ok: false, message: "That file is empty or damaged." };
  const bytes = new Uint8Array(await f.arrayBuffer());
  const real = sniff(bytes);
  if (!(name === "proof" ? PROOF_TYPES : RESUME_TYPES).has(real)) {
    return { ok: false, message: name === "resume" ? "Upload your resume as a PDF or Word file." : "Upload a JPG, PNG or WebP screenshot, or a PDF receipt." };
  }
  const value: Record<string, string> = { filename: (f.name || name).slice(0, 200), data_b64: b64(bytes) };
  const orig = form.get(`${name}_sha256`);
  if (typeof orig === "string" && /^[0-9a-f]{64}$/.test(orig)) value.original_sha256 = orig;
  return { ok: true, value };
}

export async function handlePublicAdmissions(request: Request, deps: PublicDeps = {}): Promise<Response> {
  const requestId = uuid7();
  const env = deps.env ?? process.env;
  const fetchImpl = deps.fetchImpl ?? fetch;
  const allowed = allowedOrigins(env);
  const origin = request.headers.get("origin");
  const headers = corsHeaders(origin, allowed);
  const method = request.method.toUpperCase();
  const url = new URL(request.url);
  const courseStatus = url.pathname === COURSE_STATUS_PATHNAME;
  if (!courseStatus && !url.pathname.startsWith(PUBLIC_PREFIX)) return problem(404, "not_found", "Not found.", headers, requestId);
  const path = courseStatus ? "" : url.pathname.slice(PUBLIC_PREFIX.length);

  if (method === "OPTIONS") {
    if (!origin || !allowed.has(origin)) return problem(403, "permission_denied", "Origin not allowed.", headers, requestId);
    return new Response(null, { status: 204, headers });
  }
  const route = courseStatus ? (method === "GET" ? COURSE_STATUS_ROUTE : null) : resolveRoute(method, path);
  if (!route) return problem(404, "not_found", "Not found.", headers, requestId);
  // A cross-origin call must come from the website; writes always need an allowed Origin.
  if (origin !== null && !allowed.has(origin)) return problem(403, "permission_denied", "Origin not allowed.", headers, requestId);
  if (method === "POST" && origin === null) return problem(403, "permission_denied", "Origin required.", headers, requestId);

  let config: BffConfig;
  try {
    config = deps.config ?? loadBffConfig(env);
  } catch {
    return problem(503, "service_unavailable", "The service is temporarily unavailable.", headers, requestId);
  }

  let body: string | undefined;
  if (route.kind !== "plain") {
    const declared = Number.parseInt(request.headers.get("content-length") ?? "", 10);
    const limit = route.kind === "json" ? JSON_MAX : MAX_BODY_BYTES;
    if (Number.isFinite(declared) && declared > limit) return problem(413, "payload_too_large", "The request is too large.", headers, requestId, { max_bytes: limit });
    const ct = (request.headers.get("content-type") ?? "").toLowerCase();
    if (route.kind === "json") {
      if (!ct.startsWith("application/json")) return problem(415, "unsupported_media_type", "Send JSON.", headers, requestId);
      const text = await request.text();
      if (text.length > JSON_MAX) return problem(413, "payload_too_large", "The request is too large.", headers, requestId, { max_bytes: JSON_MAX });
      body = text;
    } else {
      if (!ct.startsWith("multipart/form-data")) return problem(415, "unsupported_media_type", "Send the form as multipart/form-data.", headers, requestId);
      const buf = await request.arrayBuffer();
      if (buf.byteLength > MAX_BODY_BYTES) return problem(413, "payload_too_large", "The request is too large.", headers, requestId, { max_bytes: MAX_BODY_BYTES });
      let form: FormData;
      try {
        form = await new Response(buf, { headers: { "content-type": request.headers.get("content-type") ?? "" } }).formData();
      } catch {
        return problem(400, "validation_failed", "The form could not be read.", headers, requestId, { errors: [] });
      }
      const raw = form.get("data");
      let data: Record<string, unknown>;
      try {
        data = typeof raw === "string" && raw.length <= JSON_MAX ? (JSON.parse(raw) as Record<string, unknown>) : (null as never);
        if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("bad");
      } catch {
        return problem(400, "validation_failed", "The form could not be read.", headers, requestId, { errors: [] });
      }
      const proof = await fileField(form, "proof", true);
      if (!proof.ok) return fieldProblem("proof", proof.message, headers, requestId);
      const out: Record<string, unknown> = { ...data, proof: proof.value };
      delete out.resume;
      if (route.upstream.endsWith("registrations")) {
        const resume = await fileField(form, "resume", false);
        if (!resume.ok) return fieldProblem("resume", resume.message, headers, requestId);
        if (resume.value) out.resume = resume.value;
      }
      body = JSON.stringify(out);
    }
  }

  const up = new Headers({ accept: "application/json", "x-request-id": requestId, "accept-encoding": "identity" });
  if (body !== undefined) up.set("content-type", "application/json");
  if (config.serviceToken) up.set("authorization", `Service ${config.serviceToken}`);
  const ip = resolveClientIp(request.headers, config.trustedProxyHops);
  if (ip) up.set("x-td-client-ip", ip);
  const ua = request.headers.get("user-agent");
  if (ua) up.set("user-agent", ua.slice(0, 300));

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${config.apiInternalUrl}/api/v1/${route.upstream}`, {
      method: route.method,
      headers: up,
      body,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(config.proxyTimeoutMs),
    });
  } catch {
    return problem(503, "service_unavailable", "We could not reach the service. Please try again.", headers, requestId);
  }
  const ct = upstream.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  headers.set("x-request-id", upstream.headers.get("x-request-id") ?? requestId);
  const retry = upstream.headers.get("retry-after");
  if (retry) headers.set("retry-after", retry);
  return new Response(upstream.status === 204 ? null : await upstream.text(), { status: upstream.status, headers });
}
