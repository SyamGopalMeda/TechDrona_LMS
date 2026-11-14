"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, ErrorState } from "@/components/ui";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { formatMoney } from "../lib/format";
import type { AccessOptionDto, CourseDetailDto } from "../lib/types";
import { siteHref } from "@/lib/site/website";
import { LinkButton } from "./LinkButton";

export interface CourseAccessProps {
  course: Pick<CourseDetailDto, "id" | "slug" | "title" | "price_type"> & { access_options: AccessOptionDto[]; refund_rule?: string | null };
  signedIn: boolean;
  /** In-app overview (STU-005): reload in place after enrolling instead of navigating. */
  onEnrolled?: () => void;
}

function accessLabel(o: AccessOptionDto): string {
  if (o.interval === "month") return "per month";
  if (o.interval === "year") return "per year";
  if (o.access_days) return `${o.access_days} days access`;
  return "one-time";
}

/**
 * PUB-003 access panel. Free courses enrol via LRN-03; paid courses link to checkout with the
 * selected price (STU-016). CAT-02 is anonymous (no ownership info), so signed-in learners who
 * already hold access can still start via LRN-03, which decides access server-side
 * (verified: app/modules/learning/router.py enrol returns 200 for an existing enrolment).
 */
export function CourseAccess({ course, signedIn, onEnrolled }: CourseAccessProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const overview = `/app/courses/${encodeURIComponent(course.slug)}`;
  const here = `/courses/${encodeURIComponent(course.slug)}`;
  // `/courses/*` is served by the website (marketing redirect), so a signed-in checkout returns
  // to the in-app overview instead.
  const returnTo = signedIn ? overview : here;
  const canEnrolFree = course.price_type === "free";

  async function enrol() {
    setBusy(true);
    setError(null);
    try {
      await api.post("me/enrolments", { course_id: course.id }, { idempotencyKey: true });
      if (onEnrolled) onEnrolled();
      else router.push(overview);
    } catch (err) {
      // Already enrolled is not a failure for the learner.
      if (isApiError(err) && (err.code === "already_enrolled" || err.code === "already_owned")) {
        if (onEnrolled) onEnrolled();
        else router.push(overview);
        return;
      }
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {canEnrolFree ? (
        signedIn ? (
          <Button className="w-full" onClick={enrol} loading={busy}>
            Enrol for free
          </Button>
        ) : (
          <div className="space-y-2">
            <LinkButton href={`/signup?next=${encodeURIComponent(here)}`} className="w-full">
              Sign up to enrol for free
            </LinkButton>
            <p className="text-center text-sm text-fg-muted">
              Already have an account?{" "}
              <Link href={`/login?next=${encodeURIComponent(here)}`} className="font-medium text-fg-link hover:text-fg-link-hover">
                Log in
              </Link>
            </p>
          </div>
        )
      ) : course.access_options.length === 0 ? (
        <p className="text-sm text-fg-muted">This course is not on sale right now. See{" "}
          <a className="text-fg-link" href={siteHref("/courses")}>
            courses and plans
          </a>{" "}
          for access.</p>
      ) : (
        <ul className="space-y-3" aria-label="Access options">
          {course.access_options.map((o) => {
            const checkout = `/app/checkout/new?price_id=${encodeURIComponent(o.price_id)}&return_to=${encodeURIComponent(returnTo)}`;
            return (
              <li key={o.price_id} className="rounded-lg border border-line p-3">
                <p className="font-medium text-fg">{o.name}</p>
                <p className="mt-0.5 text-sm text-fg-secondary">
                  <span className="font-semibold tabular-nums text-fg">{formatMoney(o.total_paise)}</span> incl. GST · {accessLabel(o)}
                </p>
                <LinkButton
                  href={signedIn ? checkout : `/login?next=${encodeURIComponent(checkout)}`}
                  size="sm"
                  className="mt-2 w-full"
                  aria-label={`Buy ${o.name} for ${formatMoney(o.total_paise)}`}
                >
                  Buy {o.name}
                </LinkButton>
              </li>
            );
          })}
        </ul>
      )}

      {signedIn && !canEnrolFree ? (
        <p className="text-sm text-fg-muted">
          Already have access through a plan or your batch?{" "}
          <Button variant="secondary" size="sm" onClick={enrol} loading={busy}>
            Start learning
          </Button>
        </p>
      ) : null}
      {course.refund_rule && course.price_type !== "free" ? <p className="text-xs text-fg-muted">{course.refund_rule}</p> : null}
      {error ? <ErrorState error={error} onRetry={signedIn ? enrol : undefined} /> : null}
    </div>
  );
}
