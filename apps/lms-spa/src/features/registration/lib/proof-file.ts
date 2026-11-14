/**
 * A payment screenshot / receipt checked and prepared in the browser before upload (port of the
 * website's prepfile.js): real type from the first bytes, size limits, images re-drawn as JPEG
 * (strips EXIF/location and shrinks them for phone uploads), and the SHA-256 of the ORIGINAL file
 * so the same screenshot uploaded twice is still caught. The api re-checks everything (files.py).
 */
import type { ProofPayload } from "./registration";

export const PROOF_ACCEPT = "image/jpeg,image/png,image/webp,application/pdf";
/** What a phone may pick (images are shrunk before upload). */
export const MAX_INPUT_BYTES = 10 * 1024 * 1024;
/** What is sent (api files.MAX_BYTES is 2 MiB). */
export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;
const PROOF_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "application/pdf"]);

export class ProofFileError extends Error {}

export interface PreparedProof extends ProofPayload {
  size: number;
  type: string;
  /** Object URL of the image to preview ("" for a PDF). Revoke when done. */
  preview: string;
}

export function sniff(b: Uint8Array): string {
  const at = (i: number, ...xs: number[]) => xs.every((x, k) => b[i + k] === x);
  if (at(0, 0xff, 0xd8, 0xff)) return "image/jpeg";
  if (at(0, 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) return "image/png";
  if (at(0, 0x52, 0x49, 0x46, 0x46) && at(8, 0x57, 0x45, 0x42, 0x50)) return "image/webp";
  if (at(0, 0x25, 0x50, 0x44, 0x46, 0x2d)) return "application/pdf";
  if (at(4, 0x66, 0x74, 0x79, 0x70)) return "image/heic";
  return "";
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(d), (x) => x.toString(16).padStart(2, "0")).join("");
}

export function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

async function readBytes(file: Blob): Promise<Uint8Array> {
  if (typeof file.arrayBuffer === "function") return new Uint8Array(await file.arrayBuffer());
  return new Uint8Array(
    await new Promise<ArrayBuffer>((ok, fail) => {
      const r = new FileReader();
      r.onload = () => ok(r.result as ArrayBuffer);
      r.onerror = () => fail(r.error);
      r.readAsArrayBuffer(file);
    }),
  );
}

/** Re-draw as JPEG (max 1600 px), stepping down until it fits; null when the browser can't. */
async function reencode(file: Blob, maxBytes: number): Promise<Uint8Array | null> {
  if (typeof createImageBitmap !== "function" || typeof document === "undefined") return null;
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" }).catch(() => null);
  if (!bmp) throw new ProofFileError("We couldn't read that image. Upload a JPG or PNG screenshot.");
  try {
    for (const [side, q] of [
      [1600, 0.82],
      [1400, 0.75],
      [1200, 0.7],
      [1000, 0.65],
    ] as const) {
      const k = Math.min(1, side / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas");
      c.width = Math.max(1, Math.round(bmp.width * k));
      c.height = Math.max(1, Math.round(bmp.height * k));
      const g = c.getContext("2d");
      if (!g) return null;
      g.fillStyle = "#fff";
      g.fillRect(0, 0, c.width, c.height);
      g.drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise<Blob | null>((ok) => c.toBlob(ok, "image/jpeg", q));
      if (blob && blob.size <= maxBytes) return new Uint8Array(await blob.arrayBuffer());
    }
  } finally {
    bmp.close?.();
  }
  throw new ProofFileError("That image is too large even after compressing. Upload a normal screenshot.");
}

export async function prepareProof(file: File): Promise<PreparedProof> {
  if (file.size > MAX_INPUT_BYTES) throw new ProofFileError(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is 10 MB.`);
  if (file.size < 100) throw new ProofFileError("That file is empty or damaged.");
  const original = await readBytes(file);
  const real = sniff(original);
  if (real === "image/heic") throw new ProofFileError("HEIC photos aren't supported. Take a normal screenshot (PNG/JPG) of the payment instead.");
  if (!PROOF_TYPES.has(real)) throw new ProofFileError("Upload a JPG, PNG or WebP screenshot, or a PDF receipt.");
  const hash = await sha256Hex(original);
  let bytes = original;
  let type = real;
  if (real.startsWith("image/")) {
    const shrunk = await reencode(file, 1.5 * 1024 * 1024);
    if (shrunk) {
      bytes = shrunk;
      type = "image/jpeg";
    }
  }
  if (bytes.length > MAX_UPLOAD_BYTES) throw new ProofFileError("That file is too large. The limit is 2 MB.");
  const base = (file.name || "payment").replace(/[^\w.\- ()]+/g, "_").slice(0, 100) || "payment";
  const filename = type === "image/jpeg" && real !== "image/jpeg" ? `${base.replace(/\.\w+$/, "")}.jpg` : base;
  const preview = type.startsWith("image/") && typeof URL.createObjectURL === "function" ? URL.createObjectURL(new Blob([bytes as BlobPart], { type })) : "";
  return { filename, data_b64: toBase64(bytes), original_sha256: hash, size: bytes.length, type, preview };
}
