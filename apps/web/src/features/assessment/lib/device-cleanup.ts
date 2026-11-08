import { localPendingStore, openIdbBackend, validate, type PendingBackend } from "./local-store";

/**
 * Shared-device hygiene on sign-out (FE-17): test answers that were never synced, and the
 * per-attempt flags (`td.attempt.*` — write-ahead copies, integrity consent, submitted markers),
 * must not outlive the session on a shared PC.
 */

const ATTEMPT_PREFIX = "td.attempt.";
const WRITE_AHEAD_PREFIX = "td.attempt.v1.";

export interface DeviceAttemptData {
  /** Attempts with answers or events still waiting to be synced to the server. */
  unsyncedAttempts: number;
}

function storages(): Storage[] {
  const out: Storage[] = [];
  try {
    if (typeof window !== "undefined") out.push(window.localStorage);
  } catch {
    /* blocked */
  }
  try {
    if (typeof window !== "undefined") out.push(window.sessionStorage);
  } catch {
    /* blocked */
  }
  return out;
}

function keysWithPrefix(s: Storage, prefix: string): string[] {
  const keys: string[] = [];
  try {
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i);
      if (k?.startsWith(prefix)) keys.push(k);
    }
  } catch {
    /* ignore */
  }
  return keys;
}

const hasUnsynced = (raw: unknown) => {
  const d = validate(raw);
  return !!d && (d.items.length > 0 || d.events.length > 0);
};

/** Counts attempts with unsynced answers on this device (IndexedDB + localStorage write-ahead). */
export async function inspectDeviceAttemptData(backend?: PendingBackend | null): Promise<DeviceAttemptData> {
  const ids = new Set<string>();
  const b = backend === undefined ? await openIdbBackend() : backend;
  if (b) {
    try {
      for (const d of await b.getAll()) if (hasUnsynced(d)) ids.add(d.attemptId);
    } catch {
      /* unreadable store: nothing we can report */
    }
  }
  for (const s of storages()) {
    for (const k of keysWithPrefix(s, WRITE_AHEAD_PREFIX)) {
      try {
        const raw: unknown = JSON.parse(s.getItem(k) ?? "null");
        if (hasUnsynced(raw)) ids.add(k.slice(WRITE_AHEAD_PREFIX.length));
      } catch {
        /* ignore corrupt entries */
      }
    }
  }
  return { unsyncedAttempts: ids.size };
}

/** Removes every locally kept attempt record (IndexedDB `td-assessment/pending`) and `td.attempt.*` keys. */
export async function clearDeviceAttemptData(backend?: PendingBackend | null): Promise<void> {
  // Let the app store finish hydrating first: it re-persists write-ahead entries into IndexedDB,
  // which would otherwise race with (and undo) the deletes below.
  try {
    await localPendingStore.ready;
  } catch {
    /* ignore */
  }
  for (const s of storages()) {
    for (const k of keysWithPrefix(s, ATTEMPT_PREFIX)) {
      try {
        s.removeItem(k);
      } catch {
        /* ignore */
      }
    }
  }
  const b = backend === undefined ? await openIdbBackend() : backend;
  if (!b) return;
  try {
    const all = await b.getAll();
    await Promise.all(all.map((d) => b.delete(d.attemptId)));
  } catch {
    /* best effort: the 14-day retention still applies */
  }
}
