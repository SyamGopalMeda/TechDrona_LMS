"use client";

import { useState } from "react";
import { Badge, Button, Card, Checkbox, Dialog, FormField, Input, Select, useToast } from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import { useApi, useApiAll, seg, type SendBody } from "@/features/trainer/shared/use-api";
import { TextArea, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import type { TestSummary } from "@/features/trainer/lib/types";
import { postToProvider, requestFileUpload } from "../lib/media";
import type { CodingProblemSummary, Lesson, ResourceOut } from "../lib/types";
import { LessonMediaPanel } from "./Media";
import { RefSelect, TopicSelect, type useTopics } from "./Pickers";

/* ------------------------------------------------------------ article body <-> text */

type DocNode = { type?: string; text?: string; attrs?: { level?: number }; content?: DocNode[] };

function textOfNode(n: DocNode | undefined): string {
  if (!n) return "";
  if (typeof n.text === "string") return n.text;
  return (n.content ?? []).map(textOfNode).join("");
}

/**
 * LRN-05 `article_body` is a structured document ({type:"doc", content:[…]}) rendered by the
 * lesson player. The editor uses a small plain-text form of it: blocks separated by a blank
 * line, `## ` / `### ` headings, `- ` bullet lists, `1. ` numbered lists, everything else a paragraph.
 */
export function docToText(doc: unknown): string {
  const root = doc as DocNode | null;
  if (!root || !Array.isArray(root.content)) return "";
  return root.content
    .map((b) => {
      switch (b.type) {
        case "heading":
          return `${(b.attrs?.level ?? 2) <= 2 ? "##" : "###"} ${textOfNode(b)}`;
        case "bulletList":
        case "bullet_list":
          return (b.content ?? []).map((li) => `- ${textOfNode(li)}`).join("\n");
        case "orderedList":
        case "ordered_list":
          return (b.content ?? []).map((li, i) => `${i + 1}. ${textOfNode(li)}`).join("\n");
        default:
          return textOfNode(b);
      }
    })
    .filter((s) => s.trim())
    .join("\n\n");
}

const para = (text: string): DocNode => ({ type: "paragraph", content: [{ type: "text", text }] });
const item = (text: string): DocNode => ({ type: "listItem", content: [para(text)] });

export function textToDoc(text: string): { type: "doc"; content: DocNode[] } {
  const content: DocNode[] = [];
  for (const raw of text.replace(/\r\n/g, "\n").split(/\n\s*\n/)) {
    const block = raw.trim();
    if (!block) continue;
    const lines = block.split("\n").map((l) => l.trim());
    const h = /^(#{2,3})\s+(.+)$/.exec(block);
    if (h && lines.length === 1) content.push({ type: "heading", attrs: { level: h[1]!.length }, content: [{ type: "text", text: h[2]! }] });
    else if (lines.every((l) => /^[-*]\s+/.test(l))) content.push({ type: "bulletList", content: lines.map((l) => item(l.replace(/^[-*]\s+/, ""))) });
    else if (lines.every((l) => /^\d+[.)]\s+/.test(l))) content.push({ type: "orderedList", content: lines.map((l) => item(l.replace(/^\d+[.)]\s+/, ""))) });
    else content.push(para(lines.join(" ")));
  }
  return { type: "doc", content };
}

/* --------------------------------------------------------------- reference pickers */

type Ref = "test_id" | "coding_problem_id" | "assignment_id";
const REF_FOR: Record<string, Ref | undefined> = { quiz: "test_id", practice_set: "test_id", coding: "coding_problem_id", assignment: "assignment_id" };

/**
 * Options for a lesson reference (ADM-51): studio tests (every page; a `practice_set` lesson
 * only offers practice-set tests), coding problems, or the course's assignments.
 */
