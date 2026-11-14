"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Dialog,
  FormField,
  Pagination,
  Select,
  Table,
  nextCursorStack,
  previousCursorStack,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useTrainerBatches } from "../lib/batches";
import type {
  IntegrityDecisionResult,
  IntegrityFlag,
  IntegrityFlagPage,
  IntegrityOutcome,
  TestSummary,
} from "../lib/types";
import { useApiAll, useApi, seg } from "../shared/use-api";
import {
  StatusBadge,
  TextArea,
  fieldErrorsOf,
  formatDateTime,
  useFailToast,
} from "../shared/ui";

const OUTCOMES: {
  value: IntegrityOutcome;
  label: string;
  description: string;
}[] = [
  {
    value: "no_action",
    label: "No action",
    description:
      "The signals have an innocent explanation. The flag is closed.",
  },
  {
    value: "refer_security",
    label: "Refer to security",
    description:
      "Opens a case for the security team to look at. The attempt is unchanged.",
  },
  {
    value: "invalidate",
    label: "Invalidate the attempt",
    description:
      "The attempt no longer counts. The student is notified and can appeal. You'll be asked to confirm it's you.",
  },
];

const OUTCOME_LABEL: Record<IntegrityOutcome, string> = {
  no_action: "No action",
  refer_security: "Referred to security",
  invalidate: "Invalidated",
};

/**
 * TRN-010 advisory integrity flags (ASM-19 list, ASM-20 decision). Signals are advisory only:
 * the wording never says "cheating", and nothing changes a score without a human decision.
 */
