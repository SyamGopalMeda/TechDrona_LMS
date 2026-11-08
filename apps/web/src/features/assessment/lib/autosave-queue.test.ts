import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { ProblemDetails } from "@/lib/api/problem";
import { AutosaveQueue, type QueueSnapshot } from "./autosave-queue";
import { memoryStore } from "./local-store";
import type { AutosaveRequest, AutosaveResponse } from "./types";

const ok = (acked: number, status = "in_progress"): AutosaveResponse => ({
  acked_seq: acked,
  server_now: "2026-11-03T10:22:33.010Z",
  deadline_at: "2026-11-03T11:45:02.100Z",
  section_deadline_at: null,
  status,
});

const problem = (status: number, code: string, extra: Record<string, unknown> = {}): ApiError =>
  new ApiError(status, { type: "x", title: code, status, detail: code, code, request_id: "r", ...extra } as ProblemDetails, "r");

const opt = (id: string) => ({ option_ids: [id] });

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function setup(send: (req: AutosaveRequest) => Promise<AutosaveResponse>, extra: Partial<ConstructorParameters<typeof AutosaveQueue>[0]> = {}) {
  const store = memoryStore();
  const snaps: QueueSnapshot[] = [];
  const q = new AutosaveQueue({ attemptId: "a1", send, store, debounceMs: 1_000, maxIntervalMs: 10_000, onChange: (s) => snaps.push(s), ...extra });
  return { q, store, snaps };
}

