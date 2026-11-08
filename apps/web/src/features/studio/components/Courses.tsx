"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Card, Dialog, FormField, Input, Select, Table, useToast } from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useApi, seg, type SendBody } from "@/features/trainer/shared/use-api";
import { Boundary, StatusBadge, TextArea, fieldErrorsOf, formatDate, formatDateTime, useFailToast } from "@/features/trainer/shared/ui";
import type { Body } from "@/lib/api-types";
import type { CourseDetail, CourseSummary, CourseVersion, CourseVersionTree, Lesson } from "../lib/types";
import { LessonEditor, REF_NOUN, useRefOptions } from "./LessonEditor";
import { RefSelect, useTopics } from "./Pickers";

/** Course status for display: the editable draft being in review wins over the course status. */
export function courseStatus(c: Pick<CourseSummary, "status"> & { draft: { status: string } | null }): string {
  return c.draft?.status === "in_review" ? "in_review" : c.status;
}

/**
 * CMS-002 / TRN-003 courses in scope (CAT-08) + create (CAT-09).
 * The api picks the owner (WS4): Content manager / Admin (platform scope) create platform courses;
 * a batch trainer (ADM-41) gets a company course that never appears in the public catalogue.
 */
export function CourseList({ hrefPattern }: { hrefPattern: string }) {
  const editHref = (id: string) => hrefPattern.replace(":id", encodeURIComponent(id));
  const router = useRouter();
  const fail = useFailToast();
  const [status, setStatus] = useState("");
  const courses = useApi<Page<CourseSummary>>("studio/courses", { status: status || undefined, limit: 100 });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ title: "", slug: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const create = async () => {
    const errs: Record<string, string> = {};
    if (f.title.trim().length < 3) errs.title = "Enter a title (at least 3 characters).";
    if (!/^[a-z0-9][a-z0-9-]{1,118}$/.test(f.slug)) errs.slug = "Lowercase letters, numbers and single dashes.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const res = await api.post<CourseSummary>("studio/courses", {
        title: f.title.trim(),
        slug: f.slug,
      } satisfies SendBody<"studio/courses", "post">);
      if (res.kind === "ok") router.push(editHref(res.data.id));
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't create the course");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-56">
          <FormField label="Status">
            {(p) => (
              <Select
                {...p}
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                options={[
                  { value: "", label: "All" },
                  { value: "draft", label: "Draft" },
                  { value: "published", label: "Published" },
                  { value: "archived", label: "Archived" },
                ]}
              />
            )}
          </FormField>
        </div>
        <Button onClick={() => setOpen(true)}>New course</Button>
      </div>
      <Table
        caption="Courses"
        columns={[
          {
            key: "t",
            header: "Course",
            cell: (c: CourseSummary) => (
              <Link className="text-fg-link underline" href={editHref(c.id)}>
                {c.title}
              </Link>
            ),
          },
          { key: "s", header: "Status", cell: (c) => <StatusBadge status={courseStatus(c)} /> },
          { key: "v", header: "Draft version", cell: (c) => (c.draft ? c.draft.version_no : "—") },
          { key: "u", header: "Updated", cell: (c) => formatDate(c.updated_at) },
        ]}
        rows={courses.data?.data}
        rowKey={(c) => c.id}
        loading={courses.loading}
        error={courses.error}
        onRetry={() => void courses.reload()}
        empty={{ title: "No courses yet", action: <Button onClick={() => setOpen(true)}>New course</Button> }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        dismissible={!busy}
        title="New course"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void create()} loading={busy}>
              Create draft
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Title" required error={errors.title}>
            {(p) => (
              <Input
                {...p}
                value={f.title}
                onChange={(e) => {
                  const title = e.target.value;
                  setF((x) => ({ title, slug: x.slug && x.slug !== slugify(x.title) ? x.slug : slugify(title) }));
                }}
              />
            )}
          </FormField>
          <FormField label="URL slug" required error={errors.slug}>
            {(p) => <Input {...p} value={f.slug} onChange={(e) => setF((x) => ({ ...x, slug: e.target.value }))} className="font-mono" />}
          </FormField>
        </div>
      </Dialog>
    </div>
  );
}

export function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