export function IntegrityReview() {
  const { batches } = useTrainerBatches();
  const tests = useApiAll<TestSummary>("studio/tests");
  const [filters, setFilters] = useState({
    test_id: "",
    batch_id: "",
    status: "open",
  });
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const cursor = stack[stack.length - 1];
  const list = useApi<IntegrityFlagPage>("integrity/flags", {
    test_id: filters.test_id || undefined,
    batch_id: filters.batch_id || undefined,
    status: filters.status || undefined,
    cursor,
    limit: 25,
  });
  const [deciding, setDeciding] = useState<IntegrityFlag | null>(null);
  const setFilter =
    (k: keyof typeof filters) => (e: { target: { value: string } }) => {
      setFilters((f) => ({ ...f, [k]: e.target.value }));
      setStack([undefined]);
    };
  const batchName = (id: string | null) =>
    // Unknown (e.g. no batch.read for evaluators) reads as "—", not a placeholder name.
    id ? (batches?.find((b) => b.id === id)?.name ?? "—") : "—";

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-fg-muted">
        These are advisory signals (focus changes, paste, disconnects, device
        switches) that crossed a review threshold. They are not proof of
        anything and never change a score on their own. Review the attempt, then
        record what you decided.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-56">
          <FormField label="Test">
            {(p) => (
              <Select
                {...p}
                value={filters.test_id}
                onChange={setFilter("test_id")}
                options={[
                  { value: "", label: "All tests" },
                  ...(tests.data?.items ?? []).map((t) => ({
                    value: t.id,
                    label: t.title,
                  })),
                ]}
              />
            )}
          </FormField>
        </div>
        <div className="min-w-48">
          <FormField label="Batch">
            {(p) => (
              <Select
                {...p}
                value={filters.batch_id}
                onChange={setFilter("batch_id")}
                options={[
                  { value: "", label: "All batches" },
                  ...(batches ?? []).map((b) => ({
                    value: b.id,
                    label: b.name,
                  })),
                ]}
              />
            )}
          </FormField>
        </div>
        <div className="min-w-40">
          <FormField label="Status">
            {(p) => (
              <Select
                {...p}
                value={filters.status}
                onChange={setFilter("status")}
                options={[
                  { value: "open", label: "Needs review" },
                  { value: "decided", label: "Reviewed" },
                  { value: "", label: "All" },
                ]}
              />
            )}
          </FormField>
        </div>
      </div>
      <Table
        caption="Integrity flags"
        columns={[
          {
            key: "s",
            header: "Student",
            cell: (f: IntegrityFlag) =>
              `${f.student_name ?? "Student"}${f.attempt_no > 1 ? ` (attempt ${f.attempt_no})` : ""}`,
          },
          { key: "t", header: "Test", cell: (f) => f.test_title },
          { key: "b", header: "Batch", cell: (f) => batchName(f.batch_id) },
          {
            key: "d",
            header: "Started",
            cell: (f) => formatDateTime(f.started_at),
          },
          {
            key: "r",
            header: "Signals",
            cell: (f) => (
              <ul className="space-y-0.5 text-sm">
                {f.reasons.map((r) => (
                  <li key={r.code}>
                    {r.label}: <span className="tabular-nums">{r.count}</span>
                    <span className="text-fg-muted">
                      {" "}
                      (review at {r.threshold})
                    </span>
                  </li>
                ))}
              </ul>
            ),
          },
          {
            key: "a",
            header: "Attempt",
            cell: (f) => <StatusBadge status={f.attempt_status} />,
          },
          {
            key: "st",
            header: "Review",
            cell: (f) =>
              f.decision ? (
                <span className="flex flex-col gap-0.5">
                  <Badge
                    tone={
                      f.decision.outcome === "invalidate"
                        ? "danger"
                        : f.decision.outcome === "refer_security"
                          ? "warning"
                          : "neutral"
                    }
                  >
                    {OUTCOME_LABEL[f.decision.outcome]}
                  </Badge>
                  {f.decision.security_case_ref ? (
                    <span className="text-xs text-fg-muted">
                      Case {f.decision.security_case_ref}
                    </span>
                  ) : null}
                </span>
              ) : (
                <Badge tone="warning">Review recommended</Badge>
              ),
          },
          {
            key: "x",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (f) => (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setDeciding(f)}
                aria-label={`Review ${f.student_name ?? "student"}`}
              >
                {f.decision ? "Change" : "Review"}
              </Button>
            ),
          },
        ]}
        rows={list.data?.data}
        rowKey={(f) => f.attempt_id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{
          title: "Nothing to review",
          description:
            "No attempts in your batches have crossed a review threshold.",
        }}
      />
      <Pagination
        hasMore={list.data?.page.has_more ?? false}
        hasPrevious={stack.length > 1}
        onNext={() =>
          setStack((s) =>
            nextCursorStack(s, list.data?.page.next_cursor ?? null),
          )
        }
        onPrevious={() => setStack((s) => previousCursorStack(s))}
        loading={list.loading}
        label="Integrity flag pages"
      />
      {deciding ? (
        <DecisionDialog
          flag={deciding}
          onClose={() => setDeciding(null)}
          onDone={() => {
            setDeciding(null);
            void list.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function DecisionDialog({
  flag,
  onClose,
  onDone,
}: {
  flag: IntegrityFlag;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const fail = useFailToast();
  const [outcome, setOutcome] = useState<IntegrityOutcome | "">("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const inProgress = flag.attempt_status === "in_progress";

  const submit = async () => {
    const errs: Record<string, string> = {};
    if (!outcome) errs.outcome = "Choose an outcome.";
    if (note.trim().length < 3)
      errs.note = "Add a note explaining the decision (at least 3 characters).";
    setErrors(errs);
    if (Object.keys(errs).length || !outcome) return;
    setBusy(true);
    try {
      const res = await api.post<IntegrityDecisionResult>(
        `attempts/${seg(flag.attempt_id)}/integrity-decision`,
        { outcome, note: note.trim() },
        { idempotencyKey: true },
      );
      const ref = res.kind === "ok" ? res.data.security_case_ref : null;
      toast.show({
        tone: "success",
        title: "Decision recorded",
        description: ref ? `Security case ${ref} opened.` : undefined,
      });
      onDone();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't record the decision");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      title={`Review ${flag.student_name ?? "student"}'s attempt`}
      description={`${flag.test_title} · started ${formatDateTime(flag.started_at)}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void submit()}
            loading={busy}
            variant={outcome === "invalidate" ? "danger" : "primary"}
          >
            Record decision
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          {Object.entries(flag.signals)
            .filter(([, v]) => v > 0)
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-fg-secondary">{k.replace(/_/g, " ")}</dt>
                <dd className="tabular-nums text-fg">{v}</dd>
              </div>
            ))}
        </dl>
        <fieldset>
          <legend className="text-sm font-medium text-fg">Outcome</legend>
          <div className="mt-2 space-y-2">
            {OUTCOMES.map((o) => {
              const disabled = o.value === "invalidate" && inProgress;
              return (
                <label
                  key={o.value}
                  className={`flex gap-2 text-sm ${disabled ? "opacity-60" : ""}`}
                >
                  <input
                    type="radio"
                    name="outcome"
                    value={o.value}
                    checked={outcome === o.value}
                    disabled={disabled}
                    onChange={() => setOutcome(o.value)}
                  />
                  <span>
                    <span className="font-medium text-fg">{o.label}</span>
                    <span className="block text-fg-muted">
                      {disabled
                        ? "Available once the attempt has ended."
                        : o.description}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
          {errors.outcome ? (
            <p role="alert" className="mt-1 text-sm text-danger-fg">
              {errors.outcome}
            </p>
          ) : null}
        </fieldset>
        <FormField
          label="Note"
          required
          error={errors.note}
          hint="Recorded in the audit log."
        >
          {(p) => (
            <TextArea
              {...p}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </FormField>
      </div>
    </Dialog>
  );
}

/** Dashboard tile: count of open advisory flags on the current page (no totals; cursor API). */
export function useOpenFlagCount(): {
  count: number | null;
  more: boolean;
  error: unknown;
} {
  const res = useApi<IntegrityFlagPage>("integrity/flags", {
    status: "open",
    limit: 25,
  });
  return {
    count: res.data ? res.data.data.length : null,
    more: res.data?.page.has_more ?? false,
    error: res.error,
  };
}
