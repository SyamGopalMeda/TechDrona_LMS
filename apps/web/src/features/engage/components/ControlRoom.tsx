"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, StatTile, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { plural, settingsSummary, TYPE_LABEL } from "../lib/labels";
import { usePoll } from "../lib/use-poll";
import type { Activity, ControlAction, InviteResult, PresenterState, RunSummary } from "../lib/types";
import { QrCode } from "./QrCode";
import { errorText, Loading, QuestionHeading, QuestionResults, StatusBadge, useJoinUrl } from "./parts";
import { useEngageScope } from "../lib/scope";

export const linkBtn =
  "inline-flex h-8 items-center justify-center rounded-md px-3 text-sm font-medium focus-visible:outline-none focus-visible:shadow-focus";

/** Run control helper shared by the control room and the big screen. */
export function useRunControl(onDone: () => void | Promise<void>) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const control = async (runId: string, action: ControlAction, position?: number) => {
    setBusy(action);
    try {
      await api.post<RunSummary>(`engage/runs/${seg(runId)}/control`, position === undefined ? { action } : { action, position });
      await onDone();
    } catch (err) {
      // SEC-06: results (answer keys) can only be published once the run is closed.
      if (action === "publish" && isApiError(err) && err.status === 409) {
        toast.show({ title: "Close the activity first", description: "Results can be published only after the activity has closed.", tone: "danger" });
      } else toast.show({ ...errorText(err, "That didn't work"), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };
  return { busy, control };
}

/** Whether the shown question(s) are revealed. */
export function isRevealed(run: RunSummary, position: number): boolean {
  if (run.settings.pacing === "one_by_one") return run.revealed_positions.includes(position);
  return run.question_count > 0 && run.revealed_positions.length >= run.question_count;
}

function ShareCard({ run }: { run: RunSummary }) {
  const { base } = useEngageScope();
  const toast = useToast();
  const url = useJoinUrl(run.join_path);
  const [sending, setSending] = useState(false);
  const live = run.status === "scheduled" || run.status === "open";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast.show({ title: "Link copied", tone: "success" });
    } catch {
      toast.show({ title: "Couldn't copy — select the link and copy it", tone: "warning" });
    }
  };
  const email = async () => {
    setSending(true);
    try {
      const res = await api.post<InviteResult>(`engage/runs/${seg(run.id)}/invite`);
      if (res.kind === "ok") toast.show({ title: `Invitation sent to ${res.data.recipients} ${res.data.recipients === 1 ? "person" : "people"}`, tone: "success" });
    } catch (err) {
      toast.show({ ...errorText(err, "Couldn't send invitations"), tone: "danger" });
    } finally {
      setSending(false);
    }
  };
  return (
    <Card title="Share to join">
      <div className="flex flex-col gap-4 sm:flex-row lg:flex-col">
        <div className="w-40 shrink-0 self-center">{url ? <QrCode value={url} label={`QR code to join: ${url}`} /> : null}</div>
        <div className="min-w-0 flex-1 space-y-3">
          <p className="text-sm text-fg-secondary">
            Code <span className="font-mono text-lg font-bold tracking-widest text-fg">{run.join_code}</span>
          </p>
          <p className="break-all rounded-md bg-surface-sunken px-2 py-1 font-mono text-xs text-fg" aria-label="Join link">
            {url}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => void copy()} disabled={!url}>
              Copy
            </Button>
            <Button size="sm" variant="secondary" onClick={() => void email()} loading={sending} disabled={!live}>
              Email
            </Button>
            <a href={`${base}/runs/${seg(run.id)}/present`} target="_blank" rel="noopener" className={cn(linkBtn, "bg-brand text-brand-on hover:bg-brand-hover")}>
              Present on big screen
            </a>
          </div>
        </div>
      </div>
    </Card>
  );
}

