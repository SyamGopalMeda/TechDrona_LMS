"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Button, EmptyState, ErrorState, LinkButton, PageHeader } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { Boundary, LoadingBlock, useFailToast } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { pathsApi, seg } from "../lib/api";
import { embeddableUrl, safeHttpsUrl } from "../lib/embed";
import { formatHours, formatPlanDate } from "../lib/pace";
import type { MyPath, PlayerPath, PlayerStep } from "../lib/types";
import { ArticleView, useReaderArticle } from "./ArticleReader";
import { FlowBadge, OrderBadge, ProgressBar, ProgressRing, STEP_TYPE_LABEL, StepStateBadge } from "./bits";
import type { StepType } from "../lib/types";
import { useEnabledApps } from "@/features/ai";

const PLAYER_BASE = "/app/path/my";

/* 16px stroke icons for the learner's step list (the shared emoji glyphs render differently per OS). */
const STEP_ICON_PATHS: Record<StepType, string> = {
  reading: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zm0 0v5h5M9 13h6M9 17h4",
  video: "M5 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L6.5 3.64A1 1 0 0 0 5 4.5z",
  article: "M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5zM13 4h5.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H13z",
  assignment: "M4 20h4L19 9l-4-4L4 16zm9-13 4 4",
  assessment: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm-4-9 3 3 5-6",
  super_step: "M4 6h16M4 12h16M4 18h16",
};

/** Step type icon with an accessible name (inline SVG, inherits the text colour). */
export function StepIcon({ type, className }: { type: StepType; className?: string }) {
  return (
    <svg role="img" aria-label={STEP_TYPE_LABEL[type]} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className ?? "h-4 w-4 shrink-0 text-fg-secondary"}>
      <title>{STEP_TYPE_LABEL[type]}</title>
      <path d={STEP_ICON_PATHS[type]} />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg role="img" aria-label="Locked" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="ml-auto h-4 w-4 shrink-0 text-fg-muted">
      <title>Locked</title>
      <path d="M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z" />
    </svg>
  );
}

/* ------------------------------------------------------------------ My paths */

export function MyPaths() {
  const state = useApi<{ data: MyPath[] }>("me/paths");
  const enabled = useEnabledApps();
  if (!enabled.isEnabled("paths")) {
    return <EmptyState icon="lock" title="Paths are not available" description="Learning paths are turned off." />;
  }
  return (
    <Boundary state={state}>
      {(d) =>
        d.data.length === 0 ? (
          <EmptyState
            icon="book"
            title="No paths yet"
            description="Learning paths assigned to you or your batch will appear here."
            action={
              <LinkButton href="/app/learning" variant="secondary" size="sm">
                Go to My learning
              </LinkButton>
            }
          />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2">
            {d.data.map((p) => (
              <li key={p.allocation_id} className="flex flex-col rounded-xl border border-line bg-surface p-4 shadow-xs">
                <div className="flex flex-wrap gap-2">
                  <FlowBadge flow={p.flow} />
                  {p.sequential ? <OrderBadge sequential /> : null}
                </div>
                <h2 className="mt-2 font-display text-base font-bold text-fg-heading">{p.title}</h2>
                <p className="text-sm text-fg-muted">
                  {p.step_count} steps · {p.total_credits} credits · {formatHours(p.total_hours)}
                </p>
                {p.finish_date ? <p className="text-xs text-fg-muted">Planned finish {formatPlanDate(p.finish_date)}</p> : null}
                <div className="mt-3 flex items-center gap-2 text-sm">
                  <span className="tabular-nums">
                    {p.completed_count}/{p.step_count} done
                  </span>
                  <span className="ml-auto tabular-nums">{Math.round(p.pct)}%</span>
                </div>
                <ProgressBar pct={p.pct} label={`${p.title} progress`} />
                <div className="mt-4">
                  <LinkButton href={`${PLAYER_BASE}/${encodeURIComponent(p.allocation_id)}`} variant={p.started ? "primary" : "secondary"}>
                    {p.started ? "Continue →" : "Start →"}
                    <span className="sr-only"> {p.title}</span>
                  </LinkButton>
                </div>
              </li>
            ))}
          </ul>
        )
      }
    </Boundary>
  );
}

