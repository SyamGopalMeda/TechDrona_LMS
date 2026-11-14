import { afterEach, describe, expect, it } from "vitest";
import { clearDeviceAttemptData, inspectDeviceAttemptData } from "./device-cleanup";
import type { PendingBackend, PersistedAttempt } from "./local-store";

const rec = (attemptId: string, items = 0): PersistedAttempt => ({
  v: 1,
  attemptId,
  nextSeq: items + 1,
  items: Array.from({ length: items }, (_, i) => ({ question_version_id: `q${i}`, response: null, flagged: false, client_seq: i + 1, time_spent_ms: 0 })),
  events: [],
  visited: [],
  updatedAt: Date.now(),
});

function backend(initial: PersistedAttempt[]): PendingBackend & { data: Map<string, PersistedAttempt> } {
  const data = new Map(initial.map((d) => [d.attemptId, d]));
  return {
    data,
    getAll: async () => [...data.values()],
    put: async (d) => void data.set(d.attemptId, d),
    delete: async (id) => void data.delete(id),
  };
}

afterEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("FE-17: sign-out clears test data kept on this device", () => {
  it("counts attempts with unsynced answers (IndexedDB + write-ahead copies)", async () => {
    window.localStorage.setItem("td.attempt.v1.a3", JSON.stringify(rec("a3", 1)));
    const b = backend([rec("a1", 2), rec("a2", 0)]);
    expect(await inspectDeviceAttemptData(b)).toEqual({ unsyncedAttempts: 2 });
  });

  it("removes IndexedDB records and every td.attempt.* key, leaving other keys alone", async () => {
    window.localStorage.setItem("td.attempt.v1.a3", JSON.stringify(rec("a3", 1)));
    window.localStorage.setItem("td.attempt.integrity.a1", "1");
    window.sessionStorage.setItem("td.attempt.submitted.a1", "{}");
    window.localStorage.setItem("td.coding.lang", "python3");
    const b = backend([rec("a1", 2), rec("a2", 0)]);
    await clearDeviceAttemptData(b);
    expect(b.data.size).toBe(0);
    expect(window.localStorage.getItem("td.attempt.v1.a3")).toBeNull();
    expect(window.localStorage.getItem("td.attempt.integrity.a1")).toBeNull();
    expect(window.sessionStorage.getItem("td.attempt.submitted.a1")).toBeNull();
    expect(window.localStorage.getItem("td.coding.lang")).toBe("python3");
    expect(await inspectDeviceAttemptData(b)).toEqual({ unsyncedAttempts: 0 });
  });
});