function RunPanel({ run, onChanged }: { run: RunSummary; onChanged: () => Promise<void> }) {
  const { base } = useEngageScope();
  const poll = usePoll<PresenterState>(`engage/runs/${seg(run.id)}/presenter`, { done: (d) => d.run.status === "finalised" });
  const state = poll.data;
  const live = state?.run ?? run;
  const { busy, control } = useRunControl(async () => {
    await Promise.all([poll.refresh(), onChanged()]);
  });
  const [view, setView] = useState(0);
  const oneByOne = live.settings.pacing === "one_by_one";
  const n = live.question_count;
  const pos = oneByOne ? live.current_position : Math.min(view, Math.max(0, n - 1));
  const question = state?.questions.find((q) => q.position === pos);
  const revealed = isRevealed(live, pos);
  const finalised = live.status === "finalised";

  const go = (p: number) => {
    if (p < 0 || p >= n) return;
    if (oneByOne) void control(live.id, "goto", p);
    else setView(p);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-6">
        <Card title={`Run ${live.run_no}`} actions={<StatusBadge status={live.status} />}>
          <div className="flex flex-wrap gap-2">
            {live.status === "scheduled" ? (
              <Button onClick={() => void control(live.id, "start")} loading={busy === "start"}>
                ▶ Start
              </Button>
            ) : null}
            {live.status === "scheduled" || live.status === "open" ? (
              <Button variant="secondary" onClick={() => void control(live.id, "close")} loading={busy === "close"}>
                Close
              </Button>
            ) : null}
            {!finalised ? (
              <Button variant="secondary" onClick={() => void control(live.id, "finalise")} loading={busy === "finalise"}>
                ✓ Finalise
              </Button>
            ) : null}
            <Button
              variant="secondary"
              onClick={() => void control(live.id, live.results_published ? "unpublish" : "publish")}
              loading={busy === "publish" || busy === "unpublish"}
            >
              {live.results_published ? "Unpublish results" : "Publish results"}
            </Button>
            <Link href={`${base}/runs/${seg(live.id)}/results`} className={cn(linkBtn, "border border-line-control bg-surface text-fg hover:bg-surface-hover")}>
              Results
            </Link>
          </div>
          {live.status === "scheduled" ? (
            <p className="mt-3 text-sm text-fg-muted">
              {live.settings.run_mode === "scheduled" && live.opens_at
                ? `Opens automatically at ${new Date(live.opens_at).toLocaleString()}. People can join now.`
                : "Waiting room: people can join now and answer once you start."}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-fg-muted">{live.results_published ? "Results are published to participants." : "Results are not published yet."}</p>
        </Card>

        <div className="grid grid-cols-3 gap-3" aria-live="polite">
          <StatTile label="Joined" value={state ? state.joined : null} />
          <StatTile label="Voted" value={state ? state.voted : null} />
          <StatTile label="Total votes" value={state ? state.total_votes : null} />
        </div>

        <Card
          title="Shared screen"
          actions={
            <nav aria-label="Question pager" className="flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={() => go(pos - 1)} disabled={pos <= 0 || (oneByOne && finalised) || busy !== null} aria-label="Previous question">
                ‹
              </Button>
              <span className="text-sm tabular-nums text-fg-secondary">
                Q{n ? pos + 1 : 0}/{n}
              </span>
              <Button size="sm" variant="ghost" onClick={() => go(pos + 1)} disabled={pos >= n - 1 || (oneByOne && finalised) || busy !== null} aria-label="Next question">
                ›
              </Button>
            </nav>
          }
        >
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={revealed ? "secondary" : "primary"}
              onClick={() => void control(live.id, revealed ? "hide" : "reveal")}
              loading={busy === "reveal" || busy === "hide"}
            >
              {revealed ? "Hide answers" : oneByOne ? "Reveal answers" : "Reveal all answers"}
            </Button>
            <span className="text-sm text-fg-muted">{revealed ? "Answers are shown to the room." : "Question shown — answers hidden."}</span>
          </div>
          {poll.error && !state ? (
            <ErrorState error={poll.error} onRetry={() => void poll.refresh()} />
          ) : !question ? (
            <Loading label="Loading live results" rows={2} />
          ) : (
            <div>
              <QuestionHeading question={question} total={n}>
                <Badge>{plural(question.answered, "response")}</Badge>
              </QuestionHeading>
              <QuestionResults question={question} showCorrect={revealed} texts={question.texts} winner={question.winner} />
            </div>
          )}
        </Card>
      </div>
      <div className="space-y-6">
        <ShareCard run={live} />
        {state && state.participants.length ? (
          <Card title="Recently joined">
            <ul className="flex flex-wrap gap-1.5">
              {state.participants.slice(-20).map((p) => (
                <li key={p.seq}>
                  <Badge>{p.label}</Badge>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

/** TRN-020 Engage control room for one activity. */
export function ControlRoom({ activityId }: { activityId: string }) {
  const { base } = useEngageScope();
  const toast = useToast();
  const detail = useApi<Activity>(`engage/activities/${seg(activityId)}`);
  const [selected, setSelected] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  if (detail.loading && !detail.data) return <Loading label="Loading activity" />;
  if (detail.error || !detail.data) return <ErrorState error={detail.error} onRetry={() => void detail.reload()} />;
  const a = detail.data;
  const runs = a.runs ?? [];
  const current = runs[0];
  const run = runs.find((r) => r.id === selected) ?? current;

  const launch = async () => {
    setLaunching(true);
    try {
      const res = await api.post<RunSummary>(`engage/activities/${seg(a.id)}/runs`, {}, { idempotencyKey: true });
      if (res.kind === "ok") {
        setSelected(res.data.id);
        toast.show({ title: `Run ${res.data.run_no} is ready — share the code ${res.data.join_code}`, tone: "success" });
      }
      await detail.reload();
    } catch (err) {
      toast.show({ ...errorText(err, "Couldn't launch"), tone: "danger" });
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href={base} className="text-sm text-fg-link hover:text-fg-link-hover">
            ← Engage
          </Link>
          <h1 className="mt-1 break-words font-display text-2xl font-bold text-fg">{a.title}</h1>
          <p className="mt-1 text-sm text-fg-muted">
            {TYPE_LABEL[a.activity_type]} · {plural(a.question_count, "question")} · {settingsSummary(a)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {run ? <StatusBadge status={run.status} /> : null}
          <Link href={`${base}/${seg(a.id)}/edit`} className={cn(linkBtn, "border border-line-control bg-surface text-fg hover:bg-surface-hover")}>
            Edit
          </Link>
          <Button size="sm" onClick={() => void launch()} loading={launching} disabled={a.question_count === 0}>
            {current ? "Rerun" : "Launch"}
          </Button>
        </div>
      </div>

      {runs.length ? (
        <nav aria-label="Runs" className="flex flex-wrap gap-2">
          {runs.map((r, i) => (
            <button
              key={r.id}
              type="button"
              aria-pressed={r.id === run?.id}
              onClick={() => setSelected(r.id)}
              className={cn(
                "rounded-full border px-3 py-1 text-sm focus-visible:outline-none focus-visible:shadow-focus",
                r.id === run?.id ? "border-brand bg-brand-subtle text-brand-on-subtle" : "border-line bg-surface text-fg-secondary hover:bg-surface-hover",
              )}
            >
              Run {r.run_no}
              {i === 0 ? " · current" : ""}
            </button>
          ))}
        </nav>
      ) : null}

      {run ? (
        <RunPanel key={run.id} run={run} onChanged={detail.reload} />
      ) : (
        <EmptyState
          title="Not launched yet"
          description={
            a.question_count === 0
              ? "Add at least one question before launching."
              : "Launch to get a join code and QR code. People can join while you wait, and answer once you start."
          }
          action={
            <Button onClick={() => void launch()} loading={launching} disabled={a.question_count === 0}>
              Launch
            </Button>
          }
        />
      )}
    </div>
  );
}
