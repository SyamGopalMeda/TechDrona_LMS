"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Badge, Button, Card, EmptyState, FormField, Input, Select, useToast } from "@/components/ui";
import { Boundary, TextArea, fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { pathsApi, seg } from "../lib/api";
import { formatHours, formatPlanDate } from "../lib/pace";
import type { Allocation, Level, LinkOption, PathDetail, Step, StepIn, StepType } from "../lib/types";
import { AllocateDialog } from "./AllocateDialog";
import { STEP_TYPE_LABEL, StepTypeIcon } from "./bits";
import { usePathsBase } from "../lib/base";

/* ------------------------------------------------------------------ draft model */

export interface EditorStep extends Omit<StepIn, "children"> {
  _k: string;
  children: EditorStep[];
}

let seq = 0;
const localKey = () => `n${++seq}`;

export function toEditor(steps: Step[]): EditorStep[] {
  // `embeddable` is server-computed output; StepIn forbids extra fields, so it never goes back.
  return steps.map(({ embeddable: _out, ...s }) => ({ ...s, _k: s.step_key || localKey(), children: toEditor(s.children ?? []) }));
}

export function toStepIn(steps: EditorStep[]): StepIn[] {
  return steps.map(({ _k: _ignored, children, ...s }) => ({
    ...s,
    est_hours: s.step_type === "super_step" ? 0 : Number(s.est_hours) || 0,
    credits: s.step_type === "super_step" ? 0 : Math.max(0, Math.round(Number(s.credits) || 0)),
    children: s.step_type === "super_step" ? toStepIn(children) : [],
  }));
}

export function newStep(type: StepType): EditorStep {
  return {
    _k: localKey(),
    step_type: type,
    title: "",
    description_md: "",
    est_hours: type === "super_step" ? 0 : 1,
    credits: type === "super_step" ? 0 : 10,
    url: null,
    lesson_id: null,
    assignment_id: null,
    test_id: null,
    article_id: null,
    children: [],
  };
}

export function move<T>(arr: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= arr.length || to >= arr.length) return arr;
  const next = arr.slice();
  const [it] = next.splice(from, 1);
  next.splice(to, 0, it!);
  return next;
}

export function totals(steps: EditorStep[]): { hours: number; credits: number; count: number } {
  let hours = 0;
  let credits = 0;
  let count = 0;
  for (const s of steps) {
    if (s.step_type === "super_step") {
      const t = totals(s.children);
      hours += t.hours;
      credits += t.credits;
      count += t.count;
    } else {
      hours += Number(s.est_hours) || 0;
      credits += Number(s.credits) || 0;
      count += 1;
    }
  }
  return { hours, credits, count };
}

const ADDABLE: StepType[] = ["reading", "video", "article", "assignment", "assessment", "super_step"];

/* ------------------------------------------------------------------ page */

export function PathEditor({ pathId }: { pathId: string }) {
  const state = useApi<PathDetail>(`paths/${seg(pathId)}`);
  return <Boundary state={state}>{(p) => <EditorBody key={`${p.id}:${p.updated_at}`} path={p} reload={state.reload} />}</Boundary>;
}

