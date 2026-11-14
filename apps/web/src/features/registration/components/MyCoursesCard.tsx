"use client";

import Link from "next/link";
import { Badge, Card, Icon, ViewAllLink } from "@/components/ui";
import { buttonClasses } from "@/components/ui/Button";
import { useResource } from "@/features/account/lib/use-resource";
import { fmtDay, type MyBatchClasses, type MyClasses } from "@/features/batches/lib/delivery";
import { MY_ADMISSIONS, MY_REGISTRATIONS_HREF, STATE_LABEL, registerHref, type MyRegistration } from "../lib/registration";

export const MY_CLASSES_HREF = "/app/classes";

export interface MyCourseItem {
  key: string;
  title: string;
  batchName: string | null;
  href: string;
  nextClass: string | null;
}

/** "Mon, 02 Nov · 18:00 IST · Arrays" for the next class that isn't cancelled. */
export function nextClassText(b: MyBatchClasses | undefined): string | null {
  const s = b?.upcoming.find((x) => !x.cancelled);
  if (!s) return null;
  return [fmtDay(s.session_date), s.starts_at ? `${s.starts_at} IST` : null, s.topic || null].filter(Boolean).join(" · ");
}

/**
 * Enrolled courses from both sources: verified registrations (`me/admissions`, with the batch the
 * admin added the student to) and active batch memberships (`me/classes`, which also has the next
 * class). A registration and a batch are the same course when the batch id or course slug match.
 */
export function myCourseItems(regs: MyRegistration[], batches: MyBatchClasses[]): MyCourseItem[] {
  const used = new Set<string>();
  const items: MyCourseItem[] = regs
    .filter((r) => r.enrolled)
    .map((r) => {
      const b =
        batches.find((x) => r.batch?.batch_id && x.batch.id === r.batch.batch_id) ??
        batches.find((x) => !used.has(x.batch.id) && x.batch.website_course_slug === r.course_slug);
      if (b) used.add(b.batch.id);
      return {
        key: `r-${r.registration_id}`,
        title: r.course_title,
        batchName: r.batch?.name ?? b?.batch.name ?? null,
        href: r.course_href || MY_CLASSES_HREF,
        nextClass: nextClassText(b),
      };
    });
  for (const b of batches) {
    if (used.has(b.batch.id)) continue;
    items.push({ key: `b-${b.batch.id}`, title: b.batch.name, batchName: null, href: MY_CLASSES_HREF, nextClass: nextClassText(b) });
  }
  return items;
}

const ENDED = new Set(["rejected", "cancelled"]);

/**
 * Student dashboard "My courses": each enrolled course with its batch, the next class and an
 * "Open course" button, then registrations still waiting on payment verification. Renders
 * nothing until loaded, and nothing at all for a learner with neither (the catalogue strip
 * below invites them to register).
 */
export function MyCoursesCard() {
  const regsRes = useResource<{ data: MyRegistration[] }>(MY_ADMISSIONS);
  const classesRes = useResource<MyClasses>("me/classes");
  if (regsRes.loading || classesRes.loading) return null;
  const regs = regsRes.data?.data ?? [];
  const items = myCourseItems(regs, classesRes.data?.batches ?? []);
  const pending = regs.filter((r) => !r.enrolled && !ENDED.has(r.state));
  if (!items.length && !pending.length) return null;

  return (
    <Card title="My courses" icon="book" description={items.length ? "Your enrolled courses and batches." : "Your course registrations."} actions={items.length ? <ViewAllLink href={MY_CLASSES_HREF}>My classes</ViewAllLink> : undefined}>
      <ul className="space-y-3" aria-label="My courses">
        {items.map((c) => (
          <li key={c.key} className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="break-words font-display font-bold text-fg-heading">{c.title}</p>
                <Badge tone="success" dot>
                  Enrolled
                </Badge>
              </div>
              {c.batchName ? <p className="text-sm text-fg-secondary">Batch: {c.batchName}</p> : null}
              {c.nextClass ? (
                <p className="flex items-start gap-1.5 text-sm text-fg-secondary">
                  <Icon name="calendar" className="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" />
                  <span>Next class: {c.nextClass}</span>
                </p>
              ) : null}
            </div>
            <Link href={c.href} className={buttonClasses({ className: "w-full shrink-0 gap-1.5 sm:w-auto" })} aria-label={`Open course: ${c.title}`}>
              Open course
              <Icon name="arrowRight" className="h-4 w-4" />
            </Link>
          </li>
        ))}
        {pending.map((r) => {
          const meta = STATE_LABEL[r.state] ?? STATE_LABEL.pending;
          const label = r.state === "pending" ? "Payment under review" : meta.label;
          const fix = r.can_pay && (r.state === "needs_info" || r.state === "payment_rejected" || r.state === "awaiting_payment" || r.state === "partially_paid");
          return (
            <li key={`p-${r.registration_id}`} className="flex flex-col gap-3 rounded-xl border border-dashed border-line-strong p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="break-words font-display font-bold text-fg-heading">{r.course_title}</p>
                  <Badge tone={r.state === "pending" ? "info" : meta.tone} dot>
                    {label}
                  </Badge>
                </div>
                <p className="text-sm text-fg-secondary">
                  {r.state === "pending" ? "We're verifying your payment. You'll be added to the batch once it's verified." : meta.text}
                </p>
              </div>
              <Link
                href={fix ? registerHref(r.course_slug) : MY_REGISTRATIONS_HREF}
                className={buttonClasses({ variant: fix ? "primary" : "secondary", className: "w-full shrink-0 sm:w-auto" })}
              >
                {fix ? (r.state === "needs_info" || r.state === "payment_rejected" ? "Upload proof again" : "Pay and upload proof") : "My registrations"}
              </Link>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
