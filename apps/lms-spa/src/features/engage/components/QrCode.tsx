"use client";

import { useMemo } from "react";
import QRCode from "qrcode";
import { cn } from "@/lib/ui/cn";

/** Largest symbol drawn (version 10: 213 bytes at level M); longer links show a message instead. */
const MAX_VERSION = 10;
/** Quiet zone in modules on each side. */
const QUIET = 4;

/** Byte-mode (UTF-8) QR at error correction level M as one SVG path, one unit per module. */
function qrSvg(value: string): { size: number; d: string } | null {
  const qr = QRCode.create([{ data: new TextEncoder().encode(value), mode: "byte" }], { errorCorrectionLevel: "M" });
  if (qr.version > MAX_VERSION) return null;
  const n = qr.modules.size;
  const parts: string[] = [];
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      if (qr.modules.get(y, x)) parts.push(`M${x + QUIET} ${y + QUIET}h1v1h-1z`);
    }
  }
  return { size: n + 2 * QUIET, d: parts.join("") };
}

/** QR code for a join link, drawn as one SVG path (dark modules on a white quiet zone). */
export function QrCode({ value, className, label }: { value: string; className?: string; label?: string }) {
  const qr = useMemo(() => {
    try {
      return qrSvg(value);
    } catch {
      return null;
    }
  }, [value]);
  if (!qr) return <p className="text-sm text-fg-muted">This link is too long for a QR code.</p>;
  return (
    <svg
      role="img"
      aria-label={label ?? `QR code for ${value}`}
      viewBox={`0 0 ${qr.size} ${qr.size}`}
      shapeRendering="crispEdges"
      className={cn("h-auto w-full rounded-md bg-white", className)}
    >
      <rect width={qr.size} height={qr.size} fill="#ffffff" />
      <path d={qr.d} fill="#000000" />
    </svg>
  );
}
