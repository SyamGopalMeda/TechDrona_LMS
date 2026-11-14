import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";

/**
 * Studio media uploads (MED-01..03).
 *
 * MED-01 `POST media/uploads/video` and MED-02 `POST media/uploads/file` return an upload ticket
 * `{url, fields}`: a form POST the browser sends straight to the provider (VdoCipher's S3 policy
 * or our presigned content bucket) — the file never passes through the api. MED-03
 * `GET media/assets/{id}/status` refreshes provider/scan state until the asset is ready or failed.
 */

export interface UploadTicket {
  url: string;
  fields: Record<string, unknown>;
}

export interface VideoTicket {
  lesson_asset_id: string;
  provider: string;
  status: string;
  upload: UploadTicket;
}

export interface FileTicket {
  purpose: string;
  s3_key: string;
  upload: UploadTicket;
  expires_at: string;
  max_bytes: number;
  lesson_asset_id?: string;
}

export interface AssetStatus {
  id: string;
  asset_type: string;
  provider: string;
  status: "uploading" | "processing" | "ready" | "failed" | string;
  scan_status: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  duration_seconds: number | null;
}

export const TERMINAL_ASSET_STATUSES = ["ready", "failed"];

/** Lesson files accepted by MED-02 (`lesson_file`): PDF and captions. */
export const LESSON_FILE_TYPES: Record<string, NonNullable<Body<"media/uploads/file", "post">["asset_type"]>> = {
  "application/pdf": "pdf",
  "text/vtt": "captions",
};

export class ProviderUploadError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
    this.name = "ProviderUploadError";
  }
}

/** Multipart form POST of `file` to the provider URL with the ticket fields first (S3 POST policy order). */
export async function postToProvider(ticket: UploadTicket, file: File, fetchImpl: typeof fetch = fetch): Promise<void> {
  if (!/^https?:\/\//.test(ticket.url)) throw new ProviderUploadError("The upload service returned no upload address.", null);
  // The api's fake (demo) video adapter hands out tickets for an `*.invalid` host (RFC 2606),
  // which can never be reached: say the provider is not integrated instead of blaming the network.
  if (/^https?:\/\/[^/]*\.invalid(?::\d+)?(?:\/|$)/i.test(ticket.url))
    throw new ProviderUploadError("Not integrated yet: video hosting is a placeholder in this environment, so files can't be uploaded here.", null);
  const form = new FormData();
  for (const [k, v] of Object.entries(ticket.fields ?? {})) form.append(k, typeof v === "string" ? v : JSON.stringify(v));
  form.append("file", file);
  let res: Response;
  try {
    res = await fetchImpl(ticket.url, { method: "POST", body: form, credentials: "omit" });
  } catch {
    throw new ProviderUploadError("The upload couldn't reach the storage provider. Check your connection and try again.", null);
  }
  if (!res.ok) throw new ProviderUploadError(`The storage provider rejected the upload (HTTP ${res.status}).`, res.status);
}

export function requestVideoUpload(lessonId: string, title: string) {
  return api.post<VideoTicket>("media/uploads/video", { lesson_id: lessonId, title: title.slice(0, 200) } satisfies Body<"media/uploads/video", "post">, { idempotencyKey: true });
}

export function requestFileUpload(body: Partial<Body<"media/uploads/file", "post">>) {
  return api.post<FileTicket>("media/uploads/file", body, { idempotencyKey: true });
}

export function getAssetStatus(assetId: string) {
  return api.get<AssetStatus>(`media/assets/${encodeURIComponent(assetId)}/status`);
}

/**
 * Poll MED-03 until the asset is ready/failed, `maxTries` is reached or `signal` aborts.
 * Returns the last status seen (null when aborted before the first answer).
 */
export async function pollAssetStatus(
  assetId: string,
  opts: { intervalMs?: number; maxTries?: number; signal?: AbortSignal; onStatus?: (s: AssetStatus) => void } = {},
): Promise<AssetStatus | null> {
  const { intervalMs = 5000, maxTries = 60, signal, onStatus } = opts;
  let last: AssetStatus | null = null;
  for (let i = 0; i < maxTries; i++) {
    if (signal?.aborted) return last;
    last = await getAssetStatus(assetId);
    onStatus?.(last);
    if (TERMINAL_ASSET_STATUSES.includes(last.status)) return last;
    await new Promise<void>((resolve) => {
      const t = setTimeout(resolve, intervalMs);
      signal?.addEventListener("abort", () => {
        clearTimeout(t);
        resolve();
      });
    });
  }
  return last;
}
