import { api } from "@/lib/api/client";
import { postToProvider } from "@/features/studio/lib/media";
import type { MediaStatus, MediaTicket } from "./types";

export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

/** Client-side check before asking for an upload ticket (the api enforces the same limits). */
export function imageProblem(file: File): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return "Use a PNG, JPEG, WebP or GIF image.";
  if (file.size > MAX_IMAGE_BYTES) return "Images can be at most 5 MB.";
  return null;
}

export type UploadPhase = "uploading" | "scanning" | "ready" | "failed";

/**
 * Question image upload: request a ticket (`studio/question-media/uploads`), form-POST the file
 * straight to the storage provider, then `complete` and re-check while the virus scan is pending.
 * Resolves with the last status; `phase` is "ready" only for a clean scan.
 */
export async function uploadQuestionImage(
  file: File,
  opts: { organizationId?: string | null; onPhase?: (p: UploadPhase) => void; intervalMs?: number; maxChecks?: number } = {},
): Promise<{ media_id: string; url: string | null; phase: UploadPhase }> {
  const { organizationId, onPhase, intervalMs = 1500, maxChecks = 8 } = opts;
  onPhase?.("uploading");
  const res = await api.post<MediaTicket>(
    "studio/question-media/uploads",
    { filename: file.name, content_type: file.type, size_bytes: file.size, ...(organizationId ? { organization_id: organizationId } : {}) },
    { idempotencyKey: true },
  );
  if (res.kind !== "ok") throw new Error("The upload needs approval before it can continue.");
  const ticket = res.data;
  await postToProvider(ticket.upload, file);
  onPhase?.("scanning");
  let status: MediaStatus | null = null;
  for (let i = 0; i < maxChecks; i++) {
    const done = await api.post<MediaStatus>(`studio/question-media/${encodeURIComponent(ticket.media_id)}/complete`, {});
    if (done.kind === "ok") status = done.data;
    if (!status || status.status === "failed" || status.scan_status !== "pending") break;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  const phase: UploadPhase = status && status.status !== "failed" && status.scan_status === "clean" ? "ready" : status?.scan_status === "pending" ? "scanning" : "failed";
  onPhase?.(phase);
  return { media_id: ticket.media_id, url: status?.url ?? null, phase };
}
