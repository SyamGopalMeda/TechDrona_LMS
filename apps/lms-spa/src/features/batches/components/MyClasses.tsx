"use client";

import { Badge, Card, EmptyState, ProgressBar, Reveal, StatusBadge } from "@/components/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { Boundary, safeExternalUrl } from "@/features/trainer/shared/ui";
import { MARK_LABEL, fmtDay, pctText, type MyBatchClasses, type MyClass, type MyClasses as MyClassesData } from "../lib/delivery";

const MARK_TONE = { P: "success", L: "warning", A: "danger" } as const;

/**
 * STU-040 "My classes" (moved from the website learning portal): for each of the learner's batches,
 * the next live classes with their join link, past classes with recordings and the learner's own
 * mark, the current week of the plan and attendance %. verified: GET me/classes (orgs/classes.py).
 */
export function MyClasses() {
  const res = useApi<MyClassesData>("me/classes");
  return (
    <Boundary state={res} rows={3}>
      {(d) =>
        d.batches.length === 0 ? (
          <EmptyState icon="calendar" title="No live classes" description="When you join a batch, its classes, class links and recordings show up here." />
        ) : (
          <div className="space-y-8">
            {d.batches.map((b) => (
              <BatchClasses key={b.batch.id} b={b} today={d.today} />
            ))}
          </div>
        )
      }
    </Boundary>
  );
}

function BatchClasses({ b, today }: { b: MyBatchClasses; today: string }) {
  const pct = b.attendance.percent;
  const below = b.min_attendance_percent !== null && pct !== null && pct < b.min_attendance_percent;
  const next = b.upcoming.find((s) => !s.cancelled);
  return (
    <section aria-labelledby={`batch-${b.batch.id}`} className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={`batch-${b.batch.id}`} className="font-display text-lg font-extrabold text-fg-heading">
          {b.batch.name}
        </h2>
        <StatusBadge status={b.batch.status} />
        {b.current_week ? (
          <Badge tone="brand" dot>
            Week {b.current_week} of {b.weeks_count}
            {b.current_week_title ? ` · ${b.current_week_title}` : ""}
          </Badge>
        ) : null}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Next class" icon="calendar" className="lg:col-span-2">
          {next ? <NextClass s={next} today={today} /> : <p className="text-fg-muted">No class is scheduled yet.</p>}
        </Card>
        <Card title="My attendance" icon="check">
          <p className="font-display text-3xl font-extrabold text-fg-heading">{pctText(pct)}</p>
          {pct !== null ? <ProgressBar value={pct} label="Attendance" /> : null}
          <p className="mt-2 text-sm text-fg-muted">
            {b.attendance.marked
              ? `${b.attendance.present} present · ${b.attendance.late} late · ${b.attendance.absent} absent`
              : "No class has been marked yet."}
          </p>
          {b.min_attendance_percent ? (
            <p className={`mt-1 text-sm ${below ? "font-semibold text-warning-fg" : "text-fg-muted"}`}>
              {below ? `Below the ${b.min_attendance_percent}% needed for the certificate.` : `${b.min_attendance_percent}% is needed for the certificate.`}
            </p>
          ) : null}
        </Card>
      </div>
      {b.upcoming.length > 1 ? (
        <div>
          <h3 className="mb-2 font-display text-base font-bold text-fg-heading">Upcoming</h3>
          <Reveal as="ul" stagger className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label={`Upcoming classes of ${b.batch.name}`}>
            {b.upcoming.slice(next ? b.upcoming.indexOf(next) + 1 : 0).map((s) => (
              <li key={s.id} className="rounded-xl border border-line bg-surface p-3">
                <ClassLine s={s} />
              </li>
            ))}
          </Reveal>
        </div>
      ) : null}
      {b.recent.length ? (
        <div>
          <h3 className="mb-2 font-display text-base font-bold text-fg-heading">Past classes</h3>
          <Reveal as="ul" stagger className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label={`Past classes of ${b.batch.name}`}>
            {b.recent.map((s) => {
              const rec = safeExternalUrl(s.recording_url);
              return (
                <li key={s.id} className="flex flex-col gap-1.5 rounded-xl border border-line bg-surface p-3">
                  <ClassLine s={s} />
                  <div className="flex flex-wrap items-center gap-2">
                    {s.my_status ? <Badge tone={MARK_TONE[s.my_status]}>{MARK_LABEL[s.my_status]}</Badge> : s.cancelled ? null : <Badge>Not marked</Badge>}
                    {rec ? (
                      <a className="text-sm font-semibold text-fg-link underline-offset-2 hover:underline" href={rec} target="_blank" rel="noopener noreferrer">
                        Watch recording
                      </a>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </Reveal>
        </div>
      ) : null}
    </section>
  );
}

function ClassLine({ s }: { s: MyClass }) {
  return (
    <>
      <span className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold text-brand">{fmtDay(s.session_date)}</span>
        {s.starts_at ? <span className="text-fg-muted">{s.starts_at} IST</span> : null}
        {s.cancelled ? <Badge tone="danger">Cancelled</Badge> : null}
      </span>
      <span className="block font-medium text-fg">{s.topic || "Class"}</span>
    </>
  );
}

function NextClass({ s, today }: { s: MyClass; today: string }) {
  const join = safeExternalUrl(s.meet_url);
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div>
        <p className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-brand-subtle px-3 py-0.5 font-display text-sm font-bold text-brand">{fmtDay(s.session_date)}</span>
          {s.starts_at ? <span className="text-sm text-fg-muted">{s.starts_at} IST</span> : null}
          {s.session_date === today ? <Badge tone="brand" dot>Today</Badge> : null}
        </p>
        <p className="mt-2 font-display text-lg font-bold text-fg-heading">{s.topic || "Class"}</p>
      </div>
      {join ? (
        <a className="inline-flex min-h-touch items-center rounded-full bg-[#0b3b24] px-5 font-display font-semibold text-white shadow-[0_2px_10px_rgba(11,59,36,0.2)] hover:bg-[#082d1c]" href={join} target="_blank" rel="noopener noreferrer">
          Join class
        </a>
      ) : (
        <p className="text-sm text-fg-muted">The class link will appear here.</p>
      )}
    </div>
  );
}