export function useRefOptions(kind: string, courseId: string) {
  const ref = REF_FOR[kind];
  const tests = useApiAll<TestSummary>(ref === "test_id" ? "studio/tests" : null);
  const problems = useApi<{ data: CodingProblemSummary[] }>(ref === "coding_problem_id" ? "studio/coding/problems" : null, { limit: 100 });
  const assignments = useApi<Page<{ id: string; title: string }>>(ref === "assignment_id" ? "assignments" : null, { course_id: courseId, limit: 100 });
  const pick = ref === "test_id" ? tests : ref === "coding_problem_id" ? problems : assignments;
  const data =
    ref === "test_id"
      ? tests.data?.items.filter((t) => kind !== "practice_set" || t.test_kind === "practice_set").map((t) => ({ id: t.id, label: `${t.title} (${t.status})` }))
      : ref === "coding_problem_id"
        ? problems.data?.data.map((p) => ({ id: p.problem_id, label: `${p.title} (${p.status})` }))
        : assignments.data?.data.map((a) => ({ id: a.id, label: a.title }));
  return { ref, state: { data, loading: pick.loading, error: pick.error, reload: pick.reload } };
}

export const REF_NOUN: Record<Ref, string> = { test_id: "test", coding_problem_id: "coding problem", assignment_id: "assignment" };

/* -------------------------------------------------------------------- lesson editor */

/**
 * CMS-003 lesson editor (audit ADM-45 / INV-03): CAT-14 lesson fields and content, CAT-15 topics,
 * MED-01..03 media, CAT-21/22 resources and CAT-20 preview. Only lessons of an editable draft
 * version can change.
 */
