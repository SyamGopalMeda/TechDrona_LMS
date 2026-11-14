import { api } from "@/lib/api/client";
import type { UploadTicket } from "./types";

/** MED-02 per-file cap for assignment submissions (verified: app/modules/media/router.py FILE_LIMITS). */
export const MAX_ASSIGNMENT_FILE_MB = 20;

/** MED-02 presigned upload of one assignment file; returns its s3 key. */
export async function uploadAssignmentFile(f: File): Promise<string> {
  const ticket = await api.post<UploadTicket>(
    "media/uploads/file",
    { purpose: "assignment_submission", filename: f.name, content_type: f.type || "application/octet-stream", size_bytes: f.size },
    { idempotencyKey: true },
  );
  if (ticket.kind !== "ok") throw new Error("Upload could not start");
  const form = new FormData();
  for (const [k, v] of Object.entries(ticket.data.upload.fields)) form.append(k, v);
  form.append("file", f);
  const put = await fetch(ticket.data.upload.url, { method: "POST", body: form });
  if (!put.ok) throw new Error(`Upload of ${f.name} failed. Try again.`);
  return ticket.data.s3_key;
}
