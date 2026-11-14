/**
 * Signed-URL downloads (invoice / credit-note PDFs, GST register exports). The api returns a
 * short-lived signed URL (≈5 min), so it is fetched at click time and never cached.
 */
import { api } from "@/lib/api/client";

/** GET me/invoices/{id}/pdf, finance/invoices/{id}/pdf, finance/gst-exports/{id}/download. */
export interface SignedDownloadDto {
  url: string;
  expires_at: string;
  filename: string;
}

/** Indirection so tests can observe the navigation (jsdom does not navigate). */
export const downloadSink = {
  open(dl: SignedDownloadDto): void {
    const a = document.createElement("a");
    a.href = dl.url;
    a.download = dl.filename;
    a.rel = "noopener";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
  },
};

/** Fetches a fresh signed URL for `path` and starts the download. Throws ApiError on failure. */
export async function startSignedDownload(path: string): Promise<SignedDownloadDto> {
  const dl = await api.get<SignedDownloadDto>(path);
  downloadSink.open(dl);
  return dl;
}
