"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Dialog } from "@/components/ui";
import { ContentErrorState } from "@/features/learning/components/States";
import type { VideoEvents } from "@/lib/analytics/video";
import { drmSupported, embedUrl, isDemoPlaybackToken, loadVdoApi, type VdoPlayerInstance, type VdoVideo } from "../lib/vdocipher";
import { usePlaybackSession, type PlayerSignals } from "../lib/use-playback-session";

export interface VideoPlayerProps {
  lessonAssetId: string;
  lessonTitle: string;
  /** Reported to the analytics tracker (media playing counts as ACTIVE when visible). */
  onPlayingChange?: (playing: boolean) => void;
  /** `video.*` analytics sink (tracker.video); played ranges ride on heartbeats (FE-08). */
  video?: VideoEvents;
}

/**
 * Maps the VdoCipher player API (HTMLMediaElement-style events) onto `video.*` analytics events
 * (analytics-event-schema §2.2). Returns the listener cleanup.
 */
export function bindVideoAnalytics(v: VdoVideo, events: VideoEvents, onPlaying?: (playing: boolean) => void): () => void {
  let playing = !v.paused;
  let waiting = false;
  let seeking = false;
  let lastPos = v.currentTime || 0;
  let rate = v.playbackRate || 1;
  const t = () => v.currentTime || 0;
  const startPlaying = () => {
    if (playing) return;
    playing = true;
    events.play(t(), rate);
  };
  const handlers: Record<string, () => void> = {
    play: () => {
      startPlaying();
      onPlaying?.(true);
    },
    playing: () => {
      if (waiting) {
        waiting = false;
        events.bufferingEnd(t());
      }
      startPlaying();
      onPlaying?.(true);
    },
    pause: () => {
      if (playing) {
        playing = false;
        events.pause(t());
      }
      onPlaying?.(false);
    },
    ended: () => {
      playing = false;
      events.ended(t(), v.duration && Number.isFinite(v.duration) ? v.duration : t());
      onPlaying?.(false);
    },
    waiting: () => {
      if (waiting) return;
      waiting = true;
      events.bufferingStart(t());
    },
    seeking: () => {
      seeking = true;
    },
    seeked: () => {
      seeking = false;
      const to = t();
      if (Math.abs(to - lastPos) >= 1) events.seek(lastPos, to);
      lastPos = to;
    },
    timeupdate: () => {
      if (seeking) return;
      lastPos = t();
      events.timeUpdate(lastPos);
    },
    ratechange: () => {
      const next = v.playbackRate || 1;
      if (next !== rate) events.rateChange(rate, next, t());
      rate = next;
    },
    error: () => {
      events.error(v.error?.code ?? "player_error", t());
      playing = false;
      onPlaying?.(false);
    },
  };
  for (const [type, cb] of Object.entries(handlers)) v.addEventListener(type, cb);
  return () => {
    for (const [type, cb] of Object.entries(handlers)) v.removeEventListener(type, cb);
  };
}

function Frame({ children, busy }: { children: ReactNode; busy?: boolean }) {
  return (
    <div aria-busy={busy || undefined} className="relative flex aspect-video w-full items-center justify-center overflow-hidden rounded-xl bg-surface-sunken p-6 text-center">
      {children}
    </div>
  );
}

/**
 * PLY-001 video frame: VdoCipher iframe from a MED-04 playback token, heartbeats (MED-05),
 * and the PLY-005 playback-conflict dialog (copy: design-system §9.5).
 */
