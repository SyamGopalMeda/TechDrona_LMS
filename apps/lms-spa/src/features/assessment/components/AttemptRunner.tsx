"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button, Dialog, ErrorState, Skeleton } from "@/components/ui";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { isApiError } from "@/lib/api/errors";
import type { ProblemDetails } from "@/lib/api/problem";
import { uuid7 } from "@/lib/ids/uuid7";
import { cn } from "@/lib/ui/cn";
import { assessmentApi } from "../lib/api";
import { AutosaveQueue, type QueueSnapshot } from "../lib/autosave-queue";
import { localPendingStore, type PendingStore } from "../lib/local-store";
import { paletteCounts, paletteState } from "../lib/palette";
import { isAnswered, planResume, type AnswerState } from "../lib/resume";
import { createEventThrottle, eventFilter, integrityWarning, isRecordable } from "../lib/integrity-capture";
import { formatCountdown, ServerClock } from "../lib/server-clock";
import type {
  AttemptPayload,
  AttemptSection,
  BoundElsewhere,
  ExamProtocol,
  IntegrityEventType,
  IntegritySummary,
  QuestionResponse,
  SubmitResponse,
} from "../lib/types";
import { BoundElsewhereView } from "./BoundElsewhere";
import { QuestionView } from "./QuestionView";
import { AutosaveIndicator, QuestionPalette, Timer } from "./RunnerParts";

export const INTEGRITY_FLAG_KEY = (attemptId: string) => `td.attempt.integrity.${attemptId}`;
export const SUBMITTED_KEY = (attemptId: string) => `td.attempt.submitted.${attemptId}`;

export const ATTEMPT_ROUTE = "/app/attempts/[attempt_id]";
export const ATTEMPT_RESUME_ROUTE = "/app/attempts/[attempt_id]/resume";

const TIME_SYNC_MS = 60_000;
/** After expiry: ATT-07 is rate-limited to 4/min, so poll at most every 15 s for up to 5 minutes. */
export const EXPIRY_POLL_MS = 15_000;
const EXPIRY_POLLS = 20;
const BACK_ONLINE_MS = 6_000;

type Phase = "loading" | "ready" | "bound" | "error" | "expired" | "leaving";

interface ResumeNotice {
  restored: number;
  pending: number;
  conflicts: number;
}

export interface AttemptRunnerProps {
  attemptId: string;
  /** Show the TST-004 welcome-back panel even without local state (route /resume). */
  forceResume?: boolean;
  store?: PendingStore;
  /** Interval between post-expiry ATT-07 polls (tests shorten it). */
  expiryPollMs?: number;
}

function activeSection(p: AttemptPayload | null): AttemptSection | null {
  if (!p) return null;
  return (
    p.sections.find((s) => s.section_id === p.current_section_id && s.questions?.length) ??
    p.sections.find((s) => s.status === "active" && s.questions?.length) ??
    p.sections.find((s) => s.questions?.length) ??
    null
  );
}

/** Sections the student can no longer enter (ATT-09 submit or server-side section timeout). */
const isClosedSection = (s: AttemptSection) => s.status === "submitted" || s.status === "timed_out";

function earlier(a: string | null | undefined, b: string | null | undefined): string | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return Date.parse(a) <= Date.parse(b) ? a : b;
}

/**
 * TST-002 attempt runner (+ TST-003 submit dialog, TST-004 resume, FR-SES-011 rebind).
 * Focus shell: covers the portal chrome; no global navigation (leaving needs confirmation).
 */
