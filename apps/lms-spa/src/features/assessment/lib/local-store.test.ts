import { beforeEach, describe, expect, it } from "vitest";
import { createIdbPendingStore, createLocalStorageStore, openIdbBackend, STALE_AFTER_MS, type PendingBackend, type PersistedAttempt } from "./local-store";

const NOW = 1_762_164_000_000;

const rec = (attemptId: string, nextSeq: number, extra: Partial<PersistedAttempt> = {}): PersistedAttempt => ({
  v: 1,
  attemptId,
  nextSeq,
  items: [{ question_version_id: "q1", response: { option_ids: ["o1"] }, flagged: false, time_spent_ms: 10, client_seq: nextSeq - 1 }],
  events: [],
  visited: ["q1"],
  updatedAt: NOW,
  ...extra,
});

/** Async in-memory backend with controllable failures and a write gate. */
function fakeBackend(initial: PersistedAttempt[] = []) {
  const data = new Map(initial.map((d) => [d.attemptId, structuredClone(d)]));
  let gate: Promise<void> = Promise.resolve();
  let release: () => void = () => undefined;
  const backend: PendingBackend & { data: Map<string, PersistedAttempt>; failPuts: boolean; hold(): void; release(): void } = {
    data,
    failPuts: false,
    getAll: async () => [...data.values()].map((d) => structuredClone(d)),
    put: async (d) => {
      await gate;
      if (backend.failPuts) throw new Error("quota");
      data.set(d.attemptId, structuredClone(d));
    },
    delete: async (id) => {
      await gate;
      data.delete(id);
    },
    hold() {
      gate = new Promise((r) => (release = r));
    },
    release() {
      release();
    },
  };
  return backend;
}

const flush = async () => {
  for (let i = 0; i < 10; i++) await Promise.resolve();
};

const lsKey = (id: string) => `td.attempt.v1.${id}`;

beforeEach(() => localStorage.clear());

