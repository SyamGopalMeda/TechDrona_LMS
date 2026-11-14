"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Card, ErrorState, LinkButton, LoadingBlock, StatusBadge, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { formatINR } from "@/features/admin/lib/console";
import { COURSE_STATUSES, COURSE_STATUS_LABEL, COURSE_STATUS_TONE, planEditHref, type CourseStatus, type CourseStatusRow } from "../lib/admissions";
import { useResource } from "@/lib/api/use-resource";
import { formatDateTime } from "@/lib/format";

/**
 * Admin > Admissions > Courses: one switch per course (Open for registration / Coming soon /
 * Closed). Saved at once; the website and the LMS course pages read it within a minute. Opening
 * needs an active fee plan (409 no_fee_plan): the row then links to that course's fee plan.
 */

export { planEditHref };

/** Anchor of the Courses section (`COURSE_STATUS_HREF`). */
const COURSE_STATUS_ID = "course-status";

/** Three joined buttons (a native radio group) that wrap their text on a phone. */
function StatusSwitch({ title, value, busy, onChange }: { title: string; value: CourseStatus; busy: boolean; onChange: (s: CourseStatus) => void }) {
  const id = useId();
  return (
    <fieldset className="min-w-0" disabled={busy}>
      <legend className="sr-only">Registration for {title}</legend>
      <div className="grid grid-cols-3 gap-1 rounded-lg border border-line-control bg-surface p-1">
        {COURSE_STATUSES.map((s) => {
          const checked = s === value;
          return (
            <label
              key={s}
              htmlFor={`${id}-${s}`}
              className={cn(
                "flex min-h-touch cursor-pointer items-center justify-center rounded-md px-2 py-1 text-center font-display text-sm font-semibold leading-tight transition-colors duration-fast focus-within:shadow-focus md:min-h-9",
                checked ? (s === "open" ? "bg-success-solid text-success-on" : s === "coming_soon" ? "bg-brand text-brand-on" : "bg-fg-secondary text-fg-on") : "text-fg-secondary hover:bg-surface-hover hover:text-brand",
                busy && "cursor-wait opacity-70",
              )}
            >
              <input id={`${id}-${s}`} type="radio" className="sr-only" name={`status-${id}`} value={s} checked={checked} onChange={() => onChange(s)} />
              {COURSE_STATUS_LABEL[s]}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function CourseRow({ row, title, onSaved }: { row: CourseStatusRow; title: string; onSaved: (r: CourseStatusRow) => void }) {
  const toast = useToast();
  const [value, setValue] = useState<CourseStatus>(row.status);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ text: string; feePlan: boolean } | null>(null);
  useEffect(() => setValue(row.status), [row.status]);

  const change = async (next: CourseStatus) => {
    if (next === value || busy) return;
    const before = value;
    setValue(next);
    setBusy(true);
    setProblem(null);
    try {
      const res = await api.put<CourseStatusRow>(`admin/courses/${encodeURIComponent(row.course_slug)}/status`, { status: next });
      if (res.kind !== "ok") {
        setValue(before);
        toast.show({ title: "Sent for a second approval. The course changes once it's approved.", tone: "info" });
        return;
      }
      onSaved(res.data && typeof res.data === "object" && "course_slug" in res.data ? res.data : { ...row, status: next });
      toast.show({ title: `${title}: ${COURSE_STATUS_LABEL[next].toLowerCase()}.`, description: "The website and the LMS show it within a minute.", tone: "success" });
    } catch (e) {
      setValue(before);
      const err = e instanceof ApiError ? e : null;
      if (err?.code === "no_fee_plan") setProblem({ text: err.problem?.detail || "Set a fee for this course before opening registration.", feePlan: true });
      else setProblem({ text: err?.problem?.detail || err?.title || "Couldn't save. Check your connection and try again.", feePlan: false });
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="space-y-3 border-b border-line px-5 py-4 last:border-b-0 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{title}</p>
          <p className="text-xs text-fg-secondary">
            {row.fee_paise != null ? `Fee ${formatINR(row.fee_paise)}` : <span className="text-warning-fg">No fee set</span>}
            {" · "}
            {row.batch ? `Batch: ${row.batch.name}` : <span className="text-warning-fg">No batch linked</span>}
            {row.updated_at ? ` · changed ${formatDateTime(row.updated_at)}` : ""}
          </p>
        </div>
        <StatusBadge status={COURSE_STATUS_TONE[value]} label={COURSE_STATUS_LABEL[value]} />
      </div>
      <StatusSwitch title={title} value={value} busy={busy} onChange={(s) => void change(s)} />
      {problem ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          <span className="min-w-0 flex-1">{problem.text}</span>
          {problem.feePlan ? (
            <LinkButton size="sm" href={planEditHref(row.course_slug)}>
              Set the fee
            </LinkButton>
          ) : null}
        </div>
      ) : row.fee_paise == null || !row.plan_active || !row.batch ? (
        <p className={cn("text-xs", value === "open" && !row.plan_active ? "font-medium text-warning-fg" : "text-fg-secondary")}>
          {value === "open" && !row.plan_active
            ? "Students see this course as Closed: its fee plan is inactive. Activate the plan to take registrations. "
            : row.fee_paise == null
              ? "Set a fee before opening registration. "
              : !row.plan_active
                ? "The fee plan is inactive: activate it before opening registration. "
                : ""}
          {!row.batch ? "Link a batch so verified students are added to it. " : ""}
          <Link className="font-semibold text-brand underline" href={planEditHref(row.course_slug)}>
            {row.fee_paise == null ? "Set up the fee plan" : "Open the fee plan"}
          </Link>
        </p>
      ) : null}
    </li>
  );
}

/** The "Courses" section at the top of Admissions. `titles` maps slug -> website title. */
export function CourseStatusSection({ titles = {} }: { titles?: Record<string, string> }) {
  const res = useResource<{ data: CourseStatusRow[] }>("admin/courses/status");
  const [rows, setRows] = useState<CourseStatusRow[] | null>(null);
  // Every website course is listed, also one the api doesn't know yet (no status row, fee plan or
  // batch): it reads Coming soon; opening it needs a fee plan (409 no_fee_plan -> "Set the fee").
  const titleKey = Object.keys(titles).join("|");
  useEffect(() => {
    if (!res.data) return;
    const known = new Set(res.data.data.map((r) => r.course_slug));
    const extra: CourseStatusRow[] = titleKey
      .split("|")
      .filter((slug) => slug && !known.has(slug))
      .map((slug) => ({ course_slug: slug, status: "coming_soon", effective_status: "coming_soon", updated_at: null, fee_paise: null, plan_active: false, batch: null }));
    setRows([...res.data.data, ...extra]);
  }, [res.data, titleKey]);
  // Admin > Courses links here as /finance/admissions#course-status: the SPA doesn't scroll to a
  // hash by itself, so bring the section into view once its rows are in.
  const ref = useRef<HTMLDivElement>(null);
  const loaded = rows !== null;
  useEffect(() => {
    if (loaded && typeof window !== "undefined" && window.location.hash === `#${COURSE_STATUS_ID}`) ref.current?.scrollIntoView?.({ block: "start" });
  }, [loaded]);

  return (
    <div id={COURSE_STATUS_ID} ref={ref} className="scroll-mt-24">
      <Card title="Courses" description="Choose which courses take registrations. Changes show on the website and in the LMS within a minute. Students can register only while a course is open." padding="none">
        {res.error && !rows ? (
          <div className="p-5">
            <ErrorState error={res.error} onRetry={() => void res.reload()} />
          </div>
        ) : !rows ? (
          <div className="p-5">
            <LoadingBlock label="Loading courses…" rows={3} />
          </div>
        ) : rows.length === 0 ? (
          <p className="px-5 pb-5 text-sm text-fg-secondary sm:px-6">No courses yet. Add a fee plan for a website course to manage it here.</p>
        ) : (
          <ul aria-label="Course registration status">
            {rows.map((r) => (
              <CourseRow key={r.course_slug} row={r} title={titles[r.course_slug] || r.title || r.course_slug} onSaved={(saved) => setRows((all) => (all ?? []).map((x) => (x.course_slug === saved.course_slug ? { ...x, ...saved } : x)))} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
