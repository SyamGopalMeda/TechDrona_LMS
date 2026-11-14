"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Button, Card, Checkbox, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { uuid7 } from "@/lib/ids/uuid7";
import { assessmentApi } from "../lib/api";
import { formatDuration, formatIstDateTime } from "../lib/format";
import { useLoader } from "../lib/use-resource";
import { INTEGRITY_FLAG_KEY } from "./AttemptRunner";

const DISABLED_REASON: Record<string, string> = {
  test_not_open: "This test hasn't opened yet.",
  test_window_closed: "The window for this test has closed.",
  attempt_limit_reached: "You've used all your attempts for this test.",
  contact_not_verified: "Verify your email or mobile number before starting a timed test.",
};

/** TST-001 Instructions & system check (ASM-02, ATT-01). */
export function TestInstructions({ testId }: { testId: string }) {
  const router = useRouter();
  const rtt = useRef<number | null>(null);
  const res = useLoader(testId, async () => {
    const t0 = performance.now();
    const d = await assessmentApi.getTest(testId);
    rtt.current = Math.round(performance.now() - t0);
    return d;
  });
  const [read, setRead] = useState(false);
  const [consent, setConsent] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const startKey = useRef<string | null>(null);

  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (!res.data)
    return (
      <div aria-busy="true" className="space-y-4">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );

  const t = res.data;
  const protocol = t.protocol;
  const examMode = !!protocol?.exam_mode;
  const needsAgreement = !!protocol?.require_agreement;
  // Advisory integrity events are always offered; they're recorded only with consent (ATT-06).
  // In exam mode, agreeing to the conduct instructions (which list what is recorded) is the consent.
  const integrity = !examMode;
  const consentRequired = !!t.integrity_notice?.settings?.consent_mandatory;
  const browserOk = typeof window !== "undefined" && "fetch" in window && "localStorage" in window;
  // ASM-02 only reports access (403 otherwise); window/attempt limits are derived from its fields
  // and enforced again by ATT-01.
  const now = Date.parse(t.server_now);
  const notOpen = !!t.window?.available_from && now < Date.parse(t.window.available_from);
  const closed = !!t.window?.available_until && now >= Date.parse(t.window.available_until) + (t.window.window_extension_seconds ?? 0) * 1000;
  const reason = notOpen ? "test_not_open" : closed ? "test_window_closed" : t.attempts_left === 0 ? "attempt_limit_reached" : null;
  const canStart = t.eligibility?.eligible !== false && reason === null;
  const blockedReason = !canStart ? (reason ? DISABLED_REASON[reason] : "You can't start this test right now.") : null;
  const ready = read && canStart && (examMode || !consentRequired || consent) && (!needsAgreement || agreed);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    startKey.current ??= uuid7();
    if (protocol?.require_fullscreen && typeof document !== "undefined" && !document.fullscreenElement) {
      // Same click (user gesture): enter full screen before the timer starts.
      await document.documentElement.requestFullscreen?.().catch(() => undefined);
    }
    try {
      const a = await assessmentApi.start(
        {
          test_id: t.id,
          test_assignment_id: t.eligibility?.test_assignment_id ?? null,
          integrity_consent: integrity && consent,
          ...(needsAgreement ? { instructions_agreed: agreed } : {}),
        },
        startKey.current,
      );
      try {
        if (integrity && consent) window.localStorage.setItem(INTEGRITY_FLAG_KEY(a.attempt_id), "1");
      } catch {
        /* ignore */
      }
      router.push(`/app/attempts/${encodeURIComponent(a.attempt_id)}`);
    } catch (e) {
      if (isApiError(e) && e.code === "active_attempt_exists" && typeof e.problem?.attempt_id === "string") {
        router.push(`/app/attempts/${encodeURIComponent(e.problem.attempt_id)}`);
        return;
      }
      startKey.current = null;
      setStartError(e);
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="max-w-content">
      <PageHeader
        breadcrumbs={[{ label: "Tests", href: "/app/tests" }, { label: t.title }]}
        title={t.title}
        description={`${formatDuration(t.duration_seconds)} · ${t.sections.length} section${t.sections.length === 1 ? "" : "s"}`}
      />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title="Pattern and marking">
          <table className="w-full text-sm">
            <caption className="sr-only">Sections</caption>
            <thead className="text-left text-xs uppercase text-fg-muted">
              <tr>
                <th scope="col" className="py-1">Section</th>
                <th scope="col" className="py-1 text-right">Questions</th>
                <th scope="col" className="py-1 text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              {t.sections.map((s, i) => (
                <tr key={s.section_id ?? i} className="border-t border-line">
                  <td className="py-2">{s.title}</td>
                  <td className="py-2 text-right tabular-nums">{s.question_count ?? "—"}</td>
                  <td className="py-2 text-right tabular-nums">{s.duration_seconds ? formatDuration(s.duration_seconds) : "Shared"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-sm text-fg-secondary">
            Navigation:{" "}
            {t.navigation_mode === "free"
              ? "move freely between questions and sections."
              : "sections in order; you can't return to a section after you submit it."}
          </p>
          {t.marking ? <p className="mt-1 text-sm text-fg-secondary">Marking: {t.marking}</p> : null}
          {t.window?.available_until ? <p className="mt-1 text-sm text-fg-secondary">Window closes {formatIstDateTime(t.window.available_until)}.</p> : null}
          {t.sections.some((s) => s.instructions_md) ? (
            <div className="mt-4 space-y-2 text-sm text-fg">
              {t.sections
                .filter((s) => s.instructions_md)
                .map((s) => (
                  <p key={s.section_id} className="whitespace-pre-line">
                    {t.sections.length > 1 ? <strong>{s.title}: </strong> : null}
                    {s.instructions_md}
                  </p>
                ))}
            </div>
          ) : null}
        </Card>
        <Card title="System check">
          <ul className="space-y-2 text-sm">
            <li>{browserOk ? "✓ Browser supported" : "✕ Please use a recent Chrome, Edge, Firefox or Safari"}</li>
            <li>{rtt.current !== null ? `✓ Connection working (${rtt.current} ms)` : "○ Checking connection…"}</li>
            <li className="flex flex-wrap items-center gap-2">
              {fullscreen ? "✓ Full screen" : "○ Full screen (recommended)"}
              {!fullscreen && typeof document !== "undefined" && document.documentElement.requestFullscreen ? (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    void document.documentElement
                      .requestFullscreen()
                      .then(() => setFullscreen(true))
                      .catch(() => setFullscreen(false))
                  }
                >
                  Enter full screen
                </Button>
              ) : null}
            </li>
          </ul>
          {integrity ? (
            <p className="mt-4 rounded-md border-l-4 border-info-border bg-info-subtle p-3 text-sm text-info-fg">
              {t.integrity_notice?.text ||
                "We record events like leaving full screen or switching tabs. They're reviewed by a person and never penalise you automatically."}
            </p>
          ) : null}
        </Card>
      </div>

      {needsAgreement && protocol ? (
        <Card title="Exam conduct" className="mt-4">
          {protocol.conduct_instructions ? <p className="whitespace-pre-line text-sm text-fg">{protocol.conduct_instructions}</p> : null}
          {protocol.record_events.length ? (
            <div className="mt-3 text-sm">
              <p className="font-medium text-fg">Recorded during the exam and shared with your evaluators:</p>
              <ul className="mt-1 flex flex-wrap gap-2" aria-label="Recorded events">
                {protocol.record_events.map((e) => (
                  <li key={e} className="rounded-full border border-line px-2 py-0.5 text-xs text-fg-secondary">
                    {protocol.labels?.[e] ?? e}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-fg-secondary">
            <li>Your {formatDuration(t.duration_seconds)} timer starts when you agree and start; it can&apos;t be paused.</li>
            <li>Answers are submitted automatically when time runs out{t.window?.available_until ? " or the exam window closes, whichever is first" : ""}.</li>
            {protocol.require_fullscreen ? <li>The exam runs in full screen.</li> : null}
            {protocol.auto_submit_after ? <li>After {protocol.auto_submit_after} recorded events your exam is submitted automatically.</li> : null}
            <li>Recorded events are reviewed by a person; they never change your marks automatically.</li>
          </ul>
        </Card>
      ) : null}

      <div className="mt-6 space-y-3">
        <Checkbox label="I've read the instructions" checked={read} onChange={(e) => setRead(e.target.checked)} />
        {needsAgreement ? (
          <Checkbox label="I agree to the exam conduct instructions (required)" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        ) : null}
        {integrity ? (
          <Checkbox
            label={consentRequired ? "I agree to integrity events being recorded for this test (required)" : "I agree to integrity events being recorded for this test"}
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
        ) : null}
        {blockedReason ? <p className="text-sm text-fg-secondary">{blockedReason}</p> : null}
        {startError ? <ErrorState error={startError} /> : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button size="lg" onClick={() => void start()} disabled={!ready} loading={starting}>
            {needsAgreement ? "Agree and start exam" : "Start test"}
          </Button>
          <Link href="/app/tests" className="text-sm text-fg-link underline">
            Back to tests
          </Link>
        </div>
        {!ready && canStart ? (
          <p className="text-xs text-fg-muted">
            Confirm you&apos;ve read the instructions{needsAgreement ? " and agree to the exam conduct" : consentRequired ? " and the integrity notice" : ""} to start.
          </p>
        ) : null}
      </div>
    </div>
  );
}