type LessonType = Body<"studio/courses/{course_id}/draft/lessons", "post">["lesson_type"];

/** `ref` = the field check_lesson_refs (apps/api catalog/service.py) requires for that type. */
const LESSON_KINDS: { value: LessonType; label: string; ref?: { field: "test_id" | "coding_problem_id" | "assignment_id" | "live_url"; label: string } }[] = [
  { value: "video", label: "Video" },
  { value: "article", label: "Article" },
  { value: "pdf", label: "PDF document" },
  { value: "quiz", label: "Quiz", ref: { field: "test_id", label: "Test" } },
  { value: "practice_set", label: "Practice set", ref: { field: "test_id", label: "Practice set test" } },
  { value: "coding", label: "Coding problem", ref: { field: "coding_problem_id", label: "Coding problem" } },
  { value: "assignment", label: "Assignment", ref: { field: "assignment_id", label: "Assignment" } },
  { value: "live_link", label: "Live session link", ref: { field: "live_url", label: "Session URL (https://)" } },
];

/* ---------------------------------------------------------------- outline ordering */

type Outline = Body<"studio/courses/{course_id}/draft/outline", "put">["modules"];

/** CAT-12 body for the current draft order. */
export function outlineOf(modules: CourseVersionTree["modules"]): Outline {
  return modules.map((m) => ({ module_key: m.module_key, title: m.title, lesson_ids: m.lessons.map((l) => l.id) }));
}

/** Move a module one place up (-1) or down (+1). Returns null when it can't move. */
export function moveModule(outline: Outline, moduleKey: string, dir: -1 | 1): Outline | null {
  const i = outline.findIndex((m) => m.module_key === moduleKey);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= outline.length) return null;
  const out = [...outline];
  [out[i], out[j]] = [out[j]!, out[i]!];
  return out;
}

/**
 * Move a lesson one place up/down; at a module boundary it moves to the end of the previous
 * module or the start of the next one. Returns null when it can't move.
 */
export function moveLesson(outline: Outline, lessonId: string, dir: -1 | 1): Outline | null {
  const mi = outline.findIndex((m) => (m.lesson_ids ?? []).includes(lessonId));
  if (mi < 0) return null;
  const out = outline.map((m) => ({ ...m, lesson_ids: [...(m.lesson_ids ?? [])] }));
  const ids = out[mi]!.lesson_ids;
  const li = ids.indexOf(lessonId);
  const lj = li + dir;
  if (lj >= 0 && lj < ids.length) {
    [ids[li], ids[lj]] = [ids[lj]!, ids[li]!];
    return out;
  }
  const target = out[mi + dir];
  if (!target) return null;
  ids.splice(li, 1);
  if (dir < 0) target.lesson_ids.push(lessonId);
  else target.lesson_ids.unshift(lessonId);
  return out;
}

/**
 * CMS-003 / TRN-004 course builder: CAT-10 detail, CAT-11 draft metadata, CAT-13 add lesson,
 * CAT-16 submit for review, CAT-17 publish (author ≠ publisher for platform), CAT-19 versions;
 * CAT-12 outline order, and the lesson editor (CAT-14/15/20/21/22, MED-01..03) for draft lessons.
 * `canPublish={false}` (trainer portal, audit ADM-56) hides Publish and Archive.
 */
