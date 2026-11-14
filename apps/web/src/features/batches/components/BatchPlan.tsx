"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Badge, Button, Card, Checkbox, EmptyState, FormField, Input, Reveal, SectionHeader, Select, StatGrid, StatTile, TextArea, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useApi, seg } from "@/features/trainer/shared/use-api";
import { Boundary, fieldErrorsOf, formatDate, useFailToast } from "@/features/trainer/shared/ui";
import { archivedBatchGuard } from "../lib/api";
import {
  ACTIVITY_KINDS,
  DAY_NAMES,
  EMPTY_PLAN,
  WEEK_ORDER,
  fmtDay,
  newActivityId,
  type BatchPlanBody,
  type BatchPlanResponse,
  type PlanActivity,
  type PlanWeek,
  type Schedule,
} from "../lib/delivery";

/** verified: admin/courses/overview (courses_overview.py), used for the LMS course picker. */
interface CourseOption {
  course_id: string;
  title: string;
  slug: string;
}

interface Draft {
  plan: BatchPlanBody;
  starts_on: string;
  course_id: string;
  website_course_slug: string;
  min_attendance_percent: string;
}

function draftOf(r: BatchPlanResponse): Draft {
  return {
    plan: r.has_plan ? r.plan : { ...EMPTY_PLAN },
    starts_on: r.batch.starts_on ?? "",
    course_id: r.batch.course_id ?? "",
    website_course_slug: r.batch.website_course_slug ?? "",
    min_attendance_percent: r.min_attendance_percent ? String(r.min_attendance_percent) : "",
  };
}

const num = (v: string) => (v.trim() === "" || Number.isNaN(Number(v)) ? 0 : Number(v));

/**
 * Batch "Plan" tab (moved from the website's Admin > Courses week editor): schedule settings,
 * week-by-week titles, topics and activities. The api computes the dates (classes per working day,
 * holidays skipped, week n = 7 days from the start date); edits are previewed live through
 * `batches/{id}/plan/preview` and saved with PUT `batches/{id}/plan` (Admin: `batch.update`).
 * Trainers see the same plan read-only.
 */
export function BatchPlan({ batchId, editable = false }: { batchId: string; editable?: boolean }) {
  const res = useApi<BatchPlanResponse>(`batches/${seg(batchId)}/plan`);
  return (
    <Boundary state={res} rows={4}>
      {(data) => (editable && data.batch.status !== "archived" ? <PlanEditor batchId={batchId} data={data} onSaved={() => void res.reload()} /> : <PlanView data={data} />)}
    </Boundary>
  );
}

/* ------------------------------------------------------------------ read-only */

function PlanView({ data }: { data: BatchPlanResponse }) {
  if (!data.has_plan)
    return <EmptyState icon="calendar" title="No plan yet" description="An Admin adds the week-by-week plan for this batch in Admin > Batches." />;
  return (
    <div className="space-y-6">
      <ScheduleTiles schedule={data.schedule} />
      <PlanFacts data={data} />
      <WeekCards schedule={data.schedule} />
    </div>
  );
}

function PlanFacts({ data }: { data: BatchPlanResponse }) {
  const p = data.plan;
  const days = WEEK_ORDER.filter((d) => p.working_days.includes(d)).map((d) => DAY_NAMES[d]).join(", ");
  return (
    <Card title="Schedule" icon="calendar">
      <dl className="grid gap-3 text-[0.9375rem] sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Hours">{`${p.total_hours} h · ${p.daily_hours} h a day`}</Fact>
        <Fact label="Class days">{days || "—"}</Fact>
        <Fact label="Class time">{p.class_time ? `${p.class_time} IST` : "—"}</Fact>
        <Fact label="Holidays">{p.holidays.length ? p.holidays.map(fmtDay).join(", ") : "None"}</Fact>
        <Fact label="Minimum attendance">{data.min_attendance_percent ? `${data.min_attendance_percent}% for the certificate` : "Not required"}</Fact>
        <Fact label="Class link">{p.meet_url ? <a className="text-fg-link underline-offset-2 hover:underline" href={p.meet_url} target="_blank" rel="noopener noreferrer">Open</a> : "—"}</Fact>
      </dl>
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="font-medium text-fg">{children}</dd>
    </div>
  );
}

