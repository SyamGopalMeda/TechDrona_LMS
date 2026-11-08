"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Dialog, EmptyState, FormField, Select, Table, type BadgeTone } from "@/components/ui";
import type { Page } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary } from "@/features/trainer/shared/ui";
import {
  LESSON_FILE_TYPES,
  ProviderUploadError,
  getAssetStatus,
  pollAssetStatus,
  postToProvider,
  requestFileUpload,
  requestVideoUpload,
  type AssetStatus,
} from "../lib/media";
import type { CourseDetail, CourseSummary, Lesson, LessonAssetOut } from "../lib/types";

const ASSET_TONE: Record<string, BadgeTone> = { ready: "success", failed: "danger", uploading: "info", processing: "info" };
const ASSET_LABEL: Record<string, string> = { ready: "Ready", failed: "Failed", uploading: "Waiting for upload", processing: "Processing" };

export function AssetStatusBadge({ status }: { status: string }) {
  return <Badge tone={ASSET_TONE[status] ?? "neutral"}>{ASSET_LABEL[status] ?? status}</Badge>;
}

type Phase = "idle" | "requesting" | "uploading" | "processing" | "done";

interface UploadError {
  title: string;
  detail?: string;
  requestId?: string | null;
}

/** An api problem (e.g. provider not configured → 503) or a provider rejection, shown as-is. */
function uploadErrorOf(err: unknown): UploadError {
  if (err instanceof ApiError) return { title: err.title, detail: err.detail ?? undefined, requestId: err.requestId };
  if (err instanceof ProviderUploadError) return { title: "Upload failed", detail: err.message };
  return { title: "Upload failed", detail: "Please try again." };
}

/**
 * MED-01/02/03 upload panel for one lesson (audit INV-03): get a ticket from the api, POST the
 * file directly to the provider URL, then poll the asset status until it is ready or failed.
 * Video goes to VdoCipher (video lessons only); PDF and captions go to the content bucket.
 */