export function CourseEditor({ courseId, canPublish = true }: { courseId: string; canPublish?: boolean }) {
  const toast = useToast();
  const fail = useFailToast();
  const course = useApi<CourseDetail>(`studio/courses/${seg(courseId)}`);
  const versions = useApi<{ data: CourseVersion[] }>(`studio/courses/${seg(courseId)}/versions`);
  const [meta, setMeta] = useState({ title: "", summary: "", level: "beginner" as NonNullable<CourseVersion["level"]> });
  const [lesson, setLesson] = useState({ module_title: "", title: "", kind: "article" as LessonType, ref: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [changeType, setChangeType] = useState<"minor" | "major">("minor");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const topics = useTopics();
  const refOptions = useRefOptions(lesson.kind, courseId);

  const d = course.data;
  const version = d ? (d.draft ?? d.published) : null;
  useEffect(() => {
    if (version) setMeta({ title: version.title, summary: version.summary ?? "", level: version.level ?? "beginner" });
  }, [version]);

  // Editing a published course creates a new draft version (catalog ensure_draft); an in-review draft is locked.
  const status = d ? courseStatus(d) : "draft";
  const editable = !!d && d.status !== "archived" && d.draft?.status !== "in_review";
  const kind = LESSON_KINDS.find((k) => k.value === lesson.kind);
  // Lessons (fields, order, media, topics, resources) can change only on the editable draft version.
  const lessonsEditable = editable && d?.draft?.status === "draft";
  const allLessons: Lesson[] = (version?.modules ?? []).flatMap((m) => m.lessons);
  const selectedLesson = allLessons.find((l) => l.id === selected) ?? null;
  const reorder = (next: Outline | null) => {
    if (!next) return;
    void run("outline", () => api.put(`studio/courses/${seg(courseId)}/draft/outline`, { modules: next } satisfies Body<"studio/courses/{course_id}/draft/outline", "put">), "Order saved");
  };

  const lessonBody = (): Body<"studio/courses/{course_id}/draft/lessons", "post"> => {
    const existing = version?.modules.find((m) => m.title.trim().toLowerCase() === lesson.module_title.trim().toLowerCase());
    return {
      title: lesson.title.trim(),
      lesson_type: lesson.kind,
      ...(existing && d?.draft ? { module_key: existing.module_key } : { module_title: lesson.module_title.trim() }),
      ...(kind?.ref ? { [kind.ref.field]: lesson.ref.trim() } : {}),
    };
  };

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    setErrors({});
    try {
      await fn();
      toast.show({ tone: "success", title: ok });
      await Promise.all([course.reload(), versions.reload()]);
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.code === "sod_violation")
        toast.show({ tone: "warning", title: "Someone else must publish this", description: "The author of a platform course can't publish it. Ask another content manager.", requestId: err.requestId });
      else if (err instanceof ApiError && err.code === "invalid_state_transition") toast.show({ tone: "warning", title: "This course has changed status. Refresh to see the latest.", requestId: err.requestId });
      else {
        const fe = fieldErrorsOf(err);
        if (Object.keys(fe).length) setErrors(fe);
        else fail(err);
      }
      return false;
    } finally {
      setBusy(null);
    }
  };

  return (
    <Boundary state={course}>
      {(c) => (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={status} />
            {status === "in_review" ? <span className="text-sm text-fg-muted">Waiting for a reviewer. Editing is locked.</span> : null}
            {c.status === "published" && !c.draft ? <span className="text-sm text-fg-muted">Published versions can&apos;t change. Edits create a new draft version.</span> : null}
          </div>
          <Card title="Details">
            <div className="grid gap-4 md:grid-cols-2">
              <FormField label="Title" required error={errors.title}>
                {(p) => <Input {...p} value={meta.title} disabled={!editable} onChange={(e) => setMeta((m) => ({ ...m, title: e.target.value }))} />}
              </FormField>
              <FormField label="Level">
                {(p) => (
                  <Select
                    {...p}
                    value={meta.level}
                    disabled={!editable}
                    onChange={(e) => setMeta((m) => ({ ...m, level: e.target.value as typeof m.level }))}
                    options={[
                      { value: "beginner", label: "Beginner" },
                      { value: "intermediate", label: "Intermediate" },
                      { value: "advanced", label: "Advanced" },
                    ]}
                  />
                )}
              </FormField>
              <div className="md:col-span-2">
                <FormField label="Summary" error={errors.summary}>
                  {(p) => <TextArea {...p} value={meta.summary} disabled={!editable} onChange={(e) => setMeta((m) => ({ ...m, summary: e.target.value }))} />}
                </FormField>
              </div>
            </div>
            {editable ? (
              <Button className="mt-4" variant="secondary" loading={busy === "meta"} onClick={() => void run("meta", () => api.patch(`studio/courses/${seg(courseId)}/draft`, meta satisfies Body<"studio/courses/{course_id}/draft", "patch">), "Draft saved")}>
                Save draft
              </Button>
            ) : null}
          </Card>
          <Card title="Outline">
            {(version?.modules ?? []).length === 0 ? (
              <p className="text-sm text-fg-muted">No lessons yet.</p>
            ) : (
              <ol className="space-y-3">
                {version!.modules.map((m, mi) => {
                  const outline = outlineOf(version!.modules);
                  return (
                    <li key={m.module_key}>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-fg">
                          {mi + 1}. {m.title}
                        </p>
                        {lessonsEditable ? (
                          <>
                            <Button size="sm" variant="ghost" aria-label={`Move module ${m.title} up`} disabled={mi === 0 || busy === "outline"} onClick={() => reorder(moveModule(outline, m.module_key, -1))}>
                              ↑
                            </Button>
                            <Button size="sm" variant="ghost" aria-label={`Move module ${m.title} down`} disabled={mi === version!.modules.length - 1 || busy === "outline"} onClick={() => reorder(moveModule(outline, m.module_key, 1))}>
                              ↓
                            </Button>
                          </>
                        ) : null}
                      </div>
                      <ol className="ml-5 mt-1 list-decimal space-y-1 text-sm text-fg-secondary">
                        {m.lessons.map((l) => (
                          <li key={l.id}>
                            <span className="inline-flex flex-wrap items-center gap-1">
                              {l.title} <span className="text-fg-muted">· {LESSON_KINDS.find((k) => k.value === l.lesson_type)?.label ?? l.lesson_type}</span>
                              {l.is_free_preview ? <Badge className="ml-2" tone="info">Free preview</Badge> : null}
                              {l.lesson_type === "video" && !(l.assets ?? []).some((a) => a.asset_type === "video") ? <Badge className="ml-2" tone="warning">No video yet</Badge> : null}
                              {l.lesson_type === "pdf" && !(l.assets ?? []).some((a) => a.asset_type === "pdf") ? <Badge className="ml-2" tone="warning">No PDF yet</Badge> : null}
                              {(l.assets ?? []).some((a) => a.status !== "ready") ? <Badge className="ml-2" tone="warning">Media processing</Badge> : null}
                              {lessonsEditable ? (
                                <>
                                  <Button size="sm" variant="ghost" aria-label={`Move ${l.title} up`} disabled={busy === "outline" || moveLesson(outline, l.id, -1) === null} onClick={() => reorder(moveLesson(outline, l.id, -1))}>
                                    ↑
                                  </Button>
                                  <Button size="sm" variant="ghost" aria-label={`Move ${l.title} down`} disabled={busy === "outline" || moveLesson(outline, l.id, 1) === null} onClick={() => reorder(moveLesson(outline, l.id, 1))}>
                                    ↓
                                  </Button>
                                </>
                              ) : null}
                              <Button size="sm" variant="secondary" aria-label={`${lessonsEditable ? "Edit" : "Open"} ${l.title}`} onClick={() => setSelected(l.id)}>
                                {lessonsEditable ? "Edit" : "Open"}
                              </Button>
                            </span>
                          </li>
                        ))}
                      </ol>
                    </li>
                  );
                })}
              </ol>
            )}
            {editable && !lessonsEditable && c.draft === null ? (
              <p className="mt-3 text-sm text-fg-muted">To change lessons, save the draft details first — that starts a new draft version.</p>
            ) : null}
            {editable ? (
              <div className="mt-4 grid gap-3 border-t border-line pt-4 md:grid-cols-3">
                <FormField label="Module" hint="Existing or new module name" error={errors.module_title}>
                  {(p) => <Input {...p} value={lesson.module_title} onChange={(e) => setLesson((l) => ({ ...l, module_title: e.target.value }))} />}
                </FormField>
                <FormField label="Lesson title" error={errors.title}>
                  {(p) => <Input {...p} value={lesson.title} onChange={(e) => setLesson((l) => ({ ...l, title: e.target.value }))} />}
                </FormField>
                <FormField label="Type">
                  {(p) => <Select {...p} value={lesson.kind} onChange={(e) => setLesson((l) => ({ ...l, kind: e.target.value as LessonType, ref: "" }))} options={LESSON_KINDS.map(({ value, label }) => ({ value, label }))} />}
                </FormField>
                {kind?.ref ? (
                  <FormField label={kind.ref.label} required error={errors[kind.ref.field]}>
                    {(p) =>
                      kind.ref!.field === "live_url" || !refOptions.ref ? (
                        <Input {...p} type="url" value={lesson.ref} onChange={(e) => setLesson((l) => ({ ...l, ref: e.target.value }))} />
                      ) : (
                        <RefSelect {...p} noun={REF_NOUN[refOptions.ref]} state={refOptions.state} value={lesson.ref} onChange={(e) => setLesson((l) => ({ ...l, ref: e.target.value }))} />
                      )
                    }
                  </FormField>
                ) : null}
                <div className="md:col-span-3">
                  <Button
                    variant="secondary"
                    loading={busy === "lesson"}
                    disabled={!lesson.title.trim() || !lesson.module_title.trim() || (!!kind?.ref && !lesson.ref.trim())}
                    onClick={async () => {
                      if (await run("lesson", () => api.post(`studio/courses/${seg(courseId)}/draft/lessons`, lessonBody(), { idempotencyKey: true }), "Lesson added"))
                        setLesson((l) => ({ ...l, title: "", ref: "" }));
                    }}
                  >
                    Add lesson
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
          {selectedLesson ? (
            <section aria-label={`Lesson ${selectedLesson.title}`} className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-lg font-semibold text-fg">{selectedLesson.title}</h2>
                <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>
                  Close lesson
                </Button>
              </div>
              <LessonEditor
                key={selectedLesson.id}
                courseId={courseId}
                lesson={selectedLesson}
                editable={lessonsEditable}
                topics={topics}
                onSaved={() => void course.reload()}
              />
            </section>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {editable && c.draft?.status === "draft" ? (
              <Button loading={busy === "review"} onClick={() => void run("review", () => api.post(`studio/courses/${seg(courseId)}/submit-review`, {}), "Submitted for review")}>
                Submit for review
              </Button>
            ) : null}
            {status === "in_review" && canPublish ? (
              <Button onClick={() => setPublishOpen(true)}>Publish</Button>
            ) : null}
            {c.status === "published" && canPublish ? (
              <Button variant="secondary" loading={busy === "archive"} onClick={() => void run("archive", () => api.post(`studio/courses/${seg(courseId)}/archive`, {}), "Course archived")}>
                Archive
              </Button>
            ) : null}
          </div>
          <Table
            caption="Version history"
            showCaption
            columns={[
              { key: "v", header: "Version", cell: (v: CourseVersion) => v.version_no },
              { key: "s", header: "Status", cell: (v) => <StatusBadge status={v.status} /> },
              { key: "t", header: "Change", cell: (v) => (v.change_type === "major" ? "Major (students opt in)" : v.change_type === "minor" ? "Minor (progress carries over)" : "—") },
              { key: "p", header: "Published", cell: (v) => formatDateTime(v.published_at) },
            ]}
            rows={versions.data?.data}
            rowKey={(v) => v.id}
            loading={versions.loading}
            error={versions.error}
            onRetry={() => void versions.reload()}
            empty={{ title: "Not published yet" }}
          />
          <Dialog
            open={publishOpen}
            onClose={() => setPublishOpen(false)}
            dismissible={busy !== "publish"}
            title="Publish this version?"
            description="Published versions are immutable. Student progress is kept by lesson."
            footer={
              <>
                <Button variant="secondary" onClick={() => setPublishOpen(false)} disabled={busy === "publish"}>
                  Cancel
                </Button>
                <Button
                  loading={busy === "publish"}
                  onClick={async () => {
                    if (await run("publish", () => api.post(`studio/courses/${seg(courseId)}/publish`, { change_type: changeType } satisfies Body<"studio/courses/{course_id}/publish", "post">, { idempotencyKey: true }), "Course published")) setPublishOpen(false);
                  }}
                >
                  Publish
                </Button>
              </>
            }
          >
            <FormField label="Type of change">
              {(p) => (
                <Select
                  {...p}
                  value={changeType}
                  onChange={(e) => setChangeType(e.target.value as "minor" | "major")}
                  options={[
                    { value: "minor", label: "Minor — move everyone to the new version" },
                    { value: "major", label: "Major — students choose when to switch" },
                  ]}
                />
              )}
            </FormField>
          </Dialog>
        </div>
      )}
    </Boundary>
  );
}