function ScheduleTiles({ schedule }: { schedule: Schedule }) {
  return (
    <StatGrid columns={4}>
      <StatTile icon="calendar" label="Classes" value={String(schedule.sessions)} hint={`${schedule.hours_planned} h planned`} />
      <StatTile icon="layers" label="Weeks" value={String(schedule.weeks_count)} hint={`${schedule.days_per_week} class days a week`} />
      <StatTile icon="clock" label="Ends on" value={schedule.end_date ? formatDate(schedule.end_date) : null} hint={schedule.start_date ? `Starts ${formatDate(schedule.start_date)}` : "Set a start date"} />
      <StatTile icon="target" label="This week" value={schedule.current_week ? `Week ${schedule.current_week}` : "—"} tone={schedule.current_week ? "success" : "neutral"} hint={schedule.current_week ? undefined : "Not running today"} />
    </StatGrid>
  );
}

function weekRange(w: { from: string | null; to: string | null; days: string[] }): string {
  if (!w.from) return "Dates follow the start date";
  const cls = w.days.length === 1 ? "1 class" : `${w.days.length} classes`;
  return `${fmtDay(w.from)} – ${fmtDay(w.to)} · ${cls}`;
}

function WeekCards({ schedule }: { schedule: Schedule }) {
  if (!schedule.weeks.length) return null;
  return (
    <Reveal as="ol" stagger className="grid gap-4 md:grid-cols-2" aria-label="Weeks">
      {schedule.weeks.map((w) => (
        <li key={w.n} className="rounded-[18px] border border-[#e8ecf3] bg-surface p-5 shadow-[0_14px_30px_-28px_rgba(3,34,105,0.45)]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-display text-sm font-bold uppercase tracking-wide text-accent">Week {w.n}</span>
            {schedule.current_week === w.n ? <Badge tone="brand" dot>This week</Badge> : null}
            {w.beyond_schedule ? <Badge tone="warning">Beyond the hours</Badge> : null}
          </div>
          <h3 className="mt-1 font-display text-base font-bold text-fg-heading">{w.title || "Untitled week"}</h3>
          <p className="text-sm text-fg-muted">{weekRange(w)}</p>
          {w.topics.length ? (
            <ul className="mt-3 list-disc space-y-0.5 pl-5 text-[0.9375rem] text-fg-secondary">
              {w.topics.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          ) : null}
          {w.activities.length ? (
            <ul className="mt-3 flex flex-wrap gap-2" aria-label={`Week ${w.n} activities`}>
              {w.activities.map((a) => (
                <li key={a.id}>
                  <Badge tone={a.required ? "info" : "neutral"}>
                    {a.title}
                    {a.due_effective ? ` · due ${fmtDay(a.due_effective)}` : ""}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </Reveal>
  );
}

/* ------------------------------------------------------------------ editor */

function PlanEditor({ batchId, data, onSaved }: { batchId: string; data: BatchPlanResponse; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(data));
  const [preview, setPreview] = useState<Schedule>(data.schedule);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [holiday, setHoliday] = useState("");
  const courses = useApi<{ courses: CourseOption[] }>("admin/courses/overview");
  const toast = useToast();
  const fail = useFailToast();
  const plan = draft.plan;
  const setPlan = (p: Partial<BatchPlanBody>) => setDraft((d) => ({ ...d, plan: { ...d.plan, ...p } }));
  const setWeek = (i: number, w: Partial<PlanWeek>) => setPlan({ weeks: plan.weeks.map((x, j) => (j === i ? { ...x, ...w } : x)) });
  const setActivity = (i: number, k: number, a: Partial<PlanActivity>) => setWeek(i, { activities: plan.weeks[i]!.activities.map((x, j) => (j === k ? { ...x, ...a } : x)) });

  // Live preview of the computed schedule (debounced; the api is the only schedule engine).
  const previewKey = JSON.stringify({ plan, starts_on: draft.starts_on });
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const t = setTimeout(() => {
      api
        .post<Schedule>(`batches/${seg(batchId)}/plan/preview`, { plan, starts_on: draft.starts_on || null })
        .then((r) => {
          if (r.kind === "ok") setPreview(r.data);
        })
        .catch(() => undefined); // invalid while typing: the save shows the field errors
    }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey, batchId]);

  const courseOptions = useMemo(
    () => [{ value: "", label: "Not linked" }, ...(courses.data?.courses ?? []).map((c) => ({ value: c.course_id, label: `${c.title} (${c.slug})` }))],
    [courses.data],
  );

  const save = async () => {
    setSaving(true);
    setErrors({});
    try {
      const min = draft.min_attendance_percent.trim();
      await archivedBatchGuard(
        api.put<BatchPlanResponse>(`batches/${seg(batchId)}/plan`, {
          plan,
          starts_on: draft.starts_on || null,
          course_id: draft.course_id || null,
          website_course_slug: draft.website_course_slug.trim() || null,
          min_attendance_percent: min ? Number(min) : null,
        }),
      );
      toast.show({ tone: "success", title: "Plan saved", description: "The batch dates follow the plan." });
      onSaved();
    } catch (err) {
      setErrors(fieldErrorsOf(err));
      fail(err, "Could not save the plan");
    } finally {
      setSaving(false);
    }
  };

  const toggleDay = (d: number) => setPlan({ working_days: plan.working_days.includes(d) ? plan.working_days.filter((x) => x !== d) : [...plan.working_days, d].sort() });
  const addHoliday = () => {
    if (/^\d{4}-\d{2}-\d{2}$/.test(holiday) && !plan.holidays.includes(holiday)) setPlan({ holidays: [...plan.holidays, holiday].sort() });
    setHoliday("");
  };
  const move = (i: number, by: -1 | 1) => {
    const w = [...plan.weeks];
    const j = i + by;
    if (j < 0 || j >= w.length) return;
    [w[i], w[j]] = [w[j]!, w[i]!];
    setPlan({ weeks: w });
  };
  // Pad to the computed number of weeks so every scheduled week can get a title.
  const fillWeeks = () => {
    const n = Math.max(preview.weeks_count, plan.weeks.length);
    setPlan({ weeks: [...plan.weeks, ...Array.from({ length: n - plan.weeks.length }, () => ({ title: "", topics: [], activities: [] }))] });
  };

  return (
    <div className="space-y-6">
      {data.source_ref ? <p className="text-sm text-fg-muted">Imported from the website ({data.source_ref}). The LMS is now where this plan is edited.</p> : null}
      <ScheduleTiles schedule={preview} />
      <Card title="Schedule" icon="calendar" description="Classes run on the chosen days, skipping holidays, until the hours are used. Week 1 starts on the start date.">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Start date" error={errors.starts_on}>
            {(p) => <Input {...p} type="date" value={draft.starts_on} onChange={(e) => setDraft({ ...draft, starts_on: e.target.value })} />}
          </FormField>
          <FormField label="Total hours" error={errors["plan.total_hours"]}>
            {(p) => <Input {...p} type="number" min={0} max={2000} step="0.5" value={String(plan.total_hours)} onChange={(e) => setPlan({ total_hours: num(e.target.value) })} />}
          </FormField>
          <FormField label="Hours per class day">
            {(p) => <Input {...p} type="number" min={0} max={12} step="0.5" value={String(plan.daily_hours)} onChange={(e) => setPlan({ daily_hours: num(e.target.value) })} />}
          </FormField>
          <FormField label="Class time (IST)" hint="Used for new classes">
            {(p) => <Input {...p} type="time" value={plan.class_time ?? ""} onChange={(e) => setPlan({ class_time: e.target.value || null })} />}
          </FormField>
          <FormField label="Class link" hint="https:// meeting link shown to learners">
            {(p) => <Input {...p} type="url" inputMode="url" value={plan.meet_url ?? ""} onChange={(e) => setPlan({ meet_url: e.target.value || null })} />}
          </FormField>
          <FormField label="Minimum attendance %" hint="Blank = not required for the certificate" error={errors.min_attendance_percent}>
            {(p) => <Input {...p} type="number" min={1} max={100} value={draft.min_attendance_percent} onChange={(e) => setDraft({ ...draft, min_attendance_percent: e.target.value })} />}
          </FormField>
        </div>
        <fieldset className="mt-5">
          <legend className="mb-2 text-sm font-semibold text-fg">Class days</legend>
          <div className="flex flex-wrap gap-2">
            {WEEK_ORDER.map((d) => {
              const on = plan.working_days.includes(d);
              return (
                <button key={d} type="button" aria-pressed={on} onClick={() => toggleDay(d)} className={`min-h-touch rounded-full border px-4 font-display text-sm font-semibold md:min-h-9 ${on ? "border-brand bg-brand text-brand-on" : "border-line-control bg-surface text-fg-secondary hover:bg-surface-hover"}`}>
                  {DAY_NAMES[d]}
                </button>
              );
            })}
          </div>
        </fieldset>
        <div className="mt-5 flex flex-wrap items-end gap-2">
          <FormField label="Holiday">
            {(p) => <Input {...p} type="date" value={holiday} onChange={(e) => setHoliday(e.target.value)} />}
          </FormField>
          <Button variant="secondary" onClick={addHoliday} disabled={!holiday}>
            Add holiday
          </Button>
        </div>
        {plan.holidays.length ? (
          <ul className="mt-3 flex flex-wrap gap-2" aria-label="Holidays">
            {plan.holidays.map((h) => (
              <li key={h}>
                <button type="button" className="inline-flex min-h-touch items-center gap-1 rounded-full bg-warning-subtle px-3 text-sm font-semibold text-warning-fg md:min-h-8" aria-label={`Remove holiday ${fmtDay(h)}`} onClick={() => setPlan({ holidays: plan.holidays.filter((x) => x !== h) })}>
                  {fmtDay(h)} <span aria-hidden="true">×</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <FormField label="LMS course (content)" hint="The catalog course learners study in this batch" error={errors.course_id}>
            {(p) => <Select {...p} value={draft.course_id} onChange={(e) => setDraft({ ...draft, course_id: e.target.value })} options={draft.course_id && !courseOptions.some((o) => o.value === draft.course_id) ? [...courseOptions, { value: draft.course_id, label: draft.course_id }] : courseOptions} />}
          </FormField>
          <FormField label="Website course (marketing page)" hint="Slug from the website catalogue, e.g. mern-stack-development" error={errors.website_course_slug}>
            {(p) => <Input {...p} value={draft.website_course_slug} onChange={(e) => setDraft({ ...draft, website_course_slug: e.target.value })} autoComplete="off" />}
          </FormField>
        </div>
        <Checkbox className="mt-4" label="Registrations open" description="Shown with the batch on the website course page" checked={plan.registrations_open} onChange={(e) => setPlan({ registrations_open: e.target.checked })} />
      </Card>

      <SectionHeader
        title="Weeks"
        description={`${plan.weeks.length} planned · the schedule has ${preview.weeks_count}`}
        actions={
          <>
            {preview.weeks_count > plan.weeks.length ? (
              <Button variant="secondary" onClick={fillWeeks}>
                Add the missing weeks
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => setPlan({ weeks: [...plan.weeks, { title: "", topics: [], activities: [] }] })}>
              Add week
            </Button>
          </>
        }
      />
      <Reveal as="ol" stagger className="space-y-4" aria-label="Week plan">
        {plan.weeks.map((w, i) => {
          const sw = preview.weeks[i];
          return (
            <li key={i}>
              <Card
                titleAs="h3"
                title={
                  <span className="flex flex-wrap items-center gap-2">
                    Week {i + 1}
                    {preview.current_week === i + 1 ? <Badge tone="brand" dot>This week</Badge> : null}
                    {sw && !sw.beyond_schedule ? <span className="text-sm font-normal text-fg-muted">{weekRange(sw)}</span> : <Badge tone="warning">Beyond the hours</Badge>}
                  </span>
                }
                actions={
                  <>
                    <Button size="sm" variant="ghost" aria-label={`Move week ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                      ↑
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={`Move week ${i + 1} down`} disabled={i === plan.weeks.length - 1} onClick={() => move(i, 1)}>
                      ↓
                    </Button>
                    <Button size="sm" variant="danger-secondary" aria-label={`Remove week ${i + 1}`} onClick={() => setPlan({ weeks: plan.weeks.filter((_, j) => j !== i) })}>
                      Remove
                    </Button>
                  </>
                }
              >
                <div className="grid gap-4 md:grid-cols-2">
                  <FormField label={`Week ${i + 1} title`}>
                    {(p) => <Input {...p} maxLength={160} value={w.title} onChange={(e) => setWeek(i, { title: e.target.value })} />}
                  </FormField>
                  <FormField label="Topics" hint="One per line">
                    {(p) => <TextArea {...p} rows={3} value={w.topics.join("\n")} onChange={(e) => setWeek(i, { topics: e.target.value.split("\n") })} onBlur={() => setWeek(i, { topics: w.topics.map((t) => t.trim()).filter(Boolean) })} />}
                  </FormField>
                </div>
                <div className="mt-4 space-y-3">
                  {w.activities.map((a, k) => (
                    <div key={a.id} className="grid items-end gap-3 rounded-xl border border-line p-3 sm:grid-cols-[10rem_1fr_10rem_auto]">
                      <FormField label="Kind">
                        {(p) => <Select {...p} value={a.kind} onChange={(e) => setActivity(i, k, { kind: e.target.value as PlanActivity["kind"] })} options={ACTIVITY_KINDS.map((o) => ({ value: o.value, label: o.label }))} />}
                      </FormField>
                      <FormField label="Activity">
                        {(p) => <Input {...p} maxLength={160} value={a.title} onChange={(e) => setActivity(i, k, { title: e.target.value })} />}
                      </FormField>
                      <FormField label="Due" hint={a.due ? undefined : "Week's last class"}>
                        {(p) => <Input {...p} type="date" value={a.due ?? ""} onChange={(e) => setActivity(i, k, { due: e.target.value || null })} />}
                      </FormField>
                      <div className="flex items-center gap-3 pb-2">
                        <Checkbox label="Required" checked={a.required} onChange={(e) => setActivity(i, k, { required: e.target.checked })} />
                        <Button size="sm" variant="ghost" aria-label={`Remove activity ${a.title || k + 1}`} onClick={() => setWeek(i, { activities: w.activities.filter((_, j) => j !== k) })}>
                          Remove
                        </Button>
                      </div>
                    </div>
                  ))}
                  <Button size="sm" variant="secondary" onClick={() => setWeek(i, { activities: [...w.activities, { id: newActivityId(), kind: "assignment", title: "", due: null, required: true }] })}>
                    Add activity
                  </Button>
                </div>
              </Card>
            </li>
          );
        })}
      </Reveal>
      {plan.weeks.length === 0 ? <EmptyState icon="calendar" title="No weeks yet" description="Add a week, or set the hours and add the missing weeks in one go." /> : null}
      <div className="sticky bottom-0 z-10 -mx-1 flex justify-end gap-2 border-t border-line bg-surface/95 px-1 py-3 backdrop-blur">
        <Button variant="secondary" onClick={() => setDraft(draftOf(data))} disabled={saving}>
          Discard changes
        </Button>
        <Button onClick={() => void save()} loading={saving}>
          Save plan
        </Button>
      </div>
    </div>
  );
}