describe("AutosaveQueue", () => {
  it("assigns strictly increasing client_seq and keeps only the latest change per question", async () => {
    const send = vi.fn(async (r: AutosaveRequest) => ok(Math.max(...r.items.map((i) => i.client_seq))));
    const { q } = setup(send);
    expect(q.setAnswer("q1", opt("a"), false, 1_000)).toBe(1);
    expect(q.setAnswer("q2", opt("b"), false, 500)).toBe(2);
    expect(q.setAnswer("q1", opt("c"), true, 2_000)).toBe(3);
    expect(q.pendingItems().map((i) => [i.question_version_id, i.client_seq])).toEqual([
      ["q2", 2],
      ["q1", 3],
    ]);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0]![0].items).toEqual([
      { question_version_id: "q2", response: opt("b"), client_seq: 2, time_spent_ms: 500, flagged: false },
      { question_version_id: "q1", response: opt("c"), client_seq: 3, time_spent_ms: 2_000, flagged: true },
    ]);
    expect(q.pendingCount).toBe(0);
    expect(q.snapshot.status).toBe("saved");
  });

  it("debounces on change but never waits longer than the max interval (≤ 10 s)", async () => {
    const send = vi.fn(async () => ok(100));
    const { q } = setup(send, { debounceMs: 4_000, maxIntervalMs: 60_000 });
    q.setAnswer("q1", opt("a"), false, 0);
    for (let i = 0; i < 4; i += 1) {
      await vi.advanceTimersByTimeAsync(3_000); // keep changing before the debounce fires
      q.setAnswer("q1", opt(String(i)), false, 0);
    }
    // 12 s of continuous changes: the 10 s cap (not 60 s) forced a flush
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("keeps a change made while a request is in flight (higher seq is not acked away)", async () => {
    let release!: (r: AutosaveResponse) => void;
    const send = vi.fn((_req: AutosaveRequest) => new Promise<AutosaveResponse>((r) => (release = r)));
    const { q } = setup(send);
    q.setAnswer("q1", opt("a"), false, 0); // seq 1
    const flushing = q.flush();
    q.setAnswer("q1", opt("b"), false, 0); // seq 2, during flight
    release(ok(1));
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]![0].items[0]).toMatchObject({ client_seq: 2, response: opt("b") });
    release(ok(2));
    await flushing;
    expect(q.pendingCount).toBe(0);
  });

  it("splits large pending sets into batches of max_items", async () => {
    const send = vi.fn(async (r: AutosaveRequest) => ok(Math.max(...r.items.map((i) => i.client_seq))));
    const { q } = setup(send, { maxItems: 2 });
    for (let i = 0; i < 5; i += 1) q.setAnswer(`q${i}`, opt("a"), false, 0);
    await q.flush();
    expect(send.mock.calls.map((c) => c[0].items.length)).toEqual([2, 2, 1]);
  });

  it("goes offline on network errors, keeps answers locally, and syncs on reconnect", async () => {
    let online = false;
    const send = vi.fn(async () => {
      if (!online) throw new ApiError(0, null, null);
      return ok(1);
    });
    const { q, store } = setup(send);
    q.setAnswer("q1", opt("a"), false, 0);
    await q.flush();
    expect(q.snapshot.status).toBe("offline");
    expect(store.load("a1")?.items).toHaveLength(1);
    online = true;
    q.setOnline();
    await vi.waitFor(() => expect(q.snapshot.status).toBe("synced"));
    expect(store.load("a1")?.items).toHaveLength(0);
  });

  it("retries 429/5xx with exponential backoff", async () => {
    const send = vi
      .fn<(r: AutosaveRequest) => Promise<AutosaveResponse>>()
      .mockRejectedValueOnce(problem(503, "service_unavailable"))
      .mockRejectedValueOnce(problem(429, "rate_limited"))
      .mockResolvedValue(ok(1));
    const { q } = setup(send, { backoffMs: [1_000, 2_000] });
    q.setAnswer("q1", opt("a"), false, 0);
    await q.flush();
    expect(q.snapshot.status).toBe("retrying");
    await vi.advanceTimersByTimeAsync(999);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(send).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(q.snapshot.status).toBe("saved");
  });

  it("stops and reports when the attempt is closed (409 attempt_closed or terminal status)", async () => {
    const onClosed = vi.fn();
    const { q } = setup(vi.fn(async () => Promise.reject(problem(409, "attempt_closed", { status: 409, deadline_at: "x" }))), { onClosed });
    q.setAnswer("q1", opt("a"), false, 0);
    await q.flush();
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(q.snapshot.status).toBe("closed");

    const onClosed2 = vi.fn();
    const { q: q2 } = setup(vi.fn(async () => ok(1, "auto_submitted")), { onClosed: onClosed2 });
    q2.setAnswer("q1", opt("a"), false, 0);
    await q2.flush();
    expect(onClosed2).toHaveBeenCalled();
  });

  it("hands 409 attempt_bound_elsewhere to the runner without dropping answers", async () => {
    const onBound = vi.fn();
    const { q } = setup(vi.fn(async () => Promise.reject(problem(409, "attempt_bound_elsewhere", { bound_device_label: "Chrome on Windows" }))), {
      onBoundElsewhere: onBound,
    });
    q.setAnswer("q1", opt("a"), false, 0);
    await q.flush();
    expect(onBound.mock.calls[0]![0]).toMatchObject({ bound_device_label: "Chrome on Windows" });
    expect(q.pendingCount).toBe(1);
  });

  it("sends integrity events with sequence numbers alongside answers", async () => {
    const send = vi.fn(async (r: AutosaveRequest) => ok(Math.max(0, ...r.items.map((i) => i.client_seq), ...r.events.map((e) => e.client_seq))));
    const { q } = setup(send, { now: () => Date.parse("2026-11-03T10:22:10.400Z") });
    q.addEvent("focus_lost");
    q.setAnswer("q1", opt("a"), false, 0);
    q.addEvent("paste");
    await q.flush();
    expect(send.mock.calls[0]![0].events).toEqual([
      { type: "focus_lost", client_at: "2026-11-03T10:22:10.400Z", client_seq: 1 },
      { type: "paste", client_at: "2026-11-03T10:22:10.400Z", client_seq: 3 },
    ]);
    expect(send.mock.calls[0]![0].items[0]!.client_seq).toBe(2);
  });

  it("restores pending items and continues the sequence above them", () => {
    const send = vi.fn(async () => ok(0));
    const { q } = setup(send, {
      initialSeq: 3,
      initialItems: [{ question_version_id: "q9", response: opt("z"), client_seq: 7, time_spent_ms: 0, flagged: false }],
    });
    expect(q.nextSeq).toBe(8);
    expect(q.setAnswer("q1", opt("a"), false, 0)).toBe(8);
  });
});
