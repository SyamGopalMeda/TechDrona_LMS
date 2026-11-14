"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Checkbox, ErrorState, FormField, Input, LinkButton, PageHeader, Select, StatusBadge, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { LoadingBlock, TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { fmtMarks, itemTypeLabel, staffApi, stripHtml, truncate } from "./api";
import { QuestionBankPicker } from "@/features/question-bank";
import type { RenderBankPicker } from "./bank-picker";
import { AllocateDialog } from "./AllocateDialog";
import { AllocationsPanel } from "./AllocationsPanel";
import {
  allocatedMarks,
  duplicateSection,
  emptySection,
  fromPicked,
  inlineItem,
  sectionMarks,
  toDraft,
  toStructureIn,
  zeroMarkItems,
  type DraftItem,
  type DraftSection,
} from "./draft";
import type { InlineItemType, StructureOut } from "./types";

/** "allocated / total" pill: success when equal, warning otherwise. */
export function MarksMeter({ allocated, total }: { allocated: number; total: number }) {
  const ok = total > 0 && Math.abs(allocated - total) < 0.005;
  return (
    <span
      role="status"
      aria-label={`${fmtMarks(allocated)} of ${fmtMarks(total)} marks allocated`}
      className={
        ok
          ? "inline-flex items-center gap-1 rounded-full border border-success-border bg-success-subtle px-3 py-1 text-sm font-medium tabular-nums text-success-fg"
          : "inline-flex items-center gap-1 rounded-full border border-warning-border bg-warning-subtle px-3 py-1 text-sm font-medium tabular-nums text-warning-fg"
      }
    >
      {ok ? <span aria-hidden="true">✓</span> : null}
      {fmtMarks(allocated)} / {fmtMarks(total)} allocated
    </span>
  );
}

export function marksWarning(allocated: number, total: number, zeroItems: number): string | null {
  if (total > 0 && Math.abs(allocated - total) < 0.005) return null;
  const tail = zeroItems ? ` ${zeroItems} question${zeroItems === 1 ? " has" : "s have"} 0 marks.` : "";
  return `Question marks add up to ${fmtMarks(allocated)}, but the total is ${fmtMarks(total)}. Adjust the marks so they match before allocating.${tail}`;
}

const INLINE_TYPES: { value: InlineItemType; label: string }[] = [
  { value: "essay", label: "Essay" },
  { value: "short_text", label: "Short answer" },
  { value: "file", label: "File upload" },
];