describe("IndexedDB pending store", () => {
  it("persists to IndexedDB and keeps localStorage only as an in-flight write-ahead entry", async () => {
    const be = fakeBackend();
    const store = createIdbPendingStore({ backend: be, now: () => NOW });
    await store.ready;
    expect(store.mode).toBe("indexeddb");

    be.hold();
    store.save(rec("a1", 5));
    // Before the IndexedDB transaction commits, a crash would still find the write-ahead copy.
    expect(JSON.parse(localStorage.getItem(lsKey("a1"))!).nextSeq).toBe(5);
    expect(be.data.has("a1")).toBe(false);
    be.release();
    await flush();
    expect(be.data.get("a1")!.nextSeq).toBe(5);
    expect(localStorage.getItem(lsKey("a1"))).toBeNull();
    expect(store.load("a1")!.nextSeq).toBe(5);
  });

  it("hydrates from IndexedDB on load (survives a reload)", async () => {
    const be = fakeBackend([rec("a1", 7)]);
    const store = createIdbPendingStore({ backend: be, now: () => NOW });
    await store.ready;
    expect(store.load("a1")).toEqual(rec("a1", 7));
    expect(store.load("other")).toBeNull();
  });

  it("migrates legacy / crash-left localStorage entries, keeping the newer copy", async () => {
    localStorage.setItem(lsKey("a1"), JSON.stringify(rec("a1", 9)));
    localStorage.setItem(lsKey("a2"), JSON.stringify(rec("a2", 2)));
    const be = fakeBackend([rec("a1", 4), rec("a2", 3)]);
    const store = createIdbPendingStore({ backend: be, now: () => NOW });
    await store.ready;
    await flush();
    expect(store.load("a1")!.nextSeq).toBe(9);
    expect(store.load("a2")!.nextSeq).toBe(3);
    expect(be.data.get("a1")!.nextSeq).toBe(9);
    expect(localStorage.length).toBe(0);
  });

  it("serves a write-ahead entry synchronously before hydration finishes", () => {
    localStorage.setItem(lsKey("a1"), JSON.stringify(rec("a1", 3)));
    const store = createIdbPendingStore({ backend: new Promise(() => undefined), now: () => NOW });
    expect(store.mode).toBe("pending");
    expect(store.load("a1")!.nextSeq).toBe(3);
  });

  it("saves made before hydration win over older stored copies", async () => {
    let resolve!: (b: PendingBackend) => void;
    const be = fakeBackend([rec("a1", 2)]);
    const store = createIdbPendingStore({ backend: new Promise((r) => (resolve = r)), now: () => NOW });
    store.save(rec("a1", 6));
    resolve(be);
    await store.ready;
    await flush();
    expect(store.load("a1")!.nextSeq).toBe(6);
    expect(be.data.get("a1")!.nextSeq).toBe(6);
  });

  it("clear removes the attempt everywhere", async () => {
    const be = fakeBackend([rec("a1", 2)]);
    const store = createIdbPendingStore({ backend: be, now: () => NOW });
    await store.ready;
    store.clear("a1");
    await flush();
    expect(store.load("a1")).toBeNull();
    expect(be.data.has("a1")).toBe(false);
    expect(localStorage.getItem(lsKey("a1"))).toBeNull();
  });

  it("drops stale records on hydration", async () => {
    const be = fakeBackend([rec("old", 2, { updatedAt: NOW - STALE_AFTER_MS - 1 }), rec("new", 2)]);
    const store = createIdbPendingStore({ backend: be, now: () => NOW });
    await store.ready;
    await flush();
    expect(store.load("old")).toBeNull();
    expect(be.data.has("old")).toBe(false);
    expect(store.load("new")).not.toBeNull();
  });

  it("keeps the write-ahead copy when an IndexedDB write fails", async () => {
    const be = fakeBackend();
    const store = createIdbPendingStore({ backend: be, now: () => NOW });
    await store.ready;
    be.failPuts = true;
    store.save(rec("a1", 4));
    await flush();
    expect(localStorage.getItem(lsKey("a1"))).not.toBeNull();
    expect(store.load("a1")!.nextSeq).toBe(4);
  });

  it("returns isolated copies (callers cannot mutate the cache)", async () => {
    const store = createIdbPendingStore({ backend: fakeBackend(), now: () => NOW });
    await store.ready;
    const d = rec("a1", 2);
    store.save(d);
    d.items.length = 0;
    const loaded = store.load("a1")!;
    loaded.visited.push("x");
    expect(store.load("a1")!.items).toHaveLength(1);
    expect(store.load("a1")!.visited).toEqual(["q1"]);
  });
});

describe("fallback when IndexedDB is unavailable", () => {
  it("uses localStorage for the full copy", async () => {
    const store = createIdbPendingStore({ backend: null, now: () => NOW });
    await store.ready;
    expect(store.mode).toBe("localstorage");
    store.save(rec("a1", 3));
    expect(JSON.parse(localStorage.getItem(lsKey("a1"))!).nextSeq).toBe(3);
    // A fresh instance (reload) still sees it.
    const again = createIdbPendingStore({ backend: null });
    await again.ready;
    expect(again.load("a1")!.nextSeq).toBe(3);
    again.clear("a1");
    expect(localStorage.getItem(lsKey("a1"))).toBeNull();
  });

  it("falls back when reading IndexedDB fails", async () => {
    const broken: PendingBackend = {
      getAll: () => Promise.reject(new Error("InvalidStateError")),
      put: () => Promise.reject(new Error("x")),
      delete: () => Promise.reject(new Error("x")),
    };
    const store = createIdbPendingStore({ backend: broken });
    await store.ready;
    expect(store.mode).toBe("localstorage");
  });

  it("openIdbBackend resolves null without IndexedDB or when open throws", async () => {
    await expect(openIdbBackend(undefined)).resolves.toBeNull();
    const throwing = {
      open: () => {
        throw new Error("SecurityError");
      },
    } as unknown as IDBFactory;
    await expect(openIdbBackend(throwing)).resolves.toBeNull();
  });

  it("legacy store ignores malformed data and storage errors", () => {
    localStorage.setItem(lsKey("a1"), "{not json");
    const s = createLocalStorageStore();
    expect(s.load("a1")).toBeNull();
    const noStorage = createLocalStorageStore(() => null);
    expect(() => noStorage.save(rec("a1", 1))).not.toThrow();
    expect(noStorage.load("a1")).toBeNull();
  });
});