function EditorBody({ path, reload }: { path: PathDetail; reload: () => Promise<void> }) {
  const base = usePathsBase();
  const router = useRouter();
  const toast = useToast();
  const fail = useFailToast();
  const [title, setTitle] = useState(path.title);
  const [desc, setDesc] = useState(path.description_md ?? "");
  const [level, setLevel] = useState<Level | "">(path.level ?? "");
  const [steps, setSteps] = useState<EditorStep[]>(() => toEditor(path.steps));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<"save" | "publish" | "archive" | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [allocOpen, setAllocOpen] = useState(false);
  const t = useMemo(() => totals(steps), [steps]);

  const update = (next: EditorStep[]) => {
    setSteps(next);
    setDirty(true);
  };
  const metaDirty = title !== path.title || desc !== (path.description_md ?? "") || level !== (path.level ?? "");

  const save = async (): Promise<boolean> => {
    setErrs({});
    try {
      if (metaDirty) await pathsApi.updatePath(path.id, { title: title.trim(), description_md: desc.trim() || null, level: level || null });
      if (dirty) await pathsApi.saveSteps(path.id, toStepIn(steps));
      return true;
    } catch (e) {
      const fe = fieldErrorsOf(e);
      if (Object.keys(fe).length) {
        setErrs(fe);
        toast.show({ tone: "danger", title: "Some steps need attention", description: Object.values(fe)[0] });
      } else fail(e);
      return false;
    }
  };

  const onSave = async () => {
    setBusy("save");
    if (await save()) {
      toast.show({ tone: "success", title: "Path saved" });
      setDirty(false);
      await reload();
    }
    setBusy(null);
  };

  const onPublish = async () => {
    setBusy("publish");
    try {
      if ((dirty || metaDirty) && !(await save())) return;
      const p = await pathsApi.publish(path.id);
      toast.show({ tone: "success", title: `Published version ${p.version_no}` });
      setDirty(false);
      await reload();
    } catch (e) {
      const fe = fieldErrorsOf(e);
      if (Object.keys(fe).length) setErrs(fe);
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const onArchive = async () => {
    if (!window.confirm(`Archive "${path.title}"? Learners keep their current allocations.`)) return;
    setBusy("archive");
    try {
      await pathsApi.archivePath(path.id);
      router.push(base);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href={base} className="text-sm text-fg-link underline">
            ← All paths
          </Link>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge tone={path.status === "published" ? "success" : "neutral"}>{path.status === "published" ? `Published v${path.version_no}` : path.status === "archived" ? "Archived" : "Draft"}</Badge>
            {path.has_unpublished_changes || dirty || metaDirty ? <Badge tone="warning">Unpublished changes</Badge> : null}
            <span className="text-sm text-fg-muted">
              {t.count} steps · {t.credits} credits · {formatHours(t.hours)}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => void onArchive()} loading={busy === "archive"} disabled={!!busy || path.status === "archived"}>
            Archive
          </Button>
          <Button variant="secondary" onClick={() => void onSave()} loading={busy === "save"} disabled={!!busy || (!dirty && !metaDirty)}>
            Save
          </Button>
          <Button onClick={() => void onPublish()} loading={busy === "publish"} disabled={!!busy || path.status === "archived"}>
            Publish
          </Button>
        </div>
      </div>

      <Card>
        <div className="grid gap-3 md:grid-cols-[1fr_12rem]">
          <FormField label="Title" required error={errs.title}>{(p) => <Input {...p} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />}</FormField>
          <FormField label="Level">
            {(p) => (
              <Select
                {...p}
                value={level}
                onChange={(e) => setLevel(e.target.value as Level | "")}
                options={[
                  { value: "", label: "Not set" },
                  { value: "beginner", label: "Beginner" },
                  { value: "intermediate", label: "Intermediate" },
                  { value: "advanced", label: "Advanced" },
                ]}
              />
            )}
          </FormField>
        </div>
        <div className="mt-3">
          <FormField label="Description" error={errs.description_md}>{(p) => <TextArea {...p} rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />}</FormField>
        </div>
      </Card>

      <section aria-labelledby="steps-h" className="space-y-3">
        <h2 id="steps-h" className="font-display text-lg font-semibold">
          Steps
        </h2>
        {steps.length === 0 ? <EmptyState title="No steps yet" description="Add readings, videos, articles, assignments, assessments or a super-step that groups several steps." /> : null}
        <StepList steps={steps} onChange={update} errs={errs} prefix="steps" numberPrefix="" />
        <AddStepBar onAdd={(type) => update([...steps, newStep(type)])} />
      </section>

      <AllocationsSection path={path} onAllocate={() => setAllocOpen(true)} reload={reload} />
      <AllocateDialog open={allocOpen} onClose={() => setAllocOpen(false)} path={path} onDone={() => void reload()} />
    </div>
  );
}

function AddStepBar({ onAdd, allowSuper = true }: { onAdd: (t: StepType) => void; allowSuper?: boolean }) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Add a step">
      {ADDABLE.filter((t) => allowSuper || t !== "super_step").map((t) => (
        <Button key={t} variant="secondary" size="sm" onClick={() => onAdd(t)}>
          + {STEP_TYPE_LABEL[t]}
        </Button>
      ))}
    </div>
  );
}

function StepList({
  steps,
  onChange,
  errs,
  prefix,
  numberPrefix,
}: {
  steps: EditorStep[];
  onChange: (s: EditorStep[]) => void;
  errs: Record<string, string>;
  prefix: string;
  numberPrefix: string;
}) {
  const dragFrom = useRef<number | null>(null);
  const [over, setOver] = useState<number | null>(null);

  const onDragStart = (i: number) => (e: DragEvent) => {
    dragFrom.current = i;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(i));
    e.stopPropagation();
  };
  const onDrop = (i: number) => (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const from = dragFrom.current;
    dragFrom.current = null;
    setOver(null);
    if (from !== null) onChange(move(steps, from, i));
  };

  return (
    <ol className="space-y-3">
      {steps.map((s, i) => (
        <li
          key={s._k}
          onDragOver={(e) => {
            if (dragFrom.current === null) return;
            e.preventDefault();
            e.stopPropagation();
            setOver(i);
          }}
          onDragLeave={() => setOver((o) => (o === i ? null : o))}
          onDrop={onDrop(i)}
          className={over === i ? "rounded-xl ring-2 ring-brand" : undefined}
        >
          <StepCard
            step={s}
            number={`${numberPrefix}${i + 1}`}
           
            errs={errs}
            field={`${prefix}[${i}]`}
            onDragStart={onDragStart(i)}
            onChange={(n) => onChange(steps.map((x, j) => (j === i ? n : x)))}
            onRemove={() => onChange(steps.filter((_, j) => j !== i))}
            onUp={i > 0 ? () => onChange(move(steps, i, i - 1)) : undefined}
            onDown={i < steps.length - 1 ? () => onChange(move(steps, i, i + 1)) : undefined}
          />
        </li>
      ))}
    </ol>
  );
}

