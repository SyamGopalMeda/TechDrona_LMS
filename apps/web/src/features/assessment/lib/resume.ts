import type { PersistedAttempt } from "./local-store";
import type { AutosaveItem, IntegrityEvent, QuestionResponse, SavedResponse } from "./types";

/**
 * Resume after crash / refresh / reconnect (TST-004, design-system §9.7).
 *
 * Inputs: the server's saved responses (ATT-02/03, each with its `client_seq`) and the
 * device-local pending set. For each question the higher `client_seq` wins, mirroring the
 * server rule — so a local answer that the server already has (or that another device
 * superseded) is not re-sent, and newer local answers are queued for sync.
 */

export interface AnswerState {
  response: QuestionResponse | null;
  flagged: boolean;
  client_seq: number;
}

export interface ResumePlan {
  answers: Map<string, AnswerState>;
  /** Local answers newer than the server's copy: shown immediately and synced. */
  toSync: AutosaveItem[];
  events: IntegrityEvent[];
  /** Local answers that lost to a newer answer saved from another device. */
  conflicts: number;
  /** Next client_seq: above everything seen locally and on the server. */
  nextSeq: number;
  /** Answered questions according to the server (for "We've restored {answered} answers"). */
  restoredCount: number;
  visited: string[];
  /** True when this browser held state for the attempt (crash/refresh rather than first load). */
  hadLocalState: boolean;
}

export function isAnswered(response: QuestionResponse | null | undefined): boolean {
  if (!response) return false;
  if ("option_ids" in response && Array.isArray(response.option_ids)) return response.option_ids.length > 0;
  if ("value" in response && typeof response.value === "string") return response.value.trim().length > 0;
  if ("source_code" in response) return true;
  return Object.keys(response).length > 0;
}

export function planResume(server: SavedResponse[] | undefined, local: PersistedAttempt | null): ResumePlan {
  const answers = new Map<string, AnswerState>();
  let maxSeq = 0;
  let restoredCount = 0;
  for (const r of server ?? []) {
    answers.set(r.question_version_id, { response: r.response, flagged: r.flagged, client_seq: r.client_seq });
    maxSeq = Math.max(maxSeq, r.client_seq);
    if (isAnswered(r.response)) restoredCount += 1;
  }

  const toSync: AutosaveItem[] = [];
  let conflicts = 0;
  for (const item of local?.items ?? []) {
    const srv = answers.get(item.question_version_id);
    maxSeq = Math.max(maxSeq, item.client_seq);
    if (!srv || item.client_seq > srv.client_seq) {
      answers.set(item.question_version_id, { response: item.response, flagged: item.flagged, client_seq: item.client_seq });
      toSync.push(item);
    } else if (item.client_seq < srv.client_seq) {
      conflicts += 1;
    }
    // equal seq: the server already has exactly this change — nothing to do.
  }

  const events = local?.events ?? [];
  for (const e of events) maxSeq = Math.max(maxSeq, e.client_seq);

  const visited = new Set(local?.visited ?? []);
  for (const id of answers.keys()) visited.add(id);

  return {
    answers,
    toSync: toSync.sort((a, b) => a.client_seq - b.client_seq),
    events,
    conflicts,
    nextSeq: Math.max(maxSeq + 1, local?.nextSeq ?? 1),
    restoredCount,
    visited: [...visited],
    hadLocalState: local !== null,
  };
}
