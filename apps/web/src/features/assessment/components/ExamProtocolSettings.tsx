"use client";

import { Card, Checkbox, FormField, Input } from "@/components/ui";
import { RECORDABLE_EVENTS, type RecordableEvent } from "../lib/types";

/** Labels for the recordable events (server: exam.EVENT_LABELS). */
export const EVENT_LABELS: Record<RecordableEvent, string> = {
  focus_lost: "Tab switches",
  window_blur: "Window inactive",
  copy: "Copy",
  cut: "Cut",
  paste: "Paste",
  resize: "Window resized",
  fullscreen_exit: "Left full screen",
  right_click: "Right click",
};

/** Server defaults (exam.py): used when the author leaves a field empty. */
export const DEFAULT_EXAM_EVENTS: RecordableEvent[] = ["focus_lost", "window_blur", "copy", "cut", "paste", "resize", "fullscreen_exit"];
export const DEFAULT_TYPE_THRESHOLD = 3;
export const DEFAULT_FLAG_THRESHOLD = 5;

export type IntegrityDraft = Record<string, unknown>;

const num = (v: unknown): string => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");
const toNum = (v: string): number | null => (v.trim() === "" ? null : Number(v));

/** Client checks mirroring schemas.IntegritySettings (keys = api `errors[].field` paths). */
export function validateProtocol(d: IntegrityDraft): Record<string, string> {
  const e: Record<string, string> = {};
  const inRange = (v: unknown) => v === null || v === undefined || (typeof v === "number" && Number.isInteger(v) && v >= 1 && v <= 1000);
  if (!inRange(d.flag_threshold)) e["integrity_settings.flag_threshold"] = "Between 1 and 1000.";
  if (!inRange(d.auto_submit_after)) e["integrity_settings.auto_submit_after"] = "Between 1 and 1000, or leave empty.";
  const wt = (d.warn_thresholds ?? {}) as Record<string, unknown>;
  for (const [k, v] of Object.entries(wt)) if (!inRange(v)) e[`integrity_settings.warn_thresholds.${k}`] = "Between 1 and 1000.";
  if (typeof d.conduct_instructions === "string" && d.conduct_instructions.length > 5000) e["integrity_settings.conduct_instructions"] = "At most 5000 characters.";
  return e;
}

/**
 * Exam protocol settings (stored in `tests.integrity_settings`): agreement screen, conduct
 * instructions, recorded events, per-event thresholds, auto-flag threshold, optional auto-submit.
 * AI hints are always off in exams (shown, not editable).
 */
export function ExamProtocolSettings({
  value,
  onChange,
  disabled,
  errors = {},
}: {
  value: IntegrityDraft;
  onChange: (next: IntegrityDraft) => void;
  disabled?: boolean;
  errors?: Record<string, string>;
}) {
  const exam = !!value.exam_mode;
  const events = (Array.isArray(value.record_events) ? value.record_events : DEFAULT_EXAM_EVENTS) as RecordableEvent[];
  const thresholds = (value.warn_thresholds ?? {}) as Partial<Record<RecordableEvent, number>>;
  const set = (patch: IntegrityDraft) => onChange({ ...value, ...patch });
  const toggleEvent = (e: RecordableEvent, on: boolean) => {
    const next = on ? [...new Set([...events, e])] : events.filter((x) => x !== e);
    set({ record_events: RECORDABLE_EVENTS.filter((x) => next.includes(x)) });
  };
  const setThreshold = (e: RecordableEvent, raw: string) => {
    const n = toNum(raw);
    const next = { ...thresholds };
    if (n === null) delete next[e];
    else next[e] = n;
    set({ warn_thresholds: next });
  };
  return (
    <Card title="Exam protocol">
      <fieldset disabled={disabled} className="space-y-4">
        <legend className="sr-only">Exam protocol settings</legend>
        <Checkbox
          label="Run as an invigilated exam"
          description="Candidates agree to the conduct instructions before the timer starts; the events below are recorded and shown to evaluators."
          checked={exam}
          onChange={(e) => set({ exam_mode: e.target.checked, ...(e.target.checked ? { require_agreement: true } : {}) })}
        />
        <Checkbox label="AI hints during the exam" description="Always off in exams." checked={false} disabled onChange={() => undefined} />
        {exam ? (
          <>
            <FormField label="Conduct instructions" hint="Shown on the agreement screen. Leave empty for the standard text." error={errors["integrity_settings.conduct_instructions"]}>
              {(p) => (
                <textarea
                  {...p}
                  rows={4}
                  maxLength={5000}
                  className="w-full rounded-md border border-line-control bg-surface px-3 py-2 text-sm text-fg"
                  value={typeof value.conduct_instructions === "string" ? value.conduct_instructions : ""}
                  onChange={(e) => set({ conduct_instructions: e.target.value || null })}
                />
              )}
            </FormField>
            <Checkbox
              label="Require full screen"
              description="Candidates enter full screen when they start; leaving it is recorded."
              checked={!!value.require_fullscreen}
              onChange={(e) => set({ require_fullscreen: e.target.checked })}
            />
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-fg">Events to record · flag at (count per event)</legend>
              <div className="grid gap-2 md:grid-cols-2">
                {RECORDABLE_EVENTS.map((e) => (
                  <div key={e} className="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
                    <Checkbox label={EVENT_LABELS[e]} checked={events.includes(e)} onChange={(ev) => toggleEvent(e, ev.target.checked)} />
                    <label className="flex items-center gap-1 text-xs text-fg-muted">
                      <span>≥</span>
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        aria-label={`${EVENT_LABELS[e]} threshold`}
                        className="w-16 rounded border border-line-control bg-surface px-2 py-1 text-sm text-fg"
                        placeholder={String(DEFAULT_TYPE_THRESHOLD)}
                        disabled={!events.includes(e) || disabled}
                        value={num(thresholds[e])}
                        onChange={(ev) => setThreshold(e, ev.target.value)}
                      />
                    </label>
                  </div>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-3 md:grid-cols-2">
              <FormField label="Flag for review after (total events)" hint={`Default ${DEFAULT_FLAG_THRESHOLD}`} error={errors["integrity_settings.flag_threshold"]}>
                {(p) => (
                  <Input
                    {...p}
                    type="number"
                    min={1}
                    max={1000}
                    value={num(value.flag_threshold)}
                    placeholder={String(DEFAULT_FLAG_THRESHOLD)}
                    onChange={(e) => set({ flag_threshold: toNum(e.target.value) })}
                  />
                )}
              </FormField>
              <FormField
                label="Auto-submit after (total events)"
                hint="Optional and off by default. The attempt is still graded and reviewed by a person."
                error={errors["integrity_settings.auto_submit_after"]}
              >
                {(p) => <Input {...p} type="number" min={1} max={1000} value={num(value.auto_submit_after)} onChange={(e) => set({ auto_submit_after: toNum(e.target.value) })} />}
              </FormField>
            </div>
            <p className="text-xs text-fg-muted">Recorded events are evidence for your evaluators. They never change marks automatically — decisions are made in integrity review.</p>
          </>
        ) : null}
      </fieldset>
    </Card>
  );
}
