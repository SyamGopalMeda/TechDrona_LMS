"use client";

import { useState } from "react";
import { Badge, Button, FormField } from "@/components/ui";
import { fieldErrorsOf, formatDateTime, TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { seg } from "@/features/trainer/shared/use-api";
import { BOOKING_STATUS, SCORE_LABEL, send } from "../lib/api";
import { SCORE_KEYS, type BookingStatus, type Feedback, type Note } from "../lib/types";

export function BookingBadge({ status }: { status: BookingStatus }) {
  const s = BOOKING_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

/** Rubric scores (1–5) as text, so meaning never depends on colour. */
export function FeedbackView({ feedback }: { feedback: Feedback }) {
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-5">
        {SCORE_KEYS.map((k) => (
          <div key={k}>
            <dt className="text-fg-muted">{SCORE_LABEL[k]}</dt>
            <dd className="font-medium tabular-nums text-fg">{feedback.scores[k] ?? "—"} / 5</dd>
          </div>
        ))}
      </dl>
      {feedback.comments ? <p className="whitespace-pre-line text-sm text-fg-secondary">{feedback.comments}</p> : null}
    </div>
  );
}

/** Private mentor notes on a student (never shown to the student). */
export function NotesPanel({ studentId, notes, bookingId, onAdded }: { studentId: string; notes: Note[]; bookingId?: string; onAdded: (n: Note) => void }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const fail = useFailToast();

  async function add() {
    const text = body.trim();
    if (!text) return setError("Write a note first");
    if (text.length > 5000) return setError("Keep notes under 5,000 characters");
    setBusy(true);
    setError(undefined);
    try {
      const n = await send<Note>("post", `mentor/students/${seg(studentId)}/notes`, { body: text, ...(bookingId ? { booking_id: bookingId } : {}) });
      onAdded(n);
      setBody("");
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (fe.body) setError(fe.body);
      else fail(err, "Couldn't save the note");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-fg-muted">Private — never shown to the student.</p>
      {notes.length ? (
        <ul className="space-y-2">
          {notes.map((n) => (
            <li key={n.id} className="rounded-md border border-line p-3 text-sm">
              <p className="whitespace-pre-line text-fg">{n.body}</p>
              <p className="mt-1 text-xs text-fg-muted">
                {n.author_name ?? "Mentor"} · {formatDateTime(n.created_at)}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fg-muted">No notes yet.</p>
      )}
      <FormField label="Add a note" error={error}>
        {(c) => <TextArea {...c} value={body} maxLength={5000} onChange={(e) => setBody(e.target.value)} />}
      </FormField>
      <Button size="sm" loading={busy} onClick={() => void add()}>
        Save note
      </Button>
    </div>
  );
}