export function VideoPlayer({ lessonAssetId, lessonTitle, onPlayingChange, video }: VideoPlayerProps) {
  const [supported] = useState(drmSupported);
  const signals = useRef<PlayerSignals | null>(null);
  const { state, request, takeOver, dismissConflict } = usePlaybackSession(supported ? lessonAssetId : null, signals);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const playerRef = useRef<VdoPlayerInstance | null>(null);
  const bufferingRef = useRef(false);
  const onPlayingRef = useRef(onPlayingChange);
  onPlayingRef.current = onPlayingChange;
  const videoRef = useRef(video);
  videoRef.current = video;

  const token = state.phase === "ready" ? state.token : null;

  useEffect(() => {
    signals.current = {
      position: () => playerRef.current?.video.currentTime ?? 0,
      playing: () => Boolean(playerRef.current && !playerRef.current.video.paused),
      buffering: () => bufferingRef.current,
    };
  }, []);

  // Wire the player API (best effort) once the iframe exists.
  useEffect(() => {
    if (!token || !iframeRef.current) return;
    let cancelled = false;
    let cleanup = () => {};
    const iframe = iframeRef.current;
    void loadVdoApi().then((vdo) => {
      if (cancelled || !vdo) return;
      try {
        const player = vdo.getInstance(iframe);
        playerRef.current = player;
        const v = player.video;
        const onPlay = () => {
          bufferingRef.current = false;
        };
        const onWaiting = () => {
          bufferingRef.current = true;
        };
        const onLoaded = () => {
          const resume = token.resume_position_seconds;
          if (resume && resume > 0 && v.currentTime < 1) v.currentTime = resume;
        };
        v.addEventListener("playing", onPlay);
        v.addEventListener("waiting", onWaiting);
        v.addEventListener("loadedmetadata", onLoaded);
        // Analytics: forwards through the ref so a new tracker instance (SPA nav) is picked up.
        const sink: VideoEvents = {
          play: (p, r) => videoRef.current?.play(p, r),
          pause: (p) => videoRef.current?.pause(p),
          seek: (f, to) => videoRef.current?.seek(f, to),
          rateChange: (f, to, p) => videoRef.current?.rateChange(f, to, p),
          ended: (p, d) => videoRef.current?.ended(p, d),
          bufferingStart: (p) => videoRef.current?.bufferingStart(p),
          bufferingEnd: (p, b) => videoRef.current?.bufferingEnd(p, b),
          error: (c, p) => videoRef.current?.error(c, p),
          timeUpdate: (p) => videoRef.current?.timeUpdate(p),
        };
        const unbind = bindVideoAnalytics(v, sink, (p) => onPlayingRef.current?.(p));
        cleanup = () => {
          unbind();
          v.removeEventListener("playing", onPlay);
          v.removeEventListener("waiting", onWaiting);
          v.removeEventListener("loadedmetadata", onLoaded);
        };
      } catch {
        playerRef.current = null;
      }
    });
    return () => {
      cancelled = true;
      cleanup();
      playerRef.current = null;
      onPlayingRef.current?.(false);
    };
  }, [token]);

  if (!supported) {
    return (
      <Frame>
        <div>
          <p className="font-semibold text-fg">This browser can’t play protected videos</p>
          <p className="mt-1 text-sm text-fg-secondary">Use a recent version of Chrome, Edge, Firefox or Safari (not in private mode), then reload this page.</p>
        </div>
      </Frame>
    );
  }

  const conflict = state.phase === "conflict" ? state.conflict : null;

  return (
    <div>
      {state.phase === "requesting" ? (
        <Frame busy>
          <p role="status" className="text-sm text-fg-muted">
            Loading video…
          </p>
        </Frame>
      ) : state.phase === "ready" && isDemoPlaybackToken(state.token.otp, state.token.playback_info) ? (
        <Frame>
          <div role="status">
            <p className="font-semibold text-fg">Video hosting: not integrated yet</p>
            <p className="mt-1 text-sm text-fg-secondary">
              This is a demo lesson. The secure video service (VdoCipher) is not connected, so there is no real video to play here yet.
            </p>
          </div>
        </Frame>
      ) : state.phase === "ready" ? (
        <div className="aspect-video w-full overflow-hidden rounded-xl bg-surface-sunken">
          <iframe
            ref={iframeRef}
            key={state.token.playback_session_id}
            src={embedUrl(state.token.otp, state.token.playback_info)}
            title={`Video: ${lessonTitle}`}
            className="h-full w-full border-0"
            allow="encrypted-media; fullscreen; autoplay; picture-in-picture"
            allowFullScreen
            referrerPolicy="strict-origin"
          />
        </div>
      ) : state.phase === "revoked" ? (
        <Frame>
          <div role="status">
            <p className="font-semibold text-fg">Playback moved to another device</p>
            <p className="mt-1 text-sm text-fg-secondary">
              {state.endReason === "stale" ? "This video stopped because we lost contact with this player." : "This video is now playing on another device."}
            </p>
            <Button className="mt-3" onClick={() => void request(null)}>
              Play here instead
            </Button>
          </div>
        </Frame>
      ) : state.phase === "conflict" ? (
        <Frame>
          <div role="status">
            <p className="font-semibold text-fg">Video is playing on another device</p>
            <p className="mt-1 text-sm text-fg-secondary">Your plan allows 1 video at a time.</p>
            {conflict?.takeoverAllowed ? (
              <Button className="mt-3" onClick={takeOver}>
                Play here instead
              </Button>
            ) : null}
          </div>
        </Frame>
      ) : (
        <ContentErrorState error={state.error} onRetry={() => void request(null)} />
      )}

      <Dialog
        open={state.phase === "conflict" && !state.dismissed}
        onClose={dismissConflict}
        title="Video is playing on another device"
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={dismissConflict}>
              Not now
            </Button>
            {conflict?.takeoverAllowed ? <Button onClick={takeOver}>Stop it and play here</Button> : null}
          </div>
        }
      >
        <p className="text-sm text-fg-secondary">
          Your plan allows 1 video at a time.{" "}
          {conflict?.otherDeviceLabel ? (
            <>
              &ldquo;{conflict.otherDeviceLabel}&rdquo; is playing a video.
            </>
          ) : (
            conflict?.detail
          )}
        </p>
        <p className="mt-3 text-xs text-fg-muted">
          <em>Why only one?</em> One account is for one person (
          <Link href="/legal/device-policy" className="text-fg-link">
            Device policy
          </Link>
          ).
        </p>
      </Dialog>
    </div>
  );
}
