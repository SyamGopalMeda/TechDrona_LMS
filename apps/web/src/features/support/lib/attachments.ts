import { api } from "@/lib/api/client";
import { postToProvider, type FileTicket } from "@/features/studio/lib/media";
import { ticketAttachmentPath } from "./types";

/** SUP-01/04 `attachments[]` item: a file already uploaded with MED-02 `purpose=support_attachment`. */
export interface UploadedAttachment {
  s3_key: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

/**
 * Upload each file through MED-02 (`support_attachment`): the api returns a presigned POST to the
 * uploads bucket, the browser sends the file straight there, and the ticket then references the
 * returned `s3_key` (BE-17).
 */
export async function uploadSupportAttachments(files: File[], fetchImpl: typeof fetch = fetch): Promise<UploadedAttachment[]> {
  const out: UploadedAttachment[] = [];
  for (const f of files) {
    const meta = { filename: f.name.slice(0, 200), content_type: f.type || "application/octet-stream", size_bytes: f.size };
    const res = await api.post<FileTicket>("media/uploads/file", { purpose: "support_attachment", ...meta }, { idempotencyKey: true });
    if (res.kind !== "ok") throw new Error(`Upload of ${f.name} could not start.`);
    await postToProvider(res.data.upload, f, fetchImpl);
    out.push({ s3_key: res.data.s3_key, ...meta });
  }
  return out;
}

/** `GET support/tickets/{id}/attachments/{ticket|message_id}/{index}` → short-lived download URL. */
export async function attachmentDownloadUrl(ticketId: string, ref: string, index: number): Promise<string> {
  const res = await api.get<{ url: string; expires_at: string; filename: string | null }>(ticketAttachmentPath(ticketId, ref, index));
  return res.url;
}
