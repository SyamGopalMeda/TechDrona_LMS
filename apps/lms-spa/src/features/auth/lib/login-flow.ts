import { CHANGE_PASSWORD_PATH } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { clearPendingLogin, writePendingLogin } from "./pending-login";
import type { CapSession, LoginResponse } from "./types";
import { safeNextPath } from "./validation";

/** Module launcher (app/modules/page.tsx). */
export const MODULES_HUB = "/modules";

/**
 * Where staff land after a sign-in without a deep link: /continue resumes the page this browser
 * last had open and falls back to the module hub (app/continue/page.tsx).
 */
export const STAFF_LANDING = "/continue";

/**
 * Shared routing for the AUTH-06 / AUTH-11 / AUTH-13 / AUTH-14 outcomes (api-specification
 * AUTH-06 outcome table). Returns where the browser should go next.
 */
export function routeForLoginResult(res: LoginResponse, next?: string): string {
  switch (res.result) {
    case "mfa_required":
      writePendingLogin({ next, mfaMethods: res.methods });
      return "/login/mfa";
    case "device_verification_required":
      writePendingLogin({ next, channels: res.channels, alternatives: res.alternatives });
      return "/login/verify-device";
    case "authenticated": {
      clearPendingLogin();
      const r = res.restriction;
      if (r && r.level >= 4) return restrictedHref(r.case_ref ?? undefined, r.level, r.until ?? undefined);
      if (r && r.level >= 3) return safeNextPath(res.redirect, "/app/account-status");
      // The admin ticked "Must change password on first login": choose one first, then carry on.
      if (res.must_change_password) {
        const after = next ? safeNextPath(next, STAFF_LANDING) : STAFF_LANDING;
        return `${CHANGE_PASSWORD_PATH}?next=${encodeURIComponent(after)}`;
      }
      // Central login: staff resume their last page, else the module hub (LMS / Colleges Management /
      // Company Website Admin), which forwards straight to the LMS portal when it is their only module.
      if (!next && safeNextPath(res.redirect, "/app") !== "/app") return STAFF_LANDING;
      return safeNextPath(next ?? res.redirect, safeNextPath(res.redirect, "/app"));
    }
    default:
      return "/app";
  }
}

export function restrictedHref(caseRef?: string, level?: number, until?: string): string {
  const qs = new URLSearchParams();
  if (caseRef) qs.set("case_ref", caseRef);
  if (level !== undefined) qs.set("level", String(level));
  if (until) qs.set("until", until);
  const s = qs.toString();
  return `/account/restricted${s ? `?${s}` : ""}`;
}

function isCapSession(v: unknown): v is CapSession {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return typeof o.session_id === "string" && typeof o.device_label === "string";
}

/** `409 session_cap_reached` → remember the list and go to the chooser. */
export function routeForSessionCap(err: ApiError, next?: string): string {
  const raw = err.problem?.sessions;
  const sessions = Array.isArray(raw) ? raw.filter(isCapSession) : [];
  const max = typeof err.problem?.max_concurrent === "number" ? err.problem.max_concurrent : undefined;
  writePendingLogin({ next, capSessions: sessions, maxConcurrent: max });
  return "/login/session-choice";
}

/** Pre-select the oldest session without an active attempt (DS §9.4). */
export function defaultCapChoice(sessions: CapSession[]): string | null {
  const eligible = sessions
    .filter((s) => !s.has_active_attempt)
    .sort((a, b) => (Date.parse(a.last_active_at ?? "") || 0) - (Date.parse(b.last_active_at ?? "") || 0));
  return eligible[0]?.session_id ?? null;
}
