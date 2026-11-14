import type { AutosaveItem, IntegrityEvent } from "./types";

/**
 * Device-local copy of unsynced answers for one attempt (TST-004 crash recovery,
 * FR-ASM-005/006). Holds only this student's own pending answers, is keyed by attempt id
 * and is cleared on submit / terminal status.
 *
 * Storage (spec: IndexedDB):
 * - The durable copy lives in IndexedDB (`td-assessment` / `pending`, keyPath `attemptId`).
 * - The `PendingStore` API stays synchronous (the runner and queue call it inline), so reads
 *   are served from an in-memory cache hydrated from IndexedDB at module load (`ready`).
 * - Crash safety: IndexedDB writes are asynchronous, so each save is first written to a
 *   localStorage write-ahead entry, which is removed once the IndexedDB transaction commits.
 *   localStorage therefore only holds the (tiny) in-flight snapshot, and any entry left by a
 *   crash — or by the earlier localStorage-only implementation — is migrated on hydration.
 * - Fallback: when IndexedDB is unavailable (old browsers, some private modes, SSR, tests) or
 *   fails to open, the store keeps the full copy in localStorage as before.
 * - Callers that need the persisted state before first use should `await store.ready`.
 */
export interface PersistedAttempt {
  v: 1;
  attemptId: string;
  nextSeq: number;
  items: AutosaveItem[];
  events: IntegrityEvent[];
  visited: string[];
  updatedAt: number;
}

export interface PendingStore {
  load(attemptId: string): PersistedAttempt | null;
  save(data: PersistedAttempt): void;
  clear(attemptId: string): void;
  /** Resolves once persisted state is readable via `load` (immediately for sync stores). */
  readonly ready?: Promise<void>;
}

/** Async key-value backend (IndexedDB in browsers; injectable for tests). */
export interface PendingBackend {
  getAll(): Promise<PersistedAttempt[]>;
  put(data: PersistedAttempt): Promise<void>;
  delete(attemptId: string): Promise<void>;
}

const PREFIX = "td.attempt.v1.";
const key = (attemptId: string) => `${PREFIX}${attemptId}`;
/** Records not touched for this long are dropped on hydration (attempts are hours, not weeks). */
export const STALE_AFTER_MS = 14 * 24 * 60 * 60 * 1000;

export const IDB_NAME = "td-assessment";
export const IDB_STORE = "pending";

function browserStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function validate(data: unknown, attemptId?: string): PersistedAttempt | null {
  const d = data as PersistedAttempt | null;
  if (!d || d.v !== 1 || typeof d.attemptId !== "string" || (attemptId !== undefined && d.attemptId !== attemptId) || !Array.isArray(d.items)) return null;
  return { ...d, events: Array.isArray(d.events) ? d.events : [], visited: Array.isArray(d.visited) ? d.visited : [] };
}

function readLs(s: Storage | null, attemptId: string): PersistedAttempt | null {
  if (!s) return null;
  try {
    const raw = s.getItem(key(attemptId));
    return raw ? validate(JSON.parse(raw), attemptId) : null;
  } catch {
    return null;
  }
}

function writeLs(s: Storage | null, data: PersistedAttempt): void {
  try {
    s?.setItem(key(data.attemptId), JSON.stringify(data));
  } catch {
    /* quota / private mode: the in-memory queue still syncs */
  }
}

function removeLs(s: Storage | null, attemptId: string): void {
  try {
    s?.removeItem(key(attemptId));
  } catch {
    /* ignore */
  }
}

function lsAttemptIds(s: Storage | null): string[] {
  if (!s) return [];
  const ids: string[] = [];
  try {
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i);
      if (k?.startsWith(PREFIX)) ids.push(k.slice(PREFIX.length));
    }
  } catch {
    /* ignore */
  }
  return ids;
}

