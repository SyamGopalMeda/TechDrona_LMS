import type { CapSession, DeviceChannel } from "./types";

/**
 * Non-secret state carried between the login steps (/login → /login/mfa | verify-device |
 * session-choice) in sessionStorage. Never stores passwords, OTPs, codes or tokens: only the
 * methods/channels/session lists the API returned and the post-login target.
 */
export interface PendingLogin {
  next?: string;
  mfaMethods?: string[];
  channels?: DeviceChannel[];
  alternatives?: string[];
  capSessions?: CapSession[];
  maxConcurrent?: number;
  savedAt: number;
}

const KEY = "td.pending_login";
const MAX_AGE_MS = 10 * 60 * 1000;

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

export function readPendingLogin(): PendingLogin | null {
  const s = storage();
  if (!s) return null;
  try {
    const raw = s.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as PendingLogin;
    if (!v || typeof v.savedAt !== "number" || Date.now() - v.savedAt > MAX_AGE_MS) {
      s.removeItem(KEY);
      return null;
    }
    return v;
  } catch {
    return null;
  }
}

export function writePendingLogin(patch: Omit<Partial<PendingLogin>, "savedAt">): void {
  const s = storage();
  if (!s) return;
  const prev = readPendingLogin() ?? { savedAt: Date.now() };
  try {
    s.setItem(KEY, JSON.stringify({ ...prev, ...patch, savedAt: Date.now() }));
  } catch {
    /* storage full / disabled: the steps fall back to their "start again" states */
  }
}

export function clearPendingLogin(): void {
  try {
    storage()?.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
