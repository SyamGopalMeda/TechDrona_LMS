"use client";

import Link from "next/link";
import { EmptyState, ErrorState, LoadingBlock, PageHeader } from "@/components/ui";
import { buttonClasses } from "@/components/ui/Button";
import { MY_ADMISSIONS, registerHref, type MyRegistration } from "../lib/registration";
import { RegistrationStatus } from "./RegistrationStatus";
import { useResource } from "@/lib/api/use-resource";

/** My course registrations: status of each payment, reasons, and the next step. */
export function MyRegistrations() {
  const res = useResource<{ data: MyRegistration[] }>(MY_ADMISSIONS);
  const header = <PageHeader eyebrow="Courses" title="My registrations" description="Course registrations and the payments you submitted. We verify each payment and enrol you here." />;
  if (res.loading && !res.data) return (<div>{header}<LoadingBlock label="Loading registrations…" /></div>);
  if (res.error || !res.data) return (<div>{header}<ErrorState error={res.error} onRetry={() => void res.reload()} /></div>);
  const regs = res.data.data;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {header}
      {regs.length === 0 ? (
        <EmptyState
          icon="book"
          title="You haven't registered for a course yet"
          description="Pick a course and register here: pay by UPI and upload the payment screenshot."
          action={
            <Link href="/app/courses" className={buttonClasses({ size: "sm" })}>
              Explore courses
            </Link>
          }
        />
      ) : (
        regs.map((r) => (
          <RegistrationStatus
            key={r.registration_id}
            reg={r}
            action={
              r.can_pay ? (
                <Link href={registerHref(r.course_slug)} className={buttonClasses({ size: "sm", variant: r.enrolled ? "secondary" : "primary" })}>
                  {r.state === "needs_info" || r.state === "payment_rejected" ? "Upload proof again" : r.enrolled ? "Pay next instalment" : "Pay and upload proof"}
                </Link>
              ) : r.state === "rejected" || r.state === "cancelled" ? (
                <Link href={registerHref(r.course_slug)} className={buttonClasses({ size: "sm", variant: "secondary" })}>
                  Register again
                </Link>
              ) : undefined
            }
          />
        ))
      )}
    </div>
  );
}
