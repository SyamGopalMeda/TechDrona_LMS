"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { api, buildUrl, readCsrfToken } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { getTabId } from "@/lib/analytics/use-activity-tracker";

/** MED-04 response. verified: app/modules/media/service.py issue_playback. */
export interface PlaybackToken {
  playback_session_id: string;
  provider: "vdocipher" | string;
  otp: string;
  playback_info: string;
  otp_expires_at?: string;
  heartbeat_interval_seconds?: number;
  stale_after_seconds?: number;
  resume_position_seconds?: number | null;
  /** Applied by VdoCipher from the OTP annotation; informational only. */
  watermark?: { text: string; moving: boolean };
}

export interface PlaybackConflict {
  detail: string;
  otherDeviceLabel: string | null;
  otherPlaybackSessionId: string | null;
  takeoverAllowed: boolean;
}

export type PlaybackState =
  | { phase: "requesting" }
  | { phase: "ready"; token: PlaybackToken }
  | { phase: "conflict"; conflict: PlaybackConflict; dismissed: boolean }
  | { phase: "revoked"; endReason: string | null }
  | { phase: "error"; error: unknown };

export interface PlayerSignals {
  position: () => number;
  playing: () => boolean;
  buffering: () => boolean;
}

const DEFAULT_HEARTBEAT_S = 30;

/**
 * MED-06 stop that survives the page going away (tab close, reload, navigation away): a
 * `keepalive` fetch with the CSRF double-submit header (sendBeacon cannot set headers).
 * Fire-and-forget; the server's stale timeout remains the fallback.
 */
export function stopPlaybackKeepalive(sessionId: string, fetchImpl: typeof fetch | undefined = globalThis.fetch): void {
  if (!fetchImpl) return;
  const token = readCsrfToken();
  try {
    void fetchImpl(buildUrl(`media/playback-sessions/${encodeURIComponent(sessionId)}/stop`), {
      method: "POST",
      keepalive: true,
      credentials: "same-origin",
      headers: { "content-type": "application/json", accept: "application/json", ...(token ? { "x-csrf-token": token } : {}) },
      body: "{}",
    }).catch(() => undefined);
  } catch {
    /* page is unloading */
  }
}

/**
 * Playback session lifecycle for one lesson asset:
 *  - MED-04 token (stream cap); 409 playback_conflict → "Play here instead?" (PLY-005),
 *    retried with take_over_playback_session_id when the learner confirms;
 *  - MED-05 heartbeat every `heartbeat_interval_seconds`; 410 playback_revoked → "Playback
 *    moved to another device" with "Play here instead";
 *  - MED-06 stop on unmount, and on `pagehide` via a keepalive request (FE-19) so closing the
 *    tab frees the stream slot at once; a bfcache restore (`pageshow` persisted) asks again.
 */
export function usePlaybackSession(lessonAssetId: string | null, signals: RefObject<PlayerSignals | null>) {
  const [state, setState] = useState<PlaybackState>({ phase: "requesting" });
  const sessionRef = useRef<string | null>(null);
  const seq = useRef(0);

  const stop = useCallback(() => {
    const id = sessionRef.current;
    sessionRef.current = null;
    if (id) void api.post(`media/playback-sessions/${encodeURIComponent(id)}/stop`, {}).catch(() => undefined);
  }, []);

  const request = useCallback(
    async (takeOver: string | null = null) => {
      if (!lessonAssetId) return;
      const id = ++seq.current;
      setState({ phase: "requesting" });
      try {
        const res = await api.post<PlaybackToken>(
          "media/playback-tokens",
          { lesson_asset_id: lessonAssetId, tab_id: getTabId(), take_over_playback_session_id: takeOver },
          { idempotencyKey: true },
        );
        if (id !== seq.current) return;
        if (res.kind !== "ok") throw new Error("Unexpected response");
        sessionRef.current = res.data.playback_session_id;
        setState({ phase: "ready", token: res.data });
      } catch (err) {
        if (id !== seq.current) return;
        if (isApiError(err) && err.code === "playback_conflict") {
          const p = err.problem;
          setState({
            phase: "conflict",
            dismissed: false,
            conflict: {
              detail: err.detail,
              otherDeviceLabel: typeof p?.other_device_label === "string" ? p.other_device_label : null,
              otherPlaybackSessionId: typeof p?.other_playback_session_id === "string" ? p.other_playback_session_id : null,
              takeoverAllowed: p?.takeover_allowed !== false,
            },
          });
          return;
        }
        setState({ phase: "error", error: err });
      }
    },
    [lessonAssetId],
  );

  useEffect(() => {
    void request(null);
    return () => {
      seq.current += 1;
      stop();
    };
  }, [request, stop]);

  // Tab close / reload / cross-document navigation: release the slot now (unmount does not run).
  useEffect(() => {
    if (!lessonAssetId) return;
    const onPageHide = () => {
      const id = sessionRef.current;
      sessionRef.current = null;
      if (id) stopPlaybackKeepalive(id);
    };
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted && sessionRef.current === null) void request(null);
    };
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [lessonAssetId, request]);

  const token = state.phase === "ready" ? state.token : null;
  useEffect(() => {
    if (!token) return;
    const sessionId = token.playback_session_id;
    const every = Math.max(10, token.heartbeat_interval_seconds ?? DEFAULT_HEARTBEAT_S) * 1000;
    const timer = setInterval(() => {
      const s = signals.current;
      void api
        .post(`media/playback-sessions/${encodeURIComponent(sessionId)}/heartbeat`, {
          position_seconds: Math.max(0, Math.floor(s?.position() ?? 0)),
          buffering: s?.buffering() ?? false,
          playing: s?.playing() ?? false,
        })
        .catch((err: unknown) => {
          if (isApiError(err) && (err.status === 410 || err.code === "playback_revoked")) {
            if (sessionRef.current === sessionId) sessionRef.current = null;
            const reason = err.problem?.end_reason;
            setState({ phase: "revoked", endReason: typeof reason === "string" ? reason : null });
          }
          // Other failures are transient: the next heartbeat retries; the server marks the
          // session stale after `stale_after_seconds` without one.
        });
    }, every);
    return () => clearInterval(timer);
  }, [token, signals]);

  const takeOver = useCallback(() => {
    if (state.phase !== "conflict") return;
    void request(state.conflict.otherPlaybackSessionId);
  }, [state, request]);

  const dismissConflict = useCallback(() => {
    setState((s) => (s.phase === "conflict" ? { ...s, dismissed: true } : s));
  }, []);

  return { state, request, takeOver, dismissConflict };
}
