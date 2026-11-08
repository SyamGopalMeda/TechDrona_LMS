"use client";

import { useEffect, useRef } from "react";

export interface ErrorSummaryProps {
  /** field key → message (e.g. from `fieldErrors(problem.errors)`); empty → renders nothing. */
  errors: Record<string, string>;
  /** field key → control id (FormField's `id`) so each message links to and focuses its field. */
  fieldIds?: Record<string, string>;
  /** Heading override; default "Please fix this problem" / "Please fix these N problems". */
  title?: string;
}

/**
 * The ONE announcement for a failed submit (audit S7): a single alert region at the top of the
 * form that takes focus when the set of errors changes. Field errors in `FormField` are plain
 * text wired by aria-describedby, so screen readers hear the summary once, then each error as
 * they reach its field.
 */
export function ErrorSummary({ errors, fieldIds = {}, title }: ErrorSummaryProps) {
  const ref = useRef<HTMLDivElement>(null);
  const entries = Object.entries(errors);
  const key = entries.map(([k, v]) => `${k}:${v}`).join("|");
  useEffect(() => {
    if (key) ref.current?.focus();
  }, [key]);
  if (entries.length === 0) return null;
  const heading = title ?? `Please fix ${entries.length === 1 ? "this problem" : `these ${entries.length} problems`}`;
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="alert"
      className="rounded-xl border border-danger-border bg-danger-subtle p-4 text-sm text-fg focus:outline-none focus-visible:shadow-focus"
    >
      <p className="font-display font-bold text-danger-fg">{heading}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {entries.map(([field, msg]) => {
          const target = fieldIds[field];
          return (
            <li key={field}>
              {target ? (
                <a
                  href={`#${target}`}
                  className="inline-flex min-h-6 items-center text-fg-link underline"
                  onClick={(e) => {
                    e.preventDefault();
                    (document.getElementById(target) ?? document.getElementsByName(target)[0])?.focus();
                  }}
                >
                  {msg}
                </a>
              ) : (
                msg
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