function errorFor(errs: Record<string, string>, field: string, name: string): string | undefined {
  return errs[`${field}.${name}`] ?? errs[`body.${field}.${name}`];
}

function StepCard({
  step,
  number,
  errs,
  field,
  onChange,
  onRemove,
  onUp,
  onDown,
  onDragStart,
}: {
  step: EditorStep;
  number: string;
  errs: Record<string, string>;
  field: string;
  onChange: (s: EditorStep) => void;
  onRemove: () => void;
  onUp?: () => void;
  onDown?: () => void;
  onDragStart: (e: DragEvent) => void;
}) {
  const set = (patch: Partial<EditorStep>) => onChange({ ...step, ...patch });
  const isSuper = step.step_type === "super_step";
  const sub = isSuper ? totals(step.children) : null;
  const label = STEP_TYPE_LABEL[step.step_type];
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-xs">
      <div className="flex items-center gap-2">
        <span draggable onDragStart={onDragStart} className="cursor-grab select-none px-1 text-fg-muted" title="Drag to reorder" aria-hidden="true">
          ⋮⋮
        </span>
        <span className="text-sm font-semibold tabular-nums text-fg-muted">{number}.</span>
        <StepTypeIcon type={step.step_type} />
        <span className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{label}</span>
        <div className="ml-auto flex gap-1">
          <Button variant="ghost" size="sm" onClick={onUp} disabled={!onUp} aria-label={`Move step ${number} up`}>
            ↑
          </Button>
          <Button variant="ghost" size="sm" onClick={onDown} disabled={!onDown} aria-label={`Move step ${number} down`}>
            ↓
          </Button>
          <Button variant="ghost" size="sm" onClick={onRemove} aria-label={`Delete step ${number}`}>
            🗑
          </Button>
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_7rem_7rem]">
        <FormField label="Title" required error={errorFor(errs, field, "title")}>{(p) => <Input {...p} value={step.title} maxLength={200} onChange={(e) => set({ title: e.target.value })} />}</FormField>
        {isSuper ? (
          <>
            <div className="text-sm">
              <p className="font-medium">Hours</p>
              <p className="mt-2 text-fg-muted">{formatHours(sub!.hours)}</p>
            </div>
            <div className="text-sm">
              <p className="font-medium">Credits</p>
              <p className="mt-2 text-fg-muted">{sub!.credits}</p>
            </div>
          </>
        ) : (
          <>
            <FormField label="Hours" error={errorFor(errs, field, "est_hours")}>
              {(p) => <Input {...p} type="number" min={0} max={200} step={0.25} value={String(step.est_hours)} onChange={(e) => set({ est_hours: Number(e.target.value) })} />}
            </FormField>
            <FormField label="Credits" error={errorFor(errs, field, "credits")}>
              {(p) => <Input {...p} type="number" min={0} max={1000} step={1} value={String(step.credits)} onChange={(e) => set({ credits: Number(e.target.value) })} />}
            </FormField>
          </>
        )}
      </div>
      <div className="mt-3">
        <FormField label="Description">{(p) => <TextArea {...p} rows={2} value={step.description_md ?? ""} onChange={(e) => set({ description_md: e.target.value })} />}</FormField>
      </div>
      <div className="mt-3">
        <StepLinkEditor step={step} set={set} error={errorFor(errs, field, "url") ?? errorFor(errs, field, "link") ?? errorFor(errs, field, `${linkField(step.step_type)}`)} />
      </div>
      {isSuper ? (
        <div className="mt-4 space-y-3 border-l-2 border-line pl-4">
          <StepList steps={step.children} onChange={(c) => set({ children: c })} errs={errs} prefix={`${field}.children`} numberPrefix={`${number}.`} />
          <AddStepBar allowSuper={false} onAdd={(type) => set({ children: [...step.children, newStep(type)] })} />
        </div>
      ) : null}
    </div>
  );
}