export function AttemptRunner({ attemptId, forceResume = false, store = localPendingStore, expiryPollMs = EXPIRY_POLL_MS }: AttemptRunnerProps) {
  const router = useRouter();
  const clock = useMemo(() => new ServerClock(), []);
  const queueRef = useRef<AutosaveQueue | null>(null);

  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<unknown>(null);
  const [payload, setPayload] = useState<AttemptPayload | null>(null);
  const [deadlineAt, setDeadlineAt] = useState<string | null>(null);
  const [sectionDeadlineAt, setSectionDeadlineAt] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Map<string, AnswerState>>(new Map());
  const [visited, setVisited] = useState<Set<string>>(new Set());
  const [index, setIndex] = useState(0);
  const [snap, setSnap] = useState<QueueSnapshot>({ status: "idle", pendingCount: 0, lastSavedAt: null, lastAckedSeq: 0 });
  const [bound, setBound] = useState<BoundElsewhere | null>(null);
  const [resumeNotice, setResumeNotice] = useState<ResumeNotice | null>(null);
  const [online, setOnline] = useState(true);
  const [otherTabOpen, setOtherTabOpen] = useState(false);
  const [backOnline, setBackOnline] = useState<number | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const submitKey = useRef<string | null>(null);
  const rebindKey = useRef<string | null>(null);
  const pendingAtOffline = useRef(0);
  const wasOffline = useRef(false);
  const integrityRef = useRef(false);
  const protocolRef = useRef<ExamProtocol | null>(null);
  const closedByIntegrity = useRef(false);
  const [integrity, setIntegrity] = useState<IntegritySummary | null>(null);
  // Answers the server refused (e.g. letters in a numeric box), by question version: shown on that
  // question until the learner changes the answer. Other answers keep saving normally.
  const [rejected, setRejected] = useState<Record<string, string>>({});
  const [localEvents, setLocalEvents] = useState(0);
  const [fullscreenOff, setFullscreenOff] = useState(false);
  const timeOnQuestion = useRef(new Map<string, number>());
  const viewStart = useRef<{ id: string; at: number } | null>(null);

  // Free navigation: every section is delivered and sections aren't submitted separately (ATT-09
  // refuses), so the runner walks all questions in order and submits the whole test.
  const free = payload?.test.navigation_mode === "free";
  const sections = useMemo(() => payload?.sections ?? [], [payload]);
  const questions = useMemo(
    () => (free ? sections.flatMap((s) => s.questions ?? []) : (activeSection(payload)?.questions ?? [])),
    [free, sections, payload],
  );
  const question = questions[index] ?? null;
  const section =
    (free && question ? sections.find((s) => s.questions?.some((q) => q.question_version_id === question.question_version_id)) : null) ??
    activeSection(payload);
  const isLastSection = free || !section || sections.filter((s) => s.position > section.position && !isClosedSection(s)).length === 0;
  const effectiveDeadline = earlier(sectionDeadlineAt, deadlineAt);

  // FE-07: a test attempt is a learning surface (M5); test_attempt_id lets the server attribute
  // the time to the learner's batch (BE-02 resolver). One page instance per attempt view.
  const tracker = useActivityTracker({
    route: forceResume ? ATTEMPT_RESUME_ROUTE : ATTEMPT_ROUTE,
    surface: "test",
    entity: { test_attempt_id: attemptId, test_id: payload?.test.id },
    enabled: Boolean(payload) && (phase === "ready" || phase === "expired"),
  });

  const goSubmitted = useCallback(
    (reason?: string) => {
      queueRef.current?.stop();
      queueRef.current?.clearLocal();
      setPhase("leaving");
      router.replace(`/app/attempts/${encodeURIComponent(attemptId)}/submitted${reason ? `?reason=${reason}` : ""}`);
    },
    [attemptId, router],
  );

  /* ------------------------------------------------------------------ load / resume */

  const applyPayload = useCallback(
    (p: AttemptPayload, sentMono: number | undefined, showResume: boolean) => {
      clock.observe(p.server_now, sentMono);
      if (p.status !== "in_progress") {
        goSubmitted(p.status === "auto_submitted" ? "deadline" : undefined);
        return;
      }
      const local = store.load(attemptId);
      const plan = planResume(p.responses, local);
      queueRef.current?.stop();
      const integrityLocal = (() => {
        try {
          return window.localStorage.getItem(INTEGRITY_FLAG_KEY(attemptId)) === "1";
        } catch {
          return false;
        }
      })();
      // The server drops events without consent (ignored_events); only send them when consent was
      // given here, or when the exam protocol applies (agreeing to its instructions is the consent).
      const integrityOn = integrityLocal || !!p.protocol?.exam_mode;
      protocolRef.current = p.protocol ?? null;
      closedByIntegrity.current = false;
      setIntegrity(p.integrity ?? null);
      setLocalEvents(0);
      const q = new AutosaveQueue({
        attemptId,
        store,
        send: async (body) => {
          const mark = clock.mark();
          const res = await assessmentApi.autosave(attemptId, integrityOn ? body : { ...body, events: [] });
          clock.observe(res.server_now, mark);
          return res;
        },
        debounceMs: p.autosave?.debounce_ms,
        maxIntervalMs: p.autosave?.max_interval_ms,
        maxItems: p.autosave?.max_items,
        initialSeq: plan.nextSeq,
        initialItems: plan.toSync,
        initialEvents: integrityOn ? plan.events : [],
        initialVisited: plan.visited,
        currentSectionId: () => currentSectionRef.current ?? activeSection(p)?.section_id,
        onChange: setSnap,
        onAck: (r) => {
          if (r.rejected?.length) {
            const bad = r.rejected;
            setRejected((m) => ({ ...m, ...Object.fromEntries(bad.map((x) => [x.question_version_id, x.message])) }));
          }
          setDeadlineAt(r.deadline_at);
          setSectionDeadlineAt(r.section_deadline_at ?? null);
          if (r.integrity) {
            setIntegrity(r.integrity);
            setLocalEvents(0);
            const limit = p.protocol?.auto_submit_after;
            if (r.status !== "in_progress" && limit && r.integrity.total >= limit) closedByIntegrity.current = true;
          }
        },
        onClosed: () => {
          goSubmitted(wasOffline.current ? "deadline_offline" : closedByIntegrity.current ? "integrity_limit" : "deadline");
        },
        onBoundElsewhere: (problem) => {
          setBound((problem ?? {}) as BoundElsewhere);
          setPhase("bound");
        },
        onSectionLocked: () => {
          const ids = (activeSection(p)?.questions ?? []).map((x) => x.question_version_id);
          q.drop(ids);
          void reloadRef.current?.();
        },
      });
      integrityRef.current = integrityOn;
      queueRef.current = q;
      q.persist();
      setSnap(q.snapshot);
      setPayload(p);
      setDeadlineAt(p.deadline_at);
      setSectionDeadlineAt(activeSection(p)?.deadline_at ?? null);
      setAnswers(plan.answers);
      setVisited(new Set(plan.visited));
      setIndex(0);
      setBound(null);
      setPhase("ready");
      if (showResume || plan.hadLocalState) {
        setResumeNotice({ restored: plan.restoredCount, pending: plan.toSync.length, conflicts: plan.conflicts });
      }
      if (plan.toSync.length || plan.events.length) void q.flush();
    },
    [attemptId, clock, goSubmitted, store],
  );

  const reloadRef = useRef<(() => Promise<void>) | null>(null);
  const currentSectionRef = useRef<string | undefined>(undefined);

  const load = useCallback(
    async (mode: "state" | "resume") => {
      setError(null);
      const mark = clock.mark();
      try {
        const p = mode === "resume" ? await assessmentApi.resume(attemptId) : await assessmentApi.state(attemptId);
        applyPayload(p, mark, forceResume);
      } catch (e) {
        if (isApiError(e) && e.code === "attempt_bound_elsewhere") {
          const info = (e.problem ?? {}) as ProblemDetails & BoundElsewhere;
          clock.observe(info.read_only?.server_now, mark);
          if (info.read_only?.deadline_at) setDeadlineAt(info.read_only.deadline_at);
          setBound(info);
          setPhase("bound");
          return;
        }
        if (isApiError(e) && e.code === "attempt_closed") {
          goSubmitted("deadline");
          return;
        }
        setError(e);
        setPhase("error");
      }
    },
    [applyPayload, attemptId, clock, forceResume, goSubmitted],
  );

  reloadRef.current = () => load("state");
  currentSectionRef.current = section?.section_id;

  useEffect(() => {
    let cancelled = false;
    // The IndexedDB-backed store hydrates asynchronously: wait for it before the first load so
    // unsaved answers from a previous visit are not missed (and resume is chosen correctly).
    void (async () => {
      try {
        await (store.ready ?? Promise.resolve());
      } catch {
        /* hydration failure falls back to the in-memory cache */
      }
      if (cancelled) return;
      const hadLocal = store.load(attemptId) !== null;
      void load(hadLocal || forceResume ? "resume" : "state");
    })();
    return () => {
      cancelled = true;
      queueRef.current?.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once per attempt
  }, [attemptId]);

  /* ------------------------------------------------------------------ connectivity, time sync, integrity */

  useEffect(() => {
    if (phase !== "ready") return;
    const syncTime = async () => {
      const mark = clock.mark();
      try {
        const t = await assessmentApi.time(attemptId);
        clock.observe(t.server_now, mark);
        setDeadlineAt(t.deadline_at);
        setSectionDeadlineAt(t.section_deadline_at ?? null);
        if (t.status && t.status !== "in_progress") goSubmitted("deadline");
      } catch {
        /* offline or rate-limited: keep the last sample */
      }
    };
    const id = setInterval(syncTime, TIME_SYNC_MS);
    const protocol = protocolRef.current;
    const wanted = eventFilter(protocol);
    const throttle = createEventThrottle();
    // Evidence only: queue the event for the server (batched with autosave, idempotent by
    // client_seq); the banner counter is provisional until the server's count comes back.
    const record = (type: IntegrityEventType) => {
      if (!integrityRef.current || !wanted(type) || !throttle(type, Date.now())) return;
      queueRef.current?.addEvent(type);
      if (protocol?.exam_mode && isRecordable(type)) setLocalEvents((n) => n + 1);
    };
    const onOffline = () => {
      setOnline(false);
      wasOffline.current = true;
      pendingAtOffline.current = queueRef.current?.pendingCount ?? 0;
      record("disconnect");
      queueRef.current?.setOffline();
    };
    const onOnline = () => {
      setOnline(true);
      record("reconnect");
      queueRef.current?.setOnline();
      void syncTime();
    };
    const onVisibility = () => record(document.visibilityState === "hidden" ? "focus_lost" : "focus_gained");
    const onPaste = () => record("paste");
    const onCopy = () => record("copy");
    const onCut = () => record("cut");
    const onContextMenu = () => record("right_click");
    let blurTimer: ReturnType<typeof setTimeout> | null = null;
    // A tab switch fires blur too; only a blur while the page stays visible is "window inactive".
    const onBlur = () => {
      if (blurTimer) clearTimeout(blurTimer);
      blurTimer = setTimeout(() => {
        if (document.visibilityState === "visible" && !document.hasFocus()) record("window_blur");
      }, 150);
    };
    let resizeTimer: ReturnType<typeof setTimeout> | null = null;
    const onResize = () => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => record("resize"), 800);
    };
    let wasFullscreen = !!document.fullscreenElement;
    if (protocol?.require_fullscreen) setFullscreenOff(!document.fullscreenElement);
    const onFullscreen = () => {
      const now = !!document.fullscreenElement;
      if (wasFullscreen && !now) record("fullscreen_exit");
      wasFullscreen = now;
      if (protocol?.require_fullscreen) setFullscreenOff(!now);
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if ((queueRef.current?.pendingCount ?? 0) > 0) {
        void queueRef.current?.flush();
        e.preventDefault();
      }
    };
    if (typeof navigator !== "undefined" && navigator.onLine === false) onOffline();
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    document.addEventListener("visibilitychange", onVisibility);
    document.addEventListener("paste", onPaste);
    document.addEventListener("copy", onCopy);
    document.addEventListener("cut", onCut);
    document.addEventListener("contextmenu", onContextMenu);
    document.addEventListener("fullscreenchange", onFullscreen);
    window.addEventListener("blur", onBlur);
    window.addEventListener("resize", onResize);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      clearInterval(id);
      if (blurTimer) clearTimeout(blurTimer);
      if (resizeTimer) clearTimeout(resizeTimer);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
      document.removeEventListener("visibilitychange", onVisibility);
      document.removeEventListener("paste", onPaste);
      document.removeEventListener("copy", onCopy);
      document.removeEventListener("cut", onCut);
      document.removeEventListener("contextmenu", onContextMenu);
      document.removeEventListener("fullscreenchange", onFullscreen);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [attemptId, clock, goSubmitted, phase]);

  // "Back online. {n} answers synced." for 6 s after the queue drains post-reconnect.
  useEffect(() => {
    if (snap.status === "synced" && online) {
      wasOffline.current = false;
      setBackOnline(pendingAtOffline.current);
      const t = setTimeout(() => setBackOnline(null), BACK_ONLINE_MS);
      return () => clearTimeout(t);
    }
  }, [snap.status, online]);

  /* ------------------------------------------------------------------ several tabs (SCN-02) */

  // Same attempt open in another tab of this browser: both keep working (answers are
  // idempotent by client_seq); tell the student so they don't answer in two places.
  useEffect(() => {
    if (phase !== "ready" || typeof BroadcastChannel === "undefined") return;
    const me = uuid7();
    const peers = new Set<string>();
    const ch = new BroadcastChannel(`td-attempt-${attemptId}`);
    ch.onmessage = (e: MessageEvent<{ type?: string; tab?: string }>) => {
      const { type, tab } = e.data ?? {};
      if (!tab || tab === me) return;
      if (type === "bye") peers.delete(tab);
      else {
        if (type === "hello") ch.postMessage({ type: "here", tab: me });
        peers.add(tab);
      }
      setOtherTabOpen(peers.size > 0);
    };
    ch.postMessage({ type: "hello", tab: me });
    const bye = () => ch.postMessage({ type: "bye", tab: me });
    window.addEventListener("pagehide", bye);
    return () => {
      window.removeEventListener("pagehide", bye);
      bye();
      ch.close();
    };
  }, [attemptId, phase]);

  /* ------------------------------------------------------------------ question time + visits */

  useEffect(() => {
    if (!question) return;
    const id = question.question_version_id;
    const spent = timeOnQuestion.current;
    viewStart.current = { id, at: performance.now() };
    queueRef.current?.markVisited(id);
    setVisited((v) => (v.has(id) ? v : new Set(v).add(id)));
    // FE-16: advisory assessment.question_viewed {question_index} (analytics-event-schema §2.4).
    tracker.event("assessment.question_viewed", { question_index: index });
    return () => {
      const vs = viewStart.current;
      if (vs && vs.id === id) {
        spent.set(id, (spent.get(id) ?? 0) + (performance.now() - vs.at));
        viewStart.current = null;
      }
    };
  }, [question, index, tracker]);

  const spentOn = (id: string) => {
    const base = timeOnQuestion.current.get(id) ?? 0;
    const vs = viewStart.current;
    return base + (vs && vs.id === id ? performance.now() - vs.at : 0);
  };

  const update = (id: string, patch: Partial<Pick<AnswerState, "response" | "flagged">>) => {
    const cur = answers.get(id) ?? { response: null, flagged: false, client_seq: 0 };
    const next: AnswerState = { ...cur, ...patch };
    if (patch.response !== undefined) setRejected((m) => (m[id] ? Object.fromEntries(Object.entries(m).filter(([k]) => k !== id)) : m));
    const seq = queueRef.current?.setAnswer(id, next.response, next.flagged, spentOn(id)) ?? cur.client_seq;
    setAnswers((m) => new Map(m).set(id, { ...next, client_seq: seq }));
  };

  /* ------------------------------------------------------------------ expiry */

  const onExpire = useCallback(async () => {
    const sectionEnds = sectionDeadlineAt && deadlineAt && Date.parse(sectionDeadlineAt) < Date.parse(deadlineAt);
    await queueRef.current?.flush();
    if (sectionEnds) {
      await load("state");
      return;
    }
    setPhase("expired");
    // The server sweeper auto-submits (§15.1). Poll until it reports a terminal status.
    // ATT-07 allows 4 requests/min, so poll every EXPIRY_POLL_MS and honour Retry-After on 429.
    for (let i = 0; i < EXPIRY_POLLS; i += 1) {
      let wait = expiryPollMs;
      try {
        const t = await assessmentApi.time(attemptId);
        if (t.status && t.status !== "in_progress") break;
      } catch (e) {
        if (isApiError(e) && (e.code === "attempt_closed" || e.status === 404)) break;
        if (isApiError(e) && e.status === 429 && e.retryAfter) wait = Math.max(wait, e.retryAfter * 1000);
      }
      await new Promise((r) => setTimeout(r, wait));
    }
    goSubmitted("deadline");
  }, [attemptId, deadlineAt, expiryPollMs, goSubmitted, load, sectionDeadlineAt]);

  /* ------------------------------------------------------------------ submit */

  const ids = questions.map((q) => q.question_version_id);
  const counts = paletteCounts(ids, answers, visited);
  // Answers the server refused are not stored: they count as not answered at submission.
  const rejectedCount = ids.filter((id) => rejected[id]).length;
  const unanswered = counts.not_answered + counts.not_visited + counts.marked + rejectedCount;

  const submit = async () => {
    const q = queueRef.current;
    if (!q || !payload) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await q.flush();
      if (!isLastSection && section) {
        await assessmentApi.submitSection(attemptId, section.section_id);
        setConfirmOpen(false);
        await load("state");
        return;
      }
      submitKey.current ??= uuid7();
      const res: SubmitResponse = await assessmentApi.submit(attemptId, q.pendingItems(), unanswered, submitKey.current);
      try {
        window.sessionStorage.setItem(SUBMITTED_KEY(attemptId), JSON.stringify(res));
      } catch {
        /* ignore */
      }
      q.stop();
      q.clearLocal();
      setPhase("leaving");
      router.replace(res.redirect?.startsWith("/app/") ? res.redirect : `/app/attempts/${encodeURIComponent(attemptId)}/submitted`);
    } catch (e) {
      if (isApiError(e) && e.code === "attempt_closed") {
        goSubmitted("deadline");
        return;
      }
      if (isApiError(e) && e.code === "confirm_required") {
        // The server counts more unanswered questions than shown here (e.g. a refused answer):
        // resync, and use a fresh key so the next confirmation isn't the replayed refusal.
        submitKey.current = null;
        setSubmitError(e);
        await load("state");
        return;
      }
      if (isApiError(e) && e.code === "attempt_bound_elsewhere") {
        setConfirmOpen(false);
        setBound((e.problem ?? {}) as BoundElsewhere);
        setPhase("bound");
        return;
      }
      setSubmitError(e);
    } finally {
      setSubmitting(false);
    }
  };

  /* ------------------------------------------------------------------ render */

  if (phase === "loading" || phase === "leaving") {
    return (
      <FocusShell>
        <div className="mx-auto max-w-3xl space-y-4 p-6" aria-busy="true">
          <span className="sr-only">Loading your test…</span>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </FocusShell>
    );
  }

  if (phase === "error") {
    return (
      <FocusShell>
        <div className="mx-auto max-w-xl p-6">
          <ErrorState error={error} onRetry={() => void load("state")} />
          <p className="mt-4 text-sm text-fg-muted">Your answers saved on this device are kept and will sync when the test loads.</p>
        </div>
      </FocusShell>
    );
  }

  if (phase === "bound" && bound) {
    return (
      <FocusShell>
        <BoundElsewhereView
          testTitle={payload?.test.title ?? null}
          info={bound}
          remainingMs={clock.remainingMs(deadlineAt ?? bound.read_only?.deadline_at)}
          onGoBack={() => router.push("/app/tests")}
          onSendOtp={async () => {
            await assessmentApi.sendRebindOtp(attemptId);
          }}
          onContinue={async (otp) => {
            rebindKey.current ??= uuid7();
            const mark = clock.mark();
            const p = await assessmentApi.rebind(attemptId, otp, rebindKey.current);
            rebindKey.current = null;
            applyPayload(p, mark, true);
          }}
        />
      </FocusShell>
    );
  }

  if (!payload || !section || !question) {
    return (
      <FocusShell>
        <div className="mx-auto max-w-xl p-6">
          <ErrorState title="This test has no questions to show" detail="Please go back and try again, or contact support." onRetry={() => void load("state")} />
        </div>
      </FocusShell>
    );
  }

  const answer = answers.get(question.question_version_id);
  const states = questions.map((q) => paletteState(answers.get(q.question_version_id), visited.has(q.question_version_id)));
  const showOffline = !online || snap.status === "offline";
  const remainingNow = clock.remainingMs(effectiveDeadline);

  const palette = (
    <QuestionPalette
      states={states}
      current={index}
      counts={counts}
      onSelect={(i) => {
        setIndex(i);
        setPaletteOpen(false);
      }}
    />
  );

  return (
    <FocusShell>
      {/* Test bar */}
      <header className="sticky top-0 z-sticky border-b border-line bg-surface">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <button
              type="button"
              onClick={() => setLeaveOpen(true)}
              className="rounded px-1 text-sm text-fg-link underline focus-visible:shadow-focus focus-visible:outline-none"
            >
              Exit
            </button>
            <h1 className="truncate font-display text-base font-semibold text-fg">{payload.test.title}</h1>
            {sections.length > 1 ? <span className="hidden text-sm text-fg-muted sm:inline">· {section.title}</span> : null}
          </div>
          {rejectedCount > 0 ? (
            <span role="status" className="text-sm font-medium text-danger-fg">
              {rejectedCount} answer{rejectedCount === 1 ? "" : "s"} not saved
            </span>
          ) : (
            <AutosaveIndicator status={snap.status} lastSavedAt={snap.lastSavedAt} />
          )}
          <Timer clock={clock} deadlineAt={effectiveDeadline} onExpire={() => void onExpire()} />
          <Button variant="secondary" size="sm" className="lg:hidden" onClick={() => setPaletteOpen(true)}>
            Questions {index + 1}/{questions.length}
          </Button>
          <Button size="sm" onClick={() => setConfirmOpen(true)} disabled={phase === "expired"}>
            {isLastSection ? "Submit test" : "Submit section"}
          </Button>
        </div>
        {sections.length > 1 ? (
          <ol aria-label="Sections" className="flex gap-2 overflow-x-auto border-t border-line px-4 py-1 text-xs">
            {sections.map((s) => (
              <li
                key={s.section_id}
                aria-current={s.section_id === section.section_id ? "step" : undefined}
                className={cn("whitespace-nowrap rounded-full px-2 py-0.5", s.section_id === section.section_id ? "bg-brand-subtle text-brand-on-subtle" : "text-fg-muted")}
              >
                {isClosedSection(s) ? "✓ " : !free && s.status === "not_started" ? "🔒 " : ""}
                {s.title}
                {!free && s.status === "not_started" ? <span className="sr-only"> (opens after you submit {section.title})</span> : null}
              </li>
            ))}
          </ol>
        ) : null}
        {/* Reconnect banner slot (non-dismissible while offline) */}
        {showOffline ? (
          <div role="status" className="border-l-4 border-warning-border bg-warning-subtle px-4 py-2 text-sm text-warning-fg">
            <span aria-hidden="true">⚠ </span>
            You&apos;re offline. Keep answering — your answers are saved on this device and will sync when you&apos;re back online. The timer keeps running on
            our server.
          </div>
        ) : backOnline !== null ? (
          <div role="status" className="border-l-4 border-success-border bg-success-subtle px-4 py-2 text-sm text-success-fg">
            <span aria-hidden="true">✓ </span>Back online. {backOnline} answer{backOnline === 1 ? "" : "s"} synced.
          </div>
        ) : null}
        {payload.protocol?.exam_mode && (integrity?.total ?? 0) + localEvents > 0 ? (
          <div role="alert" data-testid="integrity-banner" className="border-l-4 border-danger-border bg-danger-subtle px-4 py-2 text-sm text-danger-fg">
            <span aria-hidden="true">⚠ </span>
            {integrityWarning((integrity?.total ?? 0) + localEvents, !!integrity?.flagged)}
          </div>
        ) : null}
        {payload.protocol?.require_fullscreen && fullscreenOff ? (
          <div role="status" className="flex flex-wrap items-center gap-3 border-l-4 border-warning-border bg-warning-subtle px-4 py-2 text-sm text-warning-fg">
            This exam must be taken in full screen.
            {typeof document !== "undefined" && document.documentElement.requestFullscreen ? (
              <Button size="sm" variant="secondary" onClick={() => void document.documentElement.requestFullscreen().catch(() => undefined)}>
                Return to full screen
              </Button>
            ) : null}
          </div>
        ) : null}
        {otherTabOpen ? (
          <div role="status" className="border-l-4 border-info-border bg-info-subtle px-4 py-2 text-sm text-info-fg">
            This test is already open in another tab. Answers from both tabs are saved — answer in one tab to avoid confusion.
          </div>
        ) : null}
      </header>

      <div className="mx-auto flex max-w-wide gap-6 px-4 py-6 pb-24 lg:pb-6">
        <section aria-label="Question" className="min-w-0 flex-1">
          {rejected[question.question_version_id] ? (
            <p role="alert" className="mb-4 rounded-lg border border-danger-border bg-danger-subtle p-3 text-sm font-semibold text-danger-fg">
              Your answer to this question was not saved: {rejected[question.question_version_id]}. Please correct it.
            </p>
          ) : null}
          <QuestionView
            key={question.question_version_id}
            number={index + 1}
            question={question}
            attemptId={attemptId}
            tracker={tracker}
            response={answer?.response ?? null}
            flagged={!!answer?.flagged}
            disabled={phase === "expired"}
            onChange={(r: QuestionResponse | null) => update(question.question_version_id, { response: r })}
            onToggleFlag={(f) => update(question.question_version_id, { flagged: f })}
          />
          <div
            data-testid="runner-actions"
            className="fixed inset-x-0 bottom-0 z-sticky flex flex-wrap items-center justify-between gap-2 border-t border-line bg-surface p-3 lg:static lg:mt-8 lg:border-0 lg:bg-transparent lg:p-0"
          >
            <Button
              variant="ghost"
              className="px-2 sm:px-4"
              onClick={() => update(question.question_version_id, { response: null })}
              disabled={!isAnswered(answer?.response) || phase === "expired"}
            >
              Clear response
            </Button>
            <div className="ml-auto flex gap-2">
              <Button
                variant="secondary"
                className="px-3 sm:px-4"
                aria-label="Previous question"
                onClick={() => setIndex((i) => Math.max(0, i - 1))}
                disabled={index === 0 || phase === "expired"}
              >
                ←<span className="hidden sm:inline"> Previous</span>
              </Button>
              <Button
                className="px-3 sm:px-4"
                aria-label="Save and go to the next question"
                onClick={() => {
                  void queueRef.current?.flush();
                  setIndex((i) => Math.min(questions.length - 1, i + 1));
                }}
                disabled={index >= questions.length - 1 || phase === "expired"}
              >
                Save<span className="hidden sm:inline"> &amp; next</span> →
              </Button>
            </div>
          </div>
        </section>
        <aside aria-label="Question palette" className="hidden w-palette-panel shrink-0 lg:block">
          {palette}
        </aside>
      </div>

      <Dialog open={paletteOpen} onClose={() => setPaletteOpen(false)} title={free || sections.length <= 1 ? "Questions" : `Questions — ${section.title}`}>
        {palette}
      </Dialog>

      {/* TST-004 resume */}
      <Dialog
        open={resumeNotice !== null && phase === "ready"}
        onClose={() => setResumeNotice(null)}
        title="Welcome back — your test is safe"
        footer={<Button onClick={() => setResumeNotice(null)}>Resume test</Button>}
      >
        {resumeNotice ? (
          <div className="space-y-2 text-sm text-fg-secondary">
            <p>
              We&apos;ve restored {resumeNotice.restored} answers. The timer kept running on our server, so you have{" "}
              <strong className="font-mono">{remainingNow === null ? "—" : formatCountdown(remainingNow)}</strong> left.
            </p>
            {resumeNotice.pending > 0 ? (
              <p role="status">
                {snap.pendingCount > 0
                  ? `⟳ ${resumeNotice.pending} answers saved on this device are being synced…`
                  : "✓ All answers synced."}
              </p>
            ) : null}
            {resumeNotice.conflicts > 0 ? (
              <p>We kept your most recent answer for {resumeNotice.conflicts} question(s) you changed on another device.</p>
            ) : null}
          </div>
        ) : null}
      </Dialog>

      {/* TST-003 submit confirmation (Esc = cancel; guards data loss) */}
      <Dialog
        open={confirmOpen}
        onClose={() => !submitting && setConfirmOpen(false)}
        dismissible={!submitting}
        title={isLastSection ? "Submit test?" : `Submit ${section.title}?`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmOpen(false)} disabled={submitting}>
              Back to test
            </Button>
            <Button onClick={() => void submit()} loading={submitting}>
              {isLastSection ? "Submit test" : "Submit section"}
            </Button>
          </>
        }
      >
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-fg-muted">Answered</dt>
          <dd className="tabular-nums">{Math.max(0, counts.answered + counts.answered_marked - rejectedCount)}</dd>
          <dt className="text-fg-muted">Not answered</dt>
          <dd className="tabular-nums">{counts.not_answered}</dd>
          <dt className="text-fg-muted">Marked for review</dt>
          <dd className="tabular-nums">{counts.marked + counts.answered_marked}</dd>
          <dt className="text-fg-muted">Not visited</dt>
          <dd className="tabular-nums">{counts.not_visited}</dd>
          <dt className="text-fg-muted">Time left</dt>
          <dd className="font-mono tabular-nums">{remainingNow === null ? "—" : formatCountdown(remainingNow)}</dd>
        </dl>
        {rejectedCount > 0 ? (
          <p role="alert" className="mt-3 border-l-4 border-danger-border bg-danger-subtle p-2 text-sm text-danger-fg">
            {rejectedCount} answer{rejectedCount === 1 ? " was" : "s were"} not saved because {rejectedCount === 1 ? "it is" : "they are"} not valid for the question, and will
            count as not answered. Go back to correct {rejectedCount === 1 ? "it" : "them"}.
          </p>
        ) : null}
        {unanswered > 0 ? (
          <p className="mt-3 border-l-4 border-warning-border bg-warning-subtle p-2 text-sm text-warning-fg">
            {unanswered} question{unanswered === 1 ? " is" : "s are"} not answered.
          </p>
        ) : null}
        {!isLastSection ? <p className="mt-3 text-sm text-fg-secondary">You can&apos;t return to this section.</p> : null}
        {snap.pendingCount > 0 ? <p className="mt-3 text-sm text-fg-muted">Unsynced answers are sent with your submission.</p> : null}
        {submitError ? <div className="mt-3"><ErrorState error={submitError} /></div> : null}
      </Dialog>

      <Dialog
        open={leaveOpen}
        onClose={() => setLeaveOpen(false)}
        title="Leave the test?"
        description="Your answers are saved, but the timer keeps running on our server while you're away."
        footer={
          <>
            <Button variant="secondary" onClick={() => setLeaveOpen(false)}>
              Stay in test
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                void queueRef.current?.flush();
                router.push("/app/tests");
              }}
            >
              Leave test
            </Button>
          </>
        }
      />

      {/* FE-20: a real modal (native showModal → inert background, focus trapped), not dismissible. */}
      <Dialog
        open={phase === "expired"}
        onClose={() => undefined}
        dismissible={false}
        title="Time's up"
        description="We're submitting the answers we received. This takes a few seconds."
      >
        <p role="alert" className="sr-only">
          Time&apos;s up. Submitting your answers.
        </p>
      </Dialog>
    </FocusShell>
  );
}

/**
 * Focus shell: full-viewport layer over the portal chrome (design-system §4, no global nav).
 * The chrome underneath is made `inert` (FE-20) so Tab cannot reach the portal nav; live regions
 * (toasts) are left alone so announcements still work.
 */
function FocusShell({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    return el ? inertOutside(el) : undefined;
  }, []);
  return (
    <div ref={ref} data-focus-shell="" className="fixed inset-0 z-overlay overflow-y-auto bg-surface-canvas text-fg">
      {children}
    </div>
  );
}

/** Marks every element outside `el` (siblings of it and of each ancestor) inert; returns the undo. */
export function inertOutside(el: HTMLElement): () => void {
  const changed: HTMLElement[] = [];
  let node: HTMLElement | null = el;
  while (node && node.parentElement && node !== document.body) {
    for (const sib of Array.from(node.parentElement.children)) {
      if (sib === node || !(sib instanceof HTMLElement) || sib.hasAttribute("inert")) continue;
      if (sib.matches("script, style, dialog, [aria-live]") || sib.querySelector("[aria-live]")) continue;
      sib.setAttribute("inert", "");
      changed.push(sib);
    }
    node = node.parentElement;
  }
  return () => {
    for (const s of changed) s.removeAttribute("inert");
  };
}
