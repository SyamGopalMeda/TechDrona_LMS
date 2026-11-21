"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Badge, Button, Card, ErrorState, LoadingBlock, PageHeader, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { useScrollDepth } from "@/lib/analytics/scroll-depth";
import { useActivityTracker, type ActivityTrackerHandle } from "@/lib/analytics/use-activity-tracker";
import { formatPercent, humanize } from "@/features/catalog/lib/format";
import { LinkButton } from "@/features/catalog/components/LinkButton";
import { VideoPlayer } from "@/features/player/components/VideoPlayer";
import { lessonHref, useEnrolledCourse } from "../lib/use-course";
import type { CourseOverviewDto, LessonDto, LessonResourceDto, SignedUrlDto } from "../lib/types";
import { LessonStatusIcon } from "./CourseOverview";
import { ContentErrorState } from "./States";
import { useResource } from "@/lib/api/use-resource";

export const LESSON_ROUTE = "/app/learn/[course_slug]/[lesson_id]";
/** Article and PDF lessons complete via LRN-06 (verified: learning/service.py record_article_completion). */
const TEXT_KINDS = new Set(["article", "pdf"]);

function Contents({ course, slug, currentId, landmark = true }: { course: CourseOverviewDto; slug: string; currentId: string; landmark?: boolean }) {
  // E2E-08: on mobile the landmark wraps the collapsible <details>, so the list itself is not a second nav.
  const Wrap = landmark ? "nav" : "div";
  return (
    <Wrap aria-label={landmark ? "Course contents" : undefined}>
      <ol className="space-y-4">
        {course.modules.map((m) => (
          <li key={m.id}>
            <p className="px-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">{m.title}</p>
            <ul className="mt-1">
              {m.lessons.map((l) => {
                const current = l.id === currentId;
                return (
                  <li key={l.id}>
                    <Link
                      href={lessonHref(slug, l.id)}
                      aria-current={current ? "page" : undefined}
                      className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm focus-visible:shadow-focus focus-visible:outline-none ${current ? "bg-surface-selected font-medium text-fg" : "text-fg-secondary hover:bg-surface-hover"}`}
                    >
                      <LessonStatusIcon lesson={l} /> {l.title}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ol>
    </Wrap>
  );
}

function Resources({ resources }: { resources: LessonResourceDto[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (resources.length === 0) return <p className="text-sm text-fg-muted">No resources for this lesson.</p>;
  async function download(r: LessonResourceDto) {
    setBusy(r.id);
    setError(null);
    try {
      const res = await api.post<SignedUrlDto>("media/downloads", { resource_id: r.id }, { idempotencyKey: true });
      if (res.kind === "ok" && res.data.url) window.open(res.data.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {resources.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-3 rounded-md border border-line p-3 text-sm">
            <span className="text-fg">
              {r.title}
              {r.resource_type ? <span className="text-fg-muted"> · {humanize(r.resource_type)}</span> : null}
            </span>
            <Button variant="secondary" size="sm" loading={busy === r.id} onClick={() => void download(r)} aria-label={`Download ${r.title}`}>
              Download
            </Button>
          </li>
        ))}
      </ul>
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}

/** End-of-reading marker: completion for text lessons needs server-checkable evidence (LRN-06). */
function useReachedEnd(enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [reached, setReached] = useState(false);
  useEffect(() => {
    if (!enabled || !ref.current) return;
    if (typeof IntersectionObserver === "undefined") {
      setReached(true);
      return;
    }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) setReached(true);
    });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [enabled]);
  return { ref, reached };
}

function Completion({
  lesson,
  onRecorded,
  pdfOpened = false,
}: {
  lesson: LessonDto;
  onRecorded: () => Promise<void>;
  /** PDF lessons: the end marker cannot see inside the document, so opening it is the reading evidence. */
  pdfOpened?: boolean;
}) {
  const toast = useToast();
  const isText = TEXT_KINDS.has(lesson.lesson_type);
  const isPdf = lesson.lesson_type === "pdf";
  const done = lesson.progress?.status === "completed";
  const marker = useReachedEnd(isText && !isPdf && !done);
  const ref = marker.ref;
  const reached = isPdf ? pdfOpened : marker.reached;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function record() {
    setBusy(true);
    setError(null);
    try {
      await api.post(
        `me/lessons/${encodeURIComponent(lesson.lesson_key)}/completion`,
        { evidence: { scrolled_to_end: true } } satisfies Body<"me/lessons/{lesson_key}/completion", "post">,
        { idempotencyKey: true },
      );
      await onRecorded();
      toast.show({ title: "Progress saved.", tone: "success" });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div ref={ref} aria-hidden="true" />
      {done ? (
        <p role="status">
          <Badge tone="success">Completed</Badge>
        </p>
      ) : isText ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void record()} loading={busy} disabled={!reached} aria-describedby="complete-hint">
            Mark as complete
          </Button>
          <span id="complete-hint" className="text-xs text-fg-muted">
            {reached
              ? "You've reached the end of this lesson."
              : isPdf
                ? "Open and read the PDF to mark it complete."
                : "Read to the end of the lesson to mark it complete."}
          </span>
        </div>
      ) : lesson.lesson_type === "video" ? (
        <p className="text-sm text-fg-secondary" role="status">
          {lesson.progress?.status === "in_progress" ? `Watched ${formatPercent(lesson.progress.progress_pct)} so far. ` : ""}
          This lesson completes when you’ve watched at least 90% of the video. Your progress may take a minute to update.
        </p>
      ) : lesson.lesson_type === "practice_set" ? (
        <p className="text-sm text-fg-secondary" role="status">
          This lesson completes when you submit the practice set.
        </p>
      ) : lesson.lesson_type === "quiz" ? (
        <p className="text-sm text-fg-secondary" role="status">
          This lesson completes when you submit the quiz.
        </p>
      ) : lesson.lesson_type === "coding" ? (
        <p className="text-sm text-fg-secondary" role="status">
          This lesson completes when you submit your solution (Submit, not Run).
        </p>
      ) : null}
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}

type DocNode = { type?: string; text?: string; attrs?: { level?: number }; content?: DocNode[] };

/**
 * LRN-05 `article_body` is a structured JSONB document ({type:"doc", content:[...]},
 * verified: app/seeds/catalog_demo.py), not HTML. Rendered as React elements (no innerHTML).
 */
function renderDoc(node: DocNode | undefined, key: number | string = 0): ReactNode {
  if (!node || typeof node !== "object") return null;
  const children = Array.isArray(node.content) ? node.content.map((c, i) => renderDoc(c, i)) : null;
  const inner = (
    <>
      {typeof node.text === "string" ? node.text : null}
      {children}
    </>
  );
  switch (node.type) {
    case "text":
      return typeof node.text === "string" ? node.text : null;
    case "paragraph":
      return <p key={key}>{inner}</p>;
    case "heading":
      return (node.attrs?.level ?? 2) <= 2 ? <h2 key={key}>{inner}</h2> : <h3 key={key}>{inner}</h3>;
    case "bulletList":
    case "bullet_list":
      return <ul key={key}>{children}</ul>;
    case "orderedList":
    case "ordered_list":
      return <ol key={key}>{children}</ol>;
    case "listItem":
    case "list_item":
      return <li key={key}>{inner}</li>;
    case "codeBlock":
    case "code_block":
      return (
        <pre key={key}>
          <code>{inner}</code>
        </pre>
      );
    case "blockquote":
      return <blockquote key={key}>{inner}</blockquote>;
    case "hardBreak":
    case "hard_break":
      return <br key={key} />;
    default:
      return <div key={key}>{inner}</div>;
  }
}

/** Where quiz / coding / assignment lessons are launched (from the lesson's linked ids). */
function launchHref(lesson: LessonDto): string | null {
  // quiz and practice_set lessons both reference a test (verified: catalog/service.py check_lesson_refs).
  if ((lesson.lesson_type === "quiz" || lesson.lesson_type === "practice_set") && lesson.test_id) {
    return `/app/tests/${encodeURIComponent(lesson.test_id)}`;
  }
  if (lesson.lesson_type === "assignment" && lesson.assignment_id) return `/app/assignments/${encodeURIComponent(lesson.assignment_id)}`;
  // LRN-05 gives coding_problem_id, but coding routes are slug-based: open the problem list.
  if (lesson.lesson_type === "coding" && lesson.coding_problem_id) return "/app/coding";
  return null;
}

/** FR-CAT-001 pdf lesson: the file is a `pdf` lesson asset, opened through a short-lived MED-07 URL. */
function PdfBody({ lesson, onOpened }: { lesson: LessonDto; onOpened: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const asset = lesson.assets?.find((a) => a.asset_type === "pdf");
  if (!asset) return <Card><p className="text-sm text-fg-secondary">The PDF for this lesson isn’t available yet.</p></Card>;
  if (asset.status !== "ready") {
    return (
      <Card>
        <p role="status" className="text-sm text-fg-secondary">
          This PDF is still being processed. Check back in a few minutes.
        </p>
      </Card>
    );
  }
  async function open() {
    if (!asset) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<SignedUrlDto>("media/downloads", { lesson_asset_id: asset.id }, { idempotencyKey: true });
      if (res.kind === "ok" && res.data.url) {
        window.open(res.data.url, "_blank", "noopener,noreferrer");
        onOpened();
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="PDF lesson">
      <div className="space-y-3">
        <p className="text-sm text-fg-secondary">This lesson is a PDF document. It opens in a new tab.</p>
        <Button onClick={() => void open()} loading={busy}>
          Open PDF
        </Button>
        {error ? <ErrorState error={error} /> : null}
      </div>
    </Card>
  );
}

function ArticleBody({ body, onDepth }: { body: DocNode; onDepth: (pct: number) => void }) {
  const ref = useRef<HTMLElement>(null);
  useScrollDepth(ref, onDepth);
  return (
    <article ref={ref} className="prose max-w-prose text-fg">
      {renderDoc(body)}
    </article>
  );
}

function LessonBody({
  lesson,
  onPlayingChange,
  tracker,
  onPdfOpened,
}: {
  lesson: LessonDto;
  onPlayingChange: (p: boolean) => void;
  tracker: ActivityTrackerHandle;
  onPdfOpened: () => void;
}) {
  if (lesson.lesson_type === "pdf") return <PdfBody lesson={lesson} onOpened={onPdfOpened} />;
  if (lesson.lesson_type === "video") {
    const asset = lesson.assets?.find((a) => a.asset_type === "video");
    if (!asset) return <Card><p className="text-sm text-fg-secondary">The video for this lesson isn’t available yet.</p></Card>;
    if (asset.status !== "ready") {
      return (
        <div className="flex aspect-video items-center justify-center rounded-xl bg-surface-sunken p-6 text-center">
          <p role="status" className="text-sm text-fg-secondary">
            This video is still being processed. Check back in a few minutes.
          </p>
        </div>
      );
    }
    return <VideoPlayer lessonAssetId={asset.id} lessonTitle={lesson.title} onPlayingChange={onPlayingChange} video={tracker.video} />;
  }
  if (lesson.lesson_type === "article") {
    return lesson.article_body ? (
      <ArticleBody body={lesson.article_body as DocNode} onDepth={tracker.scrollDepth} />
    ) : (
      <p className="text-sm text-fg-secondary">This lesson has no text yet.</p>
    );
  }
  if (lesson.lesson_type === "live_link" && lesson.live_url) {
    return (
      <Card title="Live session">
        <a href={lesson.live_url} target="_blank" rel="noopener noreferrer" className="font-medium text-fg-link">
          Join the live session (opens in a new tab)
        </a>
      </Card>
    );
  }
  const href = launchHref(lesson);
  return (
    <Card title={humanize(lesson.lesson_type)}>
      {href ? (
        <LinkButton href={href}>Open {humanize(lesson.lesson_type).toLowerCase()}</LinkButton>
      ) : (
        <p className="text-sm text-fg-secondary">This activity isn’t available in the course player yet.</p>
      )}
    </Card>
  );
}

/** PLY-001 / PLY-002 course player (focus layout inside the student shell). */
export function LessonView({ slug, lessonId }: { slug: string; lessonId: string }) {
  const { catalog, course, courseId } = useEnrolledCourse(slug);
  const lessonPath = courseId ? `me/courses/${encodeURIComponent(courseId)}/lessons/${encodeURIComponent(lessonId)}` : null;
  const lesson = useResource<LessonDto>(lessonPath);
  const [playing, setPlaying] = useState(false);
  const [pdfOpenedFor, setPdfOpenedFor] = useState<string | null>(null);
  const l = lesson.data && lesson.data.id === lessonId ? lesson.data : undefined;
  const videoAsset = l?.assets?.find((a) => a.asset_type === "video");

  const tracker = useActivityTracker({
    route: LESSON_ROUTE,
    surface: l?.lesson_type === "video" ? "lesson_video" : "lesson_text",
    entity: { course_id: courseId ?? undefined, lesson_id: lessonId, lesson_asset_id: videoAsset?.id },
    enabled: Boolean(l && courseId),
    mediaPlaying: playing,
  });

  const error = catalog.error ?? lesson.error;
  if (error) return <ContentErrorState error={error} onRetry={catalog.error ? catalog.reload : lesson.reload} />;
  if (!l || !courseId) return <LoadingBlock label="Loading lesson" rows={4} size="card" />;

  const title = course.data?.title ?? catalog.data?.title ?? "";
  // LRN-05 has no prev/next or position: derive them from the LRN-04 outline.
  const ordered = course.data?.modules.flatMap((m) => m.lessons) ?? [];
  const idx = ordered.findIndex((x) => x.id === l.id);
  const prevId = idx > 0 ? (ordered[idx - 1]?.id ?? null) : null;
  const nextId = idx >= 0 ? (ordered[idx + 1]?.id ?? null) : null;
  const position = idx >= 0 ? `Lesson ${idx + 1} of ${ordered.length}` : null;

  const resources = l.resources ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumbs={[
          { label: "My learning", href: "/app/learning" },
          { label: title || "Course", href: `/app/courses/${encodeURIComponent(slug)}` },
          { label: l.title },
        ]}
        title={l.title}
        meta={position ? <span className="text-sm text-fg-muted">{position}</span> : undefined}
      />

      {/* Phones/tablets: the lesson list comes before the lesson, so changing lessons needs no scrolling past it. */}
      <nav aria-label="Course contents" className="lg:hidden">
        <details className="rounded-xl border border-line bg-surface p-3">
          <summary className="flex min-h-touch cursor-pointer items-center font-display text-sm font-semibold text-fg">Contents{position ? ` · ${position}` : ""}</summary>
          <div className="pt-3">{course.data ? <Contents course={course.data} slug={slug} currentId={lessonId} landmark={false} /> : null}</div>
        </details>
      </nav>

      {/* The shell drops its sidebar on lesson routes, so the player takes the full width beside the contents. */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] 2xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <LessonBody lesson={l} onPlayingChange={setPlaying} tracker={tracker} onPdfOpened={() => setPdfOpenedFor(l.id)} />
          <Completion
            lesson={l}
            pdfOpened={pdfOpenedFor === l.id}
            onRecorded={async () => {
              await Promise.all([lesson.reload(), course.reload()]);
            }}
          />
          {resources.length ? (
            <Card title="Resources" titleAs="h2">
              <Resources resources={resources} />
            </Card>
          ) : null}
          <nav aria-label="Lesson navigation" className="flex flex-wrap justify-between gap-2 border-t border-line pt-4">
            {prevId ? (
              <LinkButton href={lessonHref(slug, prevId)} variant="secondary">
                ← Previous
              </LinkButton>
            ) : (
              <span />
            )}
            {nextId ? <LinkButton href={lessonHref(slug, nextId)}>Next →</LinkButton> : null}
          </nav>
        </div>
        <aside className="hidden lg:sticky lg:top-20 lg:block lg:self-start">
          <div className="rounded-xl border border-line bg-surface p-3">
            {course.data ? <Contents course={course.data} slug={slug} currentId={lessonId} /> : course.error ? <p className="text-sm text-fg-muted">Contents unavailable.</p> : <LoadingBlock label="Loading contents" rows={3} size="card" />}
          </div>
        </aside>
      </div>
    </div>
  );
}