/** localStorage-only store (fallback and previous behaviour). */
export function createLocalStorageStore(getStorage: () => Storage | null = browserStorage): PendingStore {
  return {
    ready: Promise.resolve(),
    load: (attemptId) => readLs(getStorage(), attemptId),
    save: (data) => writeLs(getStorage(), data),
    clear: (attemptId) => removeLs(getStorage(), attemptId),
  };
}

const newer = (a: PersistedAttempt | null | undefined, b: PersistedAttempt | null | undefined): PersistedAttempt | null => {
  if (!a) return b ?? null;
  if (!b) return a;
  return b.nextSeq > a.nextSeq || (b.nextSeq === a.nextSeq && b.updatedAt > a.updatedAt) ? b : a;
};

export interface IdbStoreOptions {
  /** null → IndexedDB unavailable; the store falls back to localStorage. */
  backend: PendingBackend | null | Promise<PendingBackend | null>;
  storage?: () => Storage | null;
  now?: () => number;
}

/**
 * IndexedDB-backed store with a synchronous facade (see file header). Exposed for tests;
 * the app uses `localPendingStore`.
 */
export function createIdbPendingStore(opts: IdbStoreOptions): PendingStore & { readonly mode: "pending" | "indexeddb" | "localstorage" } {
  const getStorage = opts.storage ?? browserStorage;
  const now = opts.now ?? Date.now;
  const cache = new Map<string, PersistedAttempt>();
  const cleared = new Set<string>();
  let backend: PendingBackend | null = null;
  let mode: "pending" | "indexeddb" | "localstorage" = "pending";
  let chain: Promise<void> = Promise.resolve();

  const enqueue = (op: () => Promise<void>) => {
    chain = chain.then(op).catch(() => {
      /* keep the write-ahead entry; the next save retries */
    });
    return chain;
  };

  const persist = (data: PersistedAttempt) => {
    const b = backend;
    if (!b) return;
    void enqueue(async () => {
      await b.put(data);
      // Drop the write-ahead entry only if nothing newer was saved meanwhile.
      if (cache.get(data.attemptId) === data) removeLs(getStorage(), data.attemptId);
    });
  };

  const ready = (async () => {
    try {
      backend = await opts.backend;
    } catch {
      backend = null;
    }
    if (!backend) {
      mode = "localstorage";
      return;
    }
    let stored: PersistedAttempt[] = [];
    try {
      stored = await backend.getAll();
    } catch {
      backend = null;
      mode = "localstorage";
      return;
    }
    mode = "indexeddb";
    const s = getStorage();
    const merged = new Map<string, PersistedAttempt>();
    for (const raw of stored) {
      const d = validate(raw);
      if (d) merged.set(d.attemptId, d);
    }
    // Write-ahead entries (crash mid-write) and legacy localStorage data → IndexedDB.
    for (const id of lsAttemptIds(s)) {
      const fromLs = readLs(s, id);
      const best = newer(merged.get(id), fromLs);
      if (best) merged.set(id, best);
    }
    for (const [id, d] of merged) {
      if (cleared.has(id)) {
        void enqueue(() => backend!.delete(id));
        continue;
      }
      if (now() - d.updatedAt > STALE_AFTER_MS) {
        void enqueue(() => backend!.delete(id));
        removeLs(s, id);
        continue;
      }
      const best = newer(d, cache.get(id)); // saves made before hydration win if newer
      cache.set(id, best!);
      persist(best!);
    }
    // Saves made before hydration for attempts not found in storage.
    for (const [id, d] of cache) if (!merged.has(id)) persist(d);
    await chain;
  })();

  return {
    get mode() {
      return mode;
    },
    ready,
    load(attemptId) {
      if (mode === "localstorage") return readLs(getStorage(), attemptId);
      const hit = cache.get(attemptId);
      if (hit) return structuredClone(hit);
      // Before hydration, a write-ahead / legacy localStorage entry is still readable synchronously.
      if (mode === "pending") {
        const d = readLs(getStorage(), attemptId);
        if (d) cache.set(attemptId, d);
        return d ? structuredClone(d) : null;
      }
      return null;
    },
    save(data) {
      const copy = structuredClone(data);
      cleared.delete(data.attemptId);
      writeLs(getStorage(), copy); // write-ahead (or the full copy in fallback mode)
      if (mode === "localstorage") return;
      cache.set(copy.attemptId, copy);
      if (mode === "indexeddb") persist(copy);
    },
    clear(attemptId) {
      cache.delete(attemptId);
      cleared.add(attemptId);
      removeLs(getStorage(), attemptId);
      const b = backend;
      if (b) void enqueue(() => b.delete(attemptId));
    },
  };
}

