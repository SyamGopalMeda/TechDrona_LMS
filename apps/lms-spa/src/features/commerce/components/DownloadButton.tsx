"use client";

import { useState } from "react";
import { Button, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { startSignedDownload } from "../lib/download";

export interface DownloadButtonProps {
  /** api path returning `{url, expires_at, filename}`; requested on every click (signed URLs expire). */
  path: string;
  label: string;
  /** Accessible name, e.g. "Download PDF for TD/2627/000123". */
  ariaLabel: string;
  variant?: "primary" | "secondary" | "ghost";
}

/** Fetches a short-lived signed URL at click time and downloads it; failures go to a toast. */
export function DownloadButton({ path, label, ariaLabel, variant = "ghost" }: DownloadButtonProps) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true);
    try {
      await startSignedDownload(path);
    } catch (err) {
      const e = err instanceof ApiError ? err : null;
      toast.show({ title: e?.title ?? "Download failed", description: e?.detail ?? "Please try again.", tone: "danger", requestId: e?.requestId ?? null });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant={variant} size="sm" loading={busy} onClick={() => void download()} aria-label={ariaLabel}>
      {label}
    </Button>
  );
}