export function LessonEditor({
  courseId,
  lesson,
  editable,
  topics,
  onSaved,
}: {
  courseId: string;
  lesson: Lesson;
  editable: boolean;
  topics: ReturnType<typeof useTopics>;
  onSaved: () => void;
}) {
  const toast = useToast();
  const fail = useFailToast();
  const [f, setF] = useState({
    title: lesson.title,
    is_required: lesson.is_required,
    is_free_preview: lesson.is_free_preview,
    duration_min: lesson.duration_seconds ? String(Math.round(lesson.duration_seconds / 60)) : "",
    reading_min: lesson.est_reading_minutes != null ? String(lesson.est_reading_minutes) : "",
    article: docToText(lesson.article_body),
    ref: (REF_FOR[lesson.lesson_type] ? lesson[REF_FOR[lesson.lesson_type]!] : null) ?? "",
    live_url: lesson.live_url ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const refs = useRefOptions(lesson.lesson_type, courseId);

  const body = (): Body<"studio/lessons/{lesson_id}", "patch"> => {
    const out: Body<"studio/lessons/{lesson_id}", "patch"> = {
      title: f.title.trim(),
      is_required: f.is_required,
      is_free_preview: f.is_free_preview,
    };
    if (lesson.lesson_type === "video") out.duration_seconds = f.duration_min ? Math.round(Number(f.duration_min) * 60) : null;
    if (lesson.lesson_type === "article") {
      out.est_reading_minutes = f.reading_min ? Number(f.reading_min) : null;
      out.article_body = f.article.trim() ? textToDoc(f.article) : null;
    }
    if (refs.ref) out[refs.ref] = f.ref || null;
    if (lesson.lesson_type === "live_link") out.live_url = f.live_url.trim() || null;
    return out;
  };

  const save = async () => {
    const e: Record<string, string> = {};
    if (!f.title.trim()) e.title = "Enter a title.";
    if (f.duration_min && !(Number(f.duration_min) >= 0 && Number(f.duration_min) <= 1440)) e.duration_seconds = "Enter minutes between 0 and 1440.";
    if (f.reading_min && !(Number.isInteger(Number(f.reading_min)) && Number(f.reading_min) >= 0 && Number(f.reading_min) <= 600)) e.est_reading_minutes = "Enter whole minutes between 0 and 600.";
    if (lesson.lesson_type === "live_link" && !/^https:\/\//.test(f.live_url.trim())) e.live_url = "Use an https:// link.";
    if (refs.ref && !f.ref) e[refs.ref] = `Choose a ${REF_NOUN[refs.ref]}.`;
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy("save");
    try {
      await api.patch(`studio/lessons/${seg(lesson.id)}`, body());
      toast.show({ tone: "success", title: "Lesson saved" });
      onSaved();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't save the lesson");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <Card title="Lesson">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField label="Title" required error={errors.title}>
            {(p) => <Input {...p} value={f.title} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, title: e.target.value }))} />}
          </FormField>
          {lesson.lesson_type === "video" ? (
            <FormField label="Duration (minutes)" hint="Filled in from the video once it is processed" error={errors.duration_seconds}>
              {(p) => <Input {...p} inputMode="numeric" value={f.duration_min} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, duration_min: e.target.value }))} />}
            </FormField>
          ) : null}
          {lesson.lesson_type === "article" ? (
            <FormField label="Reading time (minutes)" error={errors.est_reading_minutes}>
              {(p) => <Input {...p} inputMode="numeric" value={f.reading_min} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, reading_min: e.target.value }))} />}
            </FormField>
          ) : null}
          {refs.ref ? (
            <FormField label={`Linked ${REF_NOUN[refs.ref]}`} required error={errors[refs.ref]}>
              {(p) => <RefSelect {...p} noun={REF_NOUN[refs.ref!]} state={refs.state} value={f.ref} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, ref: e.target.value }))} />}
            </FormField>
          ) : null}
          {lesson.lesson_type === "live_link" ? (
            <FormField label="Session URL" required error={errors.live_url}>
              {(p) => <Input {...p} type="url" value={f.live_url} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, live_url: e.target.value }))} />}
            </FormField>
          ) : null}
          <div className="flex flex-col gap-2 md:col-span-2">
            <Checkbox label="Required for completion" checked={f.is_required} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, is_required: e.target.checked }))} />
            <Checkbox label="Free preview (visible before purchase)" checked={f.is_free_preview} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, is_free_preview: e.target.checked }))} />
          </div>
          {lesson.lesson_type === "article" ? (
            <div className="md:col-span-2">
              <FormField label="Article" hint="Separate blocks with a blank line. Use ## or ### for headings, - for bullets, 1. for numbered lists." error={errors.article_body}>
                {(p) => <TextArea {...p} rows={10} value={f.article} disabled={!editable} onChange={(e) => setF((x) => ({ ...x, article: e.target.value }))} />}
              </FormField>
            </div>
          ) : null}
        </div>
        {editable ? (
          <Button className="mt-4" loading={busy === "save"} onClick={() => void save()}>
            Save lesson
          </Button>
        ) : null}
      </Card>
      <Card title="Media">
        <LessonMediaPanel lesson={lesson} editable={editable} onChanged={onSaved} />
      </Card>
      <LessonTopics lessonId={lesson.id} editable={editable} topics={topics} initial={lesson.topics} />
      <LessonResources courseId={courseId} lessonId={lesson.id} editable={editable} />
      <LessonPreview lessonId={lesson.id} />
    </div>
  );
}

/* --------------------------------------------------------------------------- topics */

