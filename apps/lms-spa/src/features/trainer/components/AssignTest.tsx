"use client";

import { useState } from "react";
import {
  Button,
  Dialog,
  FormField,
  Input,
  Select,
  Table,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { useApi, seg } from "../shared/use-api";
import {
  fieldErrorsOf,
  useFailToast,
} from "../shared/ui";
import type { Body } from "@/lib/api-types";
import type { ReleaseMode, TestAssignment } from "../lib/types";
import { formatDateTime } from "@/lib/format";
import { localInputToIso } from "@/lib/time";

const RELEASE: { value: ReleaseMode; label: string }[] = [
  { value: "after_window", label: "After the window closes" },
  { value: "immediate", label: "Immediately after each submission" },
  { value: "scheduled", label: "At a scheduled time" },
  { value: "manual", label: "When I release them" },
];

export interface AssignTestProps {
  testId: string;
  testTitle: string;
  batches: { value: string; label: string }[];
  open: boolean;
  onClose: () => void;
  onAssigned?: () => void;
}

/** Assign a published test to a batch with a window (ASM-10) and show existing assignments (ASM-11). */
export function AssignTestDialog({
  testId,
  testTitle,
  batches,
  open,
  onClose,
  onAssigned,
}: AssignTestProps) {
  const toast = useToast();
  const fail = useFailToast();
  const existing = useApi<{ items: TestAssignment[] }>(
    open ? `tests/${seg(testId)}/assignments` : null,
  );
  const [f, setF] = useState({
    batch_id: "",
    opens: "",
    closes: "",
    max_attempts: "1",
    release_mode: "after_window" as ReleaseMode,
    release_at: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF((x) => ({ ...x, [k]: e.target.value }));
  const batchName = (id: string) =>
    batches.find((b) => b.value === id)?.label ?? "Batch";

  const submit = async () => {
    const errs: Record<string, string> = {};
    const opens = localInputToIso(f.opens);
    const closes = localInputToIso(f.closes);
    if (!f.batch_id) errs.batch_id = "Choose a batch.";
    if (!opens) errs.available_from = "Choose when the test opens.";
    if (!closes) errs.available_until = "Choose when the test closes.";
    if (opens && closes && closes <= opens)
      errs.available_until = "The window must close after it opens.";
    const attempts = Number(f.max_attempts);
    if (!Number.isInteger(attempts) || attempts < 1 || attempts > 10)
      errs.attempts_allowed = "Between 1 and 10 attempts.";
    const releaseAt = localInputToIso(f.release_at);
    if (f.release_mode === "scheduled" && !releaseAt)
      errs.results_release_at = "Choose when results are released.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.post(`tests/${seg(testId)}/assignments`, {
        batch_id: f.batch_id,
        available_from: opens!,
        available_until: closes!,
        attempts_allowed: attempts,
        release_mode: f.release_mode,
        results_release_at: f.release_mode === "scheduled" ? releaseAt : null,
      } satisfies Body<"tests/{test_id}/assignments", "post">);
      toast.show({
        tone: "success",
        title: `Assigned ${testTitle} to ${batchName(f.batch_id)}`,
      });
      setF((x) => ({ ...x, batch_id: "", opens: "", closes: "" }));
      await existing.reload();
      onAssigned?.();
    } catch (err) {
      if (err instanceof ApiError && err.code === "window_conflict")
        setErrors({
          available_from:
            err.detail ||
            "This batch already has a test in an overlapping window. Choose another time.",
        });
      else {
        const fe = fieldErrorsOf(err);
        if (Object.keys(fe).length) setErrors(fe);
        else fail(err, "Couldn't assign the test");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!busy}
      title={`Assign ${testTitle}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Close
          </Button>
          <Button onClick={() => void submit()} loading={busy}>
            Assign test
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Batch" required error={errors.batch_id}>
          {(p) => (
            <Select
              {...p}
              value={f.batch_id}
              onChange={set("batch_id")}
              placeholder="Choose a batch"
              options={batches}
            />
          )}
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Opens" required error={errors.available_from}>
            {(p) => (
              <Input
                {...p}
                type="datetime-local"
                value={f.opens}
                onChange={set("opens")}
              />
            )}
          </FormField>
          <FormField label="Closes" required error={errors.available_until}>
            {(p) => (
              <Input
                {...p}
                type="datetime-local"
                value={f.closes}
                onChange={set("closes")}
              />
            )}
          </FormField>
        </div>
        <FormField
          label="Attempts allowed"
          required
          error={errors.attempts_allowed}
        >
          {(p) => (
            <Input
              {...p}
              type="number"
              min={1}
              max={10}
              inputMode="numeric"
              value={f.max_attempts}
              onChange={set("max_attempts")}
            />
          )}
        </FormField>
        <FormField label="Release results">
          {(p) => (
            <Select
              {...p}
              value={f.release_mode}
              onChange={set("release_mode")}
              options={RELEASE}
            />
          )}
        </FormField>
        {f.release_mode === "scheduled" ? (
          <FormField
            label="Release at"
            required
            error={errors.results_release_at}
          >
            {(p) => (
              <Input
                {...p}
                type="datetime-local"
                value={f.release_at}
                onChange={set("release_at")}
              />
            )}
          </FormField>
        ) : null}
        <Table
          caption="Current assignments"
          showCaption
          loadingRows={2}
          columns={[
            {
              key: "a",
              header: "Audience",
              cell: (a: TestAssignment) =>
                a.batch_id ? batchName(a.batch_id) : "No batch (older assignment)",
            },
            {
              key: "w",
              header: "Window",
              cell: (a) =>
                `${formatDateTime(a.available_from)} – ${formatDateTime(a.available_until)}`,
            },
            {
              key: "n",
              header: "Attempts",
              cell: (a) => a.attempts_allowed ?? "Test default",
            },
          ]}
          rows={existing.data?.items}
          rowKey={(a) => a.id}
          loading={existing.loading}
          error={existing.error}
          onRetry={() => void existing.reload()}
          empty={{ title: "Not assigned yet" }}
        />
      </div>
    </Dialog>
  );
}
