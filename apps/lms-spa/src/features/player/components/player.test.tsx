import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import type { VideoEvents } from "@/lib/analytics/video";
import type { VdoVideo } from "../lib/vdocipher";
import { bindVideoAnalytics, VideoPlayer } from "./VideoPlayer";

vi.mock("@/lib/analytics/use-activity-tracker", () => ({ getTabId: () => "tab-1", useActivityTracker: vi.fn() }));

let restore: (() => void) | undefined;
beforeEach(() => {
  Object.defineProperty(navigator, "requestMediaKeySystemAccess", { value: vi.fn(), configurable: true });
});
afterEach(() => {
  restore?.();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const token = {
  playback_session_id: "ps-1",
  provider: "vdocipher",
  otp: "otp-abc",
  playback_info: "info-xyz",
  heartbeat_interval_seconds: 30,
  stale_after_seconds: 90,
  resume_position_seconds: 0,
};

const conflict = problem(409, "playback_conflict", "Playing on another device", {
  detail: "This account is already playing a video on Chrome on Android. Play here instead?",
  other_device_label: "Chrome on Android",
  other_playback_session_id: "ps-other",
  takeover_allowed: true,
});

describe("VideoPlayer (PLY-001 / PLY-005)", () => {
  it("requests a playback token and embeds the VdoCipher player", async () => {
    const api = mockApi({ "POST media/playback-tokens": { status: 201, body: token } });
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    const frame = await screen.findByTitle("Video: Two pointers");
    expect(frame.getAttribute("src")).toBe("https://player.vdocipher.com/v2/?otp=otp-abc&playbackInfo=info-xyz");
    const call = api.calls.find((c) => c.path === "media/playback-tokens")!;
    expect(call.body).toEqual({ lesson_asset_id: "asset-1", tab_id: "tab-1", take_over_playback_session_id: null });
  });

  it("says 'not integrated yet' instead of embedding a demo (fake adapter) token", async () => {
    const fake = { ...token, otp: "FAKE-OTP-123", playback_info: btoa(JSON.stringify({ videoId: "demo", fake: true })) };
    const api = mockApi({ "POST media/playback-tokens": { status: 201, body: fake } });
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    expect(await screen.findByText("Video hosting: not integrated yet")).toBeInTheDocument();
    expect(screen.queryByTitle("Video: Two pointers")).not.toBeInTheDocument();
  });

  it("asks before taking over a stream playing elsewhere, then retries with the takeover id", async () => {
    let n = 0;
    const api = mockApi({ "POST media/playback-tokens": () => (++n === 1 ? conflict : { status: 201, body: token }) });
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    expect(await screen.findByText(/“Chrome on Android” is playing a video/)).toBeInTheDocument();
    expect(screen.getByText("Device policy")).toHaveAttribute("href", "/legal/device-policy");
    await userEvent.click(screen.getByRole("button", { name: "Stop it and play here" }));
    expect(await screen.findByTitle("Video: Two pointers")).toBeInTheDocument();
    const calls = api.calls.filter((c) => c.path === "media/playback-tokens");
    expect(calls).toHaveLength(2);
    expect((calls[1]!.body as { take_over_playback_session_id: string }).take_over_playback_session_id).toBe("ps-other");
  });

  it("keeps the frame paused with 'Play here instead' when the learner chooses Not now", async () => {
    const api = mockApi({ "POST media/playback-tokens": conflict });
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    await userEvent.click(await screen.findByRole("button", { name: "Not now" }));
    expect(screen.getByRole("button", { name: "Play here instead" })).toBeInTheDocument();
    expect(screen.queryByTitle("Video: Two pointers")).not.toBeInTheDocument();
  });

  it("sends heartbeats and shows 'Playback moved' when the session is revoked (410)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let beats = 0;
    const api = mockApi({
      "POST media/playback-tokens": { status: 201, body: token },
      "POST media/playback-sessions/ps-1/heartbeat": () => (++beats === 1 ? { body: { state: "active" } } : problem(410, "playback_revoked", "Playback moved", { end_reason: "taken_over" })),
    });
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    await screen.findByTitle("Video: Two pointers");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    await waitFor(() => expect(beats).toBe(1));
    const hb = api.calls.find((c) => c.path.endsWith("/heartbeat"))!;
    expect(hb.body).toEqual({ position_seconds: 0, buffering: false, playing: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(await screen.findByText("Playback moved to another device")).toBeInTheDocument();
    expect(screen.queryByTitle("Video: Two pointers")).not.toBeInTheDocument();
  });

  it("shows the paywall when the lesson needs an entitlement", async () => {
    const api = mockApi({
      "POST media/playback-tokens": problem(403, "entitlement_required", "Get access to watch", {
        detail: "This lesson is part of the TCS NQT path.",
        purchase_options: [{ sku: "PP-TCS", price_id: "p9", total_paise: 149900, name: "TCS NQT path" }],
      }),
    });
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    expect(await screen.findByText("This lesson is part of the TCS NQT path.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TCS NQT path · ₹1,499" })).toHaveAttribute("href", "/app/checkout/new?price_id=p9");
  });

  it("explains when the browser cannot play protected video", () => {
    Object.defineProperty(navigator, "requestMediaKeySystemAccess", { value: undefined, configurable: true });
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    expect(screen.getByText(/can.t play protected videos/)).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });

  it("stops the playback session on unmount", async () => {
    const api = mockApi({ "POST media/playback-tokens": { status: 201, body: token }, "POST media/playback-sessions/ps-1/stop": { status: 204 } });
    restore = api.restore;
    const view = renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    await screen.findByTitle("Video: Two pointers");
    view.unmount();
    await waitFor(() => expect(api.calls.some((c) => c.path === "media/playback-sessions/ps-1/stop")).toBe(true));
  });

  it("FE-19: releases the stream slot on pagehide with a keepalive stop (tab close)", async () => {
    const api = mockApi({ "POST media/playback-tokens": { status: 201, body: token } });
    restore = api.restore;
    const beacon = vi.fn(async (_url: string, _init: RequestInit) => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", beacon);
    renderWithProviders(<VideoPlayer lessonAssetId="asset-1" lessonTitle="Two pointers" />);
    await screen.findByTitle("Video: Two pointers");
    window.dispatchEvent(new Event("pagehide"));
    expect(beacon).toHaveBeenCalledTimes(1);
    const [url, init] = beacon.mock.calls[0]!;
    expect(url).toBe("/api/v1/media/playback-sessions/ps-1/stop");
    expect(init.keepalive).toBe(true);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["x-csrf-token"]).toBe("test-csrf-token");
  });
});

/** Minimal HTMLMediaElement-like stub for the VdoCipher player API. */
function fakeVideo(): VdoVideo & { fire: (t: string) => void } {
  const ls = new Map<string, Set<() => void>>();
  return {
    currentTime: 0,
    paused: true,
    duration: 600,
    playbackRate: 1,
    error: null,
    addEventListener: (t, cb) => void (ls.get(t) ?? ls.set(t, new Set()).get(t)!).add(cb),
    removeEventListener: (t, cb) => void ls.get(t)?.delete(cb),
    fire(t) {
      for (const cb of ls.get(t) ?? []) cb();
    },
  };
}

describe("FE-08: VdoCipher events → video.* analytics", () => {
  it("maps play/seek/rate/buffering/pause/ended/error and reports playing state", () => {
    const v = fakeVideo();
    const calls: [string, ...unknown[]][] = [];
    const rec =
      (name: string) =>
      (...args: unknown[]) =>
        void calls.push([name, ...args]);
    const events: VideoEvents = {
      play: rec("play"),
      pause: rec("pause"),
      seek: rec("seek"),
      rateChange: rec("rateChange"),
      ended: rec("ended"),
      bufferingStart: rec("bufferingStart"),
      bufferingEnd: rec("bufferingEnd"),
      error: rec("error"),
      timeUpdate: rec("timeUpdate"),
    };
    const playing = vi.fn();
    const unbind = bindVideoAnalytics(v, events, playing);
    v.fire("play");
    v.fire("playing"); // no duplicate play
    v.currentTime = 10;
    v.fire("timeupdate");
    v.fire("seeking");
    v.currentTime = 120;
    v.fire("seeked");
    v.playbackRate = 1.5;
    v.fire("ratechange");
    v.fire("waiting");
    v.fire("playing");
    v.currentTime = 130;
    v.fire("pause");
    v.currentTime = 600;
    v.fire("ended");
    v.error = { code: 4 };
    v.fire("error");
    expect(calls).toEqual([
      ["play", 0, 1],
      ["timeUpdate", 10],
      ["seek", 10, 120],
      ["rateChange", 1, 1.5, 120],
      ["bufferingStart", 120],
      ["bufferingEnd", 120],
      ["pause", 130],
      ["ended", 600, 600],
      ["error", 4, 600],
    ]);
    expect(playing.mock.calls.map((c) => c[0])).toEqual([true, true, true, false, false, false]);
    unbind();
    v.fire("play");
    expect(calls).toHaveLength(9);
  });
});
