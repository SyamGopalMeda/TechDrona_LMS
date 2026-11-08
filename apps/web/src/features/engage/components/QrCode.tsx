"use client";

import { useMemo } from "react";
import { cn } from "@/lib/ui/cn";
import { encodeQr, qrPath } from "../lib/qr";

/** QR code for a join link, drawn as one SVG path (dark modules on a white quiet zone). */
export function QrCode({ value, className, label }: { value: string; className?: string; label?: string }) {
  const qr = useMemo(() => {
    try {
      const m = encodeQr(value, { ecc: "M" });
      return { size: m.size + 8, d: qrPath(m) };
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