export function LessonMediaPanel({ lesson, editable, onChanged }: { lesson: Lesson; editable: boolean; onChanged?: () => void }) {
  const [assets, setAssets] = useState<LessonAssetOut[]>(lesson.assets ?? []);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<UploadError | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const videoInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => setAssets(lesson.assets ?? []), [lesson.assets]);
  useEffect(() => () => abort.current?.abort(), []);

  const merge = (s: AssetStatus) =>
    setAssets((xs) => (xs.some((a) => a.id === s.id) ? xs.map((a) => (a.id === s.id ? { ...a, ...s } : a)) : [...xs, s]));

  const upload = async (kind: "video" | "file", file: File) => {
    setError(null);
    setPhase("requesting");
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    try {
      let assetId: string | undefined;
      let ticket;
      if (kind === "video") {
        const res = await requestVideoUpload(lesson.id, lesson.title || file.name);
        if (res.kind !== "ok") return;
        assetId = res.data.lesson_asset_id;
        ticket = res.data.upload;
      } else {
        const res = await requestFileUpload({
          purpose: "lesson_file",
          filename: file.name,
          content_type: file.type,
          size_bytes: file.size,
          lesson_id: lesson.id,
          asset_type: LESSON_FILE_TYPES[file.type],
        });
        if (res.kind !== "ok") return;
        assetId = res.data.lesson_asset_id;
        ticket = res.data.upload;
      }
      setPhase("uploading");
      await postToProvider(ticket, file);
      setPhase("processing");
      if (assetId) await pollAssetStatus(assetId, { signal: ctl.signal, onStatus: merge });
      setPhase("done");
      onChanged?.();
    } catch (err) {
      setError(uploadErrorOf(err));
      setPhase("idle");
    }
  };

  const check = async (id: string) => {
    setChecking(id);
    try {
      merge(await getAssetStatus(id));
    } catch (err) {
      setError(uploadErrorOf(err));
    } finally {
      setChecking(null);
    }
  };

  const busy = phase === "requesting" || phase === "uploading" || phase === "processing";
  const pick = (kind: "video" | "file") => (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (kind === "file" && !LESSON_FILE_TYPES[f.type]) {
      setError({ title: "Unsupported file", detail: "Attach a PDF or a WebVTT (.vtt) captions file." });
      return;
    }
    void upload(kind, f);
  };

  return (
    <div className="space-y-3">
      {assets.length === 0 ? (
        <p className="text-sm text-fg-muted">No media attached yet.</p>
      ) : (
        <ul className="space-y-2" aria-label="Lesson media">
          {assets.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-fg">{a.asset_type === "video" ? "Video" : a.asset_type === "pdf" ? "PDF" : a.asset_type === "captions" ? "Captions" : a.asset_type}</span>
              <AssetStatusBadge status={a.status} />
              {a.duration_seconds ? <span className="text-fg-muted">{Math.round(a.duration_seconds / 60)} min</span> : null}
              {a.status !== "ready" && a.status !== "failed" ? (
                <Button size="sm" variant="secondary" loading={checking === a.id} onClick={() => void check(a.id)}>
                  Check status
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {error ? (
        <div role="alert" className="rounded-md border border-danger-border bg-danger-subtle p-3 text-sm text-danger-fg">
          <p className="font-medium">{error.title}</p>
          {error.detail ? <p>{error.detail}</p> : null}
          {error.requestId ? <p className="text-xs">Request id: {error.requestId}</p> : null}
        </div>
      ) : null}
      {busy ? (
        <p role="status" className="text-sm text-fg-secondary">
          {phase === "requesting" ? "Preparing the upload…" : phase === "uploading" ? "Uploading the file…" : "Uploaded. Processing — this can take a few minutes…"}
        </p>
      ) : null}
      {editable ? (
        <div className="flex flex-wrap gap-2">
          {lesson.lesson_type === "video" ? (
            <>
              <input ref={videoInput} type="file" accept="video/*" className="sr-only" aria-label="Video file" onChange={pick("video")} tabIndex={-1} />
              <Button variant="secondary" disabled={busy} onClick={() => videoInput.current?.click()}>
                Upload video
              </Button>
            </>
          ) : null}
          <input ref={fileInput} type="file" accept="application/pdf,text/vtt,.vtt" className="sr-only" aria-label="PDF or captions file" onChange={pick("file")} tabIndex={-1} />
          <Button variant="secondary" disabled={busy} onClick={() => fileInput.current?.click()}>
            Attach PDF or captions
          </Button>
        </div>
      ) : (
        <p className="text-xs text-fg-muted">Media can be changed on a draft version only.</p>
      )}
    </div>
  );
}

/**
 * CMS-012 media screen (audit INV-03 / ADM-50): pick a course, see every lesson's media and its
 * processing status, and upload or attach media to lessons of the editable draft.
 */
export function MediaLibrary() {
  const courses = useApi<Page<CourseSummary>>("studio/courses", { limit: 100 });
  const [courseId, setCourseId] = useState("");
  const course = useApi<CourseDetail>(courseId ? `studio/courses/${seg(courseId)}` : null);
  const [open, setOpen] = useState<Lesson | null>(null);

  const list = courses.data?.data ?? [];
  return (
    <div className="space-y-4">
      <Boundary state={courses}>
        {() =>
          list.length === 0 ? (
            <EmptyState title="No courses yet" description="Create a course first, then add video lessons to upload media." />
          ) : (
            <div className="w-full max-w-md">
              <FormField label="Course">
                {(p) => (
                  <Select {...p} value={courseId} placeholder="Choose a course" onChange={(e) => setCourseId(e.target.value)} options={list.map((c) => ({ value: c.id, label: c.title }))} />
                )}
              </FormField>
            </div>
          )
        }
      </Boundary>
      {courseId ? (
        <Boundary state={course}>
          {(c) => {
            const version = c.draft ?? c.published;
            const editable = c.draft?.status === "draft";
            const lessons = (version?.modules ?? []).flatMap((m) => m.lessons.map((l) => ({ ...l, module: m.title })));
            return (
              <Card title={version?.title ?? c.title}>
                {!editable ? <p className="mb-3 text-sm text-fg-muted">This course has no editable draft. Open it in the course builder and save the draft to change media.</p> : null}
                <Table
                  caption="Lessons and media"
                  columns={[
                    { key: "m", header: "Module", cell: (l: Lesson & { module: string }) => l.module },
                    { key: "t", header: "Lesson", cell: (l) => l.title },
                    { key: "k", header: "Type", cell: (l) => l.lesson_type },
                    {
                      key: "a",
                      header: "Media",
                      cell: (l) =>
                        (l.assets ?? []).length ? (
                          <span className="flex flex-wrap gap-1">
                            {(l.assets ?? []).map((a) => (
                              <AssetStatusBadge key={a.id} status={a.status} />
                            ))}
                          </span>
                        ) : (
                          "—"
                        ),
                    },
                    {
                      key: "x",
                      header: <span className="sr-only">Actions</span>,
                      align: "right",
                      cell: (l) => (
                        <Button size="sm" variant="secondary" onClick={() => setOpen(l)}>
                          {editable ? "Manage media" : "View media"}
                        </Button>
                      ),
                    },
                  ]}
                  rows={lessons}
                  rowKey={(l) => l.id}
                  empty={{ title: "No lessons yet" }}
                />
                <Dialog open={open !== null} onClose={() => setOpen(null)} title={open ? `Media · ${open.title}` : "Media"}>
                  {open ? <LessonMediaPanel lesson={open} editable={editable} onChanged={() => void course.reload()} /> : null}
                </Dialog>
              </Card>
            );
          }}
        </Boundary>
      ) : null}
    </div>
  );
}
