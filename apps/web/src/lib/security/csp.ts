/**
 * Content-Security-Policy per security-threat-model.md ("XSS leading to session riding").
 *
 * - Scripts: per-request nonce + 'strict-dynamic'. Scripts inserted by our nonce-trusted bundle
 *   (Razorpay Checkout, VdoCipher player API, the self-hosted Monaco AMD loader under /vendor)
 *   inherit trust; the host entries are only the CSP Level 2 fallback (ignored by CSP3 browsers
 *   when 'strict-dynamic' is present). Never 'unsafe-inline'; 'unsafe-eval' only in dev (React
 *   Refresh). Monaco needs neither: its workers are same-origin files (worker-src 'self' blob:)
 *   and /vendor/** is excluded from the middleware so worker scripts carry no page CSP.
 * - Frames: VdoCipher player, Razorpay Checkout and the learning-path embed allow-list (owner
 *   decision D9 / SEC-08: YouTube no-cookie, Vimeo player, Google Docs/Drive viewers). No 'self':
 *   nothing same-origin is framed, so a same-origin page with user HTML can never be embedded.
 * - connect-src / form-action: same origin, Razorpay Checkout APIs, and the exact origins that
 *   receive presigned POST uploads (from env): the uploads and content buckets, and the
 *   VdoCipher upload origin. Local SeaweedFS/MinIO (http://localhost:9000)
 *   only outside production; production accepts https:// origins only.
 * - No objects, no <base>, never framed.
 */

export const RAZORPAY = {
  script: "https://checkout.razorpay.com",
  frames: ["https://api.razorpay.com", "https://checkout.razorpay.com"],
  connect: ["https://api.razorpay.com", "https://lumberjack.razorpay.com"],
  img: ["https://cdn.razorpay.com", "https://checkout.razorpay.com"],
} as const;

export const VDOCIPHER = {
  script: "https://player.vdocipher.com",
  frames: ["https://player.vdocipher.com"],
  /**
   * Default origin of the presigned S3 POST in VdoCipher's `clientPayload.uploadLink` (from the
   * provider's upload docs; unverified here). Override with `TD_CSP_VDOCIPHER_UPLOAD_ORIGINS`.
   */
  upload: ["https://vdo-ap-southeast.s3-accelerate.amazonaws.com"],
} as const;

/**
 * D9: learning-path step embeds. Keep in sync with `EMBED_HOSTS` in
 * `src/features/paths/lib/embed.ts` (a unit test checks they match).
 */
export const EMBED_FRAME_ORIGINS = ["https://www.youtube-nocookie.com", "https://player.vimeo.com", "https://docs.google.com", "https://drive.google.com"] as const;

export const DEV_OBJECT_STORE_ORIGIN = "http://localhost:9000";

export interface CspOptions {
  dev: boolean;
  /** Origins that receive presigned uploads (scheme://host[:port], no path). */
  uploadOrigins?: string[];
}

/** Normalise to an origin; drop anything that is not an http(s) origin, and http:// in production. */
export function toOrigin(value: string, dev: boolean): string | null {
  try {
    const u = new URL(value.trim());
    if (u.protocol !== "https:" && !(dev && u.protocol === "http:")) return null;
    if (u.username || u.password) return null;
    if (u.hostname.includes("*")) return null; // never a wildcard source

    return u.origin;
  } catch {
    return null;
  }
}

type Env = Record<string, string | undefined>;

/**
 * Upload origins from env:
 * - `TD_CSP_UPLOAD_ORIGINS` (comma-separated) wins when set;
 * - else `S3_ENDPOINT_URL` (path-style: MinIO/SeaweedFS) — dev only unless it is https;
 * - else AWS virtual-hosted style `https://<bucket>.s3.<AWS_REGION>.amazonaws.com` for the uploads
 *   bucket (`S3_BUCKET_UPLOADS`) and the content bucket (`S3_BUCKET_CONTENT`: lesson PDFs/images);
 * - in dev, the local object store `http://localhost:9000` is always allowed.
 */
export function uploadOriginsFromEnv(env: Env, dev: boolean): string[] {
  const out = new Set<string>();
  const add = (v: string | undefined) => {
    const o = v ? toOrigin(v, dev) : null;
    if (o) out.add(o);
  };
  const explicit = env.TD_CSP_UPLOAD_ORIGINS?.trim();
  if (explicit) {
    for (const part of explicit.split(",")) add(part);
  } else if (env.S3_ENDPOINT_URL?.trim()) {
    add(env.S3_ENDPOINT_URL);
  } else if (env.AWS_REGION && /^[a-z0-9-]+$/.test(env.AWS_REGION)) {
    for (const bucket of [env.S3_BUCKET_UPLOADS, env.S3_BUCKET_CONTENT]) {
      if (bucket && /^[a-z0-9.-]{3,63}$/.test(bucket)) add(`https://${bucket}.s3.${env.AWS_REGION}.amazonaws.com`);
    }
  }
  if (dev) out.add(DEV_OBJECT_STORE_ORIGIN);
  return [...out];
}

/**
 * VdoCipher video upload origins (studio direct upload to `clientPayload.uploadLink`):
 * `TD_CSP_VDOCIPHER_UPLOAD_ORIGINS` (comma-separated) when set, else the documented default.
 * Exact origins only; wildcards and non-https are dropped.
 */
export function vdocipherUploadOriginsFromEnv(env: Env, dev: boolean): string[] {
  const explicit = env.TD_CSP_VDOCIPHER_UPLOAD_ORIGINS?.trim();
  const raw = explicit ? explicit.split(",") : [...VDOCIPHER.upload];
  const out = new Set<string>();
  for (const v of raw) {
    const o = toOrigin(v, dev);
    if (o) out.add(o);
  }
  return [...out];
}

export function cspOptionsFromEnv(env: Env = process.env): CspOptions {
  const dev = env.NODE_ENV !== "production";
  return { dev, uploadOrigins: [...new Set([...uploadOriginsFromEnv(env, dev), ...vdocipherUploadOriginsFromEnv(env, dev)])] };
}

export function buildCsp(nonce: string, options: CspOptions | boolean): string {
  const opts: CspOptions = typeof options === "boolean" ? { dev: options } : options;
  const { dev } = opts;
  const uploads = (opts.uploadOrigins ?? []).map((o) => toOrigin(o, dev)).filter((o): o is string => o !== null);
  const uniq = (xs: string[]) => [...new Set(xs)];

  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": uniq(["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", RAZORPAY.script, VDOCIPHER.script, ...(dev ? ["'unsafe-eval'"] : [])]),
    // Tailwind output is a static stylesheet; inline style attributes are used by React and Monaco.
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": uniq(["'self'", "data:", "blob:", ...RAZORPAY.img]),
    "font-src": ["'self'", "data:"],
    "connect-src": uniq(["'self'", ...RAZORPAY.connect, ...uploads, ...(dev ? ["ws:", "wss:"] : [])]),
    "frame-src": uniq([...VDOCIPHER.frames, ...RAZORPAY.frames, ...EMBED_FRAME_ORIGINS]),
    "media-src": ["'self'", "blob:"],
    // Monaco editor workers (same-origin /vendor files; blob: for its fallback worker bootstrap).
    "worker-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": uniq(["'self'", ...uploads]),
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([k, v]) => `${k} ${v.join(" ")}`)
    .join("; ");
}

/** Parse a CSP string into directive → sources (for tests and diagnostics). */
export function parseCsp(csp: string): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const part of csp.split(";")) {
    const [name, ...values] = part.trim().split(/\s+/);
    if (name) out[name] = values;
  }
  return out;
}