export function LessonTopics({
  lessonId,
  editable,
  topics,
  initial,
}: {
  lessonId: string;
  editable: boolean;
  topics: ReturnType<typeof useTopics>;
  /** The lesson's saved topics (studio `lesson_out.topics`), shown and edited in place. */
  initial?: { topic_id: string; is_primary: boolean }[];
}) {
  const toast = useToast();
  const fail = useFailToast();
  const [chosen, setChosen] = useState<{ topic_id: string; is_primary: boolean }[]>(() => (initial ?? []).map((t) => ({ topic_id: t.topic_id, is_primary: t.is_primary })));
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const nameOf = (id: string) => topics.options.find((t) => t.id === id)?.label ?? id;

  const add = () => {
    if (!pick || chosen.some((c) => c.topic_id === pick) || chosen.length >= 20) return;
    setChosen((xs) => [...xs, { topic_id: pick, is_primary: xs.length === 0 }]);
    setPick("");
  };

  const save = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await api.put(`studio/lessons/${seg(lessonId)}/topics`, { topics: chosen } satisfies Body<"studio/lessons/{lesson_id}/topics", "put">);
      toast.show({ tone: "success", title: "Topics saved" });
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setError(Object.values(fe)[0]);
      else fail(err, "Couldn't save topics");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Topics">
      <p className="mb-3 text-sm text-fg-muted">Tag the lesson with taxonomy topics for practice links and analytics. Saving replaces the lesson&apos;s topics; mark one as primary.</p>
      {chosen.length ? (
        <ul className="mb-3 space-y-1 text-sm" aria-label="Chosen topics">
          {chosen.map((c) => (
            <li key={c.topic_id} className="flex flex-wrap items-center gap-2">
              <span>{nameOf(c.topic_id)}</span>
              {c.is_primary ? (
                <Badge tone="info">Primary</Badge>
              ) : editable ? (
                <Button size="sm" variant="ghost" onClick={() => setChosen((xs) => xs.map((x) => ({ ...x, is_primary: x.topic_id === c.topic_id })))}>
                  Make primary
                </Button>
              ) : null}
              {editable ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setChosen((xs) => {
                      const rest = xs.filter((x) => x.topic_id !== c.topic_id);
                      return c.is_primary && rest.length ? rest.map((x, i) => ({ ...x, is_primary: i === 0 })) : rest;
                    })
                  }
                >
                  Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-sm text-fg-muted">No topics yet.</p>
      )}
      {error ? (
        <p role="alert" className="mb-2 text-sm text-danger-fg">
          {error}
        </p>
      ) : null}
      {editable ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-64 flex-1">
            <FormField label="Topic">{(p) => <TopicSelect {...p} topics={topics} value={pick} onChange={(e) => setPick(e.target.value)} />}</FormField>
          </div>
          <Button variant="secondary" onClick={add} disabled={!pick}>
            Add topic
          </Button>
          <Button onClick={() => void save()} loading={busy}>
            Save topics
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

/* ------------------------------------------------------------------------ resources */

type ResourceType = Body<"studio/resources", "post">["resource_type"];
type Access = NonNullable<Body<"studio/resources", "post">["access_level"]>;

const ACCESS_OPTIONS: { value: Access; label: string }[] = [
  { value: "entitled", label: "Enrolled students" },
  { value: "signed_in", label: "Any signed-in user" },
  { value: "public", label: "Public" },
];

/**
 * CAT-21 create / CAT-22 edit lesson resources. A file is uploaded first (MED-02 `resource_file`,
 * direct to the content bucket) and the returned key is attached. The lesson's resources come
 * from CAT-21b `GET studio/resources?lesson_id=` (every page).
 */
export function LessonResources({ courseId, lessonId, editable }: { courseId: string; lessonId: string; editable: boolean }) {
  const toast = useToast();
  const fail = useFailToast();
  const listed = useApiAll<ResourceOut, "data">("studio/resources", { lesson_id: lessonId, limit: 100 }, { key: "data" });
  const [added, setAdded] = useState<ResourceOut[]>([]);
  const [edited, setEdited] = useState<Record<string, ResourceOut>>({});
  const known = listed.data?.data ?? [];
  const items = [...known, ...added.filter((a) => !known.some((k) => k.id === a.id))].map((r) => edited[r.id] ?? r);
  const [f, setF] = useState({ title: "", type: "link" as ResourceType, access: "entitled" as Access, url: "" });
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<ResourceOut | null>(null);
  const [edit, setEdit] = useState({ title: "", access: "entitled" as Access, url: "" });

  const create = async () => {
    const e: Record<string, string> = {};
    if (!f.title.trim()) e.title = "Enter a title.";
    if (f.type === "file" ? !file : !/^https:\/\//.test(f.url.trim())) e[f.type === "file" ? "s3_key" : "url"] = f.type === "file" ? "Choose a file." : "Use an https:// link.";
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy("create");
    try {
      let s3_key: string | undefined;
      if (f.type === "file" && file) {
        const t = await requestFileUpload({ purpose: "resource_file", filename: file.name, content_type: file.type || "application/octet-stream", size_bytes: file.size, course_id: courseId });
        if (t.kind !== "ok") return;
        await postToProvider(t.data.upload, file);
        s3_key = t.data.s3_key;
      }
      const res = await api.post<ResourceOut>(
        "studio/resources",
        {
          title: f.title.trim(),
          resource_type: f.type,
          access_level: f.access,
          course_id: courseId,
          lesson_id: lessonId,
          ...(s3_key ? { s3_key } : { url: f.url.trim() }),
        } satisfies SendBody<"studio/resources", "post">,
        { idempotencyKey: true },
      );
      if (res.kind === "ok") {
        setAdded((xs) => [...xs, res.data]);
        setF((x) => ({ ...x, title: "", url: "" }));
        setFile(null);
        toast.show({ tone: "success", title: "Resource added" });
      }
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else if (err instanceof Error && err.name === "ProviderUploadError") toast.show({ tone: "danger", title: "Upload failed", description: err.message });
      else fail(err, "Couldn't add the resource");
    } finally {
      setBusy(null);
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    setBusy("edit");
    try {
      const res = await api.patch<ResourceOut>(`studio/resources/${seg(editing.id)}`, {
        title: edit.title.trim(),
        access_level: edit.access,
        ...(editing.has_file ? {} : { url: edit.url.trim() }),
      } satisfies Body<"studio/resources/{resource_id}", "patch">);
      if (res.kind === "ok") setEdited((m) => ({ ...m, [res.data.id]: res.data }));
      setEditing(null);
      toast.show({ tone: "success", title: "Resource updated" });
    } catch (err) {
      fail(err, "Couldn't update the resource");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card title="Resources">
      {listed.error ? (
        <p role="alert" className="mb-2 flex flex-wrap items-center gap-2 text-sm text-danger-fg">
          Couldn&apos;t load this lesson&apos;s resources.
          <Button size="sm" variant="secondary" onClick={() => void listed.reload()}>
            Retry
          </Button>
        </p>
      ) : null}
      {listed.loading && !items.length ? <p className="mb-2 text-sm text-fg-muted">Loading resources…</p> : null}
      {items.length ? (
        <ul className="mb-3 space-y-1 text-sm" aria-label="Lesson resources">
          {items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{r.title}</span>
              <Badge>{r.has_file ? "File" : "Link"}</Badge>
              <span className="text-fg-muted">{ACCESS_OPTIONS.find((a) => a.value === r.access_level)?.label ?? r.access_level}</span>
              {editable ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditing(r);
                    setEdit({ title: r.title, access: r.access_level as Access, url: r.url ?? "" });
                  }}
                >
                  Edit
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-sm text-fg-muted">Attach links, cheat sheets or downloadable files for this lesson.</p>
      )}
      {editable ? (
        <div className="grid gap-3 md:grid-cols-2">
          <FormField label="Resource title" required error={errors.title}>
            {(p) => <Input {...p} value={f.title} onChange={(e) => setF((x) => ({ ...x, title: e.target.value }))} />}
          </FormField>
          <FormField label="Kind">
            {(p) => (
              <Select
                {...p}
                value={f.type}
                onChange={(e) => setF((x) => ({ ...x, type: e.target.value as ResourceType }))}
                options={[
                  { value: "link", label: "Link" },
                  { value: "file", label: "File" },
                  { value: "cheatsheet", label: "Cheat sheet (link)" },
                ]}
              />
            )}
          </FormField>
          <FormField label="Who can open it">{(p) => <Select {...p} value={f.access} onChange={(e) => setF((x) => ({ ...x, access: e.target.value as Access }))} options={ACCESS_OPTIONS} />}</FormField>
          {f.type === "file" ? (
            <FormField label="File" required error={errors.s3_key}>
              {(p) => <input {...p} type="file" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />}
            </FormField>
          ) : (
            <FormField label="URL" required error={errors.url}>
              {(p) => <Input {...p} type="url" value={f.url} onChange={(e) => setF((x) => ({ ...x, url: e.target.value }))} />}
            </FormField>
          )}
          <div className="md:col-span-2">
            <Button variant="secondary" loading={busy === "create"} onClick={() => void create()}>
              Add resource
            </Button>
          </div>
        </div>
      ) : null}
      <Dialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        dismissible={busy !== "edit"}
        title="Edit resource"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={busy === "edit"}>
              Cancel
            </Button>
            <Button loading={busy === "edit"} disabled={!edit.title.trim() || (!editing?.has_file && !/^https:\/\//.test(edit.url.trim()))} onClick={() => void saveEdit()}>
              Save
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Title" required>
            {(p) => <Input {...p} value={edit.title} onChange={(e) => setEdit((x) => ({ ...x, title: e.target.value }))} />}
          </FormField>
          <FormField label="Who can open it">{(p) => <Select {...p} value={edit.access} onChange={(e) => setEdit((x) => ({ ...x, access: e.target.value as Access }))} options={ACCESS_OPTIONS} />}</FormField>
          {!editing?.has_file ? (
            <FormField label="URL" required>
              {(p) => <Input {...p} type="url" value={edit.url} onChange={(e) => setEdit((x) => ({ ...x, url: e.target.value }))} />}
            </FormField>
          ) : null}
        </div>
      </Dialog>
    </Card>
  );
}

/* -------------------------------------------------------------------------- preview */

interface PreviewOut {
  banner: string;
  lesson: Lesson;
}

/** CAT-20 staff preview of a lesson (any version), shown with the api's banner. */
export function LessonPreview({ lessonId }: { lessonId: string }) {
  const [open, setOpen] = useState(false);
  const preview = useApi<PreviewOut>(open ? `studio/lessons/${seg(lessonId)}/preview` : null);
  const p = preview.data;
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Preview lesson
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Lesson preview">
        {preview.error ? (
          <p role="alert" className="text-sm text-danger-fg">
            Couldn&apos;t load the preview.{" "}
            <Button size="sm" variant="secondary" onClick={() => void preview.reload()}>
              Retry
            </Button>
          </p>
        ) : !p ? (
          <p className="text-sm text-fg-muted" aria-busy="true">
            Loading preview…
          </p>
        ) : (
          <div className="space-y-3">
            <Badge tone="warning">{p.banner}</Badge>
            <h3 className="text-lg font-semibold text-fg">{p.lesson.title}</h3>
            <p className="text-sm text-fg-secondary">
              {p.lesson.lesson_type}
              {p.lesson.is_free_preview ? " · free preview" : ""}
              {p.lesson.is_required ? " · required" : " · optional"}
            </p>
            {p.lesson.article_body ? <pre className="whitespace-pre-wrap text-sm text-fg">{docToText(p.lesson.article_body)}</pre> : null}
            {(p.lesson.assets ?? []).length ? (
              <p className="text-sm text-fg-secondary">
                Media: {(p.lesson.assets ?? []).map((a) => `${a.asset_type} (${a.status === "ready" ? "ready" : a.status})`).join(", ")}
              </p>
            ) : (
              <p className="text-sm text-fg-muted">No media attached.</p>
            )}
          </div>
        )}
      </Dialog>
    </>
  );
}