function InlineQuestionForm({ onAdd, onCancel }: { onAdd: (i: DraftItem) => void; onCancel: () => void }) {
  const [type, setType] = useState<InlineItemType>("essay");
  const [prompt, setPrompt] = useState("");
  const [marks, setMarks] = useState("0");
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="mt-3 space-y-3 rounded-lg border border-dashed border-line-strong p-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
        <FormField label="Question type">
          {(p) => <Select {...p} value={type} onChange={(e) => setType(e.target.value as InlineItemType)} options={INLINE_TYPES} />}
        </FormField>
        <FormField label="Marks">
          {(p) => <Input {...p} type="number" min={0} inputMode="decimal" value={marks} onChange={(e) => setMarks(e.target.value)} />}
        </FormField>
      </div>
      <FormField label="Question" required error={err ?? undefined}>
        {(p) => <TextArea {...p} rows={3} maxLength={20000} value={prompt} onChange={(e) => setPrompt(e.target.value)} />}
      </FormField>
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() => {
            if (!prompt.trim()) return setErr("Write the question.");
            onAdd(inlineItem(type, prompt.trim(), Math.max(0, Number(marks) || 0)));
          }}
        >
          Add question
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function SectionBlock({
  section,
  index,
  locked,
  canDelete,
  onChange,
  onDuplicate,
  onDelete,
  onImport,
}: {
  section: DraftSection;
  index: number;
  locked: boolean;
  canDelete: boolean;
  onChange: (s: DraftSection) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onImport: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const marks = sectionMarks(section);
  const setItem = (key: string, patch: Partial<DraftItem>) => onChange({ ...section, items: section.items.map((i) => (i.key === key ? { ...i, ...patch } : i)) });
  return (
    <Card>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex-1">
          <FormField label={`Section ${index + 1} title`}>
            {(p) => <Input {...p} value={section.title} maxLength={200} disabled={locked} onChange={(e) => onChange({ ...section, title: e.target.value })} />}
          </FormField>
        </div>
        <p className="text-sm tabular-nums text-fg-muted">
          {section.items.length} q · {fmtMarks(marks)} marks
        </p>
      </div>
      {!locked ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" onClick={onImport}>
            Import from bank
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setAdding(true)} disabled={adding}>
            Add written question
          </Button>
          <Button size="sm" variant="secondary" onClick={onDuplicate} aria-label={`Duplicate section ${index + 1}`}>
            Duplicate
          </Button>
          {canDelete ? (
            <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Delete section ${index + 1}`}>
              Delete section
            </Button>
          ) : null}
        </div>
      ) : null}
      {adding ? (
        <InlineQuestionForm
          onAdd={(i) => {
            onChange({ ...section, items: [...section.items, i] });
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : null}
      {section.items.length === 0 ? (
        <p className="mt-3 text-sm text-fg-muted">No questions in this section yet. Import some from the bank or add a written question.</p>
      ) : (
        <ol className="mt-3 divide-y divide-line" aria-label={`Questions in ${section.title || `section ${index + 1}`}`}>
          {section.items.map((it, n) => {
            const text = truncate(it.prompt_md ?? stripHtml(it.stem_html) ?? "", 140) || "Untitled question";
            return (
              <li key={it.key} className="flex flex-wrap items-center gap-3 py-2">
                <span className="w-6 text-sm tabular-nums text-fg-muted">{n + 1}.</span>
                <Badge tone={it.item_type === "coding" ? "info" : "neutral"}>{itemTypeLabel(it.item_type)}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm text-fg" title={text}>
                  {text}
                </span>
                <span className="flex items-center gap-1 text-xs text-fg-muted">
                  <Input
                    aria-label={`Marks for question ${n + 1}`}
                    type="number"
                    min={0}
                    inputMode="decimal"
                    className="h-8 w-20"
                    value={it.marks}
                    disabled={locked}
                    onChange={(e) => setItem(it.key, { marks: e.target.value })}
                  />
                  <span aria-hidden="true">marks</span>
                </span>
                {!locked ? (
                  <Button size="sm" variant="ghost" aria-label={`Remove question ${n + 1}`} onClick={() => onChange({ ...section, items: section.items.filter((x) => x.key !== it.key) })}>
                    Remove
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

interface Settings {
  title: string;
  total: string;
  aiEnabled: boolean;
  aiLimit: string;
}

function settingsOf(s: StructureOut): Settings {
  return {
    title: s.assignment.title,
    total: String(s.assignment.max_score),
    aiEnabled: !!s.assignment.ai_help_enabled,
    aiLimit: s.assignment.ai_help_limit === null || s.assignment.ai_help_limit === undefined ? "" : String(s.assignment.ai_help_limit),
  };
}

/** Trainer assignment editor: settings, sections/questions with marks, allocations. */
export function AssignmentEditor({ assignmentId, renderPicker }: { assignmentId: string; renderPicker?: RenderBankPicker }) {
  const toast = useToast();
  const fail = useFailToast();
  const [data, setData] = useState<StructureOut | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [sections, setSections] = useState<DraftSection[]>([]);
  const [settings, setSettings] = useState<Settings>({ title: "", total: "", aiEnabled: false, aiLimit: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saveIssues, setSaveIssues] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pickerFor, setPickerFor] = useState<string | null>(null);
  const [allocating, setAllocating] = useState(false);

  const apply = useCallback((s: StructureOut) => {
    setData(s);
    setSections(toDraft(s.sections));
    setSettings(settingsOf(s));
    setDirty(false);
  }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      apply(await staffApi.structure(assignmentId));
    } catch (err) {
      setLoadError(err);
    }
  }, [assignmentId, apply]);

  useEffect(() => {
    void load();
  }, [load]);

  const crumbs = [{ label: "Assignments", href: "/trainer/assignments" }];
  if (loadError)
    return (
      <>
        <PageHeader title="Edit assignment" breadcrumbs={[...crumbs, { label: "Edit assignment" }]} />
        <ErrorState error={loadError} onRetry={() => void load()} />
      </>
    );
  if (!data)
    return (
      <>
        <PageHeader title="Edit assignment" breadcrumbs={[...crumbs, { label: "Edit assignment" }]} />
        <LoadingBlock rows={4} />
      </>
    );

  const locked = data.locked;
  const total = Number(settings.total) || 0;
  const allocated = allocatedMarks(sections);
  const warning = marksWarning(allocated, total, zeroMarkItems(sections));

  const edit = (next: DraftSection[]) => {
    setSections(next);
    setDirty(true);
  };
  const editSettings = (patch: Partial<Settings>) => {
    setSettings((s) => ({ ...s, ...patch }));
    setDirty(true);
  };

  const save = async (): Promise<boolean> => {
    const errs: Record<string, string> = {};
    if (!settings.title.trim()) errs.title = "Enter a name.";
    if (!(total > 0)) errs.max_score = "Total marks must be more than 0.";
    const limit = settings.aiLimit.trim();
    if (limit && (!/^\d+$/.test(limit) || Number(limit) < 0)) errs.ai_help_limit = "Use a whole number, or leave empty for unlimited.";
    setErrors(errs);
    setSaveIssues([]);
    if (Object.keys(errs).length) return false;
    setSaving(true);
    try {
      const base = settingsOf(data);
      const changed =
        base.title !== settings.title.trim() || base.total !== settings.total || base.aiEnabled !== settings.aiEnabled || base.aiLimit !== limit;
      if (changed) {
        await staffApi.patch(assignmentId, {
          title: settings.title.trim(),
          ...(locked ? {} : { max_score: total }),
          ai_help_enabled: settings.aiEnabled,
          ai_help_limit: limit ? Number(limit) : null,
        });
      }
      const next = locked ? await staffApi.structure(assignmentId) : await staffApi.saveStructure(assignmentId, toStructureIn(sections));
      apply(next);
      setSaveIssues(next.marks.ok ? [] : next.marks.issues.map((i) => i.message));
      toast.show({ tone: "success", title: next.marks.ok ? "Assignment saved" : "Draft saved", description: next.marks.ok ? undefined : "Marks still need to add up before you allocate." });
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.code === "assignment_locked") {
        toast.show({ tone: "warning", title: "Learners have already started", description: "Questions and total marks can no longer change." });
        await load();
      } else if (err instanceof ApiError && err.problem?.errors?.length) {
        const fe: Record<string, string> = {};
        for (const e of err.problem.errors) {
          const k = e.field.replace(/^body\./, "");
          if (k === "title" || k === "max_score" || k === "ai_help_limit") fe[k] ??= e.message;
        }
        setErrors(fe);
        setSaveIssues(err.problem.errors.filter((e) => !(e.field.replace(/^body\./, "") in fe)).map((e) => e.message));
      } else {
        fail(err, "Couldn't save the assignment");
      }
      return false;
    } finally {
      setSaving(false);
    }
  };

  const openAllocate = async () => {
    if (dirty && !locked && !(await save())) return;
    setAllocating(true);
  };

  const pickerProps = {
    open: pickerFor !== null,
    onClose: () => setPickerFor(null),
    onAdd: (qs: Parameters<typeof fromPicked>[0][]) => {
      const key = pickerFor;
      if (!key) return;
      edit(sections.map((s) => (s.key === key ? { ...s, items: [...s.items, ...qs.filter((q) => !s.items.some((i) => i.question_id === q.question_id)).map(fromPicked)] } : s)));
    },
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={data.assignment.title}
        breadcrumbs={[...crumbs, { label: data.assignment.title }]}
        meta={<StatusBadge status={data.assignment.status ?? "draft"} />}
        description={locked ? "Read-only: learners have started" : dirty ? "Unsaved changes" : undefined}
        actions={
          <>
            <LinkButton variant="secondary" href={`/trainer/grading/assignments/${encodeURIComponent(assignmentId)}`}>
              Evaluate
            </LinkButton>
            <Button variant="secondary" onClick={() => void save()} loading={saving} disabled={!dirty}>
              Save
            </Button>
            <Button onClick={() => void openAllocate()} disabled={saving || sections.length === 0}>
              Allocate
            </Button>
          </>
        }
      />

      {locked ? (
        <p role="note" className="rounded-lg border border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          Learners have already started this assignment, so its questions and marks are locked to keep grading fair. You can still rename it, change AI help,
          manage allocations and grant extensions — or clone it to build a new version.
        </p>
      ) : null}

      <Card>
        <div className="grid gap-4 md:grid-cols-[1fr_10rem_auto] md:items-end">
          <FormField label="Assignment name" required error={errors.title}>
            {(p) => <Input {...p} value={settings.title} maxLength={200} onChange={(e) => editSettings({ title: e.target.value })} />}
          </FormField>
          <FormField label="Total marks" required error={errors.max_score}>
            {(p) => <Input {...p} type="number" min={1} inputMode="decimal" disabled={locked} value={settings.total} onChange={(e) => editSettings({ total: e.target.value })} />}
          </FormField>
          <div className="pb-1">
            <MarksMeter allocated={allocated} total={total} />
          </div>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-[1fr_14rem] md:items-start">
          <Checkbox
            label="AI tutor while working (Guide & Explain)"
            description="Learners can ask the AI tutor for hints and explanations. It never hands over a full answer."
            checked={settings.aiEnabled}
            onChange={(e) => editSettings({ aiEnabled: e.target.checked })}
          />
          <FormField label="Interactions per learner" hint="Leave empty for unlimited. Your organization's AI limit still applies." error={errors.ai_help_limit}>
            {(p) => (
              <Input
                {...p}
                type="number"
                min={0}
                inputMode="numeric"
                placeholder="Unlimited"
                disabled={!settings.aiEnabled}
                value={settings.aiLimit}
                onChange={(e) => editSettings({ aiLimit: e.target.value })}
              />
            )}
          </FormField>
        </div>
        {warning ? (
          <p role="alert" className="mt-4 rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
            {warning}
          </p>
        ) : null}
        {saveIssues.length ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-warning-fg" aria-label="Issues to fix">
            {saveIssues.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        ) : null}
      </Card>

      <div className="space-y-4">
        {sections.map((s, i) => (
          <SectionBlock
            key={s.key}
            section={s}
            index={i}
            locked={locked}
            canDelete={sections.length > 1}
            onChange={(next) => edit(sections.map((x) => (x.key === s.key ? next : x)))}
            onDuplicate={() => edit([...sections.slice(0, i + 1), duplicateSection(s), ...sections.slice(i + 1)])}
            onDelete={() => edit(sections.filter((x) => x.key !== s.key))}
            onImport={() => setPickerFor(s.key)}
          />
        ))}
        {!locked ? (
          <Button variant="secondary" onClick={() => edit([...sections, emptySection(sections.length + 1)])}>
            Add section
          </Button>
        ) : null}
      </div>

      <AllocationsPanel
        allocations={data.allocations}
        sections={data.sections.map((s) => ({ id: s.id, title: s.title }))}
        onChanged={load}
        onAllocate={sections.length ? () => void openAllocate() : undefined}
      />

      {renderPicker ? (
        renderPicker(pickerProps)
      ) : (
        <QuestionBankPicker
          open={pickerProps.open}
          onClose={pickerProps.onClose}
          onPick={(qs) => pickerProps.onAdd(qs.map((q) => ({ question_id: q.question_id, question_version_id: q.question_version_id, question_type: q.question_type, stem_html: q.stem_html })))}
          excludeQuestionIds={sections.find((s) => s.key === pickerFor)?.items.flatMap((i) => (i.question_id ? [i.question_id] : []))}
          description="The selected questions are added to this section. Set their marks afterwards."
        />
      )}
      <AllocateDialog
        open={allocating}
        onClose={() => setAllocating(false)}
        assignment={data.assignment}
        sections={data.sections.map((s) => ({ id: s.id, title: s.title }))}
        marksOk={data.marks.ok}
        onAllocated={load}
      />
    </div>
  );
}
