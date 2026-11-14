/**
 * SEC-47 `GET /security/reports/exports/{id}` returns the watermarked CSV itself (text/csv),
 * not JSON or a signed URL, so it is read with `apiRequestRaw` (same CSRF and problem handling as
 * the JSON client) through the BFF (`/api/v1/...`, cookie session) and saves it as a file. A non-2xx answer is a
 * problem+json and is thrown as an ApiError (e.g. 409 `invalid_state_transition` with
 * `current_state` while the job is still awaiting approval, or after the 24 h window).
 */
import { apiRequestRaw } from "@/lib/api/client";

/** Indirection so tests can observe the save (jsdom does not download). */
export const csvSink = {
  save(filename: string, csv: string): void {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  },
};

function filenameFrom(disposition: string | null, fallback: string): string {
  const m = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return m?.[1] ?? fallback;
}

/** Fetches a CSV from the api and saves it; throws ApiError on a problem response. */
export async function downloadCsv(path: string, fallbackName: string): Promise<string> {
  const res = await apiRequestRaw(path, { headers: { accept: "text/csv, application/problem+json" } });
  const name = filenameFrom(res.headers.get("content-disposition"), fallbackName);
  csvSink.save(name, await res.text());
  return name;
}