/* ------------------------------------------------------------------ Player */

export function firstActionable(steps: PlayerStep[]): PlayerStep | undefined {
  const leaves = steps.filter((s) => s.step_type !== "super_step");
  return leaves.find((s) => s.state === "in_progress") ?? leaves.find((s) => s.state === "available") ?? leaves[0];
}

export function StepRail({ steps, selected, onSelect }: { steps: PlayerStep[]; selected: string | null; onSelect: (s: PlayerStep) => void }) {
  return (
    <nav aria-label="Path steps">
      <ol className="space-y-1">
        {steps.map((s) => {
          const filled = s.state === "completed" || s.state === "in_progress";
          const isGroup = s.step_type === "super_step";
          return (
            <li key={s.step_key} className={s.depth ? "pl-5" : undefined}>
              <button
                type="button"
                onClick={() => onSelect(s)}
                aria-current={selected === s.step_key ? "step" : undefined}
                data-state={s.state}
                className={`flex w-full items-start gap-2 rounded-lg border p-2 text-left text-sm focus-visible:shadow-focus focus-visible:outline-none ${
                  selected === s.step_key ? "border-brand bg-brand-subtle" : "border-transparent hover:bg-surface-hover"
                } ${s.state === "locked" ? "opacity-60" : ""}`}
              >
                <span
                  aria-hidden="true"
                  className={`flex h-7 min-w-7 shrink-0 items-center justify-center rounded-full border px-1 text-xs font-semibold tabular-nums ${
                    filled ? (s.state === "completed" ? "border-success-border bg-success-solid text-success-on-solid" : "border-brand bg-brand text-brand-on") : "border-line-strong"
                  }`}
                >
                  {s.state === "completed" ? "✓" : s.number}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-start gap-1.5 [&>svg]:mt-0.5">
                    <StepIcon type={s.step_type} />
                    <span className={`line-clamp-2 ${isGroup ? "font-semibold" : ""}`} title={s.title}>
                      {s.title}
                    </span>
                    {s.state === "locked" ? <LockIcon /> : null}
                  </span>
                  {!isGroup ? (
                    <span className="mt-0.5 block text-xs text-fg-muted">
                      {s.credits} credits · {formatHours(s.est_hours)}
                    </span>
                  ) : null}
                  <span className="sr-only">
                    {" "}
                    Step {s.number}, {s.state.replace("_", " ")}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function PathPlayer({ allocationId }: { allocationId: string }) {
  const state = useApi<PlayerPath>(`me/paths/${seg(allocationId)}`);
  if (state.error) {
    if (isApiError(state.error) && state.error.status === 404) {
      return (
        <EmptyState
          icon="search"
          title="Path not found"
          description="This path is no longer assigned to you."
          action={
            <LinkButton href={PLAYER_BASE} variant="secondary" size="sm">
              Back to My paths
            </LinkButton>
          }
        />
      );
    }
    return <ErrorState error={state.error} onRetry={() => void state.reload()} />;
  }
  if (!state.data) return <LoadingBlock rows={6} label="Loading path" />;
  return <PlayerBody key={state.data.allocation_id} initial={state.data} reload={state.reload} />;
}

function PlayerBody({ initial, reload }: { initial: PlayerPath; reload: () => Promise<void> }) {
  const [path, setPath] = useState(initial);
  useEffect(() => setPath(initial), [initial]);
  const [selected, setSelected] = useState<string | null>(() => firstActionable(initial.steps)?.step_key ?? null);
  const fail = useFailToast();
  const step = useMemo(() => path.steps.find((s) => s.step_key === selected) ?? null, [path.steps, selected]);

  const replaceStep = useCallback((s: PlayerStep) => {
    setPath((p) => ({ ...p, steps: p.steps.map((x) => (x.step_key === s.step_key ? s : x)) }));
  }, []);

  const select = async (s: PlayerStep) => {
    setSelected(s.step_key);
    if (s.step_type === "super_step" || s.state !== "available") return;
    try {
      replaceStep(await pathsApi.openStep(path.allocation_id, s.step_key));
    } catch (e) {
      if (!(isApiError(e) && e.code === "step_locked")) fail(e);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[{ label: "My paths", href: PLAYER_BASE }, { label: path.title }]}
        title={path.title}
        description={path.description_md || undefined}
        meta={
          <>
            <FlowBadge flow={path.flow} />
            <OrderBadge sequential={path.sequential} />
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-surface p-4 shadow-xs">
        <ProgressRing pct={path.pct} />
        <div className="min-w-0">
          <p className="text-sm">
            <span className="font-display text-2xl font-extrabold tabular-nums text-fg-heading">{path.credits_earned}</span>
            <span className="text-fg-muted"> of {path.total_credits} credits earned</span>
          </p>
          {path.finish_date ? <p className="text-sm text-fg-muted">Planned finish {formatPlanDate(path.finish_date)}</p> : null}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="max-h-[70vh] overflow-y-auto rounded-xl border border-line bg-surface p-2">
          <StepRail steps={path.steps} selected={selected} onSelect={(s) => void select(s)} />
        </div>
        <div>
          {step ? (
            <StepPane
              key={step.step_key}
              allocationId={path.allocation_id}
              step={step}
              onCompleted={(r) => {
                // The server's step states (unlocks) change after a completion, so refetch here
                // instead of offering a manual "Refresh" button.
                replaceStep(r.step);
                setPath((p) => ({ ...p, credits_earned: r.credits_earned, pct: r.pct }));
                void reload();
              }}
            />
          ) : (
            <EmptyState icon="book" title="Pick a step" description="Choose a step from the list to open it." />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * SEC-08 / D9: only allow-listed players and Google viewers are framed (`embeddableUrl`; the CSP
 * frame-src lists the same hosts). `allow-same-origin` is kept because those players need their
 * own cookies/storage and the frame is always a fixed third-party origin, never ours. No
 * allow-top-navigation (cannot redirect this page) and no allow-forms (nothing to submit).
 */
function ExternalFrame({ src, title }: { src: string; title: string }) {
  return (
    <div className="space-y-2">
      <div className="aspect-video w-full overflow-hidden rounded-lg border border-line bg-surface-sunken">
        <iframe
          src={src}
          title={title}
          className="h-full w-full"
          loading="lazy"
          referrerPolicy="strict-origin-when-cross-origin"
          sandbox="allow-scripts allow-same-origin allow-presentation allow-popups"
          allow="fullscreen; encrypted-media; picture-in-picture"
        />
      </div>
    </div>
  );
}

function NewTabLink({ href, embedded }: { href: string; embedded: boolean }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-fg-link underline">
      {embedded ? <>Open in a new tab if it doesn&apos;t load above</> : <>Open in a new tab</>} <span aria-hidden="true">↗</span>
    </a>
  );
}

function InlineArticle({ id }: { id: string }) {
  const state = useReaderArticle(id);
  if (state.error) return <ErrorState error={state.error} onRetry={() => void state.reload()} />;
  if (!state.data) return <LoadingBlock rows={5} label="Loading article" />;
  // Inside a step the step's h2 already names it: the article renders as a section (h3 title).
  return <ArticleView article={state.data} withToc={false} inline />;
}

/**
 * D9: a video/reading step is framed only when the server flagged its saved URL as `embeddable`
 * (WS4 allow-list) AND the client allow-list (kept in sync with the CSP frame-src) agrees.
 * Anything else is shown as an "Open in a new tab" link.
 */
export function stepEmbedUrl(step: Pick<PlayerStep, "step_type" | "url" | "embeddable">): string | null {
  if (step.step_type !== "video" && step.step_type !== "reading") return null;
  return step.embeddable ? embeddableUrl(step.url) : null;
}

export function StepPane({ allocationId, step, onCompleted }: { allocationId: string; step: PlayerStep; onCompleted: (r: { step: PlayerStep; credits_earned: number; pct: number }) => void }) {
  const fail = useFailToast();
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (wait === null || wait <= 0) return;
    const t = setTimeout(() => setWait((w) => (w === null ? null : w - 1)), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const complete = async () => {
    setBusy(true);
    setNote(null);
    try {
      onCompleted(await pathsApi.completeStep(allocationId, step.step_key));
    } catch (e) {
      if (isApiError(e) && e.code === "too_early") {
        const s = Number(e.problem?.retry_after_seconds ?? e.retryAfter ?? 30);
        setWait(Number.isFinite(s) && s > 0 ? Math.ceil(s) : 30);
      } else if (isApiError(e) && (e.code === "step_locked" || e.code === "completion_by_evaluation")) {
        setNote(e.detail);
      } else fail(e);
    } finally {
      setBusy(false);
    }
  };

  const url = safeHttpsUrl(step.url);
  const embed = stepEmbedUrl(step);
  const selfComplete = step.step_type === "reading" || step.step_type === "video" || step.step_type === "article";
  const locked = step.state === "locked";

  let body: ReactNode = null;
  if (locked) {
    body = <p className="rounded-lg bg-surface-sunken p-4 text-sm">Finish the earlier steps first — this path is sequential.</p>;
  } else if (step.step_type === "super_step") {
    body = <p className="text-sm text-fg-muted">This group completes when all of its steps are done.</p>;
  } else if (step.step_type === "video") {
    body = (
      <div className="space-y-2">
        {embed ? <ExternalFrame src={embed} title={step.title} /> : null}
        {url ? <NewTabLink href={url} embedded={!!embed} /> : step.lesson_id ? <Link href="/app/learning" className="text-sm text-fg-link underline">Open the linked lesson in My learning</Link> : null}
      </div>
    );
  } else if (step.step_type === "reading") {
    body = url ? (
      <div className="space-y-2">
        {embed ? <ExternalFrame src={embed} title={step.title} /> : null}
        <NewTabLink href={url} embedded={!!embed} />
      </div>
    ) : step.lesson_id ? (
      <Link href="/app/learning" className="text-sm text-fg-link underline">
        Open the linked lesson in My learning
      </Link>
    ) : null;
  } else if (step.step_type === "article") {
    body = step.article_id ? <InlineArticle id={step.article_id} /> : null;
  } else {
    const href = step.step_type === "assignment" ? (step.assignment_id ? `/app/assignments/${encodeURIComponent(step.assignment_id)}` : null) : step.test_id ? `/app/tests/${encodeURIComponent(step.test_id)}` : null;
    body = (
      <div className="rounded-lg bg-surface-sunken p-4 text-sm">
        <p>
          Open and complete the {step.step_type === "assignment" ? "assignment" : "test"} to progress. Credits release once it is evaluated
          {step.step_type === "assessment" ? " and you pass" : ""}.
        </p>
        {href && step.state !== "completed" ? (
          <LinkButton href={href} className="mt-3">
            {step.step_type === "assignment" ? "Start assignment" : "Open test"}
          </LinkButton>
        ) : null}
      </div>
    );
  }

  return (
    <section aria-labelledby="step-title" className="space-y-4 rounded-xl border border-line bg-surface p-4">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 id="step-title" className="flex items-center gap-2 font-display text-lg font-bold text-fg-heading">
            <StepIcon type={step.step_type} className="h-5 w-5 shrink-0 text-brand" /> {step.title}
          </h2>
          {step.description_md ? <p className="mt-1 text-sm text-fg-muted">{step.description_md}</p> : null}
          {step.due_date ? <p className="mt-1 text-xs text-fg-muted">Due {formatPlanDate(step.due_date)}</p> : null}
        </div>
        <div className="self-start">
          <StepStateBadge state={step.state} />
        </div>
      </header>
      {body}
      {step.step_type !== "super_step" ? (
        <footer className="flex flex-col gap-2 border-t border-line pt-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-fg-muted">
            {step.state === "completed" ? `${step.credits_awarded} credits earned` : `${step.credits} credits on completion`}
          </p>
          {selfComplete && step.state !== "completed" && !locked ? (
            <Button onClick={() => void complete()} loading={busy} disabled={wait !== null && wait > 0}>
              {step.step_type === "video" ? "Mark as watched" : "Mark as read"}
            </Button>
          ) : null}
        </footer>
      ) : null}
      {wait !== null && wait > 0 ? (
        <p role="status" className="text-sm text-fg-secondary">
          Spend a little more time on this step first — you can mark it in {wait}s.
        </p>
      ) : null}
      {note ? (
        <p role="status" className="text-sm text-fg-secondary">
          {note}
        </p>
      ) : null}
    </section>
  );
}
