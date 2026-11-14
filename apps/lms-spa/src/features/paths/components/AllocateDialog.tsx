"use client";

import { useEffect, useMemo, useState } from "react";
import { Button, Checkbox, Dialog, FormField, Input, Select, Tabs, useToast } from "@/components/ui";
import { fieldErrorsOf, useFailToast } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { pathsApi } from "../lib/api";
import { BatchMemberSearch } from "./BatchMemberSearch";
import { DAY_KEYS, DAY_LABELS, PACE_MODES, estimateFinish, isWeekend, perDayFromPace, planSummary, todayIso, weeklyHours } from "../lib/pace";
import type { AllocIn, AllocationPreview, Flow, BatchMember, PaceMode, PathDetail, PathsContext, PerDay } from "../lib/types";

/** "Allocate" dialog: batch or individual learners, flow, sequential, start date, study pace,
 * with a live finish-date preview computed by the api (local estimate while it loads). */
export function AllocateDialog({ open, onClose, path, onDone }: { open: boolean; onClose: () => void; path: PathDetail; onDone: () => void }) {
  const toast = useToast();
  const fail = useFailToast();
  const ctx = useApi<PathsContext>(open ? "paths/context" : null);
  const batches = ctx.data?.batches ?? [];
  const [target, setTarget] = useState<"batch" | "users">("batch");
  const [batchId, setBatchId] = useState("");
  const [users, setUsers] = useState<BatchMember[]>([]);
  const [flow, setFlow] = useState<Flow>("lenient");
  const [sequential, setSequential] = useState(false);
  const [start, setStart] = useState(todayIso());
  const [mode, setMode] = useState<PaceMode>("every_day");
  const [hpd, setHpd] = useState("2");
  const [custom, setCustom] = useState<PerDay>(() => perDayFromPace({ mode: "every_day", hours_per_day: 2 }));
  const [preview, setPreview] = useState<AllocationPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const pace = useMemo(
    () => (mode === "custom" ? { mode, per_day: custom } : { mode, hours_per_day: Number(hpd) || 0 }),
    [mode, custom, hpd],
  );
  const perDay = useMemo(() => perDayFromPace(pace), [pace]);
  const body: AllocIn = useMemo(
    () => ({
      target_type: target,
      ...(target === "batch" ? { batch_id: batchId || undefined } : { user_ids: users.map((u) => u.user_id) }),
      flow,
      sequential,
      start_date: start || undefined,
      pace,
    }),
    [target, batchId, users, flow, sequential, start, pace],
  );

  useEffect(() => {
    if (!open) return;
    const ctl = new AbortController();
    const t = setTimeout(() => {
      pathsApi
        .preview(path.id, body, ctl.signal)
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 400);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [open, path.id, body]);

  const local = estimateFinish(start || todayIso(), path.total_hours, perDay);
  const summary = preview
    ? planSummary(preview.weekly_hours, preview.total_hours, preview.finish_date, preview.days)
    : planSummary(weeklyHours(perDay), path.total_hours, local?.finishDate ?? null, local?.days ?? null);

  const canSubmit = (target === "batch" ? !!batchId : users.length > 0) && weeklyHours(perDay) > 0;

  const submit = async () => {
    setBusy(true);
    setErrs({});
    try {
      await pathsApi.allocate(path.id, body);
      toast.show({ tone: "success", title: "Path allocated" });
      onDone();
      onClose();
    } catch (e) {
      const fe = fieldErrorsOf(e);
      if (Object.keys(fe).length) setErrs(fe);
      else fail(e);
    } finally {
      setBusy(false);
    }
  };

  const choice = <T extends string>(name: string, value: T, current: T, set: (v: T) => void, title: string, hint: string) => (
    <label className={`flex cursor-pointer flex-col rounded-lg border p-3 ${current === value ? "border-brand bg-brand-subtle" : "border-line"}`}>
      <span className="flex items-center gap-2 text-sm font-semibold">
        <input type="radio" name={name} value={value} checked={current === value} onChange={() => set(value)} />
        {title}
      </span>
      <span className="mt-1 text-xs text-fg-muted">{hint}</span>
    </label>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title={`Allocate — ${path.title}`}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} loading={busy} disabled={!canSubmit}>
            Allocate
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Tabs
          label="Allocate to"
          value={target}
          onValueChange={(v) => setTarget(v as "batch" | "users")}
          items={[
            {
              id: "batch",
              label: "Batch",
              content: (
                <div className="pt-3">
                  <FormField label="Batch" required error={errs.batch_id}>
                    {(p) => (
                      <Select
                        {...p}
                        value={batchId}
                        onChange={(e) => setBatchId(e.target.value)}
                        placeholder={ctx.loading ? "Loading…" : batches.length ? "Choose a batch…" : "No batches you can allocate to"}
                        options={batches.map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }))}
                      />
                    )}
                  </FormField>
                </div>
              ),
            },
            {
              id: "users",
              label: "Individual",
              content: (
                <div className="pt-3">
                  <MemberPicker batches={batches} value={users} onChange={setUsers} error={errs.user_ids} />
                </div>
              ),
            },
          ]}
        />
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Flow</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {choice("flow", "lenient", flow, setFlow, "Lenient", "Own pace · credits always count")}
            {choice("flow", "strict", flow, setFlow, "Strict", "On timeline · late steps earn reduced credits")}
          </div>
        </fieldset>
        <Checkbox checked={sequential} onChange={(e) => setSequential(e.currentTarget.checked)} label={`Sequential — ${sequential ? "finish each step before the next" : "any step, any order"}`} />
        <FormField label="Start date (optional)" hint="The study plan counts from here. Defaults to today." error={errs.start_date}>
          {(p) => <Input {...p} type="date" value={start} onChange={(e) => setStart(e.target.value)} />}
        </FormField>
        <fieldset>
          <legend className="mb-1.5 text-sm font-medium">Study pace</legend>
          <p className="mb-2 text-xs text-fg-muted">How much time the learner or batch studies each day.</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Study days">
            {PACE_MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                role="radio"
                aria-checked={mode === m.value}
                onClick={() => {
                  if (m.value === "custom") setCustom(perDay);
                  setMode(m.value);
                }}
                className={`rounded-full border px-3 py-1 text-sm focus-visible:shadow-focus focus-visible:outline-none ${mode === m.value ? "border-brand bg-brand-subtle font-medium" : "border-line"}`}
              >
                {m.label}
              </button>
            ))}
          </div>
          {mode !== "custom" ? (
            <div className="mt-3 max-w-[10rem]">
              <FormField label="Hours per day">{(p) => <Input {...p} type="number" min={0.25} max={24} step={0.25} value={hpd} onChange={(e) => setHpd(e.target.value)} />}</FormField>
            </div>
          ) : null}
          <div className="mt-3 grid grid-cols-7 gap-1">
            {DAY_KEYS.map((d) => (
              <label key={d} className={`flex flex-col items-center rounded-md p-1 text-xs ${isWeekend(d) ? "bg-surface-sunken" : ""}`}>
                <span className="font-medium">{DAY_LABELS[d]}</span>
                <input
                  type="number"
                  min={0}
                  max={24}
                  step={0.25}
                  aria-label={`${DAY_LABELS[d]} hours`}
                  disabled={mode !== "custom"}
                  value={String(perDay[d])}
                  onChange={(e) => setCustom({ ...custom, [d]: Number(e.target.value) || 0 })}
                  className="mt-1 w-full rounded border border-line-control bg-surface px-1 py-0.5 text-center text-sm disabled:bg-surface-sunken"
                />
              </label>
            ))}
          </div>
        </fieldset>
        <p aria-live="polite" className="rounded-md bg-surface-sunken p-3 text-sm font-medium" data-testid="plan-summary">
          {summary}
        </p>
        <p className="text-xs text-fg-muted">
          {flow === "lenient" ? "Lenient: this is a suggested plan — time is tracked but never penalised." : "Strict: each step has a due date from this plan; steps completed after it earn reduced credits."}
        </p>
      </div>
    </Dialog>
  );
}

function MemberPicker({ batches, value, onChange, error }: { batches: PathsContext["batches"]; value: BatchMember[]; onChange: (v: BatchMember[]) => void; error?: string }) {
  const chosen = new Set(value.map((v) => v.user_id));
  return (
    <div className="space-y-2">
      <BatchMemberSearch batches={batches} chosen={chosen} onPick={(m) => onChange([...value, m])} error={error} />
      {value.length ? (
        <ul className="flex flex-wrap gap-2" aria-label="Chosen learners">
          {value.map((m) => (
            <li key={m.user_id} className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-sm">
              {m.full_name || m.email || "Learner"}
              <button type="button" aria-label={`Remove ${m.full_name || m.email || "learner"}`} onClick={() => onChange(value.filter((x) => x.user_id !== m.user_id))} className="px-1 text-fg-muted">
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