function linkField(t: StepType): string {
  switch (t) {
    case "article":
      return "article_id";
    case "assignment":
      return "assignment_id";
    case "assessment":
      return "test_id";
    default:
      return "url";
  }
}

function StepLinkEditor({ step, set, error }: { step: EditorStep; set: (p: Partial<EditorStep>) => void; error?: string }) {
  const base = usePathsBase();
  switch (step.step_type) {
    case "reading":
    case "video":
      return (
        <div className="grid gap-3 md:grid-cols-2">
          <FormField label={step.step_type === "video" ? "Video URL (https)" : "Page URL (https)"} hint="Or link a lesson from your courses instead." error={error}>
            {(p) => <Input {...p} type="url" inputMode="url" placeholder="https://" value={step.url ?? ""} onChange={(e) => set({ url: e.target.value || null })} />}
          </FormField>
          <LinkPicker label="Course lesson (optional)" kind="lesson" value={step.lesson_id} onChange={(id) => set({ lesson_id: id })} />
        </div>
      );
    case "article":
      return (
        <div className="space-y-1">
          <LinkPicker label="Article" kind="article" value={step.article_id} onChange={(id) => set({ article_id: id })} error={error} />
          <p className="text-xs text-fg-muted">
            Write articles in{" "}
            <Link href={`${base}/articles`} className="text-fg-link underline">
              Articles
            </Link>
            .
          </p>
        </div>
      );
    case "assignment":
      return <LinkPicker label="Assignment (learners complete it in Assignments; credits release once it is graded)" kind="assignment" value={step.assignment_id} onChange={(id) => set({ assignment_id: id })} error={error} />;
    case "assessment":
      return <LinkPicker label="Test (completes when the learner passes)" kind="test" value={step.test_id} onChange={(id) => set({ test_id: id })} error={error} />;
    default:
      return null;
  }
}

export function LinkPicker({
  label,
  kind,
  value,
  onChange,
  error,
}: {
  label: string;
  kind: "assignment" | "test" | "article" | "lesson";
  value: string | null;
  onChange: (id: string | null) => void;
  error?: string;
}) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);
  const opts = useApi<{ data: LinkOption[] }>("paths/link-options", { kind, q: query || undefined });
  const list = opts.data?.data ?? [];
  const options = [
    { value: "", label: opts.loading ? "Loading…" : "Not linked" },
    ...(value && !list.some((o) => o.id === value) ? [{ value, label: "Currently linked item" }] : []),
    ...list.map((o) => ({ value: o.id, label: o.meta ? `${o.title} · ${o.meta}` : o.title })),
  ];
  return (
    <FormField label={label} error={error}>
      {(p) => (
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input type="search" aria-label={`Search ${kind}s`} placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="sm:w-40" />
          <Select {...p} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} options={options} />
        </div>
      )}
    </FormField>
  );
}

function AllocationsSection({ path, onAllocate, reload }: { path: PathDetail; onAllocate: () => void; reload: () => Promise<void> }) {
  const base = usePathsBase();
  const fail = useFailToast();
  const active = path.allocations.filter((a) => a.status === "active");
  const revoke = async (a: Allocation) => {
    if (!window.confirm("Remove this allocation? Learners will no longer see the path.")) return;
    try {
      await pathsApi.revokeAllocation(a.id);
      await reload();
    } catch (e) {
      fail(e);
    }
  };
  return (
    <Card
      title="Allocated to"
      actions={
        <Button onClick={onAllocate} disabled={path.status !== "published"}>
          Allocate
        </Button>
      }
    >
      {path.status !== "published" ? <p className="mb-3 text-sm text-fg-muted">Publish the path first, then allocate it to a batch or learners.</p> : null}
      {active.length === 0 ? (
        <p className="text-sm text-fg-muted">Not allocated yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {active.map((a) => (
            <li key={a.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm">
                <p className="font-medium">{a.target_type === "batch" ? (a.batch_name ?? "Batch") : `${a.user_ids.length} learner${a.user_ids.length === 1 ? "" : "s"}`}</p>
                <p className="text-fg-muted">
                  v{a.version_no} · {a.flow === "strict" ? "Strict" : "Lenient"} · {a.sequential ? "Sequential" : "Any order"} · {a.learner_count} learners · finishes {formatPlanDate(a.finish_date)}
                </p>
              </div>
              <div className="flex gap-2">
                <Link href={`${base}/allocations/${encodeURIComponent(a.id)}`} className="inline-flex h-8 items-center rounded-md border border-line-control px-3 text-sm font-medium hover:bg-surface-hover">
                  Progress
                </Link>
                <Button variant="ghost" size="sm" onClick={() => void revoke(a)}>
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