/* ------------------------------------------------------------------ IndexedDB backend */

function req<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

/** Opens the IndexedDB backend, or resolves null when IndexedDB is unavailable/blocked. */
export function openIdbBackend(factory: IDBFactory | undefined = typeof indexedDB !== "undefined" ? indexedDB : undefined, timeoutMs = 3_000): Promise<PendingBackend | null> {
  if (!factory) return Promise.resolve(null);
  return new Promise<PendingBackend | null>((resolve) => {
    let settled = false;
    const done = (v: PendingBackend | null) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    const timer = setTimeout(() => done(null), timeoutMs);
    let open: IDBOpenDBRequest;
    try {
      open = factory.open(IDB_NAME, 1);
    } catch {
      clearTimeout(timer);
      done(null);
      return;
    }
    open.onupgradeneeded = () => {
      if (!open.result.objectStoreNames.contains(IDB_STORE)) open.result.createObjectStore(IDB_STORE, { keyPath: "attemptId" });
    };
    open.onerror = () => {
      clearTimeout(timer);
      done(null);
    };
    open.onblocked = () => {
      clearTimeout(timer);
      done(null);
    };
    open.onsuccess = () => {
      clearTimeout(timer);
      const db = open.result;
      const tx = (mode: IDBTransactionMode, fn: (s: IDBObjectStore) => unknown) =>
        new Promise<void>((resolve, reject) => {
          const t = db.transaction(IDB_STORE, mode);
          fn(t.objectStore(IDB_STORE));
          t.oncomplete = () => resolve();
          t.onerror = () => reject(t.error);
          t.onabort = () => reject(t.error);
        });
      done({
        getAll: () => req(db.transaction(IDB_STORE, "readonly").objectStore(IDB_STORE).getAll() as IDBRequest<PersistedAttempt[]>),
        put: (d) => tx("readwrite", (s) => s.put(d)),
        delete: (id) => tx("readwrite", (s) => s.delete(id)),
      });
    };
  });
}

/* ------------------------------------------------------------------ default store */

let defaultStore: PendingStore | null = null;

function getDefaultStore(): PendingStore {
  if (typeof window === "undefined") return createLocalStorageStore(() => null);
  defaultStore ??= createIdbPendingStore({ backend: openIdbBackend() });
  return defaultStore;
}

// Start hydrating as soon as the runner bundle loads (well before the attempt payload arrives).
if (typeof window !== "undefined") getDefaultStore();

/** App store: IndexedDB with localStorage write-ahead/fallback. */
export const localPendingStore: PendingStore = {
  get ready() {
    return getDefaultStore().ready ?? Promise.resolve();
  },
  load: (attemptId) => getDefaultStore().load(attemptId),
  save: (data) => getDefaultStore().save(data),
  clear: (attemptId) => getDefaultStore().clear(attemptId),
};

/** In-memory store for tests. */
export function memoryStore(initial: PersistedAttempt[] = []): PendingStore & { data: Map<string, PersistedAttempt> } {
  const data = new Map(initial.map((d) => [d.attemptId, structuredClone(d)]));
  return {
    data,
    ready: Promise.resolve(),
    load: (id) => (data.has(id) ? structuredClone(data.get(id)!) : null),
    save: (d) => void data.set(d.attemptId, structuredClone(d)),
    clear: (id) => void data.delete(id),
  };
}
