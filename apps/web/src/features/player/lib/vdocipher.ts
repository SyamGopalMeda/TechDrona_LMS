/**
 * VdoCipher embed (ADR: DRM video via VdoCipher; CSP frame-src allows only
 * https://player.vdocipher.com). The watermark is applied by VdoCipher from the OTP
 * annotation issued server-side (MED-04) — never drawn by this app.
 *
 * The optional player API script gives us play/pause/position for heartbeats and the
 * analytics `mediaPlaying` signal. It is loaded by our nonce-trusted bundle, so CSP
 * 'strict-dynamic' admits it. If it fails to load, playback still works; heartbeats then
 * report position 0 / playing=false (neutral for the idle timer).
 */

export const VDO_ORIGIN = "https://player.vdocipher.com";
const API_SRC = `${VDO_ORIGIN}/v2/api.js`;

export interface VdoVideo {
  currentTime: number;
  paused: boolean;
  /** HTMLMediaElement-like extras (may be missing when the API script is an older build). */
  duration?: number;
  playbackRate?: number;
  error?: { code?: number | string } | null;
  addEventListener(type: string, cb: () => void): void;
  removeEventListener(type: string, cb: () => void): void;
}

export interface VdoPlayerInstance {
  video: VdoVideo;
}

interface VdoGlobal {
  getInstance(iframe: HTMLIFrameElement): VdoPlayerInstance;
}

declare global {
  interface Window {
    VdoPlayer?: VdoGlobal;
  }
}

export function embedUrl(otp: string, playbackInfo: string): string {
  const qs = new URLSearchParams({ otp, playbackInfo });
  return `${VDO_ORIGIN}/v2/?${qs.toString()}`;
}

let loading: Promise<VdoGlobal | null> | null = null;

export function loadVdoApi(): Promise<VdoGlobal | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.VdoPlayer) return Promise.resolve(window.VdoPlayer);
  if (loading) return loading;
  loading = new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = API_SRC;
    s.async = true;
    s.onload = () => resolve(window.VdoPlayer ?? null);
    s.onerror = () => {
      loading = null;
      resolve(null);
    };
    document.head.appendChild(s);
  });
  return loading;
}

/** Encrypted Media Extensions are required for DRM playback. */
export function drmSupported(): boolean {
  if (typeof navigator === "undefined") return true;
  return typeof navigator.requestMediaKeySystemAccess === "function";
}
