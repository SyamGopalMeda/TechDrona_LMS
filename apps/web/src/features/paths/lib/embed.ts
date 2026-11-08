/** Embedding helpers for video / reading steps. Only https URLs are ever framed or linked. */

export function safeHttpsUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const url = new URL(u);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

const YT_ID = /^[A-Za-z0-9_-]{6,20}$/;

/** Privacy-friendly embed URL for YouTube / Vimeo links; null for anything else. */
export function videoEmbedUrl(u: string | null | undefined): string | null {
  const safe = safeHttpsUrl(u);
  if (!safe) return null;
  const url = new URL(safe);
  const host = url.hostname.replace(/^www\./, "").replace(/^m\./, "");
  let id: string | null = null;
  if (host === "youtube.com" || host === "youtube-nocookie.com") {
    if (url.pathname === "/watch") id = url.searchParams.get("v");
    else {
      const m = /^\/(?:embed|shorts|live)\/([^/?#]+)/.exec(url.pathname);
      id = m?.[1] ?? null;
    }
  } else if (host === "youtu.be") {
    id = url.pathname.slice(1).split("/")[0] ?? null;
  }
  if (id && YT_ID.test(id)) return `https://www.youtube-nocookie.com/embed/${id}`;
  if (host === "vimeo.com" || host === "player.vimeo.com") {
    const m = /\/(?:video\/)?(\d{4,12})(?:$|[/?#])/.exec(url.pathname);
    if (m) return `https://player.vimeo.com/video/${m[1]}`;
  }
  return null;
}

/**
 * D9 / SEC-08: hosts a path step may be framed from. Must match `EMBED_FRAME_ORIGINS` in the CSP
 * (`src/lib/security/csp.ts`, frame-src). Everything else is shown as an "open in a new tab" link.
 */
export const EMBED_HOSTS = ["www.youtube-nocookie.com", "player.vimeo.com", "docs.google.com", "drive.google.com"] as const;

const GOOGLE_ID = /^[A-Za-z0-9_-]{10,200}$/;
const DOC_KINDS = new Set(["document", "spreadsheets", "presentation"]);

/**
 * Google Docs/Sheets/Slides and Drive file viewers, normalised to their preview URL (read-only,
 * no editing UI). Published docs (`/d/e/{id}/pub`, `/pubhtml`, `/embed`) keep their path with
 * `embedded=true`. Forms, folders and anything else return null.
 */
export function googleEmbedUrl(u: string | null | undefined): string | null {
  const safe = safeHttpsUrl(u);
  if (!safe) return null;
  const url = new URL(safe);
  if (url.port || url.username || url.password) return null;
  const parts = url.pathname.split("/").filter(Boolean);
  if (url.hostname === "docs.google.com") {
    const [kind, d, id, rest] = parts;
    if (!kind || !DOC_KINDS.has(kind) || d !== "d" || !id) return null;
    if (id === "e") {
      const pubId = rest;
      const mode = parts[4];
      if (!pubId || !GOOGLE_ID.test(pubId) || !mode || !["pub", "pubhtml", "embed"].includes(mode)) return null;
      return `https://docs.google.com/${kind}/d/e/${pubId}/${mode}?embedded=true`;
    }
    if (!GOOGLE_ID.test(id)) return null;
    return `https://docs.google.com/${kind}/d/${id}/preview`;
  }
  if (url.hostname === "drive.google.com") {
    const [file, d, id] = parts;
    if (file !== "file" || d !== "d" || !id || !GOOGLE_ID.test(id)) return null;
    return `https://drive.google.com/file/d/${id}/preview`;
  }
  return null;
}

/** The only URLs a path step may put in an iframe: allow-listed video players and Google viewers. */
export function embeddableUrl(u: string | null | undefined): string | null {
  const out = videoEmbedUrl(u) ?? googleEmbedUrl(u);
  if (!out) return null;
  const host = new URL(out).hostname;
  return (EMBED_HOSTS as readonly string[]).includes(host) ? out : null;
}
